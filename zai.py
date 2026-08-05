#!/usr/bin/env python3
"""Compact CLI client for ZEAZ AI Command Center.

Examples:
    zai
    zai dashboard
    zai "Run tests and fix failures"
    zai --provider codex --model gpt-5.6 "Review this repository"
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

APP_NAME = "ai-cli-command-center"
SYSTEMD_USER_UNIT = f"{APP_NAME}.service"
STANDALONE_PID_FILENAME = "zai-server.pid"
TERMINAL_STATES = {"succeeded", "failed", "stopped", "timed_out", "orphaned"}
DEFAULT_PROVIDER_COMMAND_PATHS: dict[str, list[str]] = {"codex": ["exec"]}
DEFAULT_PROVIDER_RAW_ARGS: dict[str, list[str]] = {"claude": ["--print"]}
DEFAULT_LOCAL_PROVIDER = "ollama"
DEFAULT_LOCAL_MODEL = "qwen3-coder"
RATE_LIMIT_MARKERS = (
    "429",
    "rate limit",
    "rate-limit",
    "too many requests",
    "quota exceeded",
    "usage limit",
    "resource exhausted",
)


class ZaiError(RuntimeError):
    """User-facing CLI error."""


class ZaiHttpError(ZaiError):
    """HTTP error carrying status and retry metadata."""

    def __init__(self, status_code: int, detail: str, *, retry_after: float | None = None) -> None:
        super().__init__(f"Command Center returned HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail
        self.retry_after = retry_after


def config_dir() -> Path:
    return Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME


def state_dir() -> Path:
    return Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state")) / APP_NAME


def standalone_pid_path() -> Path:
    return state_dir() / STANDALONE_PID_FILENAME


def load_env_file(path: Path) -> dict[str, str]:
    """Read the simple KEY=VALUE subset used by panel.env without executing it."""
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not key.replace("_", "").isalnum() or not key[0].isalpha():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        result[key] = value
    return result


def runtime_settings() -> dict[str, str]:
    file_values = load_env_file(config_dir() / "panel.env")
    return {**file_values, **os.environ}


def default_url(settings: dict[str, str]) -> str:
    explicit = settings.get("ZAI_URL") or settings.get("PANEL_URL")
    if explicit:
        return explicit.rstrip("/")
    host = settings.get("PANEL_HOST", "127.0.0.1")
    if host in {"0.0.0.0", "::", "[::]"}:
        host = "127.0.0.1"
    port = settings.get("PANEL_PORT", "8765")
    return f"http://{host}:{port}"


def default_token(settings: dict[str, str]) -> str:
    return settings.get("ZAI_TOKEN") or settings.get("PANEL_TOKEN", "")


def bounded_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def setting_enabled(settings: dict[str, str], key: str, *, default: bool) -> bool:
    value = settings.get(key)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", "disabled"}


def local_endpoint(base_url: str) -> tuple[str, int] | None:
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    if parsed.scheme != "http" or host not in {"127.0.0.1", "localhost", "::1"}:
        return None
    return host, parsed.port or 80


class ApiClient:
    def __init__(self, base_url: str, token: str = "", timeout: float = 10.0) -> None:
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ZaiError(f"Invalid ZAI server URL: {base_url}")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        data = None
        headers = {
            "Accept": "application/json",
            "User-Agent": "zai-cli/1",
            "X-API-Version": "v1",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()
            detail = str(exc)
            retry_after: float | None = None
            try:
                decoded = json.loads(body.decode("utf-8"))
                if isinstance(decoded, dict):
                    detail = str(decoded.get("error", detail))
                    retry_after = bounded_float(
                        decoded.get("retry_after"), default=0.0, minimum=0.0, maximum=300.0
                    ) or None
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
            if retry_after is None:
                retry_after = bounded_float(
                    exc.headers.get("Retry-After"), default=0.0, minimum=0.0, maximum=300.0
                ) or None
            raise ZaiHttpError(exc.code, detail, retry_after=retry_after) from exc
        except urllib.error.URLError as exc:
            raise ZaiError(f"Cannot connect to {self.base_url}: {exc.reason}") from exc
        if not body:
            return {}
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ZaiError("Command Center returned an invalid JSON response") from exc

    def healthy(self) -> bool:
        try:
            result = self.request("GET", "/healthz")
        except ZaiError:
            return False
        return isinstance(result, dict) and result.get("status") == "ok"


def request_with_backoff(
    client: ApiClient,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    max_retries: int = 8,
) -> Any:
    """Retry only Command Center 429 responses; never retry other HTTP failures."""
    delay = 1.0
    for attempt in range(max_retries + 1):
        try:
            return client.request(method, path, payload)
        except ZaiHttpError as exc:
            if exc.status_code != 429 or attempt >= max_retries:
                raise
            wait = exc.retry_after if exc.retry_after is not None else delay
            wait = max(0.5, min(wait, 30.0))
            print(f"zai: Command Center busy; retrying in {wait:g}s", file=sys.stderr)
            time.sleep(wait)
            delay = min(delay * 2.0, 30.0)
    raise ZaiError("Command Center rate-limit retry loop ended unexpectedly")


def _current_uid() -> int | None:
    return os.getuid() if hasattr(os, "getuid") else None


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def read_standalone_record() -> dict[str, Any] | None:
    path = standalone_pid_path()
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        return None
    current_uid = _current_uid()
    if current_uid is not None and stat_result.st_uid != current_uid:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        pid = int(payload["pid"])
        server_path = str(payload["server_path"])
        base_url = str(payload["base_url"])
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        _safe_unlink(path)
        return None
    if not isinstance(payload, dict) or pid <= 1 or not server_path or not base_url:
        _safe_unlink(path)
        return None
    return payload


def _argument_value(argv: list[str], option: str) -> str | None:
    try:
        index = argv.index(option)
    except ValueError:
        return None
    return argv[index + 1] if index + 1 < len(argv) else None


def _process_start_ticks(pid: int) -> int | None:
    try:
        stat_text = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
        closing_paren = stat_text.rfind(")")
        if closing_paren < 0:
            return None
        fields_after_comm = stat_text[closing_paren + 2 :].split()
        return int(fields_after_comm[19])
    except (OSError, ValueError, IndexError):
        return None


def standalone_record_matches_process(record: dict[str, Any], *, base_url: str | None = None) -> bool:
    try:
        pid = int(record["pid"])
        recorded_uid = int(record.get("uid", -1))
        recorded_start_ticks = int(record.get("start_ticks", -1))
        server_path_raw = str(record["server_path"])
        recorded_url = str(record["base_url"]).rstrip("/")
    except (ValueError, TypeError, KeyError):
        return False
    if pid <= 1 or not server_path_raw or not recorded_url:
        return False
    if base_url is not None and recorded_url != base_url.rstrip("/"):
        return False
    current_uid = _current_uid()
    if current_uid is not None and recorded_uid != current_uid:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    if recorded_start_ticks < 0 or _process_start_ticks(pid) != recorded_start_ticks:
        return False

    proc_dir = Path("/proc") / str(pid)
    cmdline_path = proc_dir / "cmdline"
    if not cmdline_path.is_file():
        return False
    try:
        if current_uid is not None and proc_dir.stat().st_uid != current_uid:
            return False
        argv = [
            part.decode("utf-8", errors="surrogateescape")
            for part in cmdline_path.read_bytes().split(b"\0")
            if part
        ]
    except OSError:
        return False

    server_path = str(Path(server_path_raw).expanduser().resolve())
    if server_path not in argv:
        return False
    parsed = urllib.parse.urlparse(recorded_url)
    host = parsed.hostname or "127.0.0.1"
    port = str(parsed.port or 80)
    return _argument_value(argv, "--host") == host and _argument_value(argv, "--port") == port


def owned_standalone_pid(base_url: str) -> int | None:
    record = read_standalone_record()
    if record is None:
        return None
    if str(record.get("base_url", "")).rstrip("/") != base_url.rstrip("/"):
        return None
    if not standalone_record_matches_process(record, base_url=base_url):
        _safe_unlink(standalone_pid_path())
        return None
    return int(record["pid"])


def write_standalone_record(*, pid: int, server_path: Path, base_url: str) -> None:
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = standalone_pid_path()
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = {
        "pid": pid,
        "uid": _current_uid(),
        "start_ticks": _process_start_ticks(pid),
        "server_path": str(server_path.resolve()),
        "base_url": base_url.rstrip("/"),
        "started_at": int(time.time()),
    }
    temporary.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def stop_owned_standalone_server(base_url: str, *, timeout_seconds: float = 5.0) -> bool:
    record = read_standalone_record()
    if record is None:
        return False
    if str(record.get("base_url", "")).rstrip("/") != base_url.rstrip("/"):
        return False
    if not standalone_record_matches_process(record, base_url=base_url):
        _safe_unlink(standalone_pid_path())
        return False
    pid = int(record["pid"])
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not standalone_record_matches_process(record, base_url=base_url):
            break
        time.sleep(0.1)
    if standalone_record_matches_process(record, base_url=base_url):
        os.kill(pid, signal.SIGKILL)
    _safe_unlink(standalone_pid_path())
    return True


def _systemctl_user(*args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["systemctl", "--user", *args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def systemd_user_service_available() -> bool:
    result = _systemctl_user("show", SYSTEMD_USER_UNIT, "--property=LoadState", "--value")
    return result is not None and result.returncode == 0 and result.stdout.strip() == "loaded"


def systemd_user_service_state() -> tuple[bool, int]:
    result = _systemctl_user(
        "show",
        SYSTEMD_USER_UNIT,
        "--property=ActiveState",
        "--property=SubState",
        "--property=MainPID",
    )
    if result is None or result.returncode != 0:
        return False, 0
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key] = value
    try:
        pid = int(values.get("MainPID", "0"))
    except ValueError:
        pid = 0
    ready_state = values.get("ActiveState") == "active" and values.get("SubState") == "running"
    return ready_state and pid > 1, pid


def _pid_socket_inodes(pid: int) -> set[str]:
    result: set[str] = set()
    fd_dir = Path("/proc") / str(pid) / "fd"
    try:
        entries = list(fd_dir.iterdir())
    except OSError:
        return result
    for entry in entries:
        try:
            target = os.readlink(entry)
        except OSError:
            continue
        if target.startswith("socket:[") and target.endswith("]"):
            result.add(target[8:-1])
    return result


def _listening_socket_inodes(port: int) -> set[str]:
    result: set[str] = set()
    for table_path in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        try:
            lines = table_path.read_text(encoding="utf-8").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 10 or fields[3] != "0A":
                continue
            try:
                local_port = int(fields[1].rsplit(":", 1)[1], 16)
            except (IndexError, ValueError):
                continue
            if local_port == port:
                result.add(fields[9])
    return result


def pid_listens_on_port(pid: int, port: int) -> bool:
    if pid <= 1 or not 1 <= port <= 65535:
        return False
    process_sockets = _pid_socket_inodes(pid)
    return bool(process_sockets and process_sockets.intersection(_listening_socket_inodes(port)))


def systemd_user_service_ready(client: ApiClient) -> bool:
    endpoint = local_endpoint(client.base_url)
    if endpoint is None:
        return False
    _, port = endpoint
    active, main_pid = systemd_user_service_state()
    return active and pid_listens_on_port(main_pid, port) and client.healthy()


def start_systemd_user_service(client: ApiClient, wait_seconds: float = 15.0) -> None:
    result = _systemctl_user("start", SYSTEMD_USER_UNIT)
    if result is None:
        raise ZaiError("systemctl --user is unavailable; cannot start the installed service")
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit status {result.returncode}"
        raise ZaiError(f"Could not start {SYSTEMD_USER_UNIT}: {detail}")
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if systemd_user_service_ready(client):
            return
        time.sleep(0.25)
    raise ZaiError(
        f"{SYSTEMD_USER_UNIT} did not become ready or own the configured listener; inspect "
        f"journalctl --user -u {SYSTEMD_USER_UNIT} -n 100"
    )


def local_server_command(base_url: str) -> tuple[list[str], dict[str, str], Path]:
    endpoint = local_endpoint(base_url)
    if endpoint is None:
        raise ZaiError("Automatic startup is available only for a local HTTP dashboard")
    host, port = endpoint
    server_path = Path(__file__).resolve().with_name("server.py")
    if not server_path.is_file():
        raise ZaiError(f"server.py was not found beside the zai launcher: {server_path}")
    environment = os.environ.copy()
    environment.update(load_env_file(config_dir() / "panel.env"))
    environment["PANEL_HOST"] = host
    environment["PANEL_PORT"] = str(port)
    command = [sys.executable, str(server_path), "--host", host, "--port", str(port)]
    return command, environment, server_path.parent


def start_local_server(client: ApiClient, wait_seconds: float = 15.0) -> None:
    existing_pid = owned_standalone_pid(client.base_url)
    logs = state_dir()
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_path = logs / "zai-server.log"
    if existing_pid is not None:
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if client.healthy():
                return
            time.sleep(0.25)
        raise ZaiError(f"Tracked standalone server PID {existing_pid} did not become ready; inspect {log_path}")

    command, environment, working_directory = local_server_command(client.base_url)
    server_path = Path(command[1])
    with log_path.open("ab", buffering=0) as log_file:
        process = subprocess.Popen(
            command,
            cwd=working_directory,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    write_standalone_record(pid=process.pid, server_path=server_path, base_url=client.base_url)
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if client.healthy():
            return
        return_code = process.poll()
        if return_code is not None:
            _safe_unlink(standalone_pid_path())
            raise ZaiError(f"Dashboard exited with status {return_code}; inspect {log_path}")
        time.sleep(0.25)
    raise ZaiError(f"Dashboard did not become ready; inspect {log_path}")


def ensure_server(client: ApiClient, *, auto_start: bool) -> None:
    if not auto_start:
        if client.healthy():
            return
        raise ZaiError(f"Command Center is not reachable at {client.base_url}")

    endpoint = local_endpoint(client.base_url)
    if endpoint is not None and systemd_user_service_available():
        if systemd_user_service_ready(client):
            return
        stop_owned_standalone_server(client.base_url)
        start_systemd_user_service(client)
        return

    if client.healthy():
        return
    start_local_server(client)


def extract_job(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        if isinstance(payload.get("job"), dict):
            return payload["job"]
        if payload.get("id") or payload.get("job_id"):
            return payload
    raise ZaiError("Command Center did not return a job identifier")


def build_job_payload(args: argparse.Namespace, settings: dict[str, str], prompt: str) -> dict[str, Any]:
    provider = args.provider or settings.get("ZAI_PROVIDER") or "codex"
    command_path = list(args.command_path or DEFAULT_PROVIDER_COMMAND_PATHS.get(provider, []))
    raw_args = list(DEFAULT_PROVIDER_RAW_ARGS.get(provider, [])) + list(args.raw_arg or [])
    payload: dict[str, Any] = {
        "provider_id": provider,
        "cwd": str(Path(args.cwd).expanduser().resolve()),
        "prompt": prompt,
        "timeout_seconds": args.timeout,
        "priority": args.priority,
        "command_path": command_path,
        "raw_args": raw_args,
    }
    if args.model:
        payload["global_options"] = {"--model": args.model}
    return payload


def build_local_fallback_payload(
    args: argparse.Namespace,
    settings: dict[str, str],
    prompt: str,
) -> dict[str, Any]:
    provider = args.local_provider or settings.get("ZAI_LOCAL_PROVIDER") or DEFAULT_LOCAL_PROVIDER
    model = (
        args.local_model
        or settings.get("ZAI_LOCAL_MODEL")
        or settings.get("OLLAMA_MODEL")
        or DEFAULT_LOCAL_MODEL
    )
    payload: dict[str, Any] = {
        "provider_id": provider,
        "cwd": str(Path(args.cwd).expanduser().resolve()),
        "prompt": prompt,
        "timeout_seconds": args.timeout,
        "priority": args.priority,
        "raw_args": [],
    }
    if provider == "ollama":
        payload["command_path"] = ["run"]
        payload["positionals"] = [model]
    else:
        payload["command_path"] = list(DEFAULT_PROVIDER_COMMAND_PATHS.get(provider, []))
        if model:
            payload["global_options"] = {"--model": model}
    return payload


def render_dashboard(client: ApiClient, *, open_browser: bool, as_json: bool) -> int:
    ensure_server(client, auto_start=True)
    if as_json:
        analytics = request_with_backoff(client, "GET", "/api/analytics")
        load = request_with_backoff(client, "GET", "/api/load")
        print(json.dumps({"url": client.base_url, "analytics": analytics, "load": load}, indent=2))
        return 0
    print(f"Dashboard: {client.base_url}")
    if open_browser:
        webbrowser.open(client.base_url, new=2)
    return 0


def wait_for_job(
    client: ApiClient,
    job_id: str,
    *,
    as_json: bool,
    poll_interval: float,
    max_rate_limit_retries: int,
) -> tuple[dict[str, Any], str]:
    offset = 0
    final: dict[str, Any] = {}
    collected: list[str] = []
    consecutive_rate_limits = 0
    while True:
        try:
            payload = client.request("GET", f"/api/jobs/{urllib.parse.quote(job_id)}?offset={offset}")
            consecutive_rate_limits = 0
        except ZaiHttpError as exc:
            if exc.status_code != 429 or consecutive_rate_limits >= max_rate_limit_retries:
                raise
            delay = exc.retry_after or min(30.0, 2.0 ** consecutive_rate_limits)
            delay = max(0.5, delay)
            consecutive_rate_limits += 1
            print(f"zai: status polling rate-limited; resuming in {delay:g}s", file=sys.stderr)
            time.sleep(delay)
            continue
        job = extract_job(payload)
        final = job
        output = str(job.get("output") or "")
        if output:
            collected.append(output)
            if not as_json:
                print(output, end="", flush=True)
        next_offset = job.get("next_offset")
        if isinstance(next_offset, int):
            offset = next_offset
        status = str(job.get("status") or "")
        if status in TERMINAL_STATES:
            break
        time.sleep(poll_interval)
    return final, "".join(collected)


def job_rate_limited(job: dict[str, Any], output: str) -> bool:
    text = "\n".join((str(job.get("error") or ""), output)).lower()
    return any(marker in text for marker in RATE_LIMIT_MARKERS)


def print_job_result(job: dict[str, Any], *, as_json: bool, output: str) -> int:
    if as_json:
        print(json.dumps(job, indent=2))
    elif output and not output.endswith("\n"):
        print()
    status = str(job.get("status") or "failed")
    if status != "succeeded":
        error = job.get("error")
        if error:
            print(f"zai: {error}", file=sys.stderr)
        return 1
    return 0


def local_fallback_enabled(args: argparse.Namespace, settings: dict[str, str]) -> bool:
    if args.local_fallback is not None:
        return bool(args.local_fallback)
    return setting_enabled(settings, "ZAI_LOCAL_FALLBACK", default=True)


def submit_job(client: ApiClient, payload: dict[str, Any], *, max_retries: int) -> dict[str, Any]:
    return extract_job(
        request_with_backoff(client, "POST", "/api/jobs", payload, max_retries=max_retries)
    )


def submit_prompt(
    client: ApiClient,
    args: argparse.Namespace,
    settings: dict[str, str],
    prompt: str,
) -> int:
    ensure_server(client, auto_start=not args.no_start)
    poll_interval = bounded_float(
        args.poll_interval if args.poll_interval is not None else settings.get("ZAI_POLL_INTERVAL"),
        default=1.0,
        minimum=0.5,
        maximum=30.0,
    )
    max_rate_limit_retries = int(
        bounded_float(settings.get("ZAI_RATE_LIMIT_RETRIES"), default=8.0, minimum=0.0, maximum=30.0)
    )
    primary_payload = build_job_payload(args, settings, prompt)
    job = submit_job(client, primary_payload, max_retries=max_rate_limit_retries)
    job_id = str(job.get("id") or job.get("job_id") or "")
    if not job_id:
        raise ZaiError("Command Center returned an empty job identifier")
    if args.no_wait:
        if args.json:
            print(json.dumps(job, indent=2))
        else:
            print(job_id)
        return 0

    final, output = wait_for_job(
        client,
        job_id,
        as_json=args.json,
        poll_interval=poll_interval,
        max_rate_limit_retries=max_rate_limit_retries,
    )
    primary_provider = str(primary_payload.get("provider_id") or "")
    local_provider = args.local_provider or settings.get("ZAI_LOCAL_PROVIDER") or DEFAULT_LOCAL_PROVIDER
    should_fallback = (
        primary_provider != local_provider
        and local_fallback_enabled(args, settings)
        and str(final.get("status") or "") != "succeeded"
        and job_rate_limited(final, output)
    )
    if not should_fallback:
        return print_job_result(final, as_json=args.json, output=output)

    local_model = (
        args.local_model
        or settings.get("ZAI_LOCAL_MODEL")
        or settings.get("OLLAMA_MODEL")
        or DEFAULT_LOCAL_MODEL
    )
    print(
        f"zai: {primary_provider} rate-limited; falling back to local {local_provider}/{local_model}",
        file=sys.stderr,
    )
    fallback_payload = build_local_fallback_payload(args, settings, prompt)
    try:
        fallback_job = submit_job(client, fallback_payload, max_retries=max_rate_limit_retries)
    except ZaiError as exc:
        raise ZaiError(
            f"Local fallback could not start ({local_provider}/{local_model}): {exc}"
        ) from exc
    fallback_id = str(fallback_job.get("id") or fallback_job.get("job_id") or "")
    if not fallback_id:
        raise ZaiError("Command Center returned an empty local fallback job identifier")
    fallback_final, fallback_output = wait_for_job(
        client,
        fallback_id,
        as_json=args.json,
        poll_interval=poll_interval,
        max_rate_limit_retries=max_rate_limit_retries,
    )
    return print_job_result(fallback_final, as_json=args.json, output=fallback_output)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="zai",
        description="Run AI CLI jobs through ZEAZ AI Command Center or open its dashboard.",
        epilog='Examples: zai dashboard | zai "Run tests and fix failures" | zai --provider codex "Review code"',
    )
    result.add_argument("prompt", nargs="*", help="Prompt/command to execute; omit it to open the dashboard")
    result.add_argument("--dashboard", action="store_true", help="Open the web dashboard")
    result.add_argument("--no-open", action="store_true", help="Do not launch a browser for dashboard mode")
    result.add_argument("--url", help="Command Center URL (default: ZAI_URL or local panel URL)")
    result.add_argument("--token", help="Bearer token (default: ZAI_TOKEN/PANEL_TOKEN/panel.env)")
    result.add_argument("--provider", help="AI CLI provider ID (default: ZAI_PROVIDER or codex)")
    result.add_argument("--model", help="Provider model passed as --model")
    result.add_argument("--local-provider", help="Local fallback provider (default: ZAI_LOCAL_PROVIDER or ollama)")
    result.add_argument("--local-model", help="Local fallback model (default: ZAI_LOCAL_MODEL or qwen3-coder)")
    fallback_group = result.add_mutually_exclusive_group()
    fallback_group.add_argument(
        "--local-fallback", dest="local_fallback", action="store_true", help="Enable rate-limit fallback to local AI"
    )
    fallback_group.add_argument(
        "--no-local-fallback", dest="local_fallback", action="store_false", help="Disable local fallback"
    )
    result.set_defaults(local_fallback=None)
    result.add_argument("--cwd", default=os.getcwd(), help="Working directory for the job")
    result.add_argument("--timeout", type=int, default=3600, help="Job timeout in seconds")
    result.add_argument("--poll-interval", type=float, help="Status polling interval in seconds (minimum 0.5)")
    result.add_argument(
        "--priority", choices=("urgent", "normal", "background"), default="normal", help="Queue priority"
    )
    result.add_argument("--command-path", action="append", help="Provider subcommand token; may be repeated")
    result.add_argument("--raw-arg", action="append", help="Additional provider argument; may be repeated")
    result.add_argument("--no-wait", action="store_true", help="Print the job ID and return immediately")
    result.add_argument("--no-start", action="store_true", help="Do not automatically start a local server")
    result.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.timeout < 1:
        parser().error("--timeout must be at least 1 second")
    if args.poll_interval is not None and args.poll_interval < 0.5:
        parser().error("--poll-interval must be at least 0.5 seconds")
    settings = runtime_settings()
    client = ApiClient(args.url or default_url(settings), args.token or default_token(settings))
    prompt = " ".join(args.prompt).strip()
    dashboard_mode = args.dashboard or not prompt or prompt == "dashboard"
    try:
        if dashboard_mode:
            return render_dashboard(client, open_browser=not args.no_open, as_json=args.json)
        return submit_prompt(client, args, settings, prompt)
    except ZaiError as exc:
        print(f"zai: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
