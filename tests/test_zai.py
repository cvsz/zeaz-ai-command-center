import json
import os
from pathlib import Path

import pytest

import zai


class FakeClient:
    def __init__(self, responses=None):
        self.base_url = "http://127.0.0.1:8765"
        self.responses = list(responses or [])
        self.calls = []

    def healthy(self):
        return True

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if not self.responses:
            raise AssertionError(f"Unexpected request: {method} {path}")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class HealthClient:
    def __init__(self, values):
        self.base_url = "http://127.0.0.1:8765"
        self.values = list(values)

    def healthy(self):
        if len(self.values) > 1:
            return self.values.pop(0)
        return self.values[0]


def test_load_env_file_without_executing_shell(tmp_path: Path):
    path = tmp_path / "panel.env"
    path.write_text(
        "# ignored\nexport PANEL_TOKEN='secret token'\nPANEL_PORT=9000\nINVALID LINE\n",
        encoding="utf-8",
    )
    assert zai.load_env_file(path) == {"PANEL_TOKEN": "secret token", "PANEL_PORT": "9000"}


def test_default_url_uses_localhost_for_wildcard_bind():
    assert zai.default_url({"PANEL_HOST": "0.0.0.0", "PANEL_PORT": "9000"}) == "http://127.0.0.1:9000"
    assert zai.default_url({"ZAI_URL": "https://panel.example/"}) == "https://panel.example"


def test_ensure_server_prefers_installed_systemd_service(monkeypatch):
    client = HealthClient([False])
    events = []
    monkeypatch.setattr(zai, "systemd_user_service_available", lambda: True)
    monkeypatch.setattr(zai, "systemd_user_service_ready", lambda _client: False)
    monkeypatch.setattr(
        zai,
        "stop_owned_standalone_server",
        lambda url: events.append(("stop", url)) or False,
    )
    monkeypatch.setattr(
        zai,
        "start_systemd_user_service",
        lambda value: events.append(("systemd", value.base_url)),
    )
    monkeypatch.setattr(
        zai,
        "start_local_server",
        lambda _client: pytest.fail("must not spawn standalone when a user unit is installed"),
    )

    zai.ensure_server(client, auto_start=True)

    assert events == [("stop", client.base_url), ("systemd", client.base_url)]


def test_ensure_server_falls_back_to_standalone_without_user_unit(monkeypatch):
    client = HealthClient([False])
    started = []
    monkeypatch.setattr(zai, "systemd_user_service_available", lambda: False)
    monkeypatch.setattr(zai, "start_local_server", lambda value: started.append(value.base_url))

    zai.ensure_server(client, auto_start=True)

    assert started == [client.base_url]


def test_no_start_uses_existing_server_without_systemd_probe(monkeypatch):
    client = HealthClient([True])
    monkeypatch.setattr(
        zai,
        "systemd_user_service_available",
        lambda: pytest.fail("--no-start must not start or probe a service"),
    )

    zai.ensure_server(client, auto_start=False)


def test_stale_standalone_pid_record_is_removed(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(zai, "state_dir", lambda: tmp_path)
    path = zai.standalone_pid_path()
    path.write_text(
        json.dumps(
            {
                "pid": 99999999,
                "uid": zai._current_uid(),
                "server_path": "/tmp/server.py",
                "base_url": "http://127.0.0.1:8765",
            }
        ),
        encoding="utf-8",
    )

    assert zai.owned_standalone_pid("http://127.0.0.1:8765") is None
    assert not path.exists()


def test_unrelated_process_is_never_terminated(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(zai, "state_dir", lambda: tmp_path)
    path = zai.standalone_pid_path()
    path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "uid": zai._current_uid(),
                "server_path": "/tmp/not-this-process-server.py",
                "base_url": "http://127.0.0.1:8765",
            }
        ),
        encoding="utf-8",
    )
    signals = []
    monkeypatch.setattr(zai.os, "kill", lambda pid, sig: signals.append((pid, sig)))

    assert zai.stop_owned_standalone_server("http://127.0.0.1:8765") is False

    assert signals == [(os.getpid(), 0)]
    assert not path.exists()


def test_start_local_server_tracks_spawned_pid(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(zai, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(zai, "owned_standalone_pid", lambda _url: None)
    server_path = tmp_path / "server.py"
    server_path.write_text("# server\n", encoding="utf-8")
    monkeypatch.setattr(
        zai,
        "local_server_command",
        lambda _url: (
            ["python3", str(server_path), "--host", "127.0.0.1", "--port", "8765"],
            {},
            tmp_path,
        ),
    )

    class Process:
        pid = 4242

        def poll(self):
            return None

    monkeypatch.setattr(zai.subprocess, "Popen", lambda *args, **kwargs: Process())
    client = HealthClient([True])

    zai.start_local_server(client, wait_seconds=0.1)

    record = json.loads(zai.standalone_pid_path().read_text(encoding="utf-8"))
    assert record["pid"] == 4242
    assert record["server_path"] == str(server_path.resolve())


def test_codex_payload_uses_exec_and_current_workspace(tmp_path: Path):
    args = zai.parser().parse_args(["--cwd", str(tmp_path), "Review", "this", "repository"])
    payload = zai.build_job_payload(args, {}, "Review this repository")
    assert payload["provider_id"] == "codex"
    assert payload["command_path"] == ["exec"]
    assert payload["cwd"] == str(tmp_path.resolve())
    assert payload["prompt"] == "Review this repository"


def test_provider_and_model_overrides(tmp_path: Path):
    args = zai.parser().parse_args(
        ["--provider", "gemini", "--model", "gemini-pro", "--cwd", str(tmp_path), "Explain", "code"]
    )
    payload = zai.build_job_payload(args, {}, "Explain code")
    assert payload["provider_id"] == "gemini"
    assert payload["command_path"] == []
    assert payload["global_options"] == {"--model": "gemini-pro"}


def test_local_fallback_payload_uses_ollama_run_model(tmp_path: Path):
    args = zai.parser().parse_args(
        ["--cwd", str(tmp_path), "--local-model", "qwen3:8b", "Explain", "code"]
    )
    payload = zai.build_local_fallback_payload(args, {}, "Explain code")
    assert payload["provider_id"] == "ollama"
    assert payload["command_path"] == ["run"]
    assert payload["positionals"] == ["qwen3:8b"]
    assert payload["prompt"] == "Explain code"


def test_extract_job_accepts_wrapped_and_direct_payloads():
    assert zai.extract_job({"job": {"id": "abc"}})["id"] == "abc"
    assert zai.extract_job({"id": "xyz"})["id"] == "xyz"
    with pytest.raises(zai.ZaiError):
        zai.extract_job({"status": "ok"})


def test_request_with_backoff_retries_only_429(monkeypatch, capsys):
    client = FakeClient([zai.ZaiHttpError(429, "Rate limit exceeded", retry_after=0.5), {"ok": True}])
    sleeps = []
    monkeypatch.setattr(zai.time, "sleep", sleeps.append)
    assert zai.request_with_backoff(client, "POST", "/api/jobs", {"prompt": "x"}) == {"ok": True}
    assert sleeps == [0.5]
    assert "retrying in 0.5s" in capsys.readouterr().err


def test_request_with_backoff_does_not_retry_other_http_errors(monkeypatch):
    client = FakeClient([zai.ZaiHttpError(401, "Unauthorized")])
    monkeypatch.setattr(zai.time, "sleep", lambda _seconds: pytest.fail("must not sleep"))
    with pytest.raises(zai.ZaiHttpError, match="HTTP 401"):
        zai.request_with_backoff(client, "POST", "/api/jobs", {})


def test_dashboard_opens_browser(monkeypatch, capsys):
    client = FakeClient()
    opened = []
    monkeypatch.setattr(zai, "ensure_server", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(zai.webbrowser, "open", lambda url, new=0: opened.append((url, new)))
    assert zai.render_dashboard(client, open_browser=True, as_json=False) == 0
    assert opened == [(client.base_url, 2)]
    assert "Dashboard: http://127.0.0.1:8765" in capsys.readouterr().out


def test_dashboard_json_combines_analytics_and_load(monkeypatch, capsys):
    client = FakeClient([{"total_jobs": 4}, {"queue_depth": 1}])
    monkeypatch.setattr(zai, "ensure_server", lambda *_args, **_kwargs: None)
    assert zai.render_dashboard(client, open_browser=False, as_json=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["analytics"]["total_jobs"] == 4
    assert payload["load"]["queue_depth"] == 1


def test_submit_prompt_streams_job_output(monkeypatch, tmp_path: Path, capsys):
    client = FakeClient(
        [
            {"job": {"id": "job123"}},
            {"id": "job123", "status": "running", "output": "hello ", "next_offset": 6},
            {"id": "job123", "status": "succeeded", "output": "world\n", "next_offset": 12},
        ]
    )
    args = zai.parser().parse_args(["--cwd", str(tmp_path), "hello"])
    monkeypatch.setattr(zai, "ensure_server", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(zai.time, "sleep", lambda _seconds: None)
    assert zai.submit_prompt(client, args, {}, "hello") == 0
    assert capsys.readouterr().out == "hello world\n"
    method, path, payload = client.calls[0]
    assert (method, path) == ("POST", "/api/jobs")
    assert payload["provider_id"] == "codex"


def test_status_polling_429_backs_off_and_resumes(monkeypatch, tmp_path: Path, capsys):
    client = FakeClient(
        [
            {"job": {"id": "job-rate"}},
            zai.ZaiHttpError(429, "Rate limit exceeded", retry_after=0.5),
            {"id": "job-rate", "status": "succeeded", "output": "done\n", "next_offset": 5},
        ]
    )
    sleeps = []
    args = zai.parser().parse_args(["--cwd", str(tmp_path), "hello"])
    monkeypatch.setattr(zai, "ensure_server", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(zai.time, "sleep", sleeps.append)
    assert zai.submit_prompt(client, args, {}, "hello") == 0
    captured = capsys.readouterr()
    assert captured.out == "done\n"
    assert "status polling rate-limited" in captured.err
    assert sleeps == [0.5]
    assert len([call for call in client.calls if call[0] == "POST"]) == 1


def test_provider_rate_limit_falls_back_to_local_ollama(monkeypatch, tmp_path: Path, capsys):
    client = FakeClient(
        [
            {"job": {"id": "cloud-job"}},
            {
                "id": "cloud-job",
                "provider_id": "codex",
                "status": "failed",
                "error": "provider exited with 1",
                "output": "HTTP 429 rate limit exceeded\n",
                "next_offset": 29,
            },
            {"job": {"id": "local-job"}},
            {
                "id": "local-job",
                "provider_id": "ollama",
                "status": "succeeded",
                "output": "local result\n",
                "next_offset": 13,
            },
        ]
    )
    args = zai.parser().parse_args(
        ["--cwd", str(tmp_path), "--local-model", "qwen3:8b", "fix", "tests"]
    )
    monkeypatch.setattr(zai, "ensure_server", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(zai.time, "sleep", lambda _seconds: None)
    assert zai.submit_prompt(client, args, {}, "fix tests") == 0
    captured = capsys.readouterr()
    assert "HTTP 429 rate limit exceeded" in captured.out
    assert "local result" in captured.out
    assert "falling back to local ollama/qwen3:8b" in captured.err
    posts = [call for call in client.calls if call[0] == "POST"]
    assert len(posts) == 2
    fallback = posts[1][2]
    assert fallback["provider_id"] == "ollama"
    assert fallback["command_path"] == ["run"]
    assert fallback["positionals"] == ["qwen3:8b"]


def test_generic_provider_failure_does_not_fallback(monkeypatch, tmp_path: Path):
    client = FakeClient(
        [
            {"job": {"id": "cloud-job"}},
            {
                "id": "cloud-job",
                "provider_id": "codex",
                "status": "failed",
                "error": "invalid prompt",
                "output": "",
                "next_offset": 0,
            },
        ]
    )
    args = zai.parser().parse_args(["--cwd", str(tmp_path), "hello"])
    monkeypatch.setattr(zai, "ensure_server", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(zai.time, "sleep", lambda _seconds: None)
    assert zai.submit_prompt(client, args, {}, "hello") == 1
    assert len([call for call in client.calls if call[0] == "POST"]) == 1


def test_no_wait_prints_job_id(monkeypatch, tmp_path: Path, capsys):
    client = FakeClient([{"id": "job456", "status": "queued"}])
    args = zai.parser().parse_args(["--no-wait", "--cwd", str(tmp_path), "hello"])
    monkeypatch.setattr(zai, "ensure_server", lambda *_args, **_kwargs: None)
    assert zai.submit_prompt(client, args, {}, "hello") == 0
    assert capsys.readouterr().out.strip() == "job456"


def test_main_without_prompt_uses_dashboard(monkeypatch):
    observed = {}

    class StubClient:
        def __init__(self, url, token):
            observed["url"] = url
            observed["token"] = token

    monkeypatch.setattr(zai, "runtime_settings", lambda: {"ZAI_URL": "http://127.0.0.1:9999", "ZAI_TOKEN": "t"})
    monkeypatch.setattr(zai, "ApiClient", StubClient)
    monkeypatch.setattr(
        zai,
        "render_dashboard",
        lambda client, open_browser, as_json: observed.update(
            {"dashboard": True, "open_browser": open_browser, "as_json": as_json}
        )
        or 0,
    )
    assert zai.main(["--no-open"]) == 0
    assert observed == {
        "url": "http://127.0.0.1:9999",
        "token": "t",
        "dashboard": True,
        "open_browser": False,
        "as_json": False,
    }
