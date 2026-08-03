#!/usr/bin/env python3
"""Heuristic parser for common CLI ``--help`` output formats.

The pareser is provider-agnostic and intentionally dependency-free. It targets
Clap, Cobra, Commander, Click/Typer, argparse, docopt-like, Symfony Console,
and similar hand-written help layouts. Parsed schemas always retain raw help so
operators can audit and correct heuristic results.
"""

from __future__ import annotations

import re
from typing import Any

PARSER_VERSION = "heuristic-v3"
ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
SECTION_RE = re.compile(
    r"^\s*(usage|synopsis|commands?|available commands?|subcommands?|options?|flags?|global options?|global flags?|arguments?|positionals?|parameters?)\s*:?\s*(.*)$",
    re.IGNORECASE,)
FLAG_RE = re.compile(r"(?<![\w-])(-{1,2}[A-Za-z0-9?][A-Za-z0-9_.-]*|--\[no-\][A-Za-z0-9][A-Za-z0-9_.-]*)")
VALUE_RE = re.compile(
    r"(?:=|\s)(<[^>]+>|\[[^\]]+\]|\{[^}]+\}|[A-Z][A-Z0-9_.-]*)(?:\.\.\.)?"
)
CHOICES_INLINE_RE = re.compile(r"(?:possible|allowed|valid|accepted)\s+values?\s*:\s*([^\]\n.)]+)", re.IGNORECASE)
CHOICES_BRACKET_RE = re.compile(r"[\[(](?:possible|allowed|valid|accepted)\s+values?\s*:\s*([^\])]+)[\])]", re.IGNORECASE)
CHOICES_BRACE_RE = re.compile(r"\{([^{}\n]*)\}")
ALIAS_RE = re.compile(r"[\[(]aliases?\s*:\s*([^\])]+)[\])]", re.IGNORECASE)
DEFAULT_RE = re.compile(r"[\[(](?:default|default value)\s*:\s*([^\])]+)[\])]", re.IGNORECASE)
ENV_RE = re.compile(r"[\[(](?:env|environment)\s*:\s*([A-Za-z_][A-Za-z0-9_]*)(?:=[^\])]+)?[\])]", re.IGNORECASE)
REQUIRED_RE = re.compile(r"\b(required|mandatory)\b", re.IGNORECASE)
DEPRECATED_RE = re.compile(r"\b(deprecated|obsolete)\b", re.IGNORECASE)

DANGEROUS_TERMS = {
    "danger", "dangerous", "bypass", "no-sandbox", "unsandboxed", "full-access",
    "allow-all", "skip-confirm", "skip-approval", "disable-safety", "without sandbox",
}
DESTRUCTIVE_TERMS = {
    "delete", "remove", "logout", "uninstall", "reset", "purge", "destroy",
    "erase", "revoke", "archive", "apply", "update", "overwrite", "force",
}


def clean_help_text(text: str) -> str:
    text = ANSI_RE.sub("", text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x08", "")
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def _section_name(raw: str) -> str:
    name = raw.lower().strip()
    if "command" in name:
        return "commands"
    if "option" in name or "flag" in name or "parameter" in name:
        return "options"
    if "argument" in name or "position" in name:
        return "arguments"
    if name in {"usage", "synopsis"}:
        return "usage"
    return name


def _split_choices(raw: str) -> list[str]:
    values = re.split(r"\s*[,|/]\s*|\s{2,}", raw.strip())
    cleaned: list[str] = []
    for value in values:
        item = value.strip().strip("`'\"[]{}()")
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


def _split_entry(line: str) -> tuple[str, str]:
    """Split an indented help row into its spec and description columns."""
    stripped = line.strip()
    parts = re.split(r"\s{2,}|\t+", stripped, maxsplit=1)
    return parts[0], parts[1].strip() if len(parts) > 1 else ""


def _extract_value(spec: str) -> tuple[bool, str, list[str]]:
    value_match = VALUE_RE.search(spec)
    if not value_match:
        return False, "", []
    raw = value_match.group(1)
    value_name = raw.strip("<>[]{}").removesuffix("...")
    choices: list[str] = []
    if raw.startswith("{"):
        choices = _split_choices(raw.strip("{}"))
    return True, value_name, choices


def _parse_option(spec: str, description: str, *, scope: str = "local") -> dict[str, Any]:
    flags = FLAG_RE.findall(spec)
    if not flags:
        raise ValueError("Option has no flag")
    expanded_flags: list[str] = []
    for flag in flags:
        if flag.startswith("--[no-]"):
            base = flag.removeprefix("--[no-]")
            expanded_flags.extend([f"--{base}", f"--no-{base}"])
        else:
            expanded_flags.append(flag)
    flags = list(dict.fromkeys(expanded_flags))
    preferred = next((flag for flag in flags if flag.startswith("--") and not flag.startswith("--no-")), flags[0])
    takes_value, value_name, spec_choices = _extract_value(spec)
    lower_description = description.lower()
    multi_value = "..." in spec or "multiple values" in lower_description or "one or more" in lower_description
    repeatable = multi_value or "repeatable" in lower_description or "may be specified multiple" in lower_description or "can be used multiple" in lower_description

    choices = spec_choices
    match = CHOICES_BRACKET_RE.search(description) or CHOICES_INLINE_RE.search(description)
    if match:
        choices = _split_choices(match.group(1))
    elif not choices:
        brace_match = CHOICES_BRACE_RE.search(spec)
        if brace_match and any(delimiter in brace_match.group(1) for delimiter in (",", "|")):
            choices = _split_choices(brace_match.group(1))

    default_match = DEFAULT_RE.search(description)
    env_match = ENV_RE.search(description)
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
        "required": bool(REQUIRED_RE.search(description)),
        "default": default_match.group(1).strip().strip("`'\"") if default_match else None,
        "environment": env_match.group(1) if env_match else None,
        "negatable": any(flag.startswith("--no-") for flag in flags),
        "deprecated": bool(DEPRECATED_RE.search(description)),
        "scope": scope,
        "risk": _risk(f"{spec} {description}"),
    }


def _parse_option_line(line: str, *, scope: str = "local") -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped.startswith("-"):
        return None
    spec, description = _split_entry(line)
    if spec.endswith(",") and description.startswith("-"):
        second_parts = re.split(r"\s{2,}|\t+", description, maxsplit=1)
        spec = f"{spec} {second_parts[0]}"
        description = second_parts[1].strip() if len(second_parts) > 1 else ""
    if not description:
        value_match = VALUE_RE.search(stripped)
        flag_matches = list(FLAG_RE.finditer(stripped))
        boundary = value_match.end() if value_match else (flag_matches[-1].end() if flag_matches else 0)
        remainder = stripped[boundary:].strip()
        if boundary and remainder:
            spec, description = stripped[:boundary].rstrip(), remainder
    try:
        return _parse_option(spec, description, scope=scope)
    except ValueError:
        return None


def _command_arguments(spec: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in re.findall(r"<[^>]+>|\[[^\]]+\]|\{[^}]+\}", spec):
        inner = raw.strip("<>[]{}").strip()
        if not inner or inner.upper() in {"OPTIONS", "ARGS", "COMMAND"}:
            continue
        repeatable = inner.endswith("...")
        name = inner.removesuffix("...")
        result.append({"name": name, "spec": raw, "required": raw.startswith("<"), "repeatable": repeatable})
    return result


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
        "arguments": _command_arguments(spec),
        "deprecated": bool(DEPRECATED_RE.search(description)),
        "risk": _risk(f"{name} {description}"),
    }


def _parse_argument_line(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped:
        return None
    spec, description = _split_entry(line)
    if not re.fullmatch(r"(?:<[^>]+>|\[[^\]]+\]|\{[^}]+\}|[A-Z][A-Z0-9_.-]*)(?:\.\.\.)?", spec):
        return None
    raw_name = spec.strip("<>[]{}").removesuffix("...")
    choices = _split_choices(raw_name) if spec.startswith("{") else []
    return {
        "name": raw_name if not choices else "value",
        "spec": spec,
        "description": description,
        "required": spec.startswith("<"),
        "repeatable": "..." in spec,
        "choices": choices,
        "deprecated": bool(DEPRECATED_RE.search(description)),
    }


def _refresh_option_metadata(option: dict[str, Any]) -> None:
    description = option["description"]
    match = CHOICES_BRACKET_RE.search(description) or CHOICES_INLINE_RE.search(description)
    if match:
        option["choices"] = _split_choices(match.group(1))
    default_match = DEFAULT_RE.search(description)
    env_match = ENV_RE.search(description)
    if default_match:
        option["default"] = default_match.group(1).strip().strip("`'\"")
    if env_match:
        option["environment"] = env_match.group(1)
    option["required"] = option["required"] or bool(REQUIRED_RE.search(description))
    option["deprecated"] = option["deprecated"] or bool(DEPRECATED_RE.search(description))
    option["risk"] = _risk(option["spec"] + " " + description)


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
    option_scope = "local"
    current_option: dict[str, Any] | None = None
    current_command: dict[str, Any] | None = None
    current_argument: dict[str, Any] | None = None

    for index, line in enumerate(lines):
        section_match = SECTION_RE.match(line)
        if section_match:
            raw_section = section_match.group(1)
            section = _section_name(raw_section)
            option_scope = "global" if raw_section.lower().startswith("global") else "local"
            sections_seen.append("global_options" if section == "options" and option_scope == "global" else section)
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
                current_command["deprecated"] = current_command["deprecated"] or bool(DEPRECATED_RE.search(stripped))
                current_command["risk"] = _risk(current_command["name"] + " " + current_command["description"])
                continue

        if section == "options":
            option = _parse_option_line(line, scope=option_scope)
            if option:
                options.append(option)
                current_option = option
                continue
            if current_option and line.startswith(("      ", "\t")):
                current_option["description"] += " " + stripped
                _refresh_option_metadata(current_option)
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

        if stripped.startswith("-"):
            option = _parse_option_line(line, scope=option_scope)
            if option and option["flag"] not in {item["flag"] for item in options}:
                options.append(option)
                current_option = option
                continue

        if section == "description" and index > 0:
            description_lines.append(stripped)

    command_map: dict[str, dict[str, Any]] = {}
    for command in commands:
        command_map.setdefault(command["name"], command)
    option_map: dict[str, dict[str, Any]] = {}
    for option in options:
        option_map.setdefault(option["flag"], option)
    argument_map: dict[str, dict[str, Any]] = {}
    for argument in arguments:
        argument_map.setdefault(argument["spec"], argument)

    usage = "\n".join(usage_lines).strip()
    description = " ".join(description_lines).strip()
    if description == title:
        description = ""

    risks = [item["risk"] for item in command_map.values()] + [item["risk"] for item in option_map.values()]
    overall_risk = "dangerous" if "dangerous" in risks else "destructive" if "destructive" in risks else "normal"

    return {
        "title": title,
        "description": description,
        "usage": usage,
        "executable": executable,
        "command_path": command_path,
        "commands": list(command_map.values()),
        "options": list(option_map.values()),
        "arguments": list(argument_map.values()),
        "sections": list(dict.fromkeys(sections_seen)),
        "risk": overall_risk,
        "raw_help": cleaned,
        "parser": PARSER_VERSION,
    }
