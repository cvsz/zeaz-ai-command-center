# Changelog

All notable changes are documented here.


## [3.4.3] - 2026-08-04

### Fixed

- **Critical: `/api/keys` endpoint crashed** with `UnboundLocalError` due to local `import secrets` in `/api/mfa/setup` shadowing the module-level import. Removed the local import.
- **GitLab and Bitbucket merge/pull list endpoints** returned HTTP 500 when the `glab` or `bitbucket` CLIs were not installed. Now gracefully return empty lists.
- **`gui.py` SSE client** silently discarded `event:` lines from the server. Now captures the SSE event type and attaches it as `sse_type` on data events.
- **`Dockerfile`** was missing `gui.py` in the COPY command, so the GUI module was not available in container images.
- **`.env.example`** was missing 16 environment variables (SMTP, PTY, sandbox, provider rate limits, circuit breaker, load shedder, health probes). Updated header from v2.1 to v3.4.2.
- **`.gitignore`** was missing common patterns (`node_modules/`, `.DS_Store`, `.idea/`, `.vscode/`, `.mypy_cache/`, `.eggs/`, `*.swp`).

### Added

- 22 new tests: 7 for PBKDF2 password hashing and legacy SHA-256 migration, 12 for previously uncovered HTTP endpoints (analytics, webhooks, API keys, audit, backup/restore, SSE events, MFA, bulk operations, GitLab/Bitbucket), 1 for SSE event type tracking, 2 for circuit breaker reset and health probe enable.
- 15 environment variables added to the README.md configuration table (PANEL_MAX_BODY_BYTES, PANEL_LOG_LEVEL, SMTP settings, provider rate limits, circuit breaker, load shedder, health probes).
- `local_ai_provider.json` orphaned file removed and added to `.gitignore`.

## [3.4.2] - 2026-08-04

### Added

- Automated release lifecycle validation for source install, safe in-place upgrade, uninstall/purge, wheel/sdist installation, Compose validation, and container startup/health.
- Console launchers for both the web command center and Windows desktop GUI in Python wheel installations.
- A single `version.py` release source used by runtime, packaging, installer, Makefile, Docker, and validation tests.

### Fixed

- Runtime version drift (`3.3.0`), Docker/Compose tag drift (`2.1.0`), and missing GUI files in installed and packaged distributions.
- Installer upgrades now use a staged replacement, unique backups, rollback on replacement failure, and preserve external configuration/state.
- Build tooling now declares and validates its `build` dependency and verifies the generated wheel in an isolated environment.

## [3.4.1] - 2026-08-04

### Fixed

- **CodeQL #2 (path-injection)**: `validate_cwd` now uses explicit `resolve()` + `startswith` check for path containment, making validation clearer to static analysis
- **CodeQL #3 (command-line-injection)**: `run_capture` validates argv is non-empty and rejects absolute executable paths unless `PANEL_ALLOW_ABSOLUTE_BINARIES=1`
- **CodeQL #4 (weak-sensitive-data-hashing)**: Password hashing migrated from raw SHA-256 to PBKDF2-HMAC-SHA256 with 600k iterations and per-password random salt. Legacy SHA-256 hashes still verify for migration compatibility

### Changed

- Password hashes stored as `pbkdf2:600000$salt$hash` format (self-contained, no schema change needed)
- `_hash_password()` and `_verify_password()` helper functions added for secure password management

## [3.4.0] - 2026-08-04

### Added

- Windows 11 Fluent Design GUI desktop client (`gui.py`) with 15 navigation pages
- Dashboard with health stats, load metrics, and recent jobs
- Jobs page with create/stop/delete/retry, status filter, bulk operations, and output viewer
- CRUD dialogs for Workflows, Templates, Presets, API Keys, Webhooks, Notifications, MCP Servers, and Schedules
- Provider management with circuit breaker, rate limit, and health probe views
- User management with role-based creation
- Audit log viewer with chain verification and JSON export
- Settings page with connection config, auth, and database backup/restore
- Live SSE event feed panel with color-coded auto-refresh
- Fluent-styled widgets: rounded buttons, card panels, status badges, combo boxes
- Segoe UI Variable / Cascadia Code fonts, Mica-like background, accent colors
- `APIClient` REST helper with Bearer auth and /api/v1 prefix
- `SSEClient` background thread SSE stream parser for /api/events
- 19 new GUI-specific tests (103 total)

## [3.3.0] - 2026-08-04

### Added

- API versioning with /api/v1/ prefix, X-API-Version header, and GET /api/version
- Comprehensive integration test suite for all HTTP endpoints
- Job templates with CRUD API and template_id pre-fill on job creation
- Database backup and restore with JSON snapshot export/import
- Scoped API key management with create, list, revoke, and auth middleware integration
- Outgoing webhooks with HMAC-SHA256 signing and event filtering
- Bulk job operations: bulk create, bulk stop, bulk delete
- Unified SSE event stream at GET /api/events for job state changes

## [3.2.0] - 2026-08-04

### Added

- Per-provider rate limiting and concurrency caps
- Job retry policies with configurable backoff (linear, exponential, fixed)
- Circuit breaker for persistently failing providers
- Graceful degradation under load: shed low-priority jobs, throttle non-critical endpoints
- Provider health probes and automatic disable on repeated failure
- Job priority queuing (urgent, normal, background tiers)
- Request validation and schema enforcement for all API endpoints

## [3.1.0] - 2026-08-04

### Added

- Job analytics dashboard: execution duration, success/failure rates, provider usage stats
- Prometheus metrics expansion: per-provider latency, queue depth, workflow DAG latency
- Grafana dashboard templates and alerting rules
- Notification integrations: Slack, Discord, email on job/workflow completion or failure
- GitLab and Bitbucket provider integrations
- Calendar-scheduled workflows (cron + ICS import)
- Exportable audit logs with tamper-evident checksums

## [3.0.0] - 2026-08-04

### Added

- Durable workflow engine with dependencies and approval gates
- Git worktree isolation per execution
- GitHub pull-request integration
- MCP server and tool manager
- PostgreSQL and queue adapters
- Multi-user authentication and RBAC
- Remote workers and container sandbox adapters

## [2.2.0] - 2026-08-04

### Added

- WebSocket PTY and terminal stream
- Stdin relay and approval prompt relay
- Presets and favorites
- Workspace file browser and diff viewer
- Job retry/clone and downloadable logs
- Schema correction overlays

## [2.1.0] - 2026-08-04

### Added

- Durable SQLite job metadata and bounded output using WAL mode
- Restart recovery that marks interrupted jobs as orphaned
- Server-Sent Event job output streaming with reconnect offsets
- Per-job timeout overrides, bounded concurrency, retention, deletion, and terminal states
- Provider SHA-256 fingerprints, ownership metadata, and binary-change warnings
- Environment exact/prefix allowlist with loader-variable denylist
- Sensitive argv and process-environment output redaction
- `/healthz`, `/readyz`, `/api/metrics`, request IDs, and JSON logs
- Host validation, same-origin mutation checks, request rate limiting, CSP, and permissions headers
- Rootless Dockerfile, hardened Compose example, and hardened systemd user service
- Python 3.10–3.14 CI, frontend/shell checks, container build, CodeQL, and Dependabot
- OpenAPI document, architecture, deployment, threat model, security, contribution, and roadmap documents
- Parser v3 metadata for defaults, environment hints, deprecated entries, global scope, negatable flags, brace choices, and command positionals
- Expanded unit and HTTP integration tests

### Changed

- Authentication accepts bearer headers only; URL query tokens are no longer accepted
- Internal server errors are no longer returned verbatim to clients
- Job history stores redacted argv and never stores environment values
- Installer is upgrade-safe, creates backups, preserves state, and supports `--no-start`
- UI streams output instead of polling and supports timeout selection and job deletion

### Fixed

- Job timeout and cancellation now work for commands that produce no output
- Process readers no longer block the manager's timeout loop
- Queued jobs can be stopped before execution
- Output truncation offsets survive service restarts

## [2.0.0] - 2026-08-03

- Provider-agnostic AI CLI discovery
- Dynamic `--help` parser and recursive subcommands
- Structured argv command builder
- Safe `shell=False` execution
- Workspace allowlist and confirmation gates
- Live output, cancellation, history, web UI, installer, examples, and tests
