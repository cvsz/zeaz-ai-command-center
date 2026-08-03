#!/usr/bin/env python3
"""Durable SQLite storage for AI CLI Command Center jobs.

The runtime intentionally keeps SQLite behind this small adapter so a future
PostgreSQL implementation can replace it without changing the HTTP or job
execution layers.
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
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
                "CREATE INDEX IF NOT EXISTS presets_created_at_idx ON presets(created_at DESC)"
            )
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
                    timeout_seconds, output, output_base, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        }
