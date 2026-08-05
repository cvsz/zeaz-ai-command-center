import hashlib
import importlib.util
import sqlite3
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "deploy" / "public"


def read(name: str) -> str:
    return (PUBLIC / name).read_text(encoding="utf-8")


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_database(path: Path, value: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker(value) VALUES (?)", (value,))


def test_public_compose_keeps_application_behind_https_edge():
    compose = read("compose.yaml")

    assert 'name: zeaz-public' in compose
    assert 'user: "${ZEAZ_UID:-1000}:${ZEAZ_GID:-1000}"' in compose
    assert 'HOME: /home/zeaz' in compose
    assert 'PANEL_HOST: 0.0.0.0' in compose
    assert 'PANEL_TOKEN: ${PANEL_TOKEN:?' in compose
    assert 'PANEL_ALLOWED_HOSTS: ${ZEAZ_DOMAIN:?' in compose
    assert 'PANEL_ENABLE_HSTS: "1"' in compose
    assert 'PANEL_ALLOWED_ROOTS: /workspace' in compose
    assert 'read_only: true' in compose
    assert 'no-new-privileges:true' in compose
    assert 'cap_drop:' in compose
    assert 'expose:\n      - "8765"' in compose
    assert '"8765:8765"' not in compose
    assert '"80:80"' in compose
    assert '"443:443"' in compose
    assert '"443:443/udp"' in compose
    assert './data:/data' in compose
    assert './home:/home/zeaz' in compose
    assert './workspace:/workspace' in compose
    assert './providers:/providers:ro' in compose
    assert './backups:/backups' in compose


def test_caddy_enforces_tls_proxy_and_security_headers():
    caddyfile = read("Caddyfile")

    assert '{$ZEAZ_DOMAIN}' in caddyfile
    assert 'reverse_proxy app:8765' in caddyfile
    assert 'health_uri /healthz' in caddyfile
    assert 'health_headers {' in caddyfile
    assert 'Host {$ZEAZ_DOMAIN}' in caddyfile
    assert 'Strict-Transport-Security' in caddyfile
    assert 'X-Content-Type-Options "nosniff"' in caddyfile
    assert 'X-Frame-Options "DENY"' in caddyfile
    assert '-Server' in caddyfile


def test_public_environment_contains_no_real_secret():
    environment = read(".env.example")

    assert 'ZEAZ_VERSION=3.4.3' in environment
    assert 'ZEAZ_UID=1000' in environment
    assert 'ZEAZ_GID=1000' in environment
    assert 'ai.example.com' in environment
    assert 'replace-with-at-least-48-random-bytes' in environment
    assert 'ghp_' not in environment
    assert 'github_pat_' not in environment
    assert 'sk-' not in environment


def test_backup_and_restore_are_integrity_checked():
    backup = read("backup.py")
    restore = read("restore.py")

    assert 'source.backup(destination)' in backup
    assert 'PRAGMA integrity_check' in backup
    assert 'hashlib.sha256()' in backup
    assert 'RETENTION_DAYS' in backup

    assert 'verify_checksum(source)' in restore
    assert 'backup.backup(restored)' in restore
    assert 'PRAGMA integrity_check' in restore
    assert 'candidate.parent != BACKUP_ROOT' in restore
    assert 'pre-restore-' in restore


def test_backup_and_restore_round_trip(tmp_path: Path, monkeypatch):
    backup_module = load_module("zeaz_public_backup_test", PUBLIC / "backup.py")
    restore_module = load_module("zeaz_public_restore_test", PUBLIC / "restore.py")

    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "backups"
    data_dir.mkdir()
    backup_dir.mkdir()
    database = data_dir / "jobs.sqlite3"
    create_database(database, "before-backup")

    backup_module.SOURCE = database
    backup_module.BACKUP_DIR = backup_dir
    backup_module.RETENTION_DAYS = 14
    snapshot = backup_module.create_backup()
    assert snapshot is not None and snapshot.exists()
    checksum_path = snapshot.with_suffix(snapshot.suffix + ".sha256")
    assert checksum_path.exists()
    expected_checksum = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert checksum_path.read_text(encoding="utf-8").split()[0] == expected_checksum

    database.unlink()
    create_database(database, "current-state")

    restore_module.TARGET = database
    restore_module.BACKUP_ROOT = backup_dir.resolve()
    monkeypatch.setattr(sys, "argv", ["restore.py", snapshot.name])
    assert restore_module.main() == 0

    with sqlite3.connect(database) as connection:
        restored_value = connection.execute("SELECT value FROM marker").fetchone()[0]
    assert restored_value == "before-backup"
    assert list(data_dir.glob("jobs.sqlite3.pre-restore-*"))


def test_public_scripts_fail_closed():
    installer = read("install.sh")
    updater = read("update.sh")
    restore = read("restore.sh")

    for script in (installer, updater, restore):
        assert 'set -euo pipefail' in script

    assert 'PANEL_TOKEN must contain at least 48 characters' in installer
    assert 'ZEAZ_UID and ZEAZ_GID must be numeric' in installer
    assert 'docker compose config --quiet' in installer
    assert 'ZEAZ_BACKUP_INTERVAL_SECONDS=0' in updater
    assert 'Type RESTORE to continue' in restore
