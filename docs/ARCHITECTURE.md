# Architecture

## Purpose

ZEAZ AI Command Center turns the help output of installed AI CLIs into a structured browser command builder while preserving direct argv execution. It is intentionally local-first, dependency-light, and provider-agnostic.

## Components

```text
Browser
  ├─ static/index.html + app.js
  ├─ JSON control API
  └─ SSE job stream
          │
          ▼
ThreadingHTTPServer
  ├─ Host/auth/origin/rate-limit policy
  ├─ ProviderRegistry
  │    ├─ PATH + system directory discovery
  │    ├─ version + SHA-256 fingerprint
  │    └─ help schema + overlay cache
  ├─ help_parser.py
  │    └─ heuristic-v3 schema
  ├─ JobManager
  │    ├─ bounded concurrency
  │    ├─ shell=False subprocesses
  │    ├─ process-group termination
  │    ├─ output redaction + retention
  │    └─ SSE notifications
  ├─ WorkflowEngine & MCPManager
  │    ├─ multi-step DAG workflows
  │    ├─ MCP tool server registration
  │    └─ ephemeral git worktree sandboxes
  └─ JobStore
       └─ SQLite WAL database (Schema v3)
```

## Execution boundary

The browser never submits a shell command. It submits structured fields. The server validates the provider, command path, parsed options, working directory, environment policy, timeout, and risk confirmation, then constructs a Python list of argv values. `subprocess.Popen` is always called with `shell=False`.

Raw arguments remain available for CLI features not recognized by the parser. They are still individual argv items, never shell-expanded, and can be disabled with `PANEL_ALLOW_RAW_ARGS=0`.

## Persistence

SQLite stores redacted argv, status, timestamps, return code, errors, bounded output, and output offsets. Environment values are never persisted. On startup, jobs left in queued/running/stopping states become `orphaned`; the application never attempts to resume an unknown process.

The persistence adapter is isolated in `storage.py`, making a future PostgreSQL implementation possible without changing HTTP handlers or the execution model.

## Concurrency and lifecycle

A bounded semaphore limits simultaneous processes. Jobs remain `queued` while waiting for capacity. Terminal states are:

- `succeeded`
- `failed`
- `stopped`
- `timed_out`
- `orphaned`

Output is read by a dedicated reader thread so silent commands can still be timed out or stopped. Termination targets the process group, first with `SIGTERM`, then `SIGKILL` after a grace period.

## Security boundaries

The control panel is a command orchestrator, not a complete sandbox. Its controls reduce accidental and remote misuse, but a provider granted workspace-write or full system permissions can still alter data available to that process. For stronger isolation, deploy the service and providers inside a VM, container, or dedicated host and expose it only through an SSH tunnel or authenticated TLS reverse proxy.

See [THREAT-MODEL.md](THREAT-MODEL.md).
