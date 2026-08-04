#!/usr/bin/env python3
"""Durable SQLite storage for AI CLI Command Center jobs.

The runtime intentionally keeps SQLite behind this small adapter so a future
PostgreSQL implementation can replace it without changing the HTTP or job
execution layers.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 3
TERMINAL_STATES = {"succeeded", "failed", "stopped", "timed_out", "orphaned"}
ACTIVE_STATES = {"queued", "running", "stopping"}


def default_database_path() -> Path:
    explicit = os.getenv("PANEL_DATABASE_PATH", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    state_home = Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return (state_home / "ai-cli-command-center" / "jobs.sqlite3").resolve()


class JobStore:
    """Thread-safe durable job metadata and bounded output storage."""

    def __init__(self, path: Path | None = None, *, max_output_bytes: int = 8 * 1024 * 1024) -> None:
        self.path = (path or default_database_path()).expanduser().resolve()
        self.max_output_bytes = max(64 * 1024, int(max_output_bytes))
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        self._initialize()

    def _connect(self) -> contextlib.AbstractContextManager[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return contextlib.closing(connection)

    def _initialize(self) -> None:
        with self.lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    provider_id TEXT NOT NULL,
                    argv_json TEXT NOT NULL,
                    cwd TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    status TEXT NOT NULL,
                    return_code INTEGER,
                    error TEXT,
                    risk TEXT NOT NULL,
                    timeout_seconds INTEGER NOT NULL,
                    output BLOB NOT NULL DEFAULT X'',
                    output_base INTEGER NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 0,
                    retry_policy TEXT NOT NULL DEFAULT 'exponential',
                    retry_initial_delay REAL NOT NULL DEFAULT 1.0,
                    retry_max_delay REAL NOT NULL DEFAULT 300.0,
                    priority TEXT NOT NULL DEFAULT 'normal',
                    updated_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS jobs_created_at_idx ON jobs(created_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS presets (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    command_path_json TEXT NOT NULL,
                    global_options_json TEXT NOT NULL,
                    command_options_json TEXT NOT NULL,
                    positionals_json TEXT NOT NULL,
                    raw_args_json TEXT NOT NULL,
                    prompt TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_overlays (
                    id TEXT PRIMARY KEY,
                    provider_id TEXT NOT NULL,
                    overlay_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workflows (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mcp_servers (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    command TEXT NOT NULL,
                    args_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS worktrees (
                    id TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mfa_secrets (
                    user_id TEXT PRIMARY KEY,
                    secret TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'operator',
                    created_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_channels (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL DEFAULT '',
                    recipients_json TEXT NOT NULL DEFAULT '[]',
                    events_json TEXT NOT NULL DEFAULT '[]',
                    created_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_workflows (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    provider_id TEXT NOT NULL DEFAULT 'shell',
                    command_json TEXT NOT NULL DEFAULT '[]',
                    cwd TEXT NOT NULL DEFAULT '',
                    interval_seconds REAL NOT NULL DEFAULT 0,
                    next_run_at REAL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    timeout_seconds INTEGER NOT NULL DEFAULT 3600,
                    created_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL DEFAULT 'system',
                    target_type TEXT NOT NULL DEFAULT '',
                    target_id TEXT NOT NULL DEFAULT '',
                    details_json TEXT NOT NULL DEFAULT '{}',
                    checksum TEXT NOT NULL,
                    prev_checksum TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS presets_created_at_idx ON presets(created_at DESC)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS job_templates (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    template_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    key_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'operator',
                    created_at REAL NOT NULL,
                    expires_at REAL,
                    last_used_at REAL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS webhooks (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    secret TEXT NOT NULL DEFAULT '',
                    events_json TEXT NOT NULL DEFAULT '[]',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL
                )
                """
            )
            for col, coldef in [
                ("retry_count", "INTEGER NOT NULL DEFAULT 0"),
                ("max_retries", "INTEGER NOT NULL DEFAULT 0"),
                ("retry_policy", "TEXT NOT NULL DEFAULT 'exponential'"),
                ("retry_initial_delay", "REAL NOT NULL DEFAULT 1.0"),
                ("retry_max_delay", "REAL NOT NULL DEFAULT 300.0"),
                ("priority", "TEXT NOT NULL DEFAULT 'normal'"),
            ]:
                try:
                    connection.execute(f"ALTER TABLE jobs ADD COLUMN {col} {coldef}")
                except sqlite3.OperationalError:
                    pass
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass


    def health(self) -> dict[str, Any]:
        started = time.monotonic()
        with self.lock, self._connect() as connection:
            value = connection.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()
            count = connection.execute("SELECT COUNT(*) AS count FROM jobs").fetchone()["count"]
        return {
            "ok": bool(value and int(value["value"]) == SCHEMA_VERSION),
            "schema_version": int(value["value"]) if value else None,
            "jobs": int(count),
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
            "engine": "postgresql" if os.getenv("PANEL_POSTGRES_URL") else "sqlite3",
            "path": str(self.path),
        }

    def mark_interrupted_jobs_orphaned(self) -> int:
        now = time.time()
        with self.lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = 'orphaned',
                    error = COALESCE(error, 'Server restarted while the job was active'),
                    finished_at = COALESCE(finished_at, ?),
                    updated_at = ?
                WHERE status IN ('queued', 'running', 'stopping')
                """,
                (now, now),
            )
            return int(cursor.rowcount or 0)

    def upsert(self, record: dict[str, Any], output: bytes, output_base: int) -> None:
        if len(output) > self.max_output_bytes:
            remove = len(output) - self.max_output_bytes
            output = output[remove:]
            output_base += remove
        now = time.time()
        argv_json = json.dumps(record.get("argv", []), ensure_ascii=False, separators=(",", ":"))
        with self.lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO jobs(
                    id, provider_id, argv_json, cwd, created_at, started_at,
                    finished_at, status, return_code, error, risk,
                    timeout_seconds, output, output_base,
                    retry_count, max_retries, retry_policy, retry_initial_delay, retry_max_delay,
                    priority,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    provider_id = excluded.provider_id,
                    argv_json = excluded.argv_json,
                    cwd = excluded.cwd,
                    created_at = excluded.created_at,
                    started_at = excluded.started_at,
                    finished_at = excluded.finished_at,
                    status = excluded.status,
                    return_code = excluded.return_code,
                    error = excluded.error,
                    risk = excluded.risk,
                    timeout_seconds = excluded.timeout_seconds,
                    output = excluded.output,
                    output_base = excluded.output_base,
                    retry_count = excluded.retry_count,
                    max_retries = excluded.max_retries,
                    retry_policy = excluded.retry_policy,
                    retry_initial_delay = excluded.retry_initial_delay,
                    retry_max_delay = excluded.retry_max_delay,
                    priority = excluded.priority,
                    updated_at = excluded.updated_at
                """,
                (
                    record["id"],
                    record["provider_id"],
                    argv_json,
                    record["cwd"],
                    record["created_at"],
                    record.get("started_at"),
                    record.get("finished_at"),
                    record["status"],
                    record.get("return_code"),
                    record.get("error"),
                    record.get("risk", "normal"),
                    int(record.get("timeout_seconds") or 0),
                    sqlite3.Binary(output),
                    int(output_base),
                    int(record.get("retry_count") or 0),
                    int(record.get("max_retries") or 0),
                    record.get("retry_policy", "exponential"),
                    float(record.get("retry_initial_delay") or 1.0),
                    float(record.get("retry_max_delay") or 300.0),
                    record.get("priority", "normal"),
                    now,
                ),
            )
            connection.execute("COMMIT")

    def load_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 1000))
        with self.lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (bounded,)
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_record(row) if row else None

    def delete(self, job_id: str) -> bool:
        with self.lock, self._connect() as connection:
            row = connection.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if not row:
                return False
            if row["status"] not in TERMINAL_STATES:
                raise ValueError("Only terminal jobs can be deleted")
            cursor = connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            return bool(cursor.rowcount)

    def prune(self, *, max_jobs: int = 500, retention_days: int = 30) -> int:
        max_jobs = max(10, int(max_jobs))
        cutoff = time.time() - max(1, int(retention_days)) * 86400
        with self.lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor_age = connection.execute(
                "DELETE FROM jobs WHERE status IN ('succeeded','failed','stopped','timed_out','orphaned') AND finished_at < ?",
                (cutoff,),
            )
            cursor_count = connection.execute(
                """
                DELETE FROM jobs
                WHERE id IN (
                    SELECT id FROM jobs
                    WHERE status IN ('succeeded','failed','stopped','timed_out','orphaned')
                    ORDER BY created_at DESC
                    LIMIT -1 OFFSET ?
                )
                """,
                (max_jobs,),
            )
            connection.execute("COMMIT")
            return int(cursor_age.rowcount or 0) + int(cursor_count.rowcount or 0)

    def save_preset(self, preset: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        preset_id = preset.get("id") or os.urandom(6).hex()
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO presets (
                    id, name, provider_id, command_path_json, global_options_json,
                    command_options_json, positionals_json, raw_args_json, prompt, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    provider_id = excluded.provider_id,
                    command_path_json = excluded.command_path_json,
                    global_options_json = excluded.global_options_json,
                    command_options_json = excluded.command_options_json,
                    positionals_json = excluded.positionals_json,
                    raw_args_json = excluded.raw_args_json,
                    prompt = excluded.prompt,
                    updated_at = excluded.updated_at
                """,
                (
                    preset_id,
                    preset.get("name", "Untitled Preset"),
                    preset.get("provider_id", ""),
                    json.dumps(preset.get("command_path", []), ensure_ascii=False),
                    json.dumps(preset.get("global_options", {}), ensure_ascii=False),
                    json.dumps(preset.get("command_options", {}), ensure_ascii=False),
                    json.dumps(preset.get("positionals", []), ensure_ascii=False),
                    json.dumps(preset.get("raw_args", []), ensure_ascii=False),
                    preset.get("prompt", ""),
                    preset.get("created_at", now),
                    now,
                ),
            )
        return self.get_preset(preset_id)  # type: ignore

    def list_presets(self) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM presets ORDER BY created_at DESC").fetchall()
        return [self._preset_row_to_record(row) for row in rows]

    def get_preset(self, preset_id: str) -> dict[str, Any] | None:
        with self.lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM presets WHERE id = ?", (preset_id,)).fetchone()
        return self._preset_row_to_record(row) if row else None

    def delete_preset(self, preset_id: str) -> bool:
        with self.lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM presets WHERE id = ?", (preset_id,))
            return bool(cursor.rowcount)

    def save_template(self, template: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        template_id = template.get("id") or uuid.uuid4().hex[:12]
        name = template.get("name", "")
        description = template.get("description", "")
        template_json = json.dumps(template.get("template", {}), ensure_ascii=False)
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO job_templates (id, name, description, template_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    template_json = excluded.template_json,
                    updated_at = excluded.updated_at
                """,
                (template_id, name, description, template_json, now, now),
            )
        return self.get_template(template_id)  # type: ignore

    def list_templates(self) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM job_templates ORDER BY created_at DESC").fetchall()
        return [self._template_row_to_record(row) for row in rows]

    def get_template(self, template_id: str) -> dict[str, Any] | None:
        with self.lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM job_templates WHERE id = ?", (template_id,)).fetchone()
        return self._template_row_to_record(row) if row else None

    def delete_template(self, template_id: str) -> bool:
        with self.lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM job_templates WHERE id = ?", (template_id,))
            return bool(cursor.rowcount)

    def _template_row_to_record(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "template": json.loads(row["template_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def save_api_key(self, key_data: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        key_id = key_data.get("id") or uuid.uuid4().hex[:12]
        name = key_data.get("name", "")
        key_hash = key_data.get("key_hash", "")
        role = key_data.get("role", "operator")
        expires_at = key_data.get("expires_at")
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO api_keys (id, name, key_hash, role, created_at, expires_at, last_used_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    key_hash = excluded.key_hash,
                    role = excluded.role,
                    expires_at = excluded.expires_at
                """,
                (key_id, name, key_hash, role, now, expires_at, None),
            )
        return {"id": key_id, "name": name, "role": role, "created_at": now, "expires_at": expires_at}

    def list_api_keys(self) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM api_keys ORDER BY created_at DESC").fetchall()
        return [{"id": r["id"], "name": r["name"], "role": r["role"], "created_at": r["created_at"], "expires_at": r["expires_at"], "last_used_at": r["last_used_at"]} for r in rows]

    def get_api_key_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        now = time.time()
        with self.lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)).fetchone()
            if not row:
                return None
            if row["expires_at"] is not None and now > row["expires_at"]:
                return None
            connection.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now, row["id"]))
        return {"id": row["id"], "name": row["name"], "role": row["role"], "created_at": row["created_at"], "expires_at": row["expires_at"]}

    def delete_api_key(self, key_id: str) -> bool:
        with self.lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
            return bool(cursor.rowcount)

    def save_webhook(self, webhook: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        webhook_id = webhook.get("id") or uuid.uuid4().hex[:12]
        url = webhook.get("url", "")
        secret = webhook.get("secret", "")
        events = json.dumps(webhook.get("events", []), ensure_ascii=False)
        enabled = 1 if webhook.get("enabled", True) else 0
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO webhooks (id, url, secret, events_json, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    url = excluded.url,
                    secret = excluded.secret,
                    events_json = excluded.events_json,
                    enabled = excluded.enabled
                """,
                (webhook_id, url, secret, events, enabled, now),
            )
        return self.get_webhook(webhook_id)  # type: ignore

    def list_webhooks(self) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM webhooks ORDER BY created_at DESC").fetchall()
        return [self._webhook_row_to_record(r) for r in rows]

    def get_webhook(self, webhook_id: str) -> dict[str, Any] | None:
        with self.lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM webhooks WHERE id = ?", (webhook_id,)).fetchone()
        return self._webhook_row_to_record(row) if row else None

    def delete_webhook(self, webhook_id: str) -> bool:
        with self.lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))
            return bool(cursor.rowcount)

    def _webhook_row_to_record(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "url": row["url"],
            "secret": row["secret"][:4] + "..." if len(row["secret"]) > 4 else "****",
            "events": json.loads(row["events_json"]),
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
        }

    def save_overlay(self, provider_id: str, overlay: dict[str, Any]) -> None:
        now = time.time()
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO schema_overlays (id, provider_id, overlay_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    overlay_json = excluded.overlay_json,
                    updated_at = excluded.updated_at
                """,
                (provider_id, provider_id, json.dumps(overlay, ensure_ascii=False), now),
            )

    def get_overlay(self, provider_id: str) -> dict[str, Any]:
        with self.lock, self._connect() as connection:
            row = connection.execute("SELECT overlay_json FROM schema_overlays WHERE provider_id = ?", (provider_id,)).fetchone()
        if not row:
            return {}
        try:
            return json.loads(row["overlay_json"])
        except (TypeError, json.JSONDecodeError):
            return {}

    def save_workflow(self, workflow: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        wf_id = workflow.get("id") or os.urandom(6).hex()
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workflows (id, name, steps_json, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    steps_json = excluded.steps_json,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (wf_id, workflow.get("name", "Untitled Workflow"), json.dumps(workflow.get("steps", []), ensure_ascii=False), workflow.get("status", "draft"), workflow.get("created_at", now), now),
            )
        return {"id": wf_id, "name": workflow.get("name", "Untitled Workflow"), "steps": workflow.get("steps", []), "status": workflow.get("status", "draft")}

    def list_workflows(self) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM workflows ORDER BY created_at DESC").fetchall()
        result = []
        for r in rows:
            try: steps = json.loads(r["steps_json"])
            except Exception: steps = []
            result.append({"id": r["id"], "name": r["name"], "steps": steps, "status": r["status"]})
        return result

    def delete_workflow(self, wf_id: str) -> bool:
        with self.lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM workflows WHERE id = ?", (wf_id,))
            return bool(cursor.rowcount)

    def save_mcp_server(self, server: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        srv_id = server.get("id") or os.urandom(6).hex()
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO mcp_servers (id, name, command, args_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    command = excluded.command,
                    args_json = excluded.args_json,
                    status = excluded.status
                """,
                (srv_id, server.get("name", "MCP Server"), server.get("command", "npx"), json.dumps(server.get("args", []), ensure_ascii=False), server.get("status", "active"), now),
            )
        return {"id": srv_id, "name": server.get("name", "MCP Server"), "command": server.get("command", "npx"), "args": server.get("args", []), "status": server.get("status", "active")}

    def list_mcp_servers(self) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM mcp_servers ORDER BY created_at DESC").fetchall()
        result = []
        for r in rows:
            try: args = json.loads(r["args_json"])
            except Exception: args = []
            result.append({"id": r["id"], "name": r["name"], "command": r["command"], "args": args, "status": r["status"]})
        return result

    def delete_mcp_server(self, srv_id: str) -> bool:
        with self.lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM mcp_servers WHERE id = ?", (srv_id,))
            return bool(cursor.rowcount)

    def save_worktree(self, wt: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        wt_id = wt.get("id") or os.urandom(6).hex()
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO worktrees (id, path, branch, status, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    path = excluded.path,
                    branch = excluded.branch,
                    status = excluded.status
                """,
                (wt_id, wt.get("path", ""), wt.get("branch", "main"), wt.get("status", "active"), now),
            )
        return {"id": wt_id, "path": wt.get("path", ""), "branch": wt.get("branch", "main"), "status": wt.get("status", "active")}

    def list_worktrees(self) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM worktrees ORDER BY created_at DESC").fetchall()
        return [{"id": r["id"], "path": r["path"], "branch": r["branch"], "status": r["status"]} for r in rows]

    def delete_worktree(self, wt_id: str) -> bool:
        with self.lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM worktrees WHERE id = ?", (wt_id,))
            return bool(cursor.rowcount)

    def save_mfa_secret(self, user_id: str, secret: str, enabled: bool = True) -> None:
        now = time.time()
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO mfa_secrets (user_id, secret, enabled, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    secret = excluded.secret,
                    enabled = excluded.enabled
                """,
                (user_id, secret, 1 if enabled else 0, now),
            )

    def save_user(self, username: str, password_hash: str, role: str = "operator") -> dict[str, Any]:
        now = time.time()
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO users (username, password_hash, role, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    password_hash = excluded.password_hash,
                    role = excluded.role
                """,
                (username, password_hash, role, now),
            )
        return {"username": username, "role": role, "created_at": now}

    def get_user(self, username: str) -> dict[str, Any] | None:
        with self.lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not row: return None
        return {"username": row["username"], "password_hash": row["password_hash"], "role": row["role"], "created_at": row["created_at"]}

    def list_users(self) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            rows = connection.execute("SELECT username, role, created_at FROM users ORDER BY created_at ASC").fetchall()
        return [{"username": r["username"], "role": r["role"], "created_at": r["created_at"]} for r in rows]

    def get_mfa_secret(self, user_id: str) -> dict[str, Any] | None:
        with self.lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM mfa_secrets WHERE user_id = ?", (user_id,)).fetchone()
        if not row: return None
        return {"user_id": row["user_id"], "secret": row["secret"], "enabled": bool(row["enabled"])}

    @staticmethod
    def _preset_row_to_record(row: sqlite3.Row) -> dict[str, Any]:
        def safe_json(val: str, default: Any) -> Any:
            try:
                return json.loads(val)
            except (TypeError, json.JSONDecodeError):
                return default

        return {
            "id": row["id"],
            "name": row["name"],
            "provider_id": row["provider_id"],
            "command_path": safe_json(row["command_path_json"], []),
            "global_options": safe_json(row["global_options_json"], {}),
            "command_options": safe_json(row["command_options_json"], {}),
            "positionals": safe_json(row["positionals_json"], []),
            "raw_args": safe_json(row["raw_args_json"], []),
            "prompt": row["prompt"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> dict[str, Any]:
        try:
            argv = json.loads(row["argv_json"])
        except (TypeError, json.JSONDecodeError):
            argv = []
        return {
            "id": row["id"],
            "provider_id": row["provider_id"],
            "argv": argv if isinstance(argv, list) else [],
            "cwd": row["cwd"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "status": row["status"],
            "return_code": row["return_code"],
            "error": row["error"],
            "risk": row["risk"],
            "timeout_seconds": row["timeout_seconds"],
            "output": bytes(row["output"] or b""),
            "output_base": int(row["output_base"] or 0),
            "retry_count": int(row["retry_count"] or 0),
            "max_retries": int(row["max_retries"] or 0),
            "retry_policy": row["retry_policy"] or "exponential",
            "retry_initial_delay": float(row["retry_initial_delay"] or 1.0),
            "retry_max_delay": float(row["retry_max_delay"] or 300.0),
            "priority": row["priority"] or "normal",
        }

    # --- Notification channels ---

    def save_notification_channel(self, channel: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        ch_id = channel.get("id") or os.urandom(6).hex()
        ctype = channel.get("type", "slack")
        name = channel.get("name", ctype)
        url = channel.get("url", "")
        recipients = json.dumps(channel.get("recipients", []))
        events = json.dumps(channel.get("events", []))
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO notification_channels (id, type, name, url, recipients_json, events_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    type = excluded.type,
                    name = excluded.name,
                    url = excluded.url,
                    recipients_json = excluded.recipients_json,
                    events_json = excluded.events_json
                """,
                (ch_id, ctype, name, url, recipients, events, now),
            )
        return {"id": ch_id, "type": ctype, "name": name, "url": url, "recipients": channel.get("recipients", []), "events": channel.get("events", [])}

    def list_notification_channels(self) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM notification_channels ORDER BY created_at DESC").fetchall()
        result = []
        for r in rows:
            try:
                recipients = json.loads(r["recipients_json"])
            except (TypeError, json.JSONDecodeError):
                recipients = []
            try:
                events = json.loads(r["events_json"])
            except (TypeError, json.JSONDecodeError):
                events = []
            result.append({"id": r["id"], "type": r["type"], "name": r["name"], "url": r["url"], "recipients": recipients, "events": events})
        return result

    def delete_notification_channel(self, ch_id: str) -> bool:
        with self.lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM notification_channels WHERE id = ?", (ch_id,))
            return bool(cursor.rowcount)

    # --- Scheduled workflows ---

    def save_scheduled_workflow(self, sched: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        s_id = sched.get("id") or os.urandom(6).hex()
        name = sched.get("name", "Scheduled Workflow")
        provider_id = sched.get("provider_id", "shell")
        command = json.dumps(sched.get("command", []))
        cwd = sched.get("cwd", "")
        interval = sched.get("interval_seconds", 0)
        next_run = sched.get("next_run_at")
        enabled = 1 if sched.get("enabled", 1) else 0
        timeout = sched.get("timeout_seconds", 3600)
        with self.lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO scheduled_workflows (id, name, provider_id, command_json, cwd, interval_seconds, next_run_at, enabled, timeout_seconds, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    provider_id = excluded.provider_id,
                    command_json = excluded.command_json,
                    cwd = excluded.cwd,
                    interval_seconds = excluded.interval_seconds,
                    next_run_at = excluded.next_run_at,
                    enabled = excluded.enabled,
                    timeout_seconds = excluded.timeout_seconds
                """,
                (s_id, name, provider_id, command, cwd, interval, next_run, enabled, timeout, now),
            )
        return {"id": s_id, "name": name, "provider_id": provider_id, "command": sched.get("command", []), "cwd": cwd, "interval_seconds": interval, "next_run_at": next_run, "enabled": enabled, "timeout_seconds": timeout}

    def list_scheduled_workflows(self) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM scheduled_workflows ORDER BY created_at DESC").fetchall()
        result = []
        for r in rows:
            try:
                command = json.loads(r["command_json"])
            except (TypeError, json.JSONDecodeError):
                command = []
            result.append({"id": r["id"], "name": r["name"], "provider_id": r["provider_id"], "command": command, "cwd": r["cwd"], "interval_seconds": r["interval_seconds"], "next_run_at": r["next_run_at"], "enabled": r["enabled"], "timeout_seconds": r["timeout_seconds"]})
        return result

    def delete_scheduled_workflow(self, s_id: str) -> bool:
        with self.lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM scheduled_workflows WHERE id = ?", (s_id,))
            return bool(cursor.rowcount)

    # --- Audit log ---

    def append_audit(self, action: str, actor: str = "system", target_type: str = "", target_id: str = "", details: dict[str, Any] | None = None) -> dict[str, Any]:
        now = time.time()
        details_json = json.dumps(details or {}, sort_keys=True)
        with self.lock, self._connect() as connection:
            last = connection.execute("SELECT checksum FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
            prev_checksum = last["checksum"] if last else ""
            payload = f"{now}:{action}:{actor}:{target_type}:{target_id}:{details_json}:{prev_checksum}"
            checksum = hashlib.sha256(payload.encode()).hexdigest()
            cursor = connection.execute(
                """
                INSERT INTO audit_log (timestamp, action, actor, target_type, target_id, details_json, checksum, prev_checksum)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (now, action, actor, target_type, target_id, details_json, checksum, prev_checksum),
            )
            return {"id": cursor.lastrowid, "timestamp": now, "action": action, "checksum": checksum}

    def export_audit_log(self, *, since: float = 0, limit: int = 10000) -> list[dict[str, Any]]:
        with self.lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_log WHERE timestamp >= ? ORDER BY id ASC LIMIT ?",
                (since, limit),
            ).fetchall()
        result = []
        for r in rows:
            result.append({
                "id": r["id"],
                "timestamp": r["timestamp"],
                "action": r["action"],
                "actor": r["actor"],
                "target_type": r["target_type"],
                "target_id": r["target_id"],
                "details": json.loads(r["details_json"]) if r["details_json"] else {},
                "checksum": r["checksum"],
                "prev_checksum": r["prev_checksum"],
            })
        return result

    def verify_audit_chain(self) -> dict[str, Any]:
        with self.lock, self._connect() as connection:
            rows = connection.execute("SELECT * FROM audit_log ORDER BY id ASC").fetchall()
        total = len(rows)
        valid = 0
        broken_at = None
        for i, r in enumerate(rows):
            expected_prev = rows[i - 1]["checksum"] if i > 0 else ""
            if r["prev_checksum"] != expected_prev:
                broken_at = r["id"]
                break
            payload = f"{r['timestamp']}:{r['action']}:{r['actor']}:{r['target_type']}:{r['target_id']}:{r['details_json']}:{r['prev_checksum']}"
            expected = hashlib.sha256(payload.encode()).hexdigest()
            if expected != r["checksum"]:
                broken_at = r["id"]
                break
            valid += 1
        return {"total": total, "valid": valid, "intact": broken_at is None, "broken_at": broken_at}

    # --- Backup & Restore ---

    def export_backup(self) -> dict[str, Any]:
        with self.lock, self._connect() as connection:
            jobs = [dict(row) for row in connection.execute("SELECT * FROM jobs").fetchall()]
            presets = [dict(row) for row in connection.execute("SELECT * FROM presets").fetchall()]
            workflows = [dict(row) for row in connection.execute("SELECT * FROM workflows").fetchall()]
            mcp_servers = [dict(row) for row in connection.execute("SELECT * FROM mcp_servers").fetchall()]
            templates = [dict(row) for row in connection.execute("SELECT * FROM job_templates").fetchall()]
            schedules = [dict(row) for row in connection.execute("SELECT * FROM scheduled_workflows").fetchall()]
            notifications = [dict(row) for row in connection.execute("SELECT * FROM notification_channels").fetchall()]
            audit = [dict(row) for row in connection.execute("SELECT * FROM audit_log").fetchall()]
        return {
            "schema_version": SCHEMA_VERSION,
            "exported_at": time.time(),
            "jobs": jobs,
            "presets": presets,
            "workflows": workflows,
            "mcp_servers": mcp_servers,
            "templates": templates,
            "schedules": schedules,
            "notifications": notifications,
            "audit_log": audit,
        }

    def import_backup(self, backup: dict[str, Any]) -> dict[str, Any]:
        if backup.get("schema_version") != SCHEMA_VERSION:
            return {"ok": False, "error": f"Schema version mismatch: backup={backup.get('schema_version')}, current={SCHEMA_VERSION}"}
        counts: dict[str, int] = {}
        with self.lock, self._connect() as connection:
            for table_name, rows in [
                ("presets", backup.get("presets", [])),
                ("workflows", backup.get("workflows", [])),
                ("mcp_servers", backup.get("mcp_servers", [])),
                ("job_templates", backup.get("templates", [])),
                ("scheduled_workflows", backup.get("schedules", [])),
                ("notification_channels", backup.get("notifications", [])),
            ]:
                count = 0
                for row in rows:
                    cols = ", ".join(row.keys())
                    placeholders = ", ".join("?" for _ in row)
                    try:
                        connection.execute(
                            f"INSERT OR REPLACE INTO {table_name} ({cols}) VALUES ({placeholders})",
                            list(row.values()),
                        )
                        count += 1
                    except sqlite3.OperationalError:
                        pass
                counts[table_name] = count
            # Jobs are restored as orphaned to prevent unsafe resumption
            for row in backup.get("jobs", []):
                row["status"] = "orphaned"
                cols = ", ".join(row.keys())
                placeholders = ", ".join("?" for _ in row)
                try:
                    connection.execute(
                        f"INSERT OR REPLACE INTO jobs ({cols}) VALUES ({placeholders})",
                        list(row.values()),
                    )
                except sqlite3.OperationalError:
                    pass
            counts["jobs"] = len(backup.get("jobs", []))
        return {"ok": True, "imported": counts}
