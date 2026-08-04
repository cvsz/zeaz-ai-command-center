import threading
import time
from pathlib import Path

from server import JobManager
from storage import JobStore, TERMINAL_STATES


class ExecutableRegistry:
    def get(self, provider_id):
        return {"id": provider_id, "executable": "/bin/echo"}

    def schema(self, provider_id, command_path):
        return {"options": []}


class DelayedTerminalStore(JobStore):
    def __init__(self, path: Path):
        super().__init__(path)
        self.final_write_started = threading.Event()
        self.release_final_write = threading.Event()

    def upsert(self, record, output=b"", output_base=0):
        if record.get("status") in TERMINAL_STATES and not self.release_final_write.is_set():
            self.final_write_started.set()
            if not self.release_final_write.wait(timeout=5):
                raise TimeoutError("test did not release the terminal write")
        return super().upsert(record, output, output_base)


def test_shutdown_waits_for_terminal_state_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("PANEL_ALLOW_ANY_CWD", "1")
    monkeypatch.setenv("PANEL_ALLOW_ABSOLUTE_BINARIES", "1")
    database = tmp_path / "jobs.sqlite3"
    store = DelayedTerminalStore(database)
    manager = JobManager(ExecutableRegistry(), store)
    job = manager.create({
        "provider_id": "echo",
        "cwd": str(tmp_path),
        "positionals": ["durable shutdown"],
    })

    assert store.final_write_started.wait(timeout=5)
    assert job.status == "succeeded"

    shutdown = threading.Thread(target=manager.shutdown)
    shutdown.start()
    time.sleep(0.1)
    assert shutdown.is_alive(), "shutdown returned before the terminal SQLite write completed"

    store.release_final_write.set()
    shutdown.join(timeout=5)
    assert not shutdown.is_alive()

    reloaded = JobManager(ExecutableRegistry(), JobStore(database))
    try:
        restored = reloaded.get(job.id)
        assert restored is not None
        assert restored.status == "succeeded"
        assert "durable shutdown" in restored.snapshot()["output"]
    finally:
        reloaded.shutdown()
