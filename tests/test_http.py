import functools
import http.client
import json
import threading
from pathlib import Path

from server import AppServer, Handler, JobManager, ProviderRegistry, STATIC_DIR
from storage import JobStore


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
        assert json.loads(payload)["version"] == "2.1.0"
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
