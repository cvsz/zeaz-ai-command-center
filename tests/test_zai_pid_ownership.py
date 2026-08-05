import json
import os
from pathlib import Path

import zai


def test_record_for_other_endpoint_is_preserved(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(zai, "state_dir", lambda: tmp_path)
    path = zai.standalone_pid_path()
    path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "uid": zai._current_uid(),
                "start_ticks": zai._process_start_ticks(os.getpid()),
                "server_path": "/tmp/other-server.py",
                "base_url": "http://127.0.0.1:9999",
            }
        ),
        encoding="utf-8",
    )

    assert zai.owned_standalone_pid("http://127.0.0.1:8765") is None
    assert path.exists()


def test_pid_start_token_mismatch_prevents_termination(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(zai, "state_dir", lambda: tmp_path)
    path = zai.standalone_pid_path()
    actual_start_ticks = zai._process_start_ticks(os.getpid())
    assert actual_start_ticks is not None
    path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "uid": zai._current_uid(),
                "start_ticks": actual_start_ticks + 1,
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
