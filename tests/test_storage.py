from pathlib import Path

from storage import JobStore


def record(job_id: str, status: str = "succeeded"):
    return {
        "id": job_id,
        "provider_id": "test",
        "argv": ["echo", "hello"],
        "cwd": "/tmp",
        "created_at": 1.0,
        "started_at": 2.0,
        "finished_at": 3.0 if status == "succeeded" else None,
        "status": status,
        "return_code": 0 if status == "succeeded" else None,
        "error": None,
        "risk": "normal",
        "timeout_seconds": 30,
    }


def test_store_round_trip_and_delete(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.sqlite3", max_output_bytes=1024)
    store.upsert(record("a" * 12), b"hello", 0)
    loaded = store.get("a" * 12)
    assert loaded is not None
    assert loaded["argv"] == ["echo", "hello"]
    assert loaded["output"] == b"hello"
    assert store.health()["ok"] is True
    assert store.delete("a" * 12) is True
    assert store.get("a" * 12) is None


def test_store_marks_active_jobs_orphaned(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    store.upsert(record("b" * 12, status="running"), b"partial", 0)
    assert store.mark_interrupted_jobs_orphaned() == 1
    loaded = store.get("b" * 12)
    assert loaded["status"] == "orphaned"
    assert "restarted" in loaded["error"].lower()


def test_store_bounds_output(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.sqlite3", max_output_bytes=64 * 1024)
    payload = b"x" * (70 * 1024)
    store.upsert(record("c" * 12), payload, 0)
    loaded = store.get("c" * 12)
    assert len(loaded["output"]) == 64 * 1024
    assert loaded["output_base"] == 6 * 1024
