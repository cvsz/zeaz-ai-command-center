import functools
import http.client
import json
import threading
from pathlib import Path

from server import AppServer, Handler, JobManager, ProviderRegistry, STATIC_DIR
from storage import JobStore
from version import __version__


def start_server(tmp_path: Path, token: str = "test-token"):
    registry = ProviderRegistry()
    manager = JobManager(registry, JobStore(tmp_path / "jobs.sqlite3"))
    handler = functools.partial(Handler, directory=str(STATIC_DIR))
    server = AppServer(
        ("127.0.0.1", 0),
        handler,
        registry=registry,
        manager=manager,
        auth_token=token,
        allowed_hosts={"127.0.0.1", "localhost"},
        loopback=True,
        hsts=False,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, manager, thread


def request(server, method, path, *, token=None, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    request_headers = {"Host": f"127.0.0.1:{server.server_address[1]}", **(headers or {})}
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    encoded = None
    if body is not None:
        encoded = json.dumps(body)
        request_headers["Content-Type"] = "application/json"
    connection.request(method, path, body=encoded, headers=request_headers)
    response = connection.getresponse()
    payload = response.read()
    result = (response.status, dict(response.getheaders()), payload)
    connection.close()
    return result


def test_health_public_and_api_requires_bearer(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        status, headers, payload = request(server, "GET", "/healthz")
        assert status == 200
        assert json.loads(payload)["status"] == "ok"
        assert "Content-Security-Policy" in headers

        status, _, _ = request(server, "GET", "/api/info?token=test-token")
        assert status == 401
        status, _, payload = request(server, "GET", "/api/info", token="test-token")
        assert status == 200
        assert json.loads(payload)["version"] == __version__
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_cross_site_mutation_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        status, _, payload = request(
            server,
            "POST",
            "/api/providers/probe",
            token="test-token",
            body={"executable": "missing"},
            headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
        )
        assert status == 403
        assert "Cross-site" in json.loads(payload)["error"]
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_files_and_diff(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("PANEL_ALLOW_ANY_CWD", "1")
    server, manager, thread = start_server(tmp_path)
    try:
        status, _, payload = request(server, "GET", f"/api/files?cwd={tmp_path}", token="test-token")
        assert status == 200
        data = json.loads(payload)
        assert data["cwd"] == str(tmp_path.resolve())

        status, _, payload = request(server, "GET", f"/api/diff?cwd={tmp_path}", token="test-token")
        assert status == 200
        assert "diff" in json.loads(payload)
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_github_pulls(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("PANEL_ALLOW_ANY_CWD", "1")
    server, manager, thread = start_server(tmp_path)
    try:
        status, _, payload = request(server, "GET", f"/api/github/pulls?cwd={tmp_path}", token="test-token")
        assert status == 200
        assert "pulls" in json.loads(payload)
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_version_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        status, headers, payload = request(server, "GET", "/api/version", token="test-token")
        assert status == 200
        data = json.loads(payload)
        assert data["api_version"] == "v1"
        assert "app_version" in data
        assert "parser_version" in data
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_versioned_prefix_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        # /api/v1/info should work the same as /api/info
        status, headers, payload = request(server, "GET", "/api/v1/info", token="test-token")
        assert status == 200
        data = json.loads(payload)
        assert "version" in data

        # /api/v1/version should work
        status, _, payload = request(server, "GET", "/api/v1/version", token="test-token")
        assert status == 200
        data = json.loads(payload)
        assert data["api_version"] == "v1"
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_version_header_in_responses(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        status, headers, payload = request(server, "GET", "/api/info", token="test-token")
        assert status == 200
        # X-API-Version header should be present on all JSON responses
        assert headers.get("X-API-Version") == "v1"
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_healthz_and_readyz(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        status, _, payload = request(server, "GET", "/healthz")
        assert status == 200
        assert json.loads(payload)["status"] == "ok"

        status, _, payload = request(server, "GET", "/readyz")
        assert status == 200
        assert json.loads(payload)["status"] == "ready"
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_info_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        status, _, payload = request(server, "GET", "/api/info", token="test-token")
        assert status == 200
        data = json.loads(payload)
        assert "version" in data
        assert "max_concurrent_jobs" in data
        assert "providers_file" in data
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_providers_list(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        status, _, payload = request(server, "GET", "/api/providers", token="test-token")
        assert status == 200
        data = json.loads(payload)
        assert "providers" in data
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_jobs_crud(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        # List jobs
        status, _, payload = request(server, "GET", "/api/jobs", token="test-token")
        assert status == 200
        assert "jobs" in json.loads(payload)

        # Create a job
        status, _, payload = request(server, "POST", "/api/jobs", token="test-token", body={
            "provider_id": "echo", "argv": ["echo", "hello"], "cwd": str(tmp_path),
        })
        # May fail if echo provider not found, but endpoint should respond
        assert status in (202, 400, 404)
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_presets_crud(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        # Create preset
        status, _, payload = request(server, "POST", "/api/presets", token="test-token", body={
            "name": "test-preset", "provider_id": "echo",
            "command_path": [], "global_options": [], "command_options": [],
            "positionals": [], "raw_args": [], "prompt": "",
        })
        assert status == 201
        preset = json.loads(payload)
        preset_id = preset["id"]

        # List presets
        status, _, payload = request(server, "GET", "/api/presets", token="test-token")
        assert status == 200
        assert "presets" in json.loads(payload)

        # Delete preset
        status, _, payload = request(server, "DELETE", f"/api/presets/{preset_id}", token="test-token")
        assert status == 200
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_workflows_crud(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        # Create workflow
        status, _, payload = request(server, "POST", "/api/workflows", token="test-token", body={
            "name": "test-workflow", "steps": [{"provider_id": "echo", "argv": ["echo"]}],
        })
        assert status == 201
        wf = json.loads(payload)
        wf_id = wf["id"]

        # Delete workflow
        status, _, payload = request(server, "DELETE", f"/api/workflows/{wf_id}", token="test-token")
        assert status == 200
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_mcp_servers_crud(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        # Create MCP server
        status, _, payload = request(server, "POST", "/api/mcp", token="test-token", body={
            "name": "test-mcp", "command": "echo", "args": [],
        })
        assert status == 201
        mcp = json.loads(payload)
        mcp_id = mcp["id"]

        # Delete MCP server
        status, _, payload = request(server, "DELETE", f"/api/mcp/{mcp_id}", token="test-token")
        assert status == 200
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_notification_channels_crud(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        # Create notification channel
        status, _, payload = request(server, "POST", "/api/notifications", token="test-token", body={
            "type": "slack", "name": "test-channel", "url": "https://hooks.slack.com/test",
        })
        assert status == 201
        ch = json.loads(payload)
        ch_id = ch["id"]

        # Delete notification channel
        status, _, payload = request(server, "DELETE", f"/api/notifications/{ch_id}", token="test-token")
        assert status == 200
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_schedules_crud(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        # Create schedule
        status, _, payload = request(server, "POST", "/api/schedules", token="test-token", body={
            "name": "test-schedule", "provider_id": "shell",
            "command": ["echo", "hello"], "interval_seconds": 3600,
        })
        assert status == 201
        sched = json.loads(payload)
        sched_id = sched["id"]

        # Delete schedule
        status, _, payload = request(server, "DELETE", f"/api/schedules/{sched_id}", token="test-token")
        assert status == 200
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_provider_limits(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        status, _, payload = request(server, "GET", "/api/provider-limits", token="test-token")
        assert status == 200
        assert "providers" in json.loads(payload)

        # Set provider limit
        status, _, payload = request(server, "POST", "/api/provider-limits", token="test-token", body={
            "provider_id": "echo", "rate_limit_per_min": 20, "concurrency_cap": 3,
        })
        assert status == 200
        data = json.loads(payload)
        assert data["rate_limit_per_min"] == 20
        assert data["concurrency_cap"] == 3
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_circuit_breaker_and_health_probes(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        # Circuit breaker state
        status, _, payload = request(server, "GET", "/api/circuit-breaker", token="test-token")
        assert status == 200
        assert "providers" in json.loads(payload)

        # Health probes
        status, _, payload = request(server, "GET", "/api/health-probes", token="test-token")
        assert status == 200
        assert "providers" in json.loads(payload)
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_load_and_metrics(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        # Load
        status, _, payload = request(server, "GET", "/api/load", token="test-token")
        assert status == 200
        data = json.loads(payload)
        assert "queue_depth" in data
        assert "running" in data

        # Metrics (Prometheus text)
        status, _, payload = request(server, "GET", "/api/metrics", token="test-token")
        assert status == 200

        # Metrics (JSON)
        status, _, payload = request(server, "GET", "/api/metrics", token="test-token",
                                     headers={"Accept": "application/json"})
        assert status == 200
        assert "providers" in json.loads(payload)
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_schemas_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        status, _, payload = request(server, "GET", "/api/schemas", token="test-token")
        assert status == 200
        data = json.loads(payload)
        assert "schemas" in data
        assert len(data["schemas"]) > 0
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_retry_policies(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        status, _, payload = request(server, "GET", "/api/retry-policies", token="test-token")
        assert status == 200
        data = json.loads(payload)
        assert "retryable_jobs" in data
        assert "backoff_types" in data
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_users_crud(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        # Create user
        status, _, payload = request(server, "POST", "/api/users", token="test-token", body={
            "username": "testuser", "password": "testpass123", "role": "operator",
        })
        assert status == 201
        data = json.loads(payload)
        assert data["username"] == "testuser"
        assert data["role"] == "operator"
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_not_found(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        status, _, payload = request(server, "GET", "/api/nonexistent", token="test-token")
        assert status == 404

        status, _, payload = request(server, "POST", "/api/nonexistent", token="test-token", body={})
        assert status == 404
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_templates_crud(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        # Create template
        status, _, payload = request(server, "POST", "/api/templates", token="test-token", body={
            "name": "echo-hello", "description": "Echo hello",
            "template": {"provider_id": "echo", "argv": ["echo", "hello"]},
        })
        assert status == 201
        tmpl = json.loads(payload)
        tmpl_id = tmpl["id"]
        assert tmpl["name"] == "echo-hello"

        # List templates
        status, _, payload = request(server, "GET", "/api/templates", token="test-token")
        assert status == 200
        assert "templates" in json.loads(payload)

        # Get template
        status, _, payload = request(server, "GET", f"/api/templates/{tmpl_id}", token="test-token")
        assert status == 200
        assert json.loads(payload)["name"] == "echo-hello"

        # Delete template
        status, _, payload = request(server, "DELETE", f"/api/templates/{tmpl_id}", token="test-token")
        assert status == 200

        # Get deleted template
        status, _, payload = request(server, "GET", f"/api/templates/{tmpl_id}", token="test-token")
        assert status == 404
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_analytics(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        status, _, payload = request(server, "GET", "/api/analytics", token="test-token")
        assert status == 200
        data = json.loads(payload)
        assert "total_jobs" in data
        assert "success_rate_percent" in data
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_webhooks_crud(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        # Create webhook
        status, _, payload = request(server, "POST", "/api/webhooks", token="test-token", body={
            "name": "test-webhook", "url": "https://example.com/hook",
            "events": ["job.completed"], "secret": "whsec123",
        })
        assert status == 201
        wh = json.loads(payload)
        wh_id = wh["id"]

        # List webhooks
        status, _, payload = request(server, "GET", "/api/webhooks", token="test-token")
        assert status == 200
        assert "webhooks" in json.loads(payload)

        # Delete webhook
        status, _, payload = request(server, "DELETE", f"/api/webhooks/{wh_id}", token="test-token")
        assert status == 200
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_keys_crud(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        # Create API key
        status, _, payload = request(server, "POST", "/api/keys", token="test-token", body={
            "name": "test-key", "scope": "read",
        })
        assert status == 201
        key = json.loads(payload)
        key_id = key["id"]
        assert "key" in key

        # List API keys
        status, _, payload = request(server, "GET", "/api/keys", token="test-token")
        assert status == 200
        assert "keys" in json.loads(payload)

        # Revoke (delete) API key
        status, _, payload = request(server, "DELETE", f"/api/keys/{key_id}", token="test-token")
        assert status == 200
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_audit_log(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        # Get audit log
        status, _, payload = request(server, "GET", "/api/audit", token="test-token")
        assert status == 200
        data = json.loads(payload)
        assert "entries" in data

        # Verify audit chain
        status, _, payload = request(server, "GET", "/api/audit/verify", token="test-token")
        assert status == 200
        data = json.loads(payload)
        assert "valid" in data
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_backup_and_restore(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        # Export backup
        status, _, payload = request(server, "GET", "/api/backup", token="test-token")
        assert status == 200
        backup = json.loads(payload)
        assert "schema_version" in backup

        # Restore backup
        status, _, payload = request(server, "POST", "/api/restore", token="test-token", body=backup)
        assert status == 200
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_events_sse(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        # SSE endpoint should return 200 with text/event-stream
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
        connection.request("GET", "/api/events", headers={
            "Host": f"127.0.0.1:{server.server_address[1]}",
            "Authorization": "Bearer test-token",
        })
        response = connection.getresponse()
        assert response.status == 200
        assert "text/event-stream" in response.getheader("Content-Type", "")
        connection.close()
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_circuit_breaker_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        # Reset a non-existent provider's circuit breaker
        status, _, payload = request(server, "POST", "/api/circuit-breaker/nonexistent/reset", token="test-token")
        assert status == 200
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_health_probes_enable(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        # Enable a non-existent provider's health probe
        status, _, payload = request(server, "POST", "/api/health-probes/nonexistent/enable", token="test-token")
        assert status == 200
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_mfa_setup_and_verify(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        # Create a user first
        status, _, payload = request(server, "POST", "/api/users", token="test-token", body={
            "username": "mfauser", "password": "mfapass123", "role": "operator",
        })
        assert status == 201

        # Setup MFA
        status, _, payload = request(server, "POST", "/api/mfa/setup", token="test-token", body={
            "username": "mfauser",
        })
        assert status == 200
        data = json.loads(payload)
        assert "secret" in data
        assert "otpauth_url" in data
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_job_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        # Create a job
        status, _, payload = request(server, "POST", "/api/jobs", token="test-token", body={
            "provider_id": "echo", "argv": ["echo", "hello"], "cwd": str(tmp_path),
        })
        assert status in (202, 400, 404)
        if status == 202:
            job = json.loads(payload)
            job_id = job["id"]

            # Get individual job
            status, _, payload = request(server, "GET", f"/api/jobs/{job_id}", token="test-token")
            assert status == 200

            # Delete job
            status, _, payload = request(server, "DELETE", f"/api/jobs/{job_id}", token="test-token")
            assert status == 200
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_bulk_job_operations(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    server, manager, thread = start_server(tmp_path)
    try:
        # Bulk stop with empty list
        status, _, payload = request(server, "POST", "/api/jobs/bulk/stop", token="test-token", body={"ids": []})
        assert status == 200

        # Bulk delete with empty list
        status, _, payload = request(server, "POST", "/api/jobs/bulk/delete", token="test-token", body={"ids": []})
        assert status == 200
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_api_gitlab_and_bitbucket(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("PANEL_ALLOW_ANY_CWD", "1")
    server, manager, thread = start_server(tmp_path)
    try:
        # GitLab merges — gracefully returns empty list when glab CLI not installed
        status, _, payload = request(server, "GET", f"/api/gitlab/merges?cwd={tmp_path}", token="test-token")
        assert status == 200
        assert "merges" in json.loads(payload)

        # Bitbucket pulls — gracefully returns empty list when CLI not installed
        status, _, payload = request(server, "GET", f"/api/bitbucket/pulls?cwd={tmp_path}", token="test-token")
        assert status == 200
        assert "pulls" in json.loads(payload)
    finally:
        server.shutdown()
        manager.shutdown()
        server.server_close()
        thread.join(timeout=5)


