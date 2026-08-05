from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "deploy" / "public"


def read(name: str) -> str:
    return (PUBLIC / name).read_text(encoding="utf-8")


def test_public_compose_keeps_application_behind_https_edge():
    compose = read("compose.yaml")

    assert 'name: zeaz-public' in compose
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
    assert './providers:/providers:ro' in compose
    assert 'zeaz-public-data:/data' in compose
    assert 'zeaz-public-backups:/backups' in compose


def test_caddy_enforces_tls_proxy_and_security_headers():
    caddyfile = read("Caddyfile")

    assert '{$ZEAZ_DOMAIN}' in caddyfile
    assert 'reverse_proxy app:8765' in caddyfile
    assert 'health_uri /healthz' in caddyfile
    assert 'Strict-Transport-Security' in caddyfile
    assert 'X-Content-Type-Options "nosniff"' in caddyfile
    assert 'X-Frame-Options "DENY"' in caddyfile
    assert '-Server' in caddyfile


def test_public_environment_contains_no_real_secret():
    environment = read(".env.example")

    assert 'ZEAZ_VERSION=3.4.3' in environment
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

    assert 'backup.backup(restored)' in restore
    assert 'PRAGMA integrity_check' in restore
    assert 'candidate.parent != BACKUP_ROOT' in restore
    assert 'pre-restore-' in restore


def test_public_scripts_fail_closed():
    installer = read("install.sh")
    updater = read("update.sh")
    restore = read("restore.sh")

    for script in (installer, updater, restore):
        assert 'set -euo pipefail' in script

    assert 'PANEL_TOKEN must contain at least 48 characters' in installer
    assert 'docker compose config --quiet' in installer
    assert 'ZEAZ_BACKUP_INTERVAL_SECONDS=0' in updater
    assert 'Type RESTORE to continue' in restore
