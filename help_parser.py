#!/usr/bin/env python3
"""Heuristic parser for common CLI ``--help`` output formats.

The parser intentionally avoids provider-specific dependencies. It supports
Clap, Commander, Click/Typer, argparse, Cobra, and many hand-written help
layouts well enough to generate a useful command builder.
"""

from __future__ import annotations

import re
from typing import Any

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SECTION_RE = re.compile(
    r"^\s*(usage|commands?|available commands?|subcommands?|options?|flags?|global options?|global flags?|arguments?|positionals?)\s*:\s*(.*)$",
    re.IGNORECASE,
)
OPTION_START_RE = re.compile(r"^\s{0,12}(?P<spec>(?:-{1,2}[\w?][\w.-]*(?:[ =](?:<[^>]+>|\[[^\]]+\]|[A-Z][A-Z0-9_.-]*))?)(?:\s*,?\s+-{1,2}[\w?][\w.-]*(?:[ =](?:<[^>]+>|\[[^\]]+\]|[A-Z][A-Z0-9_.-]*))?)*)\s{2,}(?P<desc>.*)$")
OPTION_LOOSE_RE = re.compile(r"^\s*(?P<spec>-{1,2}[\w?][^\t]{0,120}?)(?:\t|\s{3,})(?P<desc>.*)$")
FLAG_RE = re.compile(r"(?<![\w-])(-{1,2}[A-Za-z0-9?][A-Za-z0-9_.-]*)")
VALUE_RE = re.compile(r"(?:=|\s)(<[^>]+>|\[[^\]]+\]|[A-Z][A-Z0-9_.-]*)(?:\.\.\.)?")
CHOICES_INLINE_RE = re.compile(r"(?:possible|allowed|valid)\s+values?\s*:\s*([^\]\n.]+)", re.IGNORECASE)
CHOICES_BRACKET_RE = re.compile(r"\[(?:possible|allowed|valid)\s+values?\s*:\s*([^\]]+)\]", re.IGNORECASE)
ALIAS_RE = re.compile(r"\[aliases?\s*:\s*([^\]]+)\]", re.IGNORECASE)

DANGEROUS_TERMS = {
    "danger", "dangerous", "bypass", "no-sandbox", "unsandboxed", "full-access",
    "allow-all", "skip-confirm", "skip-approval", "disable-safety",
}
DESTRUCTIVE_TERMS = {
    "delete", "remove", "logout", "uninstall", "reset", "purge", "destroy",
    "erase", "revoke", "archive", "apply", "update", "overwrite", "force",
}


def clean_help_text(text: str) -> str:
    text = ANSI_RE.sub("", text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def _section_name(raw: str) -> str:
    name = raw.lower().strip()
    if "command" in name:
        return "commands"
    if "option" in name or "flag" in name:
        return "options"
    if "argument" in name or "position" in name:
        return "arguments"
    if name == "usage":
        return "usage"
    return name


def _split_choices(raw: str) -> list[str]:
    values = re.split(r"\s*[,|/]\s*|\s{2,}", raw.strip())
    cleaned: list[str] = []
    for value in values:
        item = value.strip().strip("`'\"[]")
        if item and item.lower() not in {"etc", "etc."} and item not in cleaned:
            cleaned.append(item)
    return cleaned[:64]


def _risk(text: str) -> str:
    lower = text.lower()
    if any(term in lower for term in DANGEROUS_TERMS):
        return "dangerous"
    if any(re.search(rf"\b{re.escape(term)}\b", lower) for term in DESTRUCTIVE_TERMS):
        return "destructive"
    return "normal"


def _parse_option(spec: str, description: str) -> dict[str, Any]:
    flags = FLAG_RE.findall(spec)
    if not flags:
        raise ValueError("Option has no flag")
    preferred = next((flag for flag in flags if flag.startswith("--")), flags[0])
    value_match = VALUE_RE.search(spec)
    value_name = ""
    if value_match:
        value_name = value_match.group(1).strip("<>[]")
    takes_value = bool(value_match)
    multi_value = "..." in spec or "multiple" in description.lower()
    repeatable = multi_value or "repeatable" in description.lower() or "may be specified multiple" in description.lower()

    choices: list[str] = []
    match = CHOICES_BRACKET_RE.search(description) or CHOICES_INLINE_RE.search(description)
    if match:
        choices = _split_choices(match.group(1))

    return {
        "id": preferred.lstrip("-").replace("-", "_"),
        "flags": flags,
        "flag": preferred,
        "spec": spec.strip(),
        "description": description.strip(),
        "takes_value": takes_value,
        "value_name": value_name,
        "choices": choices,
        "repeatable": repeatable,
        "multi_value": multi_value,
        "required": "required" in description.lower(),
        "risk": _risk(f"{spec} {description}"),
    }


def _split_entry(line: str) -> tuple[str, str]:
    """Split an indented help row into its spec and description columns."""
    stripped = line.strip()
    parts = re.split(r"\s{2,}|\t+", stripped, maxsplit=1)
    return parts[0], parts[1].strip() if len(parts) > 1 else ""


def _parse_option_line(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped.startswith("-"):
        return None
    spec, description = _split_entry(line)
    # A spec can contain a short flag, a long flag, and a value placeholder.
    # If column splitting stopped too early, preserve comma-separated aliases.
    if spec.endswith(",") and description.startswith("--"):
        second_parts = re.split(r"\s{2,}|\t+", description, maxsplit=1)
        spec = f"{spec} {second_parts[0]}"
        description = second_parts[1].strip() if len(second_parts) > 1 else ""
    if not description:
        # Some tools separate the option spec and prose with only one space.
        # Locate the final value placeholder (or final flag for booleans) and
        # treat the remainder as the description column.
        value_match = VALUE_RE.search(stripped)
        flag_matches = list(FLAG_RE.finditer(stripped))
        boundary = value_match.end() if value_match else (flag_matches[-1].end() if flag_matches else 0)
        remainder = stripped[boundary:].strip()
        if boundary and remainder:
            spec, description = stripped[:boundary].rstrip(), remainder
    try:
        return _parse_option(spec, description)
    except ValueError:
        return None


def _parse_command(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("-"):
        return None
    spec, description = _split_entry(line)
    if not description:
        return None
    name = spec.split()[0]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:+-]*", name):
        return None
    aliases: list[str] = []
    alias_match = ALIAS_RE.search(line)
    if alias_match:
        aliases = [part.strip() for part in alias_match.group(1).split(",") if part.strip()]
    return {
        "name": name,
        "spec": spec,
        "description": description,
        "aliases": aliases,
        "risk": _risk(f"{name} {description}"),
    }


def _parse_argument_line(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped:
        return None
    spec, description = _split_entry(line)
    if not re.fullmatch(r"(?:<[^>]+>|\[[^\]]+\]|[A-Z][A-Z0-9_.-]*)(?:\.\.\.)?", spec):
        return None
    return {
        "name": spec.strip("<>[]").removesuffix("..."),
        "spec": spec,
        "description": description,
        "required": spec.startswith("<"),
        "repeatable": "..." in spec,
    }


def parse_help(text: str, *, executable: str = "", command_path: list[str] | None = None) -> dict[str, Any]:
    cleaned = clean_help_text(text)
    lines = cleaned.splitlines()
    command_path = command_path or []

    title = next((line.strip() for line in lines if line.strip()), executable or "CLI")
    usage_lines: list[str] = []
    description_lines: list[str] = []
    commands: list[dict[str, Any]] = []
    options: list[dict[str, Any]] = []
    arguments: list[dict[str, Any]] = []
    sections_seen: list[str] = []

    section = "description"
    current_option: dict[str, Any] | None = None
    current_command: dict[str, Any] | None = None
    current_argument: dict[str, Any] | None = None

    for index, line in enumerate(lines):
        section_match = SECTION_RE.match(line)
        if section_match:
            section = _section_name(section_match.group(1))
            sections_seen.append(section)
            trailing = section_match.group(2).strip()
            current_option = current_command = current_argument = None
            if section == "usage" and trailing:
                usage_lines.append(trailing)
            continue

        stripped = line.strip()
        if not stripped:
            if section != "options":
                current_option = None
            current_command = current_argument = None
            continue

        if section == "usage":
            if line.startswith((" ", "\t")) or not usage_lines:
                usage_lines.append(stripped)
                continue
            section = "description"

        if section == "commands":
            command = _parse_command(line)
            if command:
                commands.append(command)
                current_command = command
                continue
            if current_command and line.startswith(("      ", "\t")):
                current_command["description"] += " " + stripped
                current_command["risk"] = _risk(current_command["name"] + " " + current_command["description"])
                continue

        if section == "options":
            option = _parse_option_line(line)
            if option:
                options.append(option)
                current_option = option
                continue
            if current_option and line.startswith(("      ", "\t")):
                current_option["description"] += " " + stripped
                choice_match = CHOICES_BRACKET_RE.search(current_option["description"]) or CHOICES_INLINE_RE.search(current_option["description"])
                if choice_match:
                    current_option["choices"] = _split_choices(choice_match.group(1))
                current_option["risk"] = _risk(current_option["spec"] + " " + current_option["description"])
                continue

        if section == "arguments":
            argument = _parse_argument_line(line)
            if argument:
                arguments.append(argument)
                current_argument = argument
                continue
            if current_argument and line.startswith(("      ", "\t")):
                current_argument["description"] += " " + stripped
                continue

        # Some CLIs omit section headers. Attempt conservative detection.
        if stripped.startswith("-"):
            option = _parse_option_line(line)
            if option and option["flag"] not in {item["flag"] for item in options}:
                options.append(option)
                current_option = option
                continue

        if section == "description" and index > 0:
            description_lines.append(stripped)

    # De-duplicate while preserving order.
    command_map: dict[str, dict[str, Any]] = {}
    for command in commands:
        command_map.setdefault(command["name"], command)
    option_map: dict[str, dict[str, Any]] = {}
    for option in options:
        option_map.setdefault(option["flag"], option)

    usage = "\n".join(usage_lines).strip()
    description = " ".join(description_lines).strip()
    if description == title:
        description = ""

    overall_risk = "normal"
    risks = [item["risk"] for item in command_map.values()] + [item["risk"] for item in option_map.values()]
    if "dangerous" in risks:
        overall_risk = "dangerous"
    elif "destructive" in risks:
        overall_risk = "destructive"

    return {
        "title": title,
        "description": description,
        "usage": usage,
        "executable": executable,
        "command_path": command_path,
        "commands": list(command_map.values()),
        "options": list(option_map.values()),
        "arguments": arguments,
        "sections": list(dict.fromkeys(sections_seen)),
        "risk": overall_risk,
        "raw_help": cleaned,
        "parser": "heuristic-v2",
    }
