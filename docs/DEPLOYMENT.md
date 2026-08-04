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

Open `http://127.0.0.1:8765` in a browser, or launch the desktop GUI:

```bash
python3 gui.py
```

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

> **v3.4.3**: The Dockerfile `COPY` command now includes `gui.py` — previous images omitted it, causing the desktop GUI launcher to fail inside containers.

### Observability Stack

Docker Compose includes optional Grafana and Prometheus services for monitoring:

- **Prometheus**: `http://127.0.0.1:9090`
- **Grafana**: `http://127.0.0.1:3000` (default admin/admin)

Configuration files:
- `grafana/prometheus.yml` — Prometheus scrape targets
- `grafana/alerts.yaml` — Alerting rules (high error rate, queue depth, circuit breaker open)
- `grafana/dashboard.json` — Pre-built Grafana dashboard
- `grafana/provisioning/` — Auto-provisioned datasources and dashboards

Set `GRAFANA_ADMIN_PASSWORD` in `.env` or the environment to change the default Grafana password.

## Environment Variables

v3.4.3 added 15 environment variables to `.env.example` that were previously undocumented. Key groups:

- **SMTP**: `PANEL_SMTP_HOST`, `PANEL_SMTP_PORT`, `PANEL_SMTP_USER`, `PANEL_SMTP_PASS`, `PANEL_SMTP_FROM` — for email notification delivery
- **PTY & Sandbox**: `PANEL_USE_PTY`, `PANEL_SANDBOX_DRIVER` — pseudo-terminal and container isolation
- **Provider Rate Limits**: `PANEL_PROVIDER_RATE_LIMIT`, `PANEL_PROVIDER_CONCURRENCY` — per-provider RPM and concurrency caps
- **Circuit Breaker**: `PANEL_CIRCUIT_BREAKER_THRESHOLD`, `PANEL_CIRCUIT_BREAKER_COOLDOWN` — failure threshold and recovery time
- **Load Shedder**: `PANEL_MAX_QUEUE_DEPTH`, `PANEL_MAX_RUNNING_RATIO` — overload thresholds
- **Health Probes**: `PANEL_HEALTH_PROBE_INTERVAL`, `PANEL_HEALTH_PROBE_FAILURES` — check frequency and auto-disable count

See the full configuration table in [README.md](../README.md).

## PostgreSQL

For enterprise deployments, replace SQLite with PostgreSQL:

```bash
export PANEL_POSTGRES_URL="postgresql://user:password@localhost:5432/commandcenter"
```

The storage adapter in `storage.py` is isolated behind a common interface, so switching to PostgreSQL requires no changes to HTTP handlers or the execution model.

## Backup

### File-based backup

Stop writes or stop the service, then copy:

```bash
systemctl --user stop ai-cli-command-center
cp -a ~/.config/ai-cli-command-center ~/backup/
cp -a ~/.local/state/ai-cli-command-center ~/backup/
systemctl --user start ai-cli-command-center
```

SQLite WAL mode may create `jobs.sqlite3-wal` and `jobs.sqlite3-shm`; copy the whole state directory rather than only the main database file.

### API-based backup

Export a full database snapshot as JSON:

```bash
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/backup > backup.json
```

Import a backup:

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d @backup.json http://127.0.0.1:8765/api/restore
```

## Logs and health

```bash
journalctl --user -u ai-cli-command-center -f
curl -fsS http://127.0.0.1:8765/healthz
curl -fsS http://127.0.0.1:8765/readyz
```

Logs are JSON by default. Use `PANEL_LOG_FORMAT=text` for human-oriented output.

## Metrics

Prometheus metrics are available at `GET /api/metrics` (text format) or `GET /api/metrics` with `Accept: application/json` for structured output. Metrics include:

- Total jobs by status (queued, running, succeeded, failed, etc.)
- Per-provider totals and average latency
- Queue depth and running count
- Circuit breaker states
- Load shedder status

## Notifications

Configure Slack, Discord, or email notifications via the API or GUI:

```bash
# Slack
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"type":"slack","name":"Alerts","url":"https://hooks.slack.com/...","events":["job.failed","job.succeeded"]}' \
  http://127.0.0.1:8765/api/notifications

# Discord
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"type":"discord","name":"Alerts","url":"https://discord.com/api/webhooks/...","events":["job.failed"]}' \
  http://127.0.0.1:8765/api/notifications

# Email
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"type":"email","name":"Ops","recipients":["ops@example.com"],"events":["job.failed"]}' \
  http://127.0.0.1:8765/api/notifications
```
