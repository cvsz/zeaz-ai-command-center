import os
import stat
from pathlib import Path

import pytest

from server import ProviderRegistry, build_ai_command, detect_risk, render_options


class FakeRegistry:
    def get(self, provider_id):
        assert provider_id == "test"
        return {"id": "test", "name": "Test", "executable": "echo", "help_args": ["--help"]}

    def schema(self, provider_id, command_path):
        root = {
            "options": [
                {"flag": "--model", "flags": ["-m", "--model"], "takes_value": True, "choices": [], "repeatable": False, "multi_value": False},
                {"flag": "--search", "flags": ["--search"], "takes_value": False, "choices": [], "repeatable": False, "multi_value": False},
                {"flag": "--dangerously-bypass", "flags": ["--dangerously-bypass"], "takes_value": False, "choices": [], "repeatable": False, "multi_value": False},
            ]
        }
        if command_path:
            return {
                "options": [
                    {"flag": "--format", "flags": ["--format"], "takes_value": True, "choices": ["text", "json"], "repeatable": False, "multi_value": False},
                    {"flag": "--file", "flags": ["--file"], "takes_value": True, "choices": [], "repeatable": True, "multi_value": False},
                ]
            }
        return root


def test_render_options_structured_values():
    schema = FakeRegistry().schema("test", ["run"])
    argv = render_options(schema, {"--format": "json", "--file": ["a.txt", "b.txt"]})
    assert argv == ["--format", "json", "--file", "a.txt", "--file", "b.txt"]


def test_build_ai_command_without_shell(tmp_path, monkeypatch):
    monkeypatch.setenv("PANEL_ALLOW_ANY_CWD", "1")
    payload = {
        "provider_id": "test",
        "cwd": str(tmp_path),
        "command_path": ["run"],
        "global_options": {"--model": "fast", "--search": True},
        "command_options": {"--format": "json"},
        "positionals": ["input.txt"],
        "raw_args": ["--custom", "value with spaces"],
        "prompt": "Do the work",
        "environment": {},
    }
    argv, cwd, risk = build_ai_command(payload, FakeRegistry())
    assert argv[0].endswith("echo")
    assert argv[1:] == ["--model", "fast", "--search", "run", "--format", "json", "input.txt", "--custom", "value with spaces", "Do the work"]
    assert cwd == tmp_path.resolve()
    assert risk == "normal"


def test_dangerous_command_requires_exact_confirmation(tmp_path, monkeypatch):
    monkeypatch.setenv("PANEL_ALLOW_ANY_CWD", "1")
    payload = {
        "provider_id": "test",
        "cwd": str(tmp_path),
        "command_path": [],
        "global_options": {"--dangerously-bypass": True},
    }
    with pytest.raises(ValueError, match="I UNDERSTAND"):
        build_ai_command(payload, FakeRegistry())
    payload["confirmation"] = "I UNDERSTAND"
    _, _, risk = build_ai_command(payload, FakeRegistry())
    assert risk == "dangerous"


def test_detect_destructive_command():
    assert detect_risk(["tool", "delete", "session-1"]) == "destructive"
    assert detect_risk(["tool", "--no-sandbox"]) == "dangerous"


def test_probe_custom_provider(tmp_path, monkeypatch):
    script = tmp_path / "sample-ai"
    script.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then echo 'sample-ai 1.2.3'; exit 0; fi\n"
        "cat <<'EOF'\nSample AI\nUsage: sample-ai [OPTIONS] <COMMAND>\nCommands:\n  run     Run a task\nOptions:\n  -m, --model <MODEL>   Select model\n  -h, --help            Print help\nEOF\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PANEL_ALLOW_ABSOLUTE_BINARIES", "1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    registry = ProviderRegistry()
    result = registry.probe({"executable": str(script), "help_args": "--help", "version_args": "--version"})
    assert result["version"] == "sample-ai 1.2.3"
    assert result["schema"]["commands"][0]["name"] == "run"
    assert result["schema"]["options"][0]["flag"] == "--model"


def test_environment_policy_blocks_loader_injection(monkeypatch):
    from server import validate_environment

    monkeypatch.delenv("PANEL_ALLOW_ANY_ENV", raising=False)
    with pytest.raises(ValueError, match="not allowed"):
        validate_environment({"LD_PRELOAD": "/tmp/evil.so"})
    assert validate_environment({"OPENAI_API_KEY": "secret-value"}) == {"OPENAI_API_KEY": "secret-value"}


def test_redact_argv_sensitive_values():
    from server import redact_argv

    assert redact_argv(["tool", "--api-key", "abc123", "--token=xyz", "run"]) == [
        "tool", "--api-key", "[REDACTED]", "--token=[REDACTED]", "run"
    ]


def test_job_output_redaction_across_chunk_boundaries():
    from server import Job

    job = Job(
        id="a" * 12,
        provider_id="test",
        argv=["echo"],
        display_argv=["echo"],
        cwd="/tmp",
        created_at=0,
        redaction_values=[b"super-secret-token"],
    )
    job.append(b"prefix super-sec")
    job.append(b"ret-token suffix", final=True)
    snapshot = job.snapshot()
    assert "super-secret-token" not in snapshot["output"]
    assert "[REDACTED]" in snapshot["output"]
