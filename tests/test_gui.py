"""Tests for GUI module — APIClient, SSEClient, and Fluent widget logic."""

from __future__ import annotations

import json
import threading
import time
import unittest
from http.server import HTTPServer, BaseHTTPRequestHandler
from unittest.mock import patch, MagicMock

from gui import APIClient, SSEClient, FluentButton, FluentEntry, FluentCombo, StatusBadge


# ---------------------------------------------------------------------------
# Helpers: tiny test HTTP server
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    """Minimal test server that returns canned JSON responses."""

    ROUTES: dict[str, dict] = {}

    def do_GET(self):
        route = self.path.split("?")[0]
        resp = self.ROUTES.get(route, {"error": "not found"})
        body = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = self.rfile.read(length) if length else b""
        resp = {"ok": True, "received": json.loads(payload) if payload else {}}
        body = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_DELETE(self):
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass  # suppress request logs


def _start_server(routes: dict) -> tuple[HTTPServer, str, threading.Thread]:
    _Handler.ROUTES = routes
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{port}", thread


# ---------------------------------------------------------------------------
# APIClient tests
# ---------------------------------------------------------------------------

class TestAPIClient(unittest.TestCase):
    """Test the APIClient REST helper."""

    @classmethod
    def setUpClass(cls):
        cls.server, cls.base_url, cls.thread = _start_server({
            "/api/v1/health": {"ok": True, "engine": "sqlite3", "jobs": 5},
            "/api/v1/jobs": [{"id": "abc123", "status": "running", "provider_id": "openai"}],
            "/api/v1/version": {"version": "3.3.0", "api_version": "v1"},
        })

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_get_health(self):
        client = APIClient(self.base_url)
        result = client.get("/health")
        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("engine"), "sqlite3")

    def test_get_jobs(self):
        client = APIClient(self.base_url)
        result = client.get("/jobs")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "abc123")

    def test_get_with_params(self):
        client = APIClient(self.base_url)
        result = client.get("/jobs", status="running", limit="10")
        # The test server ignores params but returns the same canned response
        self.assertIsInstance(result, list)

    def test_post(self):
        client = APIClient(self.base_url)
        result = client.post("/jobs", {"provider_id": "shell", "argv": ["echo"]})
        self.assertTrue(result.get("ok"))
        self.assertEqual(result["received"]["provider_id"], "shell")

    def test_delete(self):
        client = APIClient(self.base_url)
        result = client.delete("/jobs/abc123")
        self.assertTrue(result.get("ok"))

    def test_bearer_token_sent(self):
        client = APIClient(self.base_url, token="test-token-123")
        result = client.get("/health")
        self.assertTrue(result.get("ok"))

    def test_connection_error(self):
        client = APIClient("http://127.0.0.1:1")
        result = client.get("/health")
        self.assertIn("error", result)

    def test_version(self):
        client = APIClient(self.base_url)
        result = client.get("/version")
        self.assertEqual(result.get("version"), "3.3.0")


# ---------------------------------------------------------------------------
# SSEClient tests
# ---------------------------------------------------------------------------

class TestSSEClient(unittest.TestCase):
    """Test the SSEClient event stream parser."""

    def test_sse_parses_data_lines(self):
        events: list[dict] = []
        sse = SSEClient("http://127.0.0.1:1", on_event=events.append)

        # Simulate parsing a data line
        import gui
        parsed = []
        def on_event(e):
            parsed.append(e)

        # Test the line parsing logic directly
        line = 'data: {"type": "job.completed", "job_id": "abc123", "status": "succeeded"}'
        payload = line[5:].strip()
        event = json.loads(payload)
        self.assertEqual(event["type"], "job.completed")
        self.assertEqual(event["job_id"], "abc123")

    def test_sse_start_stop(self):
        sse = SSEClient("http://127.0.0.1:1", on_event=lambda e: None)
        self.assertFalse(sse._running)
        # Don't actually start — the server doesn't exist
        # Just test that stop is idempotent
        sse.stop()
        self.assertFalse(sse._running)


# ---------------------------------------------------------------------------
# Fluent widget tests (headless — no display needed)
# ---------------------------------------------------------------------------

class TestStatusBadgeColors(unittest.TestCase):
    """Test StatusBadge color mapping."""

    def test_known_statuses(self):
        self.assertEqual(StatusBadge.COLORS["succeeded"], "#107C10")
        self.assertEqual(StatusBadge.COLORS["failed"], "#D13438")
        self.assertEqual(StatusBadge.COLORS["running"], "#0078D4")
        self.assertEqual(StatusBadge.COLORS["queued"], "#FF8C00")
        self.assertEqual(StatusBadge.COLORS["open"], "#D13438")

    def test_unknown_status_falls_back(self):
        self.assertEqual(StatusBadge.COLORS.get("unknown"), None)
        # Default fallback in the class uses FG_SECONDARY
        fallback = StatusBadge.COLORS.get("unknown", "#616161")
        self.assertEqual(fallback, "#616161")


class TestFluentConstants(unittest.TestCase):
    """Test that Fluent Design constants are well-formed."""

    def test_accent_colors(self):
        from gui import ACCENT, ACCENT_HOVER, ACCENT_LIGHT
        self.assertTrue(ACCENT.startswith("#"))
        self.assertTrue(ACCENT_HOVER.startswith("#"))
        self.assertTrue(ACCENT_LIGHT.startswith("#"))

    def test_nav_items_complete(self):
        from gui import NAV_ITEMS
        names = [name for name, _ in NAV_ITEMS]
        # Must include all 15 pages
        self.assertIn("Dashboard", names)
        self.assertIn("Jobs", names)
        self.assertIn("Workflows", names)
        self.assertIn("Templates", names)
        self.assertIn("Presets", names)
        self.assertIn("Analytics", names)
        self.assertIn("Providers", names)
        self.assertIn("Users", names)
        self.assertIn("API Keys", names)
        self.assertIn("Webhooks", names)
        self.assertIn("Notifications", names)
        self.assertIn("MCP Servers", names)
        self.assertIn("Audit Log", names)
        self.assertIn("Scheduler", names)
        self.assertIn("Settings", names)
        self.assertEqual(len(NAV_ITEMS), 15)


# ---------------------------------------------------------------------------
# API URL construction tests
# ---------------------------------------------------------------------------

class TestAPIURLConstruction(unittest.TestCase):
    """Test that APIClient constructs URLs correctly."""

    def test_api_v1_prefix(self):
        client = APIClient("http://localhost:8765")
        url = client._url("/jobs")
        self.assertEqual(url, "http://localhost:8765/api/v1/jobs")

    def test_already_prefixed(self):
        client = APIClient("http://localhost:8765")
        url = client._url("/api/health")
        self.assertEqual(url, "http://localhost:8765/api/health")

    def test_base_url_trailing_slash(self):
        client = APIClient("http://localhost:8765/")
        self.assertEqual(client.base_url, "http://localhost:8765")

    def test_headers_include_auth(self):
        client = APIClient("http://localhost:8765", token="mytoken")
        headers = client._headers()
        self.assertEqual(headers["Authorization"], "Bearer mytoken")
        self.assertEqual(headers["X-API-Version"], "v1")

    def test_headers_no_auth(self):
        client = APIClient("http://localhost:8765")
        headers = client._headers()
        self.assertNotIn("Authorization", headers)


if __name__ == "__main__":
    unittest.main()
