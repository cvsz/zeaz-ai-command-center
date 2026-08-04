import threading
import time

import pytest
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


def test_detailed_metrics_per_provider(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PANEL_ALLOW_ANY_CWD", "1")
    monkeypatch.setenv("PANEL_ALLOW_ABSOLUTE_BINARIES", "1")
    store = JobStore(tmp_path / "jobs.sqlite3")
    manager = JobManager(ExecutableRegistry("/bin/echo"), store)
    try:
        job1 = manager.create({
            "provider_id": "echo",
            "cwd": str(tmp_path),
            "positionals": ["hello"],
        })
        wait_terminal(job1)
        job2 = manager.create({
            "provider_id": "echo",
            "cwd": str(tmp_path),
            "positionals": ["world"],
        })
        wait_terminal(job2)
        metrics = manager.detailed_metrics()
        assert metrics["total_jobs"] >= 2
        assert "echo" in metrics["providers"]
        echo_stats = metrics["providers"]["echo"]
        assert echo_stats["succeeded"] == 2
        assert echo_stats["avg_latency_seconds"] >= 0
        assert metrics["queue_depth"] == 0
    finally:
        manager.shutdown()


def test_analytics_per_provider(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PANEL_ALLOW_ANY_CWD", "1")
    monkeypatch.setenv("PANEL_ALLOW_ABSOLUTE_BINARIES", "1")
    store = JobStore(tmp_path / "jobs.sqlite3")
    manager = JobManager(ExecutableRegistry("/bin/echo"), store)
    try:
        job1 = manager.create({
            "provider_id": "echo",
            "cwd": str(tmp_path),
            "positionals": ["hello"],
        })
        wait_terminal(job1)
        job2 = manager.create({
            "provider_id": "echo",
            "cwd": str(tmp_path),
            "positionals": ["world"],
        })
        wait_terminal(job2)
        analytics = manager.analytics()
        assert analytics["total_jobs"] >= 2
        assert analytics["totals_by_status"]["succeeded"] >= 2
        assert analytics["success_rate_percent"] > 0
        assert "echo" in analytics["providers"]
        echo_stats = analytics["providers"]["echo"]
        assert echo_stats["total"] >= 2
        assert echo_stats["success_rate"] == 100.0
        assert echo_stats["avg_duration_seconds"] >= 0
        assert analytics["p50_duration_seconds"] >= 0
    finally:
        manager.shutdown()


def test_retry_policy_backoff():
    from server import RetryPolicy
    p_fixed = RetryPolicy(max_retries=3, backoff="fixed", initial_delay_seconds=2.0)
    assert p_fixed.next_delay(1) == 2.0
    assert p_fixed.next_delay(2) == 2.0
    assert p_fixed.next_delay(3) == 2.0

    p_linear = RetryPolicy(max_retries=3, backoff="linear", initial_delay_seconds=1.0)
    assert p_linear.next_delay(1) == 1.0
    assert p_linear.next_delay(2) == 2.0
    assert p_linear.next_delay(3) == 3.0

    p_exp = RetryPolicy(max_retries=5, backoff="exponential", initial_delay_seconds=1.0)
    assert p_exp.next_delay(1) == 1.0
    assert p_exp.next_delay(2) == 2.0
    assert p_exp.next_delay(3) == 4.0
    assert p_exp.next_delay(4) == 8.0


def test_retry_policy_max_delay():
    from server import RetryPolicy
    p = RetryPolicy(max_retries=5, backoff="exponential", initial_delay_seconds=1.0, max_delay_seconds=10.0)
    assert p.next_delay(1) == 1.0
    assert p.next_delay(2) == 2.0
    assert p.next_delay(3) == 4.0
    assert p.next_delay(4) == 8.0
    assert p.next_delay(5) == 10.0  # capped


def test_retry_policy_to_from_dict():
    from server import RetryPolicy
    p = RetryPolicy(max_retries=3, backoff="linear", initial_delay_seconds=2.5, max_delay_seconds=60.0)
    d = p.to_dict()
    p2 = RetryPolicy.from_dict(d)
    assert p2.max_retries == 3
    assert p2.backoff == "linear"
    assert p2.initial_delay_seconds == 2.5
    assert p2.max_delay_seconds == 60.0


def test_job_can_retry():
    from server import Job
    job = Job(
        id="a" * 12, provider_id="test", argv=["echo"], display_argv=["echo"],
        cwd="/tmp", created_at=1.0, max_retries=3, retry_policy="exponential",
    )
    assert job.can_retry is False  # status is "queued", not failed
    job.status = "failed"
    assert job.can_retry is True
    job.retry_count = 3
    assert job.can_retry is False  # exhausted


def test_job_retry_with_configurable_backoff(tmp_path, monkeypatch):
    monkeypatch.setenv("PANEL_ALLOW_ANY_CWD", "1")
    monkeypatch.setenv("PANEL_ALLOW_ABSOLUTE_BINARIES", "1")
    store = JobStore(tmp_path / "jobs.sqlite3")
    manager = JobManager(ExecutableRegistry("/bin/sh"), store)
    try:
        job = manager.create({
            "provider_id": "sh",
            "cwd": str(tmp_path),
            "raw_args": ["-c", "exit 1"],
            "retry": {"max_retries": 2, "backoff": "fixed", "initial_delay_seconds": 0.1, "max_delay_seconds": 1.0},
        })
        wait_terminal(job)
        assert job.status == "failed"
        assert job.max_retries == 2
        assert job.retry_policy == "fixed"
        assert job.retry_initial_delay == 0.1
        assert job.can_retry is True
    finally:
        manager.shutdown()


def test_storage_retry_fields(tmp_path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    store.upsert({
        "id": "r" * 12, "provider_id": "test", "argv": ["echo"], "cwd": "/tmp",
        "created_at": 1.0, "status": "failed", "risk": "normal", "timeout_seconds": 30,
        "retry_count": 1, "max_retries": 3, "retry_policy": "linear",
        "retry_initial_delay": 2.0, "retry_max_delay": 60.0,
    }, b"output", 0)
    loaded = store.get("r" * 12)
    assert loaded["retry_count"] == 1
    assert loaded["max_retries"] == 3
    assert loaded["retry_policy"] == "linear"
    assert loaded["retry_initial_delay"] == 2.0
    assert loaded["retry_max_delay"] == 60.0


def test_circuit_breaker_states():
    from server import CircuitBreaker
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60.0)
    assert cb.is_open("test-provider") is False
    assert cb.get_state("test-provider")["state"] == "closed"
    for _ in range(3):
        cb.record_failure("test-provider")
    assert cb.is_open("test-provider") is True
    assert cb.get_state("test-provider")["state"] == "open"
    cb.reset("test-provider")
    assert cb.is_open("test-provider") is False
    assert cb.get_state("test-provider")["state"] == "closed"


def test_circuit_breaker_success_resets():
    from server import CircuitBreaker
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60.0)
    cb.record_failure("prov")
    cb.record_failure("prov")
    assert cb.is_open("prov") is False
    cb.record_success("prov")
    assert cb.get_state("prov")["consecutive_failures"] == 0
    cb.record_failure("prov")
    cb.record_failure("prov")
    assert cb.is_open("prov") is False  # only 2 consecutive after reset


def test_circuit_breaker_half_open(monkeypatch):
    from server import CircuitBreaker
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=5.0)
    cb.record_failure("prov")
    cb.record_failure("prov")
    assert cb.is_open("prov") is True
    # Simulate cooldown elapsed
    cb._opened_at["prov"] = time.monotonic() - 10.0
    assert cb.is_open("prov") is False  # transitions to half_open
    assert cb.get_state("prov")["state"] == "half_open"
    # Success in half_open closes the circuit
    cb.record_success("prov")
    assert cb.get_state("prov")["state"] == "closed"


def test_circuit_breaker_blocks_job_creation(tmp_path, monkeypatch):
    monkeypatch.setenv("PANEL_ALLOW_ANY_CWD", "1")
    monkeypatch.setenv("PANEL_ALLOW_ABSOLUTE_BINARIES", "1")
    store = JobStore(tmp_path / "jobs.sqlite3")
    manager = JobManager(ExecutableRegistry("/bin/sh"), store)
    try:
        for _ in range(5):
            manager.circuit_breaker.record_failure("sh")
        with pytest.raises(ValueError, match="Circuit breaker open"):
            manager.create({
                "provider_id": "sh",
                "cwd": str(tmp_path),
                "raw_args": ["-c", "echo hello"],
            })
    finally:
        manager.shutdown()


def test_load_shedder_overloaded():
    from server import LoadShedder
    ls = LoadShedder(max_queue_depth=10, max_running_ratio=0.9)
    assert ls.is_overloaded(queue_depth=10, running=4, max_concurrent=4) is True
    assert ls.is_overloaded(queue_depth=5, running=4, max_concurrent=4) is True
    assert ls.is_overloaded(queue_depth=0, running=4, max_concurrent=4) is False
    assert ls.is_overloaded(queue_depth=5, running=2, max_concurrent=4) is False


def test_load_shedder_sheds_background():
    from server import LoadShedder
    ls = LoadShedder(max_queue_depth=10, max_running_ratio=0.9)
    # Overloaded: shed background
    assert ls.should_shed("background", queue_depth=10, running=4, max_concurrent=4) is True
    # Overloaded: keep urgent
    assert ls.should_shed("urgent", queue_depth=10, running=4, max_concurrent=4) is False
    # Not overloaded: keep all
    assert ls.should_shed("background", queue_depth=1, running=1, max_concurrent=4) is False


def test_load_shedder_stats():
    from server import LoadShedder
    ls = LoadShedder(max_queue_depth=5, max_running_ratio=0.8)
    ls.should_shed("background", 10, 4, 4)
    ls.should_throttle_endpoint(10, 4, 4)
    stats = ls.stats()
    assert stats["jobs_shedded"] == 1
    assert stats["endpoints_throttled"] == 1
    assert stats["max_queue_depth"] == 5


def test_load_shedder_blocks_background_job(tmp_path, monkeypatch):
    monkeypatch.setenv("PANEL_ALLOW_ANY_CWD", "1")
    monkeypatch.setenv("PANEL_ALLOW_ABSOLUTE_BINARIES", "1")
    store = JobStore(tmp_path / "jobs.sqlite3")
    manager = JobManager(ExecutableRegistry("/bin/sh"), store)
    try:
        # Manually set low threshold and simulate queued jobs
        manager.load_shedder.max_queue_depth = 2
        from server import Job as JobCls
        for i in range(3):
            fake_job = JobCls(
                id=f"q{i:012d}", provider_id="sh", argv=["sleep", "1"], display_argv=["sleep", "1"],
                cwd=str(tmp_path), created_at=time.time(), status="queued",
            )
            with manager.lock:
                manager.jobs[fake_job.id] = fake_job
        with pytest.raises(ValueError, match="shedding"):
            manager.create({
                "provider_id": "sh",
                "cwd": str(tmp_path),
                "raw_args": ["-c", "echo bg"],
                "priority": "background",
            })
    finally:
        manager.shutdown()


def test_provider_health_prober():
    from server import ProviderHealthProber, CircuitBreaker
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60.0)

    class FakeRegistry:
        def list(self):
            return [{"id": "sh", "executable": "sh"}, {"id": "nonexistent_tool_xyz", "executable": "nonexistent_tool_xyz"}]

    prober = ProviderHealthProber(FakeRegistry(), cb, interval_seconds=300, consecutive_failures_disable=2)
    prober._probe_all()
    results = prober.get_results()
    sh_result = [r for r in results if r["provider_id"] == "sh"][0]
    assert sh_result["healthy"] is True
    bad_result = [r for r in results if r["provider_id"] == "nonexistent_tool_xyz"][0]
    assert bad_result["healthy"] is False


def test_provider_health_prober_auto_disable():
    from server import ProviderHealthProber, CircuitBreaker
    cb = CircuitBreaker(failure_threshold=5, cooldown_seconds=60.0)

    class FakeRegistry:
        def list(self):
            return [{"id": "bad_provider", "executable": "nonexistent_xyz"}]

    prober = ProviderHealthProber(FakeRegistry(), cb, interval_seconds=300, consecutive_failures_disable=2)
    prober._probe_all()
    assert prober.is_disabled("bad_provider") is False  # 1 failure
    prober._probe_all()
    assert prober.is_disabled("bad_provider") is True  # 2 failures
    prober.enable("bad_provider")
    assert prober.is_disabled("bad_provider") is False


def test_provider_health_prober_blocks_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("PANEL_ALLOW_ANY_CWD", "1")
    monkeypatch.setenv("PANEL_ALLOW_ABSOLUTE_BINARIES", "1")
    store = JobStore(tmp_path / "jobs.sqlite3")
    manager = JobManager(ExecutableRegistry("/bin/sh"), store)
    try:
        manager.health_prober._disabled.add("sh")
        with pytest.raises(ValueError, match="disabled by health probe"):
            manager.create({
                "provider_id": "sh",
                "cwd": str(tmp_path),
                "raw_args": ["-c", "echo hello"],
            })
    finally:
        manager.shutdown()


def test_priority_queue_ordering():
    from server import PriorityJobQueue, Job as JobCls
    sem = threading.BoundedSemaphore(1)
    pq = PriorityJobQueue(sem, 1)
    bg_job = JobCls(id="b" * 12, provider_id="test", argv=["echo"], display_argv=["echo"],
                     cwd="/tmp", created_at=1.0, priority="background")
    normal_job = JobCls(id="n" * 12, provider_id="test", argv=["echo"], display_argv=["echo"],
                        cwd="/tmp", created_at=1.0, priority="normal")
    urgent_job = JobCls(id="u" * 12, provider_id="test", argv=["echo"], display_argv=["echo"],
                        cwd="/tmp", created_at=1.0, priority="urgent")
    with pq.lock:
        pq._waiting = [bg_job, normal_job, urgent_job]
        pq._waiting.sort(key=lambda j: __import__("server").PRIORITY_ORDER.get(j.priority, 1))
    assert pq._waiting[0].id == urgent_job.id
    assert pq._waiting[1].id == normal_job.id
    assert pq._waiting[2].id == bg_job.id


def test_priority_queue_stats():
    from server import PriorityJobQueue, Job as JobCls
    sem = threading.BoundedSemaphore(4)
    pq = PriorityJobQueue(sem, 4)
    with pq.lock:
        pq._waiting = [
            JobCls(id="u" * 12, provider_id="t", argv=["e"], display_argv=["e"], cwd="/tmp", created_at=1.0, priority="urgent"),
            JobCls(id="n" * 12, provider_id="t", argv=["e"], display_argv=["e"], cwd="/tmp", created_at=1.0, priority="normal"),
            JobCls(id="b" * 12, provider_id="t", argv=["e"], display_argv=["e"], cwd="/tmp", created_at=1.0, priority="background"),
        ]
    stats = pq.queue_stats()
    assert stats["urgent"] == 1
    assert stats["normal"] == 1
    assert stats["background"] == 1


def test_job_priority_in_create(tmp_path, monkeypatch):
    monkeypatch.setenv("PANEL_ALLOW_ANY_CWD", "1")
    monkeypatch.setenv("PANEL_ALLOW_ABSOLUTE_BINARIES", "1")
    store = JobStore(tmp_path / "jobs.sqlite3")
    manager = JobManager(ExecutableRegistry("/bin/echo"), store)
    try:
        job = manager.create({
            "provider_id": "echo",
            "cwd": str(tmp_path),
            "positionals": ["hello"],
            "priority": "urgent",
        })
        wait_terminal(job)
        assert job.priority == "urgent"
    finally:
        manager.shutdown()


def test_request_validator_valid():
    from server import RequestValidator
    errors = RequestValidator.validate("notification_channel", {
        "type": "slack", "name": "Test Channel", "url": "https://hooks.slack.com/test",
    })
    assert errors == []


def test_request_validator_missing_required():
    from server import RequestValidator
    errors = RequestValidator.validate("notification_channel", {"url": "https://example.com"})
    assert len(errors) >= 1
    assert any("required" in e for e in errors)


def test_request_validator_invalid_type():
    from server import RequestValidator
    errors = RequestValidator.validate("notification_channel", {
        "type": 123, "name": "Test",
    })
    assert any("type" in e.lower() for e in errors)


def test_request_validator_invalid_allowed():
    from server import RequestValidator
    errors = RequestValidator.validate("notification_channel", {
        "type": "invalid_type", "name": "Test",
    })
    assert any("must be one of" in e for e in errors)


def test_request_validator_out_of_range():
    from server import RequestValidator
    errors = RequestValidator.validate("provider_limits", {
        "provider_id": "test", "rate_limit_per_min": 0,
    })
    assert any("below minimum" in e for e in errors)


def test_request_validator_nested_schema():
    from server import RequestValidator
    errors = RequestValidator.validate("job_create", {
        "retry": {"max_retries": 5, "backoff": "invalid"},
    })
    assert any("retry.backoff" in e for e in errors)


def test_request_validator_unknown_schema():
    from server import RequestValidator
    errors = RequestValidator.validate("nonexistent", {})
    assert len(errors) == 1
    assert "Unknown" in errors[0]


def test_template_storage_crud(tmp_path):
    store = JobStore(tmp_path / "test.sqlite3")
    # Create
    saved = store.save_template({"name": "echo-hello", "description": "Echo hello", "template": {"provider_id": "echo", "argv": ["echo", "hello"]}})
    assert saved["name"] == "echo-hello"
    template_id = saved["id"]
    # List
    templates = store.list_templates()
    assert len(templates) == 1
    # Get
    fetched = store.get_template(template_id)
    assert fetched is not None
    assert fetched["name"] == "echo-hello"
    assert fetched["template"]["provider_id"] == "echo"
    # Update
    updated = store.save_template({"id": template_id, "name": "echo-world", "description": "Updated", "template": {"provider_id": "echo", "argv": ["echo", "world"]}})
    assert updated["name"] == "echo-world"
    # Delete
    assert store.delete_template(template_id) is True
    assert store.get_template(template_id) is None
    assert store.delete_template(template_id) is False


def test_backup_export_and_restore(tmp_path):
    store = JobStore(tmp_path / "test.sqlite3")
    # Create some data
    store.save_preset({"name": "test-preset", "provider_id": "echo", "command_path": [], "global_options": [], "command_options": [], "positionals": [], "raw_args": [], "prompt": ""})
    store.save_template({"name": "test-tmpl", "template": {"provider_id": "echo"}})
    # Export
    backup = store.export_backup()
    assert backup["schema_version"] == 3
    assert "exported_at" in backup
    assert len(backup["presets"]) >= 1
    assert len(backup["templates"]) >= 1
    # Import into fresh store
    store2 = JobStore(tmp_path / "restored.sqlite3")
    result = store2.import_backup(backup)
    assert result["ok"] is True
    assert result["imported"]["presets"] >= 1
    assert result["imported"]["job_templates"] >= 1
    # Verify data restored
    assert len(store2.list_presets()) >= 1
    assert len(store2.list_templates()) >= 1


def test_backup_schema_version_mismatch(tmp_path):
    store = JobStore(tmp_path / "test.sqlite3")
    result = store.import_backup({"schema_version": 999})
    assert result["ok"] is False
    assert "mismatch" in result["error"]


def test_api_key_storage_crud(tmp_path):
    store = JobStore(tmp_path / "test.sqlite3")
    # Create
    saved = store.save_api_key({"name": "ci-key", "key_hash": "abc123", "role": "operator"})
    assert saved["name"] == "ci-key"
    key_id = saved["id"]
    # List
    keys = store.list_api_keys()
    assert len(keys) == 1
    assert keys[0]["name"] == "ci-key"
    # Lookup by hash
    found = store.get_api_key_by_hash("abc123")
    assert found is not None
    assert found["name"] == "ci-key"
    # Lookup by wrong hash
    assert store.get_api_key_by_hash("wrong") is None
    # Delete
    assert store.delete_api_key(key_id) is True
    assert store.delete_api_key(key_id) is False
    assert store.get_api_key_by_hash("abc123") is None


def test_api_key_expired(tmp_path):
    store = JobStore(tmp_path / "test.sqlite3")
    store.save_api_key({"name": "expired", "key_hash": "exp123", "role": "operator", "expires_at": time.time() - 100})
    assert store.get_api_key_by_hash("exp123") is None


def test_webhook_storage_crud(tmp_path):
    store = JobStore(tmp_path / "test.sqlite3")
    # Create
    saved = store.save_webhook({"url": "https://example.com/hook", "secret": "mysecret123", "events": ["job.completed", "job.failed"]})
    assert saved["url"] == "https://example.com/hook"
    assert saved["enabled"] is True
    assert "job.completed" in saved["events"]
    wh_id = saved["id"]
    # List
    webhooks = store.list_webhooks()
    assert len(webhooks) == 1
    # Secret is masked
    assert webhooks[0]["secret"] != "mysecret123"
    # Get
    fetched = store.get_webhook(wh_id)
    assert fetched is not None
    # Update
    updated = store.save_webhook({"id": wh_id, "url": "https://example.com/new", "secret": "newsecret", "events": ["job.completed"], "enabled": False})
    assert updated["enabled"] is False
    # Delete
    assert store.delete_webhook(wh_id) is True
    assert store.delete_webhook(wh_id) is False


def test_webhook_dispatcher(tmp_path):
    from server import WebhookDispatcher
    store = JobStore(tmp_path / "test.sqlite3")
    dispatcher = WebhookDispatcher(store)
    # No webhooks registered — should not crash
    dispatcher.dispatch("job.completed", {"job_id": "test"})
    # Register a webhook (will fail to deliver but that's fine)
    store.save_webhook({"url": "https://127.0.0.1:1/invalid", "secret": "testsecret", "events": ["job.completed"]})
    dispatcher.dispatch("job.completed", {"job_id": "test"})
    # Event not matching — should be skipped
    dispatcher.dispatch("job.failed", {"job_id": "test"})


def test_bulk_job_operations(tmp_path):
    from server import JobManager, ProviderRegistry
    registry = ProviderRegistry()
    store = JobStore(tmp_path / "test.sqlite3")
    manager = JobManager(registry, store)
    # Bulk create
    items = [
        {"provider_id": "echo", "argv": ["echo", "1"], "cwd": str(tmp_path)},
        {"provider_id": "echo", "argv": ["echo", "2"], "cwd": str(tmp_path)},
    ]
    results = []
    for item in items:
        try:
            job = manager.create(item)
            results.append({"job_id": job.id, "status": "created"})
        except Exception:
            results.append({"status": "error"})
    assert len(results) == 2
    # Bulk stop — nothing running
    for r in results:
        if "job_id" in r:
            manager.stop(r["job_id"])
    # Bulk delete
    for r in results:
        if "job_id" in r:
            ok = manager.delete(r["job_id"])
            assert ok is True


def test_event_bus(tmp_path):
    from server import JobManager, ProviderRegistry
    registry = ProviderRegistry()
    store = JobStore(tmp_path / "test.sqlite3")
    manager = JobManager(registry, store)
    # Initially empty
    events, cond, last_id = manager.subscribe_events()
    assert len(events) == 0
    assert last_id == 0
    # Emit an event
    manager.emit_event("job.created", {"job_id": "test123"})
    events, cond, last_id = manager.subscribe_events()
    assert len(events) == 1
    assert events[0]["type"] == "job.created"
    assert events[0]["data"]["job_id"] == "test123"
    assert last_id == 1
    # Subscribe with after_id
    manager.emit_event("job.finished", {"job_id": "test123", "status": "succeeded"})
    events, cond, last_id = manager.subscribe_events(after_id=1)
    assert len(events) == 1
    assert events[0]["type"] == "job.finished"
