# Architecture

## Purpose

ZEAZ AI Command Center turns the help output of installed AI CLIs into a structured browser command builder while preserving direct argv execution. It is intentionally local-first, dependency-light, and provider-agnostic.

## Components

```text
Browser / Desktop GUI
  ├─ static/index.html + app.js (Web UI)
  ├─ gui.py (Windows 11 Fluent Design desktop client)
  ├─ JSON control API
  └─ SSE job stream + global event stream
          │
          ▼
ThreadingHTTPServer
  ├─ Host/auth/origin/rate-limit policy
  ├─ API versioning (/api/v1/) and request validation
  ├─ ProviderRegistry
  │    ├─ PATH + system directory discovery
  │    ├─ version + SHA-256 fingerprint
  │    └─ help schema + overlay cache
  ├─ help_parser.py
  │    └─ heuristic-v3 schema
  ├─ JobManager
  │    ├─ bounded concurrency + priority queue
  │    ├─ shell=False subprocesses
  │    ├─ process-group termination
  │    ├─ output redaction + retention
  │    ├─ retry scheduler (linear/exponential/fixed backoff)
  │    ├─ circuit breaker + load shedder
  │    └─ SSE notifications + global event bus
  ├─ WorkflowEngine & MCPManager
  │    ├─ multi-step DAG workflows
  │    ├─ MCP tool server registration
  │    └─ ephemeral git worktree sandboxes
  ├─ NotificationDispatcher
  │    ├─ Slack webhook with rich blocks
  │    ├─ Discord webhook with embeds
  │    └─ SMTP email with configurable host/port/auth
  ├─ AuditLogger
  │    └─ SHA-256 chain-linked tamper-evident log
  └─ JobStore
       └─ SQLite WAL database (Schema v3) / PostgreSQL adapter

Grafana + Prometheus (optional, via Docker Compose)
  ├─ Pre-built dashboards and alerting rules
  └─ Per-provider latency, queue depth, workflow DAG metrics
```

## Desktop GUI (gui.py)

The Windows 11 Fluent Design GUI is a standalone tkinter application that connects to the same HTTP API as the web UI. It provides native desktop access with:

- **15 navigation pages**: Dashboard, Jobs, Workflows, Templates, Presets, Analytics, Providers, Users, API Keys, Webhooks, Notifications, MCP Servers, Audit Log, Scheduler, Settings
- **APIClient**: REST client with Bearer auth, /api/v1 prefix, and X-API-Version header
- **SSEClient**: Background thread SSE stream parser for /api/events with auto-reconnect
- **Live event feed**: Bottom panel with color-coded events and auto-refresh on active page
- **Fluent-styled widgets**: Rounded buttons, card panels, status badges, combo boxes, text areas
- **Segoe UI Variable / Cascadia Code** fonts, Mica-like background, Win11 accent colors

Launch: `python3 gui.py`

## Execution boundary

The browser and GUI never submit a shell command. They submit structured fields. The server validates the provider, command path, parsed options, working directory, environment policy, timeout, priority, retry policy, and risk confirmation, then constructs a Python list of argv values. `subprocess.Popen` is always called with `shell=False`.

Raw arguments remain available for CLI features not recognized by the parser. They are still individual argv items, never shell-expanded, and can be disabled with `PANEL_ALLOW_RAW_ARGS=0`.

## Persistence

SQLite stores redacted argv, status, timestamps, return code, errors, bounded output, output offsets, retry policy, and priority. Environment values are never persisted. On startup, jobs left in queued/running/stopping states become `orphaned`; the application never attempts to resume an unknown process.

The persistence adapter is isolated in `storage.py`, making a PostgreSQL implementation possible without changing HTTP handlers or the execution model. Activate PostgreSQL via `PANEL_POSTGRES_URL`.

## Concurrency and lifecycle

A bounded semaphore limits simultaneous processes. Jobs remain `queued` while waiting for capacity. The priority queue orders jobs as `urgent` > `normal` > `background`. Terminal states are:

- `succeeded`
- `failed`
- `stopped`
- `timed_out`
- `orphaned`

Output is read by a dedicated reader thread so silent commands can still be timed out or stopped. Termination targets the process group, first with `SIGTERM`, then `SIGKILL` after a grace period.

## Resilience

- **Circuit breaker**: Per-provider circuit with closed/open/half-open states. Auto-opens after consecutive failures, auto-recovers after cooldown.
- **Rate limiting**: Per-provider concurrency caps and RPM limits. Per-IP rate limiting (default 240/min).
- **Load shedding**: Non-critical endpoints throttled when system overloaded. Low-priority jobs shed first.
- **Retry scheduler**: Configurable backoff (linear, exponential, fixed) with max delay and max retries.
- **Health probes**: Periodic provider health checks with automatic disable on repeated failure.

## Security boundaries

The control panel is a command orchestrator, not a complete sandbox. Its controls reduce accidental and remote misuse, but a provider granted workspace-write or full system permissions can still alter data available to that process. For stronger isolation, deploy the service and providers inside a VM, container, or dedicated host and expose it only through an SSH tunnel or authenticated TLS reverse proxy.

See [THREAT-MODEL.md](THREAT-MODEL.md).
