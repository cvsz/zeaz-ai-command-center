# Changelog

All notable changes are documented here.

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
- Python 3.10–3.13 CI, frontend/shell checks, container build, CodeQL, and Dependabot
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
