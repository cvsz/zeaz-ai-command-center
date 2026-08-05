#!/usr/bin/env python3
"""Create verified SQLite backups for the standalone public deployment."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SOURCE = Path("/data/jobs.sqlite3")
BACKUP_DIR = Path("/backups")
INTERVAL = max(0, int(os.getenv("ZEAZ_BACKUP_INTERVAL_SECONDS", "86400")))
RETENTION_DAYS = max(1, int(os.getenv("ZEAZ_BACKUP_RETENTION_DAYS", "14")))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_database(path: Path) -> None:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok":
        raise RuntimeError(f"SQLite integrity check failed for {path}: {result!r}")


def create_backup() -> Path | None:
    if not SOURCE.exists():
        print(f"backup skipped: {SOURCE} does not exist", flush=True)
        return None

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = BACKUP_DIR / f"jobs-{timestamp}.sqlite3"
    temporary = target.with_suffix(".sqlite3.tmp")

    with sqlite3.connect(f"file:{SOURCE}?mode=ro", uri=True) as source:
        with sqlite3.connect(temporary) as destination:
            source.backup(destination)

    verify_database(temporary)
    temporary.chmod(0o600)
    temporary.replace(target)
    checksum = sha256(target)
    checksum_path = target.with_suffix(target.suffix + ".sha256")
    checksum_path.write_text(f"{checksum}  {target.name}\n", encoding="utf-8")
    checksum_path.chmod(0o600)
    print(f"backup created: {target.name} sha256={checksum}", flush=True)
    return target


def prune_backups() -> None:
    cutoff = time.time() - (RETENTION_DAYS * 86400)
    for path in BACKUP_DIR.glob("jobs-*.sqlite3"):
        try:
            if path.stat().st_mtime >= cutoff:
                continue
            checksum_path = path.with_suffix(path.suffix + ".sha256")
            path.unlink(missing_ok=True)
            checksum_path.unlink(missing_ok=True)
            print(f"backup pruned: {path.name}", flush=True)
        except OSError as exc:
            print(f"backup prune warning for {path}: {exc}", file=sys.stderr, flush=True)


def run_once() -> None:
    create_backup()
    prune_backups()


def main() -> int:
    if INTERVAL == 0:
        run_once()
        return 0

    while True:
        started = time.monotonic()
        try:
            run_once()
        except Exception as exc:  # noqa: BLE001 - keep the backup sidecar alive
            print(f"backup failed: {exc}", file=sys.stderr, flush=True)
        elapsed = time.monotonic() - started
        time.sleep(max(1.0, INTERVAL - elapsed))


if __name__ == "__main__":
    raise SystemExit(main())
