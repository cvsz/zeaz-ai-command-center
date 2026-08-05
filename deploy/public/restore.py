#!/usr/bin/env python3
"""Restore a verified SQLite snapshot into the standalone public deployment."""

from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

TARGET = Path("/data/jobs.sqlite3")
BACKUP_ROOT = Path("/backups").resolve()


def verify_database(path: Path) -> None:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok":
        raise RuntimeError(f"SQLite integrity check failed for {path}: {result!r}")


def resolve_backup(raw: str) -> Path:
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = BACKUP_ROOT / candidate
    candidate = candidate.resolve(strict=True)
    if candidate.parent != BACKUP_ROOT:
        raise ValueError("backup must be a direct child of /backups")
    if candidate.suffix != ".sqlite3":
        raise ValueError("backup must have a .sqlite3 suffix")
    return candidate


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: restore.py <jobs-TIMESTAMP.sqlite3>", file=sys.stderr)
        return 2

    source = resolve_backup(sys.argv[1])
    verify_database(source)
    TARGET.parent.mkdir(parents=True, exist_ok=True)

    temporary = TARGET.with_suffix(".sqlite3.restore")
    temporary.unlink(missing_ok=True)
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as backup:
        with sqlite3.connect(temporary) as restored:
            backup.backup(restored)

    verify_database(temporary)
    temporary.chmod(0o600)

    if TARGET.exists():
        previous = TARGET.with_name(f"{TARGET.name}.pre-restore-{int(time.time())}")
        TARGET.replace(previous)
        previous.chmod(0o600)
        print(f"previous database preserved as {previous.name}")

    temporary.replace(TARGET)
    TARGET.chmod(0o600)
    for suffix in ("-wal", "-shm"):
        Path(f"{TARGET}{suffix}").unlink(missing_ok=True)
    print(f"restored {source.name} to {TARGET}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, sqlite3.Error, RuntimeError) as exc:
        print(f"restore failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
