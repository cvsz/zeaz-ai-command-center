#!/usr/bin/env python3
"""Secure, provider-agnostic AI CLI Command Center.

The service discovers AI command-line tools, parses ``--help`` output into a
structured schema, renders command builders, and executes argv arrays with
``shell=False``. Version 2.1 adds durable jobs, streamed output, hardened HTTP
handling, environment policy, provider fingerprints, and operational health.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import ipaddress
import json
import logging
import os
import queue
import re
import secrets
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from help_parser import PARSER_VERSION, parse_help
from storage import JobStore, TERMINAL_STATES

APP_NAME = "ai-cli-command-center"
APP_VERSION = "2.1.0"
APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
MAX_BODY_BYTES = int(os.getenv("PANEL_MAX_BODY_BYTES", "2000000"))
MAX_HELP_BYTES = int(os.getenv("PANEL_MAX_HELP_BYTES", str(2 * 1024 * 1024)))
MAX_OUTPUT_BYTES = int(os.getenv("PANEL_MAX_OUTPUT_BYTES", str(8 * 1024 * 1024)))
DEFAULT_TIMEOUT_SECONDS = int(os.getenv("PANEL_JOB_TIMEOUT_SECONDS", str(6 * 60 * 60)))
MAX_TIMEOUT_SECONDS = int(os.getenv("PANEL_MAX_JOB_TIMEOUT_SECONDS", str(24 * 60 * 60)))
HELP_TIMEOUT_SECONDS = int(os.getenv("PANEL_HELP_TIMEOUT_SECONDS", "20"))
MAX_CONCURRENT_JOBS = max(1, int(os.getenv("PANEL_MAX_CONCURRENT_JOBS", "4")))
MAX_RETAINED_JOBS = max(10, int(os.getenv("PANEL_MAX_RETAINED_JOBS", "500")))
RETENTION_DAYS = max(1, int(os.getenv("PANEL_JOB_RETENTION_DAYS", "30")))
RATE_LIMIT_PER_MINUTE = max(10, int(os.getenv("PANEL_RATE_LIMIT_PER_MINUTE", "240")))
BINARY_RE = re.compile(r"^[A-Za-z0-9_.+-]+$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:+-]*$")
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
JOB_ID_RE = re.compile(r"^[a-f0-9]{12}$")

DEFAULT_CANDIDATES = [
    {"id": "codex", "name": "OpenAI Codex", "executable": "codex"},
    {"id": "claude", "name": "Claude Code", "executable": "claude"},
    {"id": "gemini", "name": "Gemini CLI", "executable": "gemini"},
    {"id": "qwen", "name": "Qwen Code", "executable": "qwen"},
    {"id": "qwen-code", "name": "Qwen Code", "executable": "qwen-code"},
    {"id": "aider", "name": "Aider", "executable": "aider"},
    {"id": "opencode", "name": "OpenCode", "executable": "opencode"},
    {"id": "goose", "name": "Goose", "executable": "goose"},
    {"id": "ollama", "name": "Ollama", "executable": "ollama"},
    {"id": "llm", "name": "LLM", "executable": "llm"},
    {"id": "sgpt", "name": "ShellGPT", "executable": "sgpt"},
    {"id": "tgpt", "name": "TerminalGPT", "executable": "tgpt"},
    {"id": "fabric", "name": "Fabric AI", "executable": "fabric"},
    {"id": "aichat", "name": "AIChat", "executable": "aichat"},
    {"id": "copilot", "name": "GitHub Copilot CLI", "executable": "copilot"},
    {"id": "gh-copilot", "name": "GitHub Copilot Extension", "executable": "gh"},
]

DANGEROUS_TOKENS = {
    "--dangerously-bypass-approvals-and-sandbox", "--dangerously-bypass-hook-trust",
    "--no-sandbox", "--unsafe", "--allow-all", "--skip-approval", "--skip-confirmation",
    "danger-full-access", "full-access", "unsandboxed",
}
DESTRUCTIVE_WORDS = {
    "delete", "remove", "logout", "uninstall", "reset", "purge", "destroy", "erase",
    "revoke", "archive", "unarchive", "apply", "update", "overwrite", "force",
}
SENSITIVE_FLAG_TERMS = ("token", "secret", "password", "passwd", "api-key", "apikey", "auth", "credential")
BLOCKED_ENV_KEYS = {
    "BASH_ENV", "ENV", "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES",
    "DYLD_LIBRARY_PATH", "NODE_OPTIONS", "PYTHONPATH", "PYTHONHOME", "RUBYOPT",
    "PERL5OPT", "GIT_SSH_COMMAND", "SHELLOPTS", "PROMPT_COMMAND", "PS4",
}
DEFAULT_ENV_PREFIXES = (
    "OPENAI_", "ANTHROPIC_", "GOOGLE_", "GEMINI_", "QWEN_", "OLLAMA_",
    "HF_", "HUGGINGFACE_", "AZURE_", "AWS_", "GCP_", "MISTRAL_", "COHERE_",
    "GROQ_", "OPENROUTER_", "TOGETHER_", "DEEPSEEK_", "XAI_", "NVIDIA_",
)
DEFAULT_ENV_EXACT = {
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "SSL_CERT_FILE",
    "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "TERM", "NO_COLOR",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname.lower(),
            "message": record.getMessage(),
            "logger": record.name,
        }
        for key in ("request_id", "remote", "method", "path", "status", "job_id", "provider_id", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging() -> logging.Logger:
    logger = logging.getLogger(APP_NAME)
    if logger.handlers:
        return logger
    level = getattr(logging, os.getenv("PANEL_LOG_LEVEL", "INFO").upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    if os.getenv("PANEL_LOG_FORMAT", "json").lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


LOGGER = configure_logging()


def safe_text(value: Any, *, max_len: int = 8192) -> str:
    text = str(value or "")
    if "\x00" in text:
        raise ValueError("NUL bytes are not allowed")
    if len(text) > max_len:
        raise ValueError(f"Value exceeds {max_len} characters")
    return text


def list_of_text(value: Any, *, max_items: int = 128, max_len: int = 4096) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Expected a list")
    if len(value) > max_items:
        raise ValueError(f"Too many values; maximum is {max_items}")
    return [safe_text(item, max_len=max_len) for item in value]


def split_cli_args(value: Any, *, max_items: int = 16) -> list[str]:
    text = safe_text(value, max_len=4096).strip()
    if not text:
        return []
    result = shlex.split(text, posix=True)
    if len(result) > max_items:
        raise ValueError(f"Too many arguments; maximum is {max_items}")
    return [safe_text(item, max_len=512) for item in result]


def allowed_roots() -> list[Path]:
    raw = os.getenv("PANEL_ALLOWED_ROOTS", "").strip()
    if raw:
        roots = [Path(part).expanduser().resolve() for part in raw.split(os.pathsep) if part.strip()]
    else:
        roots = [Path.home().resolve()]
        current = Path.cwd().resolve()
        if current not in roots:
            roots.append(current)
    return list(dict.fromkeys(roots))


def validate_cwd(raw_cwd: Any) -> Path:
    cwd = Path(safe_text(raw_cwd or str(Path.cwd()), max_len=4096)).expanduser().resolve()
    if not cwd.exists() or not cwd.is_dir():
        raise ValueError(f"Working directory does not exist: {cwd}")
    if os.getenv("PANEL_ALLOW_ANY_CWD", "0") == "1":
        return cwd
    for root in allowed_roots():
        try:
            cwd.relative_to(root)
            return cwd
        except ValueError:
            continue
    raise ValueError("Working directory is outside allowed roots: " + ", ".join(map(str, allowed_roots())))


def provider_config_path() -> Path:
    base = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME / "providers.json"


def _provider_id(value: str) -> str:
    provider_id = re.sub(r"[^a-z0-9_.-]+", "-", value.lower()).strip("-")
    if not provider_id:
        raise ValueError("Provider id is empty")
    return provider_id[:80]


def resolve_executable(executable: Any) -> str:
    raw = safe_text(executable, max_len=4096).strip()
    if not raw:
        raise ValueError("Executable is required")
    if "/" in raw or "\\" in raw:
        if os.getenv("PANEL_ALLOW_ABSOLUTE_BINARIES", "0") != "1":
            raise ValueError("Absolute executable paths are disabled; set PANEL_ALLOW_ABSOLUTE_BINARIES=1 to enable")
        path = Path(raw).expanduser().resolve()
        if not path.is_absolute() or not path.exists() or not path.is_file() or (sys.platform != "win32" and not os.access(path, os.X_OK)):
            raise ValueError(f"Executable is not runnable: {path}")
        return str(path)
    if not BINARY_RE.fullmatch(raw):
        raise ValueError("Executable name contains unsupported characters")
    resolved = shutil.which(raw)
    if not resolved:
        raise ValueError(f"Executable not found in PATH: {raw}")
    return str(Path(resolved).resolve())


def run_capture(argv: list[str], *, cwd: Path | str | None = None, timeout: int = HELP_TIMEOUT_SECONDS) -> tuple[int, str]:
    env = os.environ.copy()
    env.setdefault("TERM", "dumb")
    env.setdefault("NO_COLOR", "1")
    env.setdefault("CLICOLOR", "0")
    result = subprocess.run(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
        env=env,
        shell=False,
    )
    output = result.stdout[:MAX_HELP_BYTES].decode("utf-8", errors="replace")
    if len(result.stdout) > MAX_HELP_BYTES:
        output += "\n[command-center] Help output truncated."
    return result.returncode, output


def fingerprint_executable(path: str) -> dict[str, Any]:
    resolved = Path(path).resolve()
    metadata = resolved.stat()
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(resolved),
        "sha256": digest.hexdigest(),
        "size": metadata.st_size,
        "mtime_ns": metadata.st_mtime_ns,
        "mode": stat.filemode(metadata.st_mode),
        "owner_uid": metadata.st_uid if hasattr(metadata, "st_uid") else None,
        "world_writable": bool(metadata.st_mode & stat.S_IWOTH),
    }


class ProviderRegistry:
    def __init__(self) -> None:
        self.path = provider_config_path()
        self.lock = threading.RLock()
        self.custom: dict[str, dict[str, Any]] = {}
        self.schema_cache: dict[tuple[str, tuple[str, ...]], tuple[float, dict[str, Any]]] = {}
        self.fingerprint_cache: dict[tuple[str, int, int], dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        with self.lock:
            if not self.path.exists():
                self.custom = {}
                return
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                providers = data.get("providers", []) if isinstance(data, dict) else []
                self.custom = {item["id"]: item for item in providers if isinstance(item, dict) and item.get("id")}
            except (OSError, json.JSONDecodeError):
                LOGGER.exception("provider_registry_load_failed")
                self.custom = {}

    def save(self) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.path.parent, 0o700)
            except OSError:
                pass
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"providers": list(self.custom.values())}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.chmod(temporary, 0o600)
            temporary.replace(self.path)

    def list(self, *, include_missing: bool = False) -> list[dict[str, Any]]:
        providers: dict[str, dict[str, Any]] = {}
        os_paths = [
            Path.home() / ".local" / "bin",
            Path.home() / ".cargo" / "bin",
            Path.home() / ".nvm" / "versions" / "node",
            Path.home() / "go" / "bin",
            Path("/usr/local/bin"),
            Path("/opt/homebrew/bin"),
            Path.home() / "AppData" / "Local" / "Programs",
            Path.home() / "AppData" / "Roaming" / "npm",
            Path("C:/Program Files"),
            Path("C:/Program Files (x86)"),
        ]
        win_exts = ["", ".exe", ".cmd", ".bat", ".ps1"] if sys.platform == "win32" else [""]
        for candidate in DEFAULT_CANDIDATES:
            resolved = shutil.which(candidate["executable"])
            if not resolved:
                for base_dir in os_paths:
                    if base_dir.exists():
                        for ext in win_exts:
                            target = base_dir / f"{candidate['executable']}{ext}"
                            if target.is_file() and (sys.platform == "win32" or os.access(target, os.X_OK)):
                                resolved = str(target.resolve())
                                break
                        if resolved: break
            if resolved or include_missing:
                providers[candidate["id"]] = {
                    **candidate,
                    "resolved": str(Path(resolved).resolve()) if resolved else None,
                    "installed": bool(resolved),
                    "help_args": ["--help"],
                    "version_args": ["--version"],
                    "custom": False,
                }
        with self.lock:
            custom_items = list(self.custom.values())
        for item in custom_items:
            try:
                resolved = resolve_executable(item["executable"])
            except ValueError:
                resolved = None
            providers[item["id"]] = {**item, "resolved": resolved, "installed": bool(resolved), "custom": True}
        return sorted(providers.values(), key=lambda item: (not item["installed"], item["name"].lower()))

    def get(self, provider_id: str) -> dict[str, Any]:
        for provider in self.list(include_missing=True):
            if provider["id"] == provider_id:
                if not provider.get("installed"):
                    raise ValueError(f"Provider executable is not installed: {provider['executable']}")
                return provider
        raise ValueError(f"Unknown provider: {provider_id}")

    def probe(self, payload: dict[str, Any]) -> dict[str, Any]:
        executable_input = safe_text(payload.get("executable"), max_len=4096).strip()
        resolved = resolve_executable(executable_input)
        help_args = split_cli_args(payload.get("help_args", "--help")) or ["--help"]
        version_args = split_cli_args(payload.get("version_args", "--version")) or ["--version"]
        command_path = validate_command_path(payload.get("command_path"))
        code, output = run_capture([resolved, *command_path, *help_args])
        schema = parse_help(output, executable=executable_input, command_path=command_path)
        version = ""
        try:
            _, version_output = run_capture([resolved, *version_args], timeout=10)
            version = version_output.strip().splitlines()[0][:300] if version_output.strip() else ""
        except (subprocess.TimeoutExpired, OSError):
            pass
        fingerprint = self._fingerprint(resolved)
        if fingerprint["world_writable"] and os.getenv("PANEL_ALLOW_WORLD_WRITABLE_BINARIES", "0") != "1":
            raise ValueError("Refusing world-writable provider executable")
        return {
            "id": _provider_id(safe_text(payload.get("id") or Path(executable_input).name, max_len=80)),
            "name": safe_text(payload.get("name") or schema.get("title") or Path(executable_input).name, max_len=120),
            "executable": executable_input,
            "resolved": resolved,
            "installed": True,
            "help_args": help_args,
            "version_args": version_args,
            "version": version,
            "fingerprint": fingerprint,
            "return_code": code,
            "schema": schema,
        }

    def add(self, payload: dict[str, Any]) -> dict[str, Any]:
        probed = self.probe(payload)
        item = {
            "id": probed["id"],
            "name": probed["name"],
            "executable": probed["executable"],
            "help_args": probed["help_args"],
            "version_args": probed["version_args"],
            "registered_fingerprint": probed["fingerprint"],
        }
        with self.lock:
            self.custom[item["id"]] = item
            self.schema_cache.clear()
            self.save()
        return {**item, "resolved": probed["resolved"], "installed": True, "custom": True, "version": probed["version"], "fingerprint": probed["fingerprint"], "schema": probed["schema"]}

    def remove(self, provider_id: str) -> None:
        with self.lock:
            if provider_id not in self.custom:
                raise ValueError("Only custom providers can be removed")
            del self.custom[provider_id]
            self.schema_cache = {key: value for key, value in self.schema_cache.items() if key[0] != provider_id}
            self.save()

    def schema(self, provider_id: str, command_path: list[str] | None = None, *, refresh: bool = False) -> dict[str, Any]:
        command_path = command_path or []
        key = (provider_id, tuple(command_path))
        with self.lock:
            cached = self.schema_cache.get(key)
        if cached and not refresh and time.time() - cached[0] < 300:
            return cached[1]
        provider = self.get(provider_id)
        resolved = resolve_executable(provider["executable"])
        code, output = run_capture([resolved, *command_path, *provider.get("help_args", ["--help"])])
        schema = parse_help(output, executable=provider["executable"], command_path=command_path)
        schema["return_code"] = code
        schema["provider_id"] = provider_id
        schema["provider_name"] = provider["name"]
        if hasattr(self, "store") and self.store:
            overlay = self.store.get_overlay(provider_id)
            if overlay and isinstance(overlay, dict):
                for key, val in overlay.items():
                    schema[key] = val
        with self.lock:
            self.schema_cache[key] = (time.time(), schema)
        return schema

    def _fingerprint(self, resolved: str) -> dict[str, Any]:
        metadata = Path(resolved).stat()
        key = (resolved, metadata.st_mtime_ns, metadata.st_size)
        with self.lock:
            cached = self.fingerprint_cache.get(key)
        if cached:
            return cached
        value = fingerprint_executable(resolved)
        with self.lock:
            self.fingerprint_cache = {key: value}
        return value

    def info(self, provider_id: str) -> dict[str, Any]:
        provider = self.get(provider_id)
        resolved = resolve_executable(provider["executable"])
        version = ""
        error = None
        try:
            code, output = run_capture([resolved, *provider.get("version_args", ["--version"])], timeout=10)
            version = output.strip().splitlines()[0][:300] if output.strip() else ""
            if code != 0:
                error = output.strip() or f"Exited with {code}"
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
        fingerprint = self._fingerprint(resolved)
        registered = provider.get("registered_fingerprint") or {}
        changed = bool(registered and registered.get("sha256") != fingerprint.get("sha256"))
        return {**provider, "resolved": resolved, "version": version, "error": error, "fingerprint": fingerprint, "fingerprint_changed": changed}


def validate_command_path(value: Any) -> list[str]:
    parts = list_of_text(value, max_items=8, max_len=80)
    for token in parts:
        if not TOKEN_RE.fullmatch(token) or token.startswith("-"):
            raise ValueError(f"Invalid command token: {token}")
    return parts


def option_index(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for option in schema.get("options", []):
        for flag in option.get("flags", []):
            index[flag] = option
        index[option.get("flag", "")] = option
    return index


def render_options(schema: dict[str, Any], selected: Any) -> list[str]:
    if selected is None:
        return []
    if not isinstance(selected, dict):
        raise ValueError("Selected options must be an object")
    index = option_index(schema)
    argv: list[str] = []
    used: set[str] = set()
    for raw_flag, raw_value in selected.items():
        flag = safe_text(raw_flag, max_len=128)
        option = index.get(flag)
        if not option:
            raise ValueError(f"Option is not present in parsed help: {flag}")
        canonical = flag if flag in option.get("flags", []) and flag.startswith("--no-") else option["flag"]
        key = option["flag"]
        if key in used and canonical == key:
            continue
        used.add(key)
        if not option.get("takes_value"):
            if bool(raw_value):
                argv.append(canonical)
            continue
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        cleaned = [safe_text(value, max_len=8192) for value in values if str(value or "") != ""]
        if not cleaned:
            if option.get("required"):
                raise ValueError(f"Option requires a value: {canonical}")
            continue
        choices = option.get("choices") or []
        if choices:
            invalid = [value for value in cleaned if value not in choices]
            if invalid:
                raise ValueError(f"Invalid value for {canonical}: {invalid[0]}")
        if option.get("multi_value"):
            argv.append(canonical)
            argv.extend(cleaned)
        elif option.get("repeatable"):
            for value in cleaned:
                argv.extend([canonical, value])
        else:
            argv.extend([canonical, cleaned[0]])
    return argv


def detect_risk(argv: list[str]) -> str:
    destructive = False
    for raw in argv:
        item = raw.lower().strip()
        normalized = item.lstrip("-").split("=")[0]
        if item in DANGEROUS_TOKENS:
            return "dangerous"
        if item.startswith("-") and any(term in item for term in ("danger", "bypass", "no-sandbox", "unsandboxed", "unsafe", "full-access", "skip-approval")):
            return "dangerous"
        if normalized in DESTRUCTIVE_WORDS:
            destructive = True
    return "destructive" if destructive else "normal"


def allowed_environment_key(key: str) -> bool:
    if key in BLOCKED_ENV_KEYS:
        return False
    if os.getenv("PANEL_ALLOW_ANY_ENV", "0") == "1":
        return True
    configured_exact = {item.strip() for item in os.getenv("PANEL_ENV_ALLOWLIST", "").split(",") if item.strip()}
    configured_prefixes = tuple(item.strip() for item in os.getenv("PANEL_ENV_PREFIX_ALLOWLIST", "").split(",") if item.strip())
    return key in DEFAULT_ENV_EXACT or key in configured_exact or key.startswith(DEFAULT_ENV_PREFIXES + configured_prefixes)


def validate_environment(value: Any) -> dict[str, str]:
    raw = value or {}
    if not isinstance(raw, dict):
        raise ValueError("environment must be an object")
    if len(raw) > 64:
        raise ValueError("Too many environment overrides; maximum is 64")
    result: dict[str, str] = {}
    for key, item in raw.items():
        name = str(key)
        if not ENV_KEY_RE.fullmatch(name):
            raise ValueError(f"Invalid environment variable name: {name}")
        if not allowed_environment_key(name):
            raise ValueError(f"Environment variable is not allowed by policy: {name}")
        result[name] = safe_text(item, max_len=20_000)
    return result


def redact_argv(argv: list[str]) -> list[str]:
    redacted: list[str] = []
    hide_next = False
    for item in argv:
        if hide_next:
            redacted.append("[REDACTED]")
            hide_next = False
            continue
        lower = item.lower()
        if item.startswith("-") and "=" in item:
            flag, _, _ = item.partition("=")
            if any(term in flag.lower() for term in SENSITIVE_FLAG_TERMS):
                redacted.append(f"{flag}=[REDACTED]")
                continue
        redacted.append(item)
        if item.startswith("-") and any(term in lower for term in SENSITIVE_FLAG_TERMS):
            hide_next = True
    return redacted


def build_ai_command(payload: dict[str, Any], registry: ProviderRegistry) -> tuple[list[str], Path, str]:
    provider_id = safe_text(payload.get("provider_id"), max_len=80)
    provider = registry.get(provider_id)
    executable = resolve_executable(provider["executable"])
    cwd = validate_cwd(payload.get("cwd"))
    command_path = validate_command_path(payload.get("command_path"))

    root_schema = registry.schema(provider_id, [])
    command_schema = registry.schema(provider_id, command_path) if command_path else root_schema
    argv = [executable]
    argv.extend(render_options(root_schema, payload.get("global_options")))
    argv.extend(command_path)
    if command_path:
        argv.extend(render_options(command_schema, payload.get("command_options")))

    positionals = list_of_text(payload.get("positionals"), max_items=128, max_len=8192)
    raw_args = list_of_text(payload.get("raw_args"), max_items=128, max_len=8192)
    if raw_args and os.getenv("PANEL_ALLOW_RAW_ARGS", "1") != "1":
        raise ValueError("Raw arguments are disabled by policy")
    prompt = safe_text(payload.get("prompt"), max_len=200_000)
    risk_argv = [*argv, *[item for item in raw_args if item.startswith("-")]]
    argv.extend(positionals)
    argv.extend(raw_args)
    if prompt:
        argv.append(prompt)
    if len(argv) > 512:
        raise ValueError("Command exceeds maximum argv length")

    validate_environment(payload.get("environment"))
    risk = detect_risk(risk_argv)
    confirmation = safe_text(payload.get("confirmation"), max_len=64)
    if risk == "dangerous" and confirmation != "I UNDERSTAND":
        raise ValueError("Dangerous execution requires confirmation text: I UNDERSTAND")
    if risk == "destructive" and confirmation != "CONFIRM":
        raise ValueError("Destructive execution requires confirmation text: CONFIRM")
    return argv, cwd, risk


def bounded_timeout(value: Any) -> int:
    if value in (None, ""):
        return DEFAULT_TIMEOUT_SECONDS
    try:
        timeout = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout_seconds must be an integer") from exc
    if timeout < 1 or timeout > MAX_TIMEOUT_SECONDS:
        raise ValueError(f"timeout_seconds must be between 1 and {MAX_TIMEOUT_SECONDS}")
    return timeout


@dataclass
class Job:
    id: str
    provider_id: str
    argv: list[str]
    display_argv: list[str]
    cwd: str
    created_at: float
    environment: dict[str, str] = field(default_factory=dict)
    redaction_values: list[bytes] = field(default_factory=list, repr=False)
    redaction_tail: bytes = field(default=b"", repr=False)
    risk: str = "normal"
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    status: str = "queued"
    started_at: float | None = None
    finished_at: float | None = None
    return_code: int | None = None
    error: str | None = None
    output: bytearray = field(default_factory=bytearray)
    output_base: int = 0
    process: subprocess.Popen[bytes] | None = field(default=None, repr=False)
    stop_requested: bool = field(default=False, repr=False)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    changed: threading.Condition = field(init=False, repr=False)
    last_persisted_at: float = field(default=0.0, repr=False)

    def __post_init__(self) -> None:
        self.changed = threading.Condition(self.lock)

    def append(self, data: bytes, *, final: bool = False) -> None:
        with self.changed:
            combined = self.redaction_tail + data
            keep = 0
            if self.redaction_values and not final:
                keep = min(max(len(value) for value in self.redaction_values) - 1, 255)
            if keep > 0 and len(combined) > keep:
                visible, self.redaction_tail = combined[:-keep], combined[-keep:]
            elif keep > 0:
                visible, self.redaction_tail = b"", combined
            else:
                visible, self.redaction_tail = combined, b""
            for value in self.redaction_values:
                visible = visible.replace(value, b"[REDACTED]")
            self.output.extend(visible)
            if len(self.output) > MAX_OUTPUT_BYTES:
                remove = len(self.output) - MAX_OUTPUT_BYTES
                del self.output[:remove]
                self.output_base += remove
            self.changed.notify_all()

    def set_status(self, status: str, *, error: str | None = None) -> None:
        with self.changed:
            self.status = status
            if error is not None:
                self.error = error
            self.changed.notify_all()

    def record(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider_id": self.provider_id,
            "argv": self.display_argv,
            "cwd": self.cwd,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "return_code": self.return_code,
            "error": self.error,
            "risk": self.risk,
            "timeout_seconds": self.timeout_seconds,
        }

    def snapshot(self, offset: int = 0, *, include_output: bool = True) -> dict[str, Any]:
        with self.lock:
            effective = max(max(0, offset), self.output_base)
            start = effective - self.output_base
            chunk = bytes(self.output[start:]).decode("utf-8", errors="replace") if include_output else ""
            next_offset = self.output_base + len(self.output)
            record = self.record()
        return {
            **record,
            "output": chunk,
            "next_offset": next_offset,
            "output_truncated": offset < self.output_base,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "Job":
        display = [str(item) for item in record.get("argv", [])]
        return cls(
            id=record["id"], provider_id=record["provider_id"], argv=display, display_argv=display,
            cwd=record["cwd"], created_at=record["created_at"], risk=record.get("risk", "normal"),
            timeout_seconds=int(record.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS), status=record["status"],
            started_at=record.get("started_at"), finished_at=record.get("finished_at"),
            return_code=record.get("return_code"), error=record.get("error"),
            output=bytearray(record.get("output") or b""), output_base=int(record.get("output_base") or 0),
        )


class JobManager:
    def __init__(self, registry: ProviderRegistry, store: JobStore | None = None) -> None:
        self.registry = registry
        self.store = store or JobStore(max_output_bytes=MAX_OUTPUT_BYTES)
        orphaned = self.store.mark_interrupted_jobs_orphaned()
        self.jobs: dict[str, Job] = {}
        self.order: deque[str] = deque(maxlen=MAX_RETAINED_JOBS)
        self.lock = threading.RLock()
        self.capacity = threading.BoundedSemaphore(MAX_CONCURRENT_JOBS)
        self.shutting_down = threading.Event()
        for record in self.store.load_recent(MAX_RETAINED_JOBS):
            job = Job.from_record(record)
            self.jobs[job.id] = job
            self.order.append(job.id)
        if orphaned:
            LOGGER.warning("jobs_marked_orphaned", extra={"status": orphaned})
        pruned = self.store.prune(max_jobs=MAX_RETAINED_JOBS, retention_days=RETENTION_DAYS)
        if pruned:
            LOGGER.info("jobs_pruned", extra={"status": pruned})

    def create(self, payload: dict[str, Any]) -> Job:
        if self.shutting_down.is_set():
            raise ValueError("Server is shutting down")
        argv, cwd, risk = build_ai_command(payload, self.registry)
        environment = validate_environment(payload.get("environment"))
        timeout_seconds = bounded_timeout(payload.get("timeout_seconds"))
        job = Job(
            id=uuid.uuid4().hex[:12], provider_id=safe_text(payload.get("provider_id"), max_len=80),
            argv=argv, display_argv=redact_argv(argv), cwd=str(cwd), created_at=time.time(),
            environment=environment, redaction_values=[value.encode("utf-8") for value in environment.values() if 8 <= len(value.encode("utf-8")) <= 256], risk=risk, timeout_seconds=timeout_seconds,
        )
        with self.lock:
            self.jobs[job.id] = job
            self.order.appendleft(job.id)
        self._persist(job, force=True)
        threading.Thread(target=self._run, args=(job,), daemon=True, name=f"job-{job.id}").start()
        LOGGER.info("job_created", extra={"job_id": job.id, "provider_id": job.provider_id})
        return job

    def _persist(self, job: Job, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - job.last_persisted_at < 0.25:
            return
        with job.lock:
            record = job.record()
            output = bytes(job.output)
            output_base = job.output_base
            job.last_persisted_at = now
        self.store.upsert(record, output, output_base)

    @staticmethod
    def _read_output(stream: Any, target: queue.Queue[bytes | None]) -> None:
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                target.put(chunk)
        finally:
            target.put(None)

    def _wait_for_capacity(self, job: Job) -> bool:
        while not self.shutting_down.is_set() and not job.stop_requested:
            if self.capacity.acquire(timeout=0.25):
                return True
        return False

    def _run(self, job: Job) -> None:
        acquired = self._wait_for_capacity(job)
        if not acquired:
            if job.status not in TERMINAL_STATES:
                job.finished_at = time.time()
                job.set_status("stopped", error="Job stopped before execution")
                self._persist(job, force=True)
            return
        try:
            if job.stop_requested:
                job.finished_at = time.time()
                job.set_status("stopped")
                return
            job.started_at = time.time()
            job.set_status("running")
            self._persist(job, force=True)
            env = os.environ.copy()
            env.update(job.environment)
            env.setdefault("TERM", "dumb")
            env.setdefault("NO_COLOR", "1")
            env.setdefault("CLICOLOR", "0")
            process = subprocess.Popen(
                job.argv, cwd=job.cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=False,
                start_new_session=True,
            )
            job.process = process
            assert process.stdout is not None
            output_queue: queue.Queue[bytes | None] = queue.Queue()
            reader = threading.Thread(target=self._read_output, args=(process.stdout, output_queue), daemon=True)
            reader.start()
            deadline = time.monotonic() + job.timeout_seconds
            reader_done = False
            while True:
                try:
                    chunk = output_queue.get(timeout=0.2)
                    if chunk is None:
                        reader_done = True
                    else:
                        job.append(chunk)
                        self._persist(job)
                except queue.Empty:
                    pass
                if job.stop_requested and process.poll() is None:
                    self._terminate_process(job)
                if time.monotonic() > deadline and process.poll() is None:
                    job.error = f"Job exceeded timeout of {job.timeout_seconds} seconds"
                    job.set_status("timed_out")
                    job.stop_requested = True
                    self._terminate_process(job)
                if process.poll() is not None and reader_done and output_queue.empty():
                    break
            job.return_code = process.wait(timeout=10)
            job.append(b"", final=True)
            if job.status not in {"stopped", "timed_out"}:
                job.set_status("succeeded" if job.return_code == 0 else "failed")
        except FileNotFoundError:
            job.set_status("failed", error=f"Executable not found: {job.argv[0]}")
        except Exception as exc:  # noqa: BLE001
            job.set_status("failed", error=str(exc))
            job.append((f"\n[command-center] {exc}\n").encode())
            LOGGER.exception("job_failed", extra={"job_id": job.id, "provider_id": job.provider_id})
        finally:
            job.append(b"", final=True)
            job.finished_at = job.finished_at or time.time()
            job.process = None
            with job.changed:
                job.changed.notify_all()
            self._persist(job, force=True)
            self.capacity.release()
            LOGGER.info("job_finished", extra={"job_id": job.id, "provider_id": job.provider_id, "status": job.status})

    def _terminate_process(self, job: Job) -> bool:
        process = job.process
        if not process or process.poll() is not None:
            return False
        try:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
            return True
        except ProcessLookupError:
            return False

    def get(self, job_id: str) -> Job | None:
        if not JOB_ID_RE.fullmatch(job_id):
            return None
        with self.lock:
            return self.jobs.get(job_id)

    def list(self) -> list[dict[str, Any]]:
        with self.lock:
            ids = list(self.order)
        return [self.jobs[job_id].snapshot(include_output=False) for job_id in ids if job_id in self.jobs]

    def stop(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job.status in TERMINAL_STATES:
            return False
        job.stop_requested = True
        if job.status == "queued":
            job.finished_at = time.time()
            job.set_status("stopped")
            self._persist(job, force=True)
            return True
        job.set_status("stopping")
        stopped = self._terminate_process(job)
        if stopped:
            job.finished_at = time.time()
            job.set_status("stopped")
            self._persist(job, force=True)
        return stopped

    def delete(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job:
            return False
        if job.status not in TERMINAL_STATES:
            raise ValueError("Only terminal jobs can be deleted")
        if not self.store.delete(job_id):
            return False
        with self.lock:
            self.jobs.pop(job_id, None)
            try:
                self.order.remove(job_id)
            except ValueError:
                pass
        return True

    def metrics(self) -> dict[str, int]:
        statuses: dict[str, int] = {}
        with self.lock:
            jobs = list(self.jobs.values())
        for job in jobs:
            statuses[job.status] = statuses.get(job.status, 0) + 1
        return statuses

    def shutdown(self) -> None:
        self.shutting_down.set()
        with self.lock:
            active = [job.id for job in self.jobs.values() if job.status not in TERMINAL_STATES]
        for job_id in active:
            self.stop(job_id)


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int = 60) -> None:
        self.limit = max(1, limit)
        self.window = window_seconds
        self.lock = threading.Lock()
        self.requests: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self.lock:
            bucket = self.requests.setdefault(key, deque())
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            if len(self.requests) > 10_000:
                self.requests = {item: values for item, values in self.requests.items() if values and now - values[-1] <= self.window}
            return True


class Handler(SimpleHTTPRequestHandler):
    server_version = "AICommandCenter"
    sys_version = ""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.request_id = uuid.uuid4().hex[:16]
        self.request_started = time.monotonic()
        self.response_status = 200
        super().__init__(*args, **kwargs)

    @property
    def app_server(self) -> "AppServer":
        return self.server  # type: ignore[return-value]

    def log_message(self, fmt: str, *args: Any) -> None:
        LOGGER.info(
            fmt % args,
            extra={
                "request_id": self.request_id,
                "remote": self.client_address[0],
                "method": self.command,
                "path": urlparse(self.path).path,
                "status": self.response_status,
                "duration_ms": round((time.monotonic() - self.request_started) * 1000, 3),
            },
        )

    def send_response(self, code: int, message: str | None = None) -> None:
        self.response_status = code
        super().send_response(code, message)

    def end_headers(self) -> None:
        self.send_header("X-Request-ID", self.request_id)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if self.app_server.hsts:
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        super().end_headers()

    def _host_valid(self) -> bool:
        host_header = self.headers.get("Host", "").strip()
        if not host_header:
            return False
        if host_header.startswith("["):
            host = host_header.split("]", 1)[0].lstrip("[")
        else:
            host = host_header.rsplit(":", 1)[0] if host_header.count(":") == 1 else host_header
        host = host.lower().rstrip(".")
        if host in self.app_server.allowed_hosts:
            return True
        try:
            address = ipaddress.ip_address(host)
            return address.is_loopback and self.app_server.loopback
        except ValueError:
            return False

    def _same_origin(self) -> bool:
        if self.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
            return False
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parsed = urlparse(origin)
        origin_host = parsed.hostname.lower().rstrip(".") if parsed.hostname else ""
        host_header = self.headers.get("Host", "")
        if host_header.startswith("["):
            request_host = host_header.split("]", 1)[0].lstrip("[")
        else:
            request_host = host_header.rsplit(":", 1)[0] if host_header.count(":") == 1 else host_header
        return secrets.compare_digest(origin_host, request_host.lower().rstrip("."))

    def _authorized(self) -> bool:
        token = self.app_server.auth_token
        if not token:
            return True
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        supplied = auth.removeprefix("Bearer ").strip()
        return secrets.compare_digest(supplied, token)

    def _preflight(self, *, mutating: bool = False, auth: bool = True) -> bool:
        if not self._host_valid():
            self._send_json({"error": "Invalid Host header", "request_id": self.request_id}, HTTPStatus.BAD_REQUEST)
            return False
        if urlparse(self.path).path.startswith("/api/") and not self.app_server.rate_limiter.allow(self.client_address[0]):
            self._send_json({"error": "Rate limit exceeded", "request_id": self.request_id}, HTTPStatus.TOO_MANY_REQUESTS)
            return False
        if mutating and not self._same_origin():
            self._send_json({"error": "Cross-site request rejected", "request_id": self.request_id}, HTTPStatus.FORBIDDEN)
            return False
        if auth and not self._authorized():
            self._send_json({"error": "Unauthorized", "request_id": self.request_id}, HTTPStatus.UNAUTHORIZED)
            return False
        return True

    def _send_json(self, data: Any, status: int = 200) -> None:
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_text(self, data: str, *, content_type: str = "text/plain; charset=utf-8", status: int = 200) -> None:
        payload = data.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid Content-Length") from exc
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("Invalid request body size")
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def _handle_error(self, exc: Exception, *, client_error: bool = False) -> None:
        if client_error:
            self._send_json({"error": str(exc), "request_id": self.request_id}, HTTPStatus.BAD_REQUEST)
            return
        LOGGER.exception("request_failed", extra={"request_id": self.request_id, "method": self.command, "path": self.path})
        self._send_json({"error": "Internal server error", "request_id": self.request_id}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _send_job_events(self, job: Job, offset: int) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        last_offset = max(0, offset)
        last_status = ""
        try:
            while True:
                snapshot = job.snapshot(last_offset)
                changed = snapshot["next_offset"] != last_offset or snapshot["status"] != last_status
                if changed:
                    payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
                    self.wfile.write(f"event: snapshot\ndata: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    last_offset = snapshot["next_offset"]
                    last_status = snapshot["status"]
                if snapshot["status"] in TERMINAL_STATES:
                    break
                with job.changed:
                    job.changed.wait(timeout=15)
                if not changed:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        public = path in {"/healthz", "/readyz"}
        if not self._preflight(auth=not public):
            return
        try:
            if path == "/healthz":
                self._send_json({"status": "ok", "version": APP_VERSION})
                return
            if path == "/readyz":
                health = self.app_server.manager.store.health()
                status = HTTPStatus.OK if health["ok"] else HTTPStatus.SERVICE_UNAVAILABLE
                self._send_json({"status": "ready" if health["ok"] else "not_ready", "database": health}, status)
                return
            if path == "/api/info":
                self._send_json({
                    "cwd": str(Path.cwd()), "home": str(Path.home()),
                    "allowed_roots": [str(item) for item in allowed_roots()],
                    "providers_file": str(self.app_server.registry.path),
                    "database": str(self.app_server.manager.store.path),
                    "version": APP_VERSION,
                    "parser": PARSER_VERSION,
                    "max_concurrent_jobs": MAX_CONCURRENT_JOBS,
                    "environment_policy": "allowlist" if os.getenv("PANEL_ALLOW_ANY_ENV", "0") != "1" else "allow-any-except-blocked",
                })
                return
            if path == "/api/files":
                target_cwd = validate_cwd(parse_qs(parsed.query).get("cwd", [""])[0] or None)
                file_items = []
                for p in sorted(target_cwd.iterdir()):
                    if p.name.startswith((".", "__pycache__", "venv")):
                        continue
                    file_items.append({"name": p.name, "is_dir": p.is_dir(), "size": p.stat().st_size if p.is_file() else 0})
                self._send_json({"cwd": str(target_cwd), "items": file_items[:200]})
                return
            if path == "/api/diff":
                target_cwd = validate_cwd(parse_qs(parsed.query).get("cwd", [""])[0] or None)
                code, output = run_capture(["git", "diff"], cwd=target_cwd, timeout=10)
                self._send_json({"cwd": str(target_cwd), "diff": output if code == 0 else ""})
                return
            if path == "/api/metrics":
                metrics = self.app_server.manager.metrics()
                lines = ["# HELP ai_cli_command_center_jobs Current jobs by status", "# TYPE ai_cli_command_center_jobs gauge"]
                lines.extend(f'ai_cli_command_center_jobs{{status="{status}"}} {count}' for status, count in sorted(metrics.items()))
                lines.append(f"ai_cli_command_center_max_concurrent_jobs {MAX_CONCURRENT_JOBS}")
                self._send_text("\n".join(lines) + "\n", content_type="text/plain; version=0.0.4; charset=utf-8")
                return
            if path == "/api/providers":
                include_missing = parse_qs(parsed.query).get("all", ["0"])[0] == "1"
                self._send_json({"providers": self.app_server.registry.list(include_missing=include_missing)})
                return
            if path.startswith("/api/providers/") and path.endswith("/schema"):
                provider_id = unquote(path.split("/")[3])
                query_values = parse_qs(parsed.query)
                command_path = [item for item in query_values.get("command", []) if item]
                refresh = query_values.get("refresh", ["0"])[0] == "1"
                self._send_json(self.app_server.registry.schema(provider_id, validate_command_path(command_path), refresh=refresh))
                return
            if path.startswith("/api/providers/") and path.endswith("/info"):
                provider_id = unquote(path.split("/")[3])
                self._send_json(self.app_server.registry.info(provider_id))
                return
            if path == "/api/presets":
                self._send_json({"presets": self.app_server.manager.store.list_presets()})
                return
            if path == "/api/workflows":
                self._send_json({"workflows": self.app_server.manager.store.list_workflows()})
                return
            if path == "/api/mcp":
                self._send_json({"mcp_servers": self.app_server.manager.store.list_mcp_servers()})
                return
            if path == "/api/worktrees":
                self._send_json({"worktrees": self.app_server.manager.store.list_worktrees()})
                return
            if path == "/api/github/pulls":
                target_cwd = validate_cwd(parse_qs(parsed.query).get("cwd", [""])[0] or None)
                code, output = run_capture(["gh", "pr", "list", "--json", "number,title,state,url"], cwd=target_cwd, timeout=10)
                try: pulls = json.loads(output) if code == 0 else []
                except Exception: pulls = []
                self._send_json({"pulls": pulls})
                return
            if path == "/api/jobs":
                self._send_json({"jobs": self.app_server.manager.list()})
                return
            if path.startswith("/api/jobs/") and path.endswith("/events"):
                job_id = path.split("/")[3]
                job = self.app_server.manager.get(job_id)
                if not job:
                    self._send_json({"error": "Job not found"}, HTTPStatus.NOT_FOUND)
                    return
                try:
                    offset = int(parse_qs(parsed.query).get("offset", ["0"])[0])
                except ValueError:
                    offset = 0
                self._send_job_events(job, offset)
                return
            if path.startswith("/api/jobs/"):
                job_id = path.split("/")[3]
                job = self.app_server.manager.get(job_id)
                if not job:
                    self._send_json({"error": "Job not found"}, HTTPStatus.NOT_FOUND)
                    return
                try:
                    offset = int(parse_qs(parsed.query).get("offset", ["0"])[0])
                except ValueError:
                    offset = 0
                self._send_json(job.snapshot(offset))
                return
        except (ValueError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            self._handle_error(exc, client_error=True)
            return
        except Exception as exc:  # noqa: BLE001
            self._handle_error(exc)
            return

        if path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not self._preflight(mutating=True):
            return
        try:
            if parsed.path == "/api/providers/probe":
                self._send_json(self.app_server.registry.probe(self._read_json()))
                return
            if parsed.path == "/api/providers":
                self._send_json(self.app_server.registry.add(self._read_json()), HTTPStatus.CREATED)
                return
            if parsed.path.startswith("/api/providers/") and parsed.path.endswith("/overlay"):
                provider_id = unquote(parsed.path.split("/")[3])
                overlay = self._read_json()
                self.app_server.manager.store.save_overlay(provider_id, overlay)
                self.app_server.registry.schema_cache.clear()
                self._send_json({"ok": True, "provider_id": provider_id, "overlay": overlay})
                return
            if parsed.path == "/api/presets":
                saved = self.app_server.manager.store.save_preset(self._read_json())
                self._send_json(saved, HTTPStatus.CREATED)
                return
            if parsed.path == "/api/workflows":
                saved = self.app_server.manager.store.save_workflow(self._read_json())
                self._send_json(saved, HTTPStatus.CREATED)
                return
            if parsed.path == "/api/mcp":
                saved = self.app_server.manager.store.save_mcp_server(self._read_json())
                self._send_json(saved, HTTPStatus.CREATED)
                return
            if parsed.path == "/api/worktrees":
                wt_input = self._read_json()
                path = wt_input.get("path") or f"/tmp/worktree-{os.urandom(4).hex()}"
                branch = wt_input.get("branch") or f"feature/{os.urandom(4).hex()}"
                code, out = run_capture(["git", "worktree", "add", "-b", branch, path], cwd=Path.cwd(), timeout=15)
                saved = self.app_server.manager.store.save_worktree({"path": path, "branch": branch, "status": "active" if code == 0 else "failed"})
                self._send_json({**saved, "output": out}, HTTPStatus.CREATED)
                return
            if parsed.path == "/api/github/pulls":
                pr_input = self._read_json()
                title = pr_input.get("title") or "Automated AI Update"
                body = pr_input.get("body") or "Generated by ZEAZ AI Command Center v3.0"
                code, out = run_capture(["gh", "pr", "create", "--title", title, "--body", body], cwd=Path.cwd(), timeout=20)
                self._send_json({"ok": code == 0, "output": out}, HTTPStatus.CREATED)
                return
            if parsed.path == "/api/update":
                code, out = run_capture(["git", "pull", "origin", "main"], cwd=Path.cwd(), timeout=30)
                self._send_json({"ok": code == 0, "output": out, "message": "Updated from GitHub origin/main" if code == 0 else "Update failed"})
                return
            if parsed.path == "/api/mfa/setup":
                import secrets
                secret = secrets.token_hex(16).upper()
                self.app_server.manager.store.save_mfa_secret("default_operator", secret, enabled=True)
                self._send_json({"ok": True, "user_id": "default_operator", "secret": secret, "otpauth_url": f"otpauth://totp/ZEAZ-Command-Center:default_operator?secret={secret}&issuer=ZEAZ"})
                return
            if parsed.path == "/api/mfa/verify":
                token = self._read_json().get("code", "")
                rec = self.app_server.manager.store.get_mfa_secret("default_operator")
                valid = bool(rec and rec["enabled"] and len(token) == 6)
                self._send_json({"ok": valid, "verified": valid})
                return
            if parsed.path == "/api/jobs":
                job = self.app_server.manager.create(self._read_json())
                self._send_json(job.snapshot(), HTTPStatus.ACCEPTED)
                return
            if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/input"):
                job_id = parsed.path.split("/")[3]
                user_input = self._read_json().get("input", "")
                job = self.app_server.manager.get(job_id)
                if not job or not job.process or job.process.poll() is not None:
                    self._send_json({"error": "Job is not running or process handle unavailable"}, HTTPStatus.CONFLICT)
                    return
                try:
                    if job.process.stdin:
                        job.process.stdin.write((user_input + "\n").encode("utf-8"))
                        job.process.stdin.flush()
                        self._send_json({"ok": True, "job_id": job_id, "relayed": user_input})
                        return
                except Exception as e:
                    self._send_json({"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                    return
                self._send_json({"error": "stdin not writeable"}, HTTPStatus.BAD_REQUEST)
                return
            if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/stop"):
                job_id = parsed.path.split("/")[3]
                if not self.app_server.manager.stop(job_id):
                    self._send_json({"error": "Job is not running"}, HTTPStatus.CONFLICT)
                    return
                self._send_json({"ok": True, "job_id": job_id})
                return
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
            self._handle_error(exc, client_error=True)
        except Exception as exc:  # noqa: BLE001
            self._handle_error(exc)

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not self._preflight(mutating=True):
            return
        try:
            if parsed.path.startswith("/api/providers/"):
                provider_id = unquote(parsed.path.split("/")[3])
                self.app_server.registry.remove(provider_id)
                self._send_json({"ok": True, "provider_id": provider_id})
                return
            if parsed.path.startswith("/api/presets/"):
                preset_id = unquote(parsed.path.split("/")[3])
                if not self.app_server.manager.store.delete_preset(preset_id):
                    self._send_json({"error": "Preset not found"}, HTTPStatus.NOT_FOUND)
                    return
                self._send_json({"ok": True, "preset_id": preset_id})
                return
            if parsed.path.startswith("/api/jobs/"):
                job_id = parsed.path.split("/")[3]
                if not self.app_server.manager.delete(job_id):
                    self._send_json({"error": "Job not found"}, HTTPStatus.NOT_FOUND)
                    return
                self._send_json({"ok": True, "job_id": job_id})
                return
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._handle_error(exc, client_error=True)
        except Exception as exc:  # noqa: BLE001
            self._handle_error(exc)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send_json({"error": "CORS is disabled"}, HTTPStatus.METHOD_NOT_ALLOWED)


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        handler: type[Handler],
        *,
        registry: ProviderRegistry,
        manager: JobManager,
        auth_token: str | None,
        allowed_hosts: set[str],
        loopback: bool,
        hsts: bool,
    ) -> None:
        super().__init__(address, handler)
        self.registry = registry
        self.manager = manager
        self.auth_token = auth_token
        self.allowed_hosts = allowed_hosts
        self.loopback = loopback
        self.hsts = hsts
        self.rate_limiter = RateLimiter(RATE_LIMIT_PER_MINUTE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Provider-agnostic AI CLI Command Center")
    parser.add_argument("--host", default=os.getenv("PANEL_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PANEL_PORT", "8765")))
    parser.add_argument("--token", default=os.getenv("PANEL_TOKEN"), help="Bearer token for API access")
    parser.add_argument("--database", default=os.getenv("PANEL_DATABASE_PATH"), help="SQLite database path")
    return parser.parse_args()


def is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def configured_allowed_hosts(bind_host: str, loopback: bool) -> set[str]:
    values = {item.strip().lower().rstrip(".") for item in os.getenv("PANEL_ALLOWED_HOSTS", "").split(",") if item.strip()}
    if loopback:
        values.update({"localhost", "127.0.0.1", "::1", bind_host.lower()})
    elif bind_host not in {"0.0.0.0", "::"}:
        values.add(bind_host.lower())
    if not values:
        raise SystemExit("PANEL_ALLOWED_HOSTS is required for wildcard/non-loopback binding")
    return values


def main() -> None:
    args = parse_args()
    loopback = is_loopback_host(args.host)
    if not loopback and not args.token:
        raise SystemExit("Refusing non-loopback bind without PANEL_TOKEN or --token")
    allowed_hosts = configured_allowed_hosts(args.host, loopback)
    registry = ProviderRegistry()
    store = JobStore(Path(args.database).expanduser().resolve() if args.database else None, max_output_bytes=MAX_OUTPUT_BYTES)
    manager = JobManager(registry, store)
    handler = functools.partial(Handler, directory=str(STATIC_DIR))
    server = AppServer(
        (args.host, args.port), handler, registry=registry, manager=manager,
        auth_token=args.token, allowed_hosts=allowed_hosts, loopback=loopback,
        hsts=os.getenv("PANEL_ENABLE_HSTS", "0") == "1",
    )
    LOGGER.info("server_started", extra={"path": f"http://{args.host}:{args.port}/", "status": APP_VERSION})
    LOGGER.info("security_policy", extra={"status": f"hosts={','.join(sorted(allowed_hosts))}; shell=false; env_allowlist=true"})
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        LOGGER.info("server_interrupted")
    finally:
        manager.shutdown()
        server.server_close()
        LOGGER.info("server_stopped")


if __name__ == "__main__":
    main()
