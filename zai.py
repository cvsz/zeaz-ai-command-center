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
import shlex
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
TERMINAL_STATES = {"succeeded", "failed", "stopped", "timed_out", "orphaned"}
DEFAULT_PROVIDER_COMMAND_PATHS: dict[str, list[str]] = {"codex": ["exec"]}
DEFAULT_PROVIDER_RAW_ARGS: dict[str, list[str]] = {"claude": ["--print"]}


class ZaiError(RuntimeError):
    """User-facing CLI error."""


def config_dir() -> Path:
    return Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME


def state_dir() -> Path:
    return Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state")) / APP_NAME


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
            try:
                detail = json.loads(body.decode("utf-8")).get("error", str(exc))
            except (UnicodeDecodeError, json.JSONDecodeError):
                detail = str(exc)
            raise ZaiError(f"Command Center returned HTTP {exc.code}: {detail}") from exc
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


def local_server_command(base_url: str) -> tuple[list[str], dict[str, str], Path]:
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    if parsed.scheme != "http" or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ZaiError("Automatic startup is available only for a local HTTP dashboard")
    port = parsed.port or 80
    server_path = Path(__file__).resolve().with_name("server.py")
    if not server_path.is_file():
        raise ZaiError(f"server.py was not found beside the zai launcher: {server_path}")
    settings = runtime_settings()
    environment = os.environ.copy()
    environment.update(load_env_file(config_dir() / "panel.env"))
    environment["PANEL_HOST"] = host
    environment["PANEL_PORT"] = str(port)
    command = [sys.executable, str(server_path), "--host", host, "--port", str(port)]
    return command, environment, server_path.parent


def start_local_server(client: ApiClient, wait_seconds: float = 15.0) -> None:
    command, environment, working_directory = local_server_command(client.base_url)
    logs = state_dir()
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_path = logs / "zai-server.log"
    with log_path.open("ab", buffering=0) as log_file:
        subprocess.Popen(
            command,
            cwd=working_directory,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if client.healthy():
            return
        time.sleep(0.25)
    raise ZaiError(f"Dashboard did not become ready; inspect {log_path}")


def ensure_server(client: ApiClient, *, auto_start: bool) -> None:
    if client.healthy():
        return
    if not auto_start:
        raise ZaiError(f"Command Center is not reachable at {client.base_url}")
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


def render_dashboard(client: ApiClient, *, open_browser: bool, as_json: bool) -> int:
    ensure_server(client, auto_start=True)
    if as_json:
        analytics = client.request("GET", "/api/analytics")
        load = client.request("GET", "/api/load")
        print(json.dumps({"url": client.base_url, "analytics": analytics, "load": load}, indent=2))
        return 0
    print(f"Dashboard: {client.base_url}")
    if open_browser:
        webbrowser.open(client.base_url, new=2)
    return 0


def stream_job(client: ApiClient, job_id: str, *, as_json: bool) -> int:
    offset = 0
    final: dict[str, Any] = {}
    wrote_output = False
    while True:
        payload = client.request("GET", f"/api/jobs/{urllib.parse.quote(job_id)}?offset={offset}")
        job = extract_job(payload)
        final = job
        output = str(job.get("output") or "")
        if output and not as_json:
            print(output, end="", flush=True)
            wrote_output = True
        next_offset = job.get("next_offset")
        if isinstance(next_offset, int):
            offset = next_offset
        status = str(job.get("status") or "")
        if status in TERMINAL_STATES:
            break
        time.sleep(0.2)
    if as_json:
        print(json.dumps(final, indent=2))
    elif wrote_output and not str(final.get("output") or "").endswith("\n"):
        print()
    status = str(final.get("status") or "failed")
    if status != "succeeded":
        error = final.get("error")
        if error:
            print(f"zai: {error}", file=sys.stderr)
        return 1
    return 0


def submit_prompt(
    client: ApiClient,
    args: argparse.Namespace,
    settings: dict[str, str],
    prompt: str,
) -> int:
    ensure_server(client, auto_start=not args.no_start)
    job = extract_job(client.request("POST", "/api/jobs", build_job_payload(args, settings, prompt)))
    job_id = str(job.get("id") or job.get("job_id") or "")
    if not job_id:
        raise ZaiError("Command Center returned an empty job identifier")
    if args.no_wait:
        if args.json:
            print(json.dumps(job, indent=2))
        else:
            print(job_id)
        return 0
    return stream_job(client, job_id, as_json=args.json)


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
    result.add_argument("--cwd", default=os.getcwd(), help="Working directory for the job")
    result.add_argument("--timeout", type=int, default=3600, help="Job timeout in seconds")
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
