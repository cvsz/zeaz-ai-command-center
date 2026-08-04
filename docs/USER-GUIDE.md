# User Guide & Operations Manual

## Overview
AI CLI Command Center is a provider-agnostic, local-first web interface and desktop GUI that discovers installed AI CLI executables (e.g. OpenAI Codex, Claude Code, Gemini CLI, Qwen Code, Aider, Ollama), parses their `--help` outputs in real-time, and auto-generates structured, interactive command builders.

## Features

### Core (v2.0–v2.1)
- **Zero Configuration Discovery**: Auto-detects installed CLI binaries from `$PATH` or custom paths.
- **Dynamic Help Parsing**: Parses flags, subcommands, positional parameters, options, defaults, and env overrides.
- **Durable SQLite Execution Engine**: Background process execution with streamed output over Server-Sent Events (SSE).
- **Hardened Security Controls**: Unsandboxed or destructive commands require strict text confirmation (`CONFIRM` / `I UNDERSTAND`). Redacts secret tokens from job execution logs.

### Interactive Tools (v2.2)
- **Workspace File Browser**: Browse project directories directly from the UI.
- **Git Diff Viewer**: Inspect uncommitted changes in the workspace.
- **Presets & Favorites**: Save and reload reusable command configurations.
- **Downloadable Job Logs**: Export full terminal output from completed jobs.
- **Schema Correction Overlays**: Fix parsed help schemas with JSON overlays.

### Workflow Platform (v3.0)
- **Durable Workflows**: Create multi-step execution chains via `/api/workflows` to run sequential AI jobs and pipelines.
- **MCP Tool Manager**: Register Model Context Protocol (MCP) servers via `/api/mcp` to expose system tools to external AI agents.
- **Git Worktree Isolation**: Create isolated git worktrees per task via `/api/worktrees` to eliminate workspace collisions.
- **Multi-User RBAC**: User accounts with admin/operator/viewer roles.
- **MFA (TOTP)**: Two-factor authentication via authenticator apps.
- **GitHub PR Integration**: Create and list pull requests from the UI.
- **Container Sandbox Adapters**: `bwrap` and `docker` sandbox drivers for isolated execution.
- **PostgreSQL Adapter**: Enterprise storage backend via `PANEL_POSTGRES_URL`.

### Observability & Integrations (v3.1)
- **Job Analytics Dashboard**: Execution duration, success/failure rates, provider usage stats, duration percentiles (p50/p95/p99).
- **Prometheus Metrics**: Per-provider latency, queue depth, workflow DAG latency.
- **Grafana Dashboards**: Pre-built dashboards and alerting rules (included in Docker Compose).
- **Notification Integrations**: Slack, Discord, and email alerts on job/workflow completion or failure.
- **GitLab & Bitbucket**: MR/PR integration alongside GitHub.
- **Calendar-Scheduled Workflows**: Cron-based scheduling with ICS import.
- **Tamper-Evident Audit Log**: SHA-256 chain-linked log with integrity verification.

### Reliability & Hardening (v3.2)
- **Per-Provider Rate Limiting**: Concurrency caps and RPM limits per provider.
- **Job Retry Policies**: Configurable backoff (linear, exponential, fixed) with max delay.
- **Circuit Breaker**: Per-provider circuit with closed/open/half-open states.
- **Graceful Degradation**: Shed low-priority jobs and throttle non-critical endpoints under load.
- **Provider Health Probes**: Periodic health checks with automatic disable on repeated failure.
- **Job Priority Queuing**: Urgent, normal, and background tiers.
- **Request Validation**: Schema enforcement for all API endpoints.

### Real-Time & API Quality (v3.3)
- **API Versioning**: `/api/v1/` prefix, `X-API-Version` header, and `GET /api/version`.
- **Job Templates**: CRUD API with template_id pre-fill on job creation.
- **Database Backup/Restore**: JSON snapshot export/import.
- **Scoped API Keys**: Create, list, revoke with role-based permissions.
- **Outgoing Webhooks**: HMAC-SHA256 signing and event filtering.
- **Bulk Job Operations**: Bulk create, bulk stop, bulk delete.
- **Unified SSE Event Stream**: `GET /api/events` for real-time job state changes.

### Desktop GUI (v3.4)
- **Windows 11 Fluent Design**: Native-feeling desktop client with Segoe UI Variable, Mica-like background, and accent colors.
- **15 Navigation Pages**: Dashboard, Jobs, Workflows, Templates, Presets, Analytics, Providers, Users, API Keys, Webhooks, Notifications, MCP Servers, Audit Log, Scheduler, Settings.
- **Live Event Feed**: Bottom panel with color-coded SSE events and auto-refresh.
- **Full CRUD**: Create/edit/delete dialogs for all resource types.
- **Connection Management**: Configure server URL, bearer token, and backup/restore from Settings.

## Quick Start

### Web UI
```bash
python3 server.py --host 127.0.0.1 --port 8765
```
Open `http://127.0.0.1:8765` in your web browser.

### Desktop GUI
```bash
python3 gui.py
```
Configure the server URL and bearer token in the Settings page.

## Configuration Options via Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `PANEL_HOST` | `127.0.0.1` | Bind address |
| `PANEL_PORT` | `8765` | HTTP port |
| `PANEL_TOKEN` | empty | Bearer token for HTTP API authentication |
| `PANEL_ALLOW_ANY_CWD` | `0` | Allow targeting any working directory |
| `PANEL_ALLOW_ABSOLUTE_BINARIES` | `0` | Allow probing arbitrary binary locations |
| `PANEL_DATABASE_PATH` | XDG state path | SQLite database path |
| `PANEL_POSTGRES_URL` | empty | PostgreSQL connection URL |
| `PANEL_MAX_CONCURRENT_JOBS` | `4` | Simultaneous provider processes |
| `PANEL_USE_PTY` | `0` | Enable pseudo-terminal allocation |
| `PANEL_SANDBOX_DRIVER` | empty | Container sandbox driver (`bwrap`, `docker`) |
| `PANEL_RATE_LIMIT_PER_MINUTE` | `240` | API requests per source IP |
| `PANEL_LOG_FORMAT` | `json` | `json` or `text` |

## Monitoring

### Prometheus
Access at `http://127.0.0.1:9090` when using Docker Compose. Metrics include per-provider latency, queue depth, and job counts by status.

### Grafana
Access at `http://127.0.0.1:3000` (default admin/admin). Pre-built dashboards and alerting rules are in `grafana/`.

### Health Endpoints
```bash
curl http://127.0.0.1:8765/healthz    # Liveness
curl http://127.0.0.1:8765/readyz     # Readiness
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/load    # Load stats
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/analytics  # Analytics
```

## Audit Log

The audit log is tamper-evident with SHA-256 chain-linked checksums. Verify integrity:

```bash
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/audit/verify
```

Export entries:

```bash
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/audit > audit.json
```

## Backup & Restore

Export a full database backup:

```bash
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/backup > backup.json
```

Import a backup:

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d @backup.json http://127.0.0.1:8765/api/restore
```

Jobs are restored as `orphaned` to prevent unsafe resumption.
