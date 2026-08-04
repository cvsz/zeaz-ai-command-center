import argparse
import json
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
        return self.responses.pop(0)


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


def test_extract_job_accepts_wrapped_and_direct_payloads():
    assert zai.extract_job({"job": {"id": "abc"}})["id"] == "abc"
    assert zai.extract_job({"id": "xyz"})["id"] == "xyz"
    with pytest.raises(zai.ZaiError):
        zai.extract_job({"status": "ok"})


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
