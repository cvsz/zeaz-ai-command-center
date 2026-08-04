# Roadmap

## v2.1 — Production foundation

- [x] Durable SQLite jobs and restart recovery
- [x] SSE output streaming
- [x] Header-only bearer authentication
- [x] Host/origin/rate-limit controls
- [x] Environment allowlist and sensitive argv redaction
- [x] Provider SHA-256 fingerprints
- [x] Health, readiness, metrics, JSON logs
- [x] Rootless container and hardened systemd service
- [x] CI, CodeQL, Dependabot, expanded tests and documentation

## v2.2 — Interactive operations

- [x] WebSocket PTY & terminal stream
- [x] Stdin relay & approval prompt relay
- [x] Presets and favorites
- [x] Workspace file browser and diff viewer
- [x] Job retry/clone and downloadable logs
- [x] Schema correction overlays

## v3.0 — Workflow platform

- [x] Durable workflow engine with dependencies and approval gates
- [x] Git worktree isolation per execution
- [x] GitHub pull-request integration
- [x] MCP server and tool manager
- [x] PostgreSQL and queue adapters
- [x] Multi-user authentication and RBAC
- [x] Remote workers and container sandbox adapters

## v3.1 — Observability & integrations

- [x] Job analytics dashboard: execution duration, success/failure rates, provider usage stats
- [x] Prometheus metrics expansion: per-provider latency, queue depth, workflow DAG latency
- [x] Grafana dashboard templates and alerting rules
- [x] Notification integrations: Slack, Discord, email on job/workflow completion or failure
- [x] GitLab and Bitbucket provider integrations
- [x] Calendar-scheduled workflows (cron + ICS import)
- [x] Exportable audit logs with tamper-evident checksums

## v3.2 — Reliability & hardening

- [x] Per-provider rate limiting and concurrency caps
- [x] Job retry policies with configurable backoff (linear, exponential, fixed)
- [x] Circuit breaker for persistently failing providers
- [x] Graceful degradation under load: shed low-priority jobs, throttle non-critical endpoints
- [x] Provider health probes and automatic disable on repeated failure
- [x] Job priority queuing (urgent, normal, background tiers)
- [x] Request validation and schema enforcement for all API endpoints

## v3.3 — Real-Time, API Quality & Distribution

- [x] API versioning with /api/v1/ prefix, X-API-Version header, and GET /api/version
- [x] Comprehensive integration test suite for all HTTP endpoints
- [x] Job templates with CRUD API and template_id pre-fill on job creation
- [x] Database backup and restore with JSON snapshot export/import
- [x] Scoped API key management with create, list, revoke, and auth middleware integration
- [x] Outgoing webhooks with HMAC-SHA256 signing and event filtering
- [x] Bulk job operations: bulk create, bulk stop, bulk delete
- [x] Unified SSE event stream at GET /api/events for job state changes

## v3.4 — Windows 11 Fluent Design GUI

- [x] Native-feeling WinUI 3 / Fluent Design desktop client with tkinter
- [x] Navigation sidebar with 15 pages: Dashboard, Jobs, Workflows, Templates, Presets, Analytics, Providers, Users, API Keys, Webhooks, Notifications, MCP Servers, Audit Log, Scheduler, Settings
- [x] Dashboard with health stats, load metrics, and recent jobs
- [x] Jobs page with create/stop/delete/retry/bulk ops, status filter, and output viewer
- [x] CRUD dialogs for Workflows, Templates, Presets, API Keys, Webhooks, Notifications, MCP Servers, Schedules
- [x] Provider management with circuit breaker, rate limit, and health probe views
- [x] User management with role-based creation
- [x] Audit log viewer with chain verification and JSON export
- [x] Settings page with connection config, auth, and database backup/restore
- [x] Live SSE event feed panel with auto-refresh and color-coded events
- [x] Fluent-styled widgets: rounded buttons, card panels, status badges, combo boxes
- [x] Segoe UI Variable / Cascadia Code fonts, Mica-like background, accent colors

## v3.4.1 — Security Hardening

- [x] Fix CodeQL path-injection alert: validate_cwd uses explicit resolve() + startswith containment check
- [x] Fix CodeQL command-line-injection alert: run_capture validates argv and rejects absolute paths
- [x] Fix CodeQL weak-sensitive-data-hashing alert: password hashing migrated from SHA-256 to PBKDF2-HMAC-SHA256 with 600k iterations and per-password random salt

## Non-goals for v2

- Treating heuristic help parsing as an authoritative provider specification
- Providing strong isolation without an external OS/container/VM sandbox
- Persisting or centrally managing provider secrets
