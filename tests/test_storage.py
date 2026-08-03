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


def test_store_presets(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    preset = store.save_preset({"name": "Test Preset", "provider_id": "codex", "command_path": ["run"]})
    assert preset["name"] == "Test Preset"
    assert preset["command_path"] == ["run"]
    all_presets = store.list_presets()
    assert len(all_presets) == 1
    assert store.delete_preset(preset["id"]) is True
    assert len(store.list_presets()) == 0


def test_store_v3_workflows_and_mcp(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    wf = store.save_workflow({"name": "Test Pipeline", "steps": [{"name": "step1"}]})
    assert wf["name"] == "Test Pipeline"
    assert len(store.list_workflows()) == 1

    mcp = store.save_mcp_server({"name": "Test MCP", "command": "npx", "args": ["mcp-server"]})
    assert mcp["name"] == "Test MCP"
    assert len(store.list_mcp_servers()) == 1


