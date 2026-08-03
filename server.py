#!/usr/bin/env python3
"""Local, provider-agnostic AI CLI Command Center.

It discovers AI command-line tools, parses ``--help`` output into a structured
schema, renders command builders in the browser, and executes argv arrays with
``shell=False``. The server binds to loopback by default.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import subprocess
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

from help_parser import parse_help

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
MAX_BODY_BYTES = 2_000_000
MAX_HELP_BYTES = int(os.getenv("PANEL_MAX_HELP_BYTES", str(2 * 1024 * 1024)))
MAX_OUTPUT_BYTES = int(os.getenv("PANEL_MAX_OUTPUT_BYTES", str(8 * 1024 * 1024)))
DEFAULT_TIMEOUT_SECONDS = int(os.getenv("PANEL_JOB_TIMEOUT_SECONDS", str(6 * 60 * 60)))
HELP_TIMEOUT_SECONDS = int(os.getenv("PANEL_HELP_TIMEOUT_SECONDS", "20"))
BINARY_RE = re.compile(r"^[A-Za-z0-9_.+-]+$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:+-]*$")
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

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
]

DANGEROUS_TOKENS = {
    "--dangerously-bypass-approvals-and-sandbox", "--dangerously-bypass-hook-trust",
    "--no-sandbox", "--unsafe", "--allow-all", "--skip-approval", "--skip-confirmation",
    "danger-full-access", "full-access",
}
DESTRUCTIVE_WORDS = {
    "delete", "remove", "logout", "uninstall", "reset", "purge", "destroy", "erase",
    "revoke", "archive", "unarchive", "apply", "update", "overwrite", "force",
}


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
    return roots


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
    return base / "ai-cli-command-center" / "providers.json"


def _provider_id(value: str) -> str:
    provider_id = re.sub(r"[^a-z0-9_.-]+", "-", value.lower()).strip("-")
    if not provider_id:
        raise ValueError("Provider id is empty")
    return provider_id[:80]


def resolve_executable(executable: Any) -> str:
    raw = safe_text(executable, max_len=4096).strip()
    if not raw:
        raise ValueError("Executable is required")
    if "/" in raw:
        if os.getenv("PANEL_ALLOW_ABSOLUTE_BINARIES", "0") != "1":
            raise ValueError("Absolute executable paths are disabled; set PANEL_ALLOW_ABSOLUTE_BINARIES=1 to enable")
        path = Path(raw).expanduser().resolve()
        if not path.is_absolute() or not path.exists() or not path.is_file() or not os.access(path, os.X_OK):
            raise ValueError(f"Executable is not runnable: {path}")
        return str(path)
    if not BINARY_RE.fullmatch(raw):
        raise ValueError("Executable name contains unsupported characters")
    resolved = shutil.which(raw)
    if not resolved:
        raise ValueError(f"Executable not found in PATH: {raw}")
    return resolved


def run_capture(argv: list[str], *, timeout: int = HELP_TIMEOUT_SECONDS) -> tuple[int, str]:
    env = os.environ.copy()
    env.setdefault("TERM", "dumb")
    env.setdefault("NO_COLOR", "1")
    env.setdefault("CLICOLOR", "0")
    result = subprocess.run(
        argv,
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


class ProviderRegistry:
    def __init__(self) -> None:
        self.path = provider_config_path()
        self.lock = threading.RLock()
        self.custom: dict[str, dict[str, Any]] = {}
        self.schema_cache: dict[tuple[str, tuple[str, ...]], tuple[float, dict[str, Any]]] = {}
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
                self.custom = {}

    def save(self) -> None:
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"providers": list(self.custom.values())}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.chmod(temporary, 0o600)
            temporary.replace(self.path)

    def list(self, *, include_missing: bool = False) -> list[dict[str, Any]]:
        providers: dict[str, dict[str, Any]] = {}
        for candidate in DEFAULT_CANDIDATES:
            resolved = shutil.which(candidate["executable"])
            if resolved or include_missing:
                providers[candidate["id"]] = {
                    **candidate,
                    "resolved": resolved,
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
            version = ""
        return {
            "id": _provider_id(safe_text(payload.get("id") or Path(executable_input).name, max_len=80)),
            "name": safe_text(payload.get("name") or schema.get("title") or Path(executable_input).name, max_len=120),
            "executable": executable_input,
            "resolved": resolved,
            "installed": True,
            "help_args": help_args,
            "version_args": version_args,
            "version": version,
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
        }
        with self.lock:
            self.custom[item["id"]] = item
            self.schema_cache.clear()
            self.save()
        return {**item, "resolved": probed["resolved"], "installed": True, "custom": True, "version": probed["version"], "schema": probed["schema"]}

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
        with self.lock:
            self.schema_cache[key] = (time.time(), schema)
        return schema

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
        return {**provider, "resolved": resolved, "version": version, "error": error}


def validate_command_path(value: Any) -> list[str]:
    parts = list_of_text(value, max_items=6, max_len=80)
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
        canonical = option["flag"]
        if canonical in used:
            continue
        used.add(canonical)
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
        if item in {"danger-full-access", "full-access", "unsandboxed"}:
            return "dangerous"
        if normalized in DESTRUCTIVE_WORDS:
            destructive = True
    return "destructive" if destructive else "normal"


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
    prompt = safe_text(payload.get("prompt"), max_len=200_000)
    # Risk is derived from executable controls, command path, and flag-like
    # raw arguments. Prompt and ordinary positional text must not accidentally
    # trigger confirmation gates merely because they discuss risky concepts.
    risk_argv = [*argv, *[item for item in raw_args if item.startswith("-")]]
    argv.extend(positionals)
    argv.extend(raw_args)
    if prompt:
        argv.append(prompt)

    env_overrides = payload.get("environment") or {}
    if not isinstance(env_overrides, dict):
        raise ValueError("environment must be an object")
    for key, value in env_overrides.items():
        if not ENV_KEY_RE.fullmatch(str(key)):
            raise ValueError(f"Invalid environment variable name: {key}")
        safe_text(value, max_len=20_000)

    risk = detect_risk(risk_argv)
    confirmation = safe_text(payload.get("confirmation"), max_len=64)
    if risk == "dangerous" and confirmation != "I UNDERSTAND":
        raise ValueError("Dangerous execution requires confirmation text: I UNDERSTAND")
    if risk == "destructive" and confirmation != "CONFIRM":
        raise ValueError("Destructive execution requires confirmation text: CONFIRM")
    return argv, cwd, risk


@dataclass
class Job:
    id: str
    provider_id: str
    argv: list[str]
    cwd: str
    created_at: float
    environment: dict[str, str] = field(default_factory=dict)
    risk: str = "normal"
    status: str = "queued"
    started_at: float | None = None
    finished_at: float | None = None
    return_code: int | None = None
    error: str | None = None
    output: bytearray = field(default_factory=bytearray)
    output_base: int = 0
    process: subprocess.Popen[bytes] | None = field(default=None, repr=False)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def append(self, data: bytes) -> None:
        with self.lock:
            self.output.extend(data)
            if len(self.output) > MAX_OUTPUT_BYTES:
                remove = len(self.output) - MAX_OUTPUT_BYTES
                del self.output[:remove]
                self.output_base += remove

    def snapshot(self, offset: int = 0) -> dict[str, Any]:
        with self.lock:
            effective = max(offset, self.output_base)
            start = effective - self.output_base
            chunk = bytes(self.output[start:]).decode("utf-8", errors="replace")
            next_offset = self.output_base + len(self.output)
        return {
            "id": self.id,
            "provider_id": self.provider_id,
            "argv": self.argv,
            "cwd": self.cwd,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "return_code": self.return_code,
            "error": self.error,
            "risk": self.risk,
            "output": chunk,
            "next_offset": next_offset,
            "output_truncated": offset < self.output_base,
        }


class JobManager:
    def __init__(self, registry: ProviderRegistry) -> None:
        self.registry = registry
        self.jobs: dict[str, Job] = {}
        self.order: deque[str] = deque(maxlen=100)
        self.lock = threading.Lock()

    def create(self, payload: dict[str, Any]) -> Job:
        argv, cwd, risk = build_ai_command(payload, self.registry)
        environment = payload.get("environment") or {}
        job = Job(
            id=uuid.uuid4().hex[:12], provider_id=safe_text(payload.get("provider_id"), max_len=80),
            argv=argv, cwd=str(cwd), created_at=time.time(),
            environment={str(key): str(value) for key, value in environment.items()}, risk=risk,
        )
        with self.lock:
            self.jobs[job.id] = job
            self.order.appendleft(job.id)
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _run(self, job: Job) -> None:
        job.status = "running"
        job.started_at = time.time()
        env = os.environ.copy()
        env.update(job.environment)
        env.setdefault("TERM", "dumb")
        env.setdefault("NO_COLOR", "1")
        env.setdefault("CLICOLOR", "0")
        try:
            process = subprocess.Popen(
                job.argv, cwd=job.cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=False,
                start_new_session=True,
            )
            job.process = process
            assert process.stdout is not None
            deadline = time.monotonic() + DEFAULT_TIMEOUT_SECONDS
            while True:
                chunk = process.stdout.read(4096)
                if chunk:
                    job.append(chunk)
                if process.poll() is not None:
                    remaining = process.stdout.read()
                    if remaining:
                        job.append(remaining)
                    break
                if time.monotonic() > deadline:
                    self.stop(job.id)
                    job.error = f"Job exceeded timeout of {DEFAULT_TIMEOUT_SECONDS} seconds"
                    break
            job.return_code = process.wait(timeout=10)
            if job.status != "stopped":
                job.status = "succeeded" if job.return_code == 0 else "failed"
        except FileNotFoundError:
            job.status = "failed"
            job.error = f"Executable not found: {job.argv[0]}"
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.error = str(exc)
            job.append((f"\n[command-center] {exc}\n").encode())
        finally:
            job.finished_at = time.time()
            job.process = None

    def get(self, job_id: str) -> Job | None:
        with self.lock:
            return self.jobs.get(job_id)

    def list(self) -> list[dict[str, Any]]:
        with self.lock:
            ids = list(self.order)
        return [self.jobs[job_id].snapshot(10**18) for job_id in ids if job_id in self.jobs]

    def stop(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or not job.process or job.process.poll() is not None:
            return False
        try:
            os.killpg(job.process.pid, signal.SIGTERM)
            try:
                job.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(job.process.pid, signal.SIGKILL)
            job.status = "stopped"
            job.finished_at = time.time()
            return True
        except ProcessLookupError:
            return False


class Handler(SimpleHTTPRequestHandler):
    server_version = "AICommandCenter/2.0"

    @property
    def app_server(self) -> "AppServer":
        return self.server  # type: ignore[return-value]

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")

    def _authorized(self) -> bool:
        token = self.app_server.auth_token
        if not token:
            return True
        auth = self.headers.get("Authorization", "")
        if auth == f"Bearer {token}":
            return True
        query_token = parse_qs(urlparse(self.path).query).get("token", [""])[0]
        return secrets.compare_digest(query_token, token)

    def _send_json(self, data: Any, status: int = 200) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(payload)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("Invalid request body size")
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def _require_auth(self) -> bool:
        if self._authorized():
            return True
        self._send_json({"error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
        return False

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/") and not self._require_auth():
            return
        try:
            if path == "/api/info":
                self._send_json({
                    "cwd": str(Path.cwd()), "home": str(Path.home()),
                    "allowed_roots": [str(item) for item in allowed_roots()],
                    "providers_file": str(self.app_server.registry.path),
                    "version": "2.0.0",
                })
                return
            if path == "/api/providers":
                include_missing = parse_qs(parsed.query).get("all", ["0"])[0] == "1"
                self._send_json({"providers": self.app_server.registry.list(include_missing=include_missing)})
                return
            if path.startswith("/api/providers/") and path.endswith("/schema"):
                provider_id = unquote(path.split("/")[3])
                query = parse_qs(parsed.query)
                command_path = [item for item in query.get("command", []) if item]
                refresh = query.get("refresh", ["0"])[0] == "1"
                self._send_json(self.app_server.registry.schema(provider_id, validate_command_path(command_path), refresh=refresh))
                return
            if path.startswith("/api/providers/") and path.endswith("/info"):
                provider_id = unquote(path.split("/")[3])
                self._send_json(self.app_server.registry.info(provider_id))
                return
            if path == "/api/jobs":
                self._send_json({"jobs": self.app_server.manager.list()})
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
        except (ValueError, subprocess.TimeoutExpired) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not self._require_auth():
            return
        try:
            if parsed.path == "/api/providers/probe":
                self._send_json(self.app_server.registry.probe(self._read_json()))
                return
            if parsed.path == "/api/providers":
                self._send_json(self.app_server.registry.add(self._read_json()), HTTPStatus.CREATED)
                return
            if parsed.path == "/api/jobs":
                job = self.app_server.manager.create(self._read_json())
                self._send_json(job.snapshot(), HTTPStatus.ACCEPTED)
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
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if not self._require_auth():
            return
        try:
            if parsed.path.startswith("/api/providers/"):
                provider_id = unquote(parsed.path.split("/")[3])
                self.app_server.registry.remove(provider_id)
                self._send_json({"ok": True, "provider_id": provider_id})
                return
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)


class AppServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], handler: type[Handler], *, registry: ProviderRegistry, manager: JobManager, auth_token: str | None):
        super().__init__(address, handler)
        self.registry = registry
        self.manager = manager
        self.auth_token = auth_token


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Provider-agnostic AI CLI Command Center")
    parser.add_argument("--host", default=os.getenv("PANEL_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PANEL_PORT", "8765")))
    parser.add_argument("--token", default=os.getenv("PANEL_TOKEN"), help="Bearer token for API access")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    is_loopback = args.host in {"127.0.0.1", "localhost", "::1"}
    if not is_loopback and not args.token:
        raise SystemExit("Refusing non-loopback bind without PANEL_TOKEN or --token")
    registry = ProviderRegistry()
    manager = JobManager(registry)
    handler = functools.partial(Handler, directory=str(STATIC_DIR))
    server = AppServer((args.host, args.port), handler, registry=registry, manager=manager, auth_token=args.token)
    print("AI CLI Command Center v2.0.0")
    print(f"URL: http://{args.host}:{args.port}/")
    print(f"Providers: {len(registry.list())} installed")
    print("Allowed roots: " + ", ".join(map(str, allowed_roots())))
    print("Execution: argv only, shell=False")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
