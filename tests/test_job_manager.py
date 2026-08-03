import time
from pathlib import Path

from server import JobManager
from storage import JobStore, TERMINAL_STATES


class ExecutableRegistry:
    def __init__(self, executable: str):
        self.executable = executable

    def get(self, provider_id):
        return {"id": provider_id, "executable": self.executable}

    def schema(self, provider_id, command_path):
        return {"options": []}


def wait_terminal(job, timeout=5):
    deadline = time.monotonic() + timeout
    while job.status not in TERMINAL_STATES and time.monotonic() < deadline:
        time.sleep(0.05)
    assert job.status in TERMINAL_STATES


def test_silent_process_times_out(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PANEL_ALLOW_ANY_CWD", "1")
    monkeypatch.setenv("PANEL_ALLOW_ABSOLUTE_BINARIES", "1")
    store = JobStore(tmp_path / "jobs.sqlite3")
    manager = JobManager(ExecutableRegistry("/bin/sh"), store)
    try:
        job = manager.create({
            "provider_id": "shell",
            "cwd": str(tmp_path),
            "raw_args": ["-c", "sleep 5"],
            "timeout_seconds": 1,
        })
        wait_terminal(job, timeout=4)
        assert job.status == "timed_out"
        assert "exceeded timeout" in job.error.lower()
    finally:
        manager.shutdown()


def test_completed_job_reloads_from_sqlite(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PANEL_ALLOW_ANY_CWD", "1")
    monkeypatch.setenv("PANEL_ALLOW_ABSOLUTE_BINARIES", "1")
    database = tmp_path / "jobs.sqlite3"
    manager = JobManager(ExecutableRegistry("/bin/echo"), JobStore(database))
    job = manager.create({
        "provider_id": "echo",
        "cwd": str(tmp_path),
        "positionals": ["durable output"],
    })
    wait_terminal(job)
    manager.shutdown()

    reloaded = JobManager(ExecutableRegistry("/bin/echo"), JobStore(database))
    try:
        restored = reloaded.get(job.id)
        assert restored is not None
        assert restored.status == "succeeded"
        assert "durable output" in restored.snapshot()["output"]
    finally:
        reloaded.shutdown()
