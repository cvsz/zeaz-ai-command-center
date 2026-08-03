# Deployment

## Recommended: loopback plus SSH tunnel

On the server:

```bash
./install.sh --service --host=127.0.0.1 --port=8765
systemctl --user status ai-cli-command-center
```

On the workstation:

```bash
ssh -L 8765:127.0.0.1:8765 cvsz@zeaz-platform
```

Open `http://127.0.0.1:8765`.

## Upgrade

```bash
git pull --ff-only
make validate
./install.sh --service --host=127.0.0.1 --port=8765
```

The installer creates a timestamped backup of the previous application directory and preserves provider configuration and SQLite history.

## Network exposure

Set a strong token and explicit host allowlist:

```bash
export PANEL_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export PANEL_ALLOWED_HOSTS=command.example.com
./start.sh --host 0.0.0.0 --port 8765
```

Terminate TLS with Caddy, Nginx, or another reverse proxy. Set `PANEL_ENABLE_HSTS=1` only when requests always arrive through HTTPS. Restrict access with a firewall or VPN.

## Docker Compose

```bash
mkdir -p workspace
export PANEL_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
docker compose up --build -d
```

The supplied image is rootless, read-only, drops Linux capabilities, and persists state in a named volume. AI CLI binaries are not bundled. Build a derived image to install required providers, or mount carefully controlled binaries and dependencies.

## Backup

Stop writes or stop the service, then copy:

```bash
systemctl --user stop ai-cli-command-center
cp -a ~/.config/ai-cli-command-center ~/backup/
cp -a ~/.local/state/ai-cli-command-center ~/backup/
systemctl --user start ai-cli-command-center
```

SQLite WAL mode may create `jobs.sqlite3-wal` and `jobs.sqlite3-shm`; copy the whole state directory rather than only the main database file.

## Logs and health

```bash
journalctl --user -u ai-cli-command-center -f
curl -fsS http://127.0.0.1:8765/healthz
curl -fsS http://127.0.0.1:8765/readyz
```

Logs are JSON by default. Use `PANEL_LOG_FORMAT=text` for human-oriented output.
