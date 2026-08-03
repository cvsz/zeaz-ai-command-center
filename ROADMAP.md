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

- [ ] WebSocket PTY with stdin and terminal resize
- [ ] Approval prompt relay
- [x] Presets and favorites
- [x] Workspace file browser and diff viewer
- [x] Job retry/clone and downloadable logs
- [x] Schema correction overlays

## v3.0 — Workflow platform

- [x] Durable workflow engine with dependencies and approval gates
- [ ] Git worktree isolation per execution
- [ ] GitHub pull-request integration
- [x] MCP server and tool manager
- [ ] PostgreSQL and queue adapters
- [ ] Multi-user authentication and RBAC
- [ ] Remote workers and container sandbox adapters

## Non-goals for v2

- Treating heuristic help parsing as an authoritative provider specification
- Providing strong isolation without an external OS/container/VM sandbox
- Persisting or centrally managing provider secrets
