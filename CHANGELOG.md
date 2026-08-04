# Changelog

All notable changes are documented here.

## [Unreleased]

### Fixed

- `zai` no longer exceeds the Command Center's default API rate limit while streaming long-running jobs. Status polling now defaults to one request per second and HTTP 429 responses use bounded exponential backoff before resuming the same job.
- Control-plane HTTP 429 responses no longer cause a running job to be abandoned or duplicated.

### Added

- Reason-aware local fallback for genuine AI-provider rate limits. The default fallback route is `ollama run qwen3-coder`, configurable with `ZAI_LOCAL_PROVIDER` and `ZAI_LOCAL_MODEL`.
- `--local-fallback`, `--no-local-fallback`, `--local-provider`, `--local-model`, and `--poll-interval` CLI options.


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
