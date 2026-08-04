# HTTP API

The stable compatibility surface remains under `/api`. Versioned paths (`/api/v1/`) are normalized to `/api/` internally. All protected endpoints accept:

```http
Authorization: Bearer <PANEL_TOKEN>
X-API-Version: v1
```

The token is optional only when the service is bound to loopback without `PANEL_TOKEN`. URL query tokens are intentionally rejected. API keys created via `POST /api/keys` also work as Bearer tokens.

## Operational endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/healthz` | Public liveness probe |
| `GET` | `/readyz` | Public readiness probe (checks DB) |
| `GET` | `/api/version` | API/app/parser version info |
| `GET` | `/api/info` | Runtime version, paths, policy, concurrency |
| `GET` | `/api/metrics` | Prometheus text metrics (or JSON via Accept header) |
| `GET` | `/api/load` | Queue depth, running count, overload flag, priority queue stats, load shedder stats |
| `GET` | `/api/analytics` | Aggregated: totals by status, success/failure rates, duration percentiles (p50/p95/p99), per-provider breakdown |
| `GET` | `/api/schemas` | List available request validation schema names |

## Providers

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/providers` | List providers (query `?all=1` includes uninstalled) |
| `POST` | `/api/providers/probe` | Inspect a provider without saving |
| `POST` | `/api/providers` | Register a custom provider |
| `DELETE` | `/api/providers/{id}` | Remove a custom provider |
| `GET` | `/api/providers/{id}/info` | Version and executable fingerprint |
| `GET` | `/api/providers/{id}/schema` | Parsed help schema (query `?command=...&refresh=1`) |
| `POST` | `/api/providers/{id}/overlay` | Save schema correction overlay |

Provider information includes version and executable fingerprint metadata. Custom providers store their registration fingerprint and report `fingerprint_changed` when the executable SHA-256 differs.

## Jobs

### Create

`POST /api/jobs`

```json
{
  "provider_id": "codex",
  "cwd": "/home/user/project",
  "command_path": ["exec"],
  "global_options": {"--model": "gpt-5", "--search": true},
  "command_options": {},
  "positionals": [],
  "raw_args": [],
  "prompt": "Run the test suite and fix failures",
  "environment": {"OPENAI_API_KEY": "..."},
  "confirmation": "",
  "timeout_seconds": 3600,
  "priority": "normal",
  "retry": {"max_retries": 3, "policy": "exponential", "initial_delay": 1.0, "max_delay": 300.0},
  "template_id": "abc123"
}
```

Environment values are process-scoped, omitted from history, and checked by the environment policy. `priority` is one of `urgent`, `normal`, `background`. `template_id` pre-fills defaults from a saved template.

### Bulk operations

`POST /api/jobs/bulk` — Create multiple jobs: `{"jobs": [...]}`

`POST /api/jobs/bulk/stop` — Stop multiple jobs: `{"job_ids": [...]}`

`POST /api/jobs/bulk/delete` — Delete multiple terminal jobs: `{"job_ids": [...]}`

### Inspect and list

- `GET /api/jobs` — List all jobs (no output bodies)
- `GET /api/jobs/{job_id}?offset=0` — Job snapshot with incremental output delta

The `offset` is a byte offset. Responses include `next_offset` and `output_truncated`.

### Stream

`GET /api/jobs/{job_id}/events?offset=0`

Returns `text/event-stream` records:

```text
event: snapshot
data: {"id":"...","status":"running","output":"...","next_offset":42}
```

The stream closes after a terminal state.

### Control

- `POST /api/jobs/{job_id}/stop` — Stop a running/queued job
- `POST /api/jobs/{job_id}/retry` — Retry a failed/timed-out job
- `POST /api/jobs/{job_id}/input` — Relay stdin: `{"input": "..."}`
- `DELETE /api/jobs/{job_id}` — Delete a terminal job

## Presets, Templates, Workflows, MCP & Worktrees

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/presets` | List saved presets |
| `POST` | `/api/presets` | Create a preset |
| `DELETE` | `/api/presets/{id}` | Delete a preset |
| `GET` | `/api/templates` | List job templates |
| `GET` | `/api/templates/{id}` | Get a single template |
| `POST` | `/api/templates` | Create a template |
| `DELETE` | `/api/templates/{id}` | Delete a template |
| `GET` | `/api/workflows` | List workflows |
| `POST` | `/api/workflows` | Create a workflow |
| `DELETE` | `/api/workflows/{id}` | Delete a workflow |
| `GET` | `/api/mcp` | List MCP servers |
| `POST` | `/api/mcp` | Register an MCP server |
| `DELETE` | `/api/mcp/{id}` | Delete an MCP server |
| `GET` | `/api/worktrees` | List git worktrees |
| `POST` | `/api/worktrees` | Create a git worktree |
| `DELETE` | `/api/worktrees/{id}` | Delete a worktree record |

## Scheduled Workflows

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/schedules` | List scheduled workflows |
| `POST` | `/api/schedules` | Create/update a schedule |
| `DELETE` | `/api/schedules/{id}` | Delete a schedule |

## Notifications

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/notifications` | List notification channels |
| `POST` | `/api/notifications` | Create a channel (type: slack/discord/email) |
| `DELETE` | `/api/notifications/{id}` | Delete a channel |

## Webhooks

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/webhooks` | List outgoing webhooks |
| `POST` | `/api/webhooks` | Create a webhook (HMAC-SHA256 signed) |
| `DELETE` | `/api/webhooks/{id}` | Delete a webhook |

## API Keys

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/keys` | List API keys (hashes only) |
| `POST` | `/api/keys` | Generate a new API key (raw key shown once) |
| `DELETE` | `/api/keys/{id}` | Revoke an API key |

## Users & MFA

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/users` | List users |
| `POST` | `/api/users` | Create/update user (username, password, role) |
| `POST` | `/api/mfa/setup` | Generate TOTP MFA secret |
| `POST` | `/api/mfa/verify` | Verify TOTP code |

## Resilience & Observability

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/circuit-breaker` | All circuit breaker states |
| `POST` | `/api/circuit-breaker/{id}/reset` | Reset a circuit breaker to closed |
| `GET` | `/api/health-probes` | Provider health probe results |
| `POST` | `/api/health-probes/{id}/enable` | Re-enable a disabled provider |
| `GET` | `/api/provider-limits` | Per-provider rate limits and concurrency caps |
| `POST` | `/api/provider-limits` | Set per-provider rate/concurrency limits |
| `GET` | `/api/retry-policies` | List retryable jobs and pending retries |

## Audit & Backup

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/audit` | Export audit log (query `?since=EPOCH`) |
| `GET` | `/api/audit/verify` | Verify audit chain integrity |
| `GET` | `/api/backup` | Export full database backup as JSON |
| `POST` | `/api/restore` | Import a database backup |

## Events (SSE)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/events` | Global SSE event stream (query `?after=ID`) |

Events emitted: `job.created`, `job.finished` with payloads including `id`, `type`, `data`, `timestamp`.

## Git Integration

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/files` | List workspace directory (query `?cwd=...`) |
| `GET` | `/api/diff` | Git diff output (query `?cwd=...`) |
| `GET` | `/api/github/pulls` | List GitHub PRs |
| `POST` | `/api/github/pulls` | Create a GitHub PR |
| `GET` | `/api/gitlab/merges` | List GitLab MRs |
| `POST` | `/api/gitlab/merges` | Create a GitLab MR |
| `GET` | `/api/bitbucket/pulls` | List Bitbucket PRs |
| `POST` | `/api/bitbucket/pulls` | Create a Bitbucket PR |

> **Note**: `GET /api/gitlab/merges` and `GET /api/bitbucket/pulls` return an empty list (HTTP 200) instead of HTTP 500 when the corresponding CLI tools (`glab`, `bb`) are not installed.

## Self-Update

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/update` | Pull latest from GitHub origin/main |

## Error format

```json
{
  "error": "Human-readable message",
  "request_id": "0123456789abcdef"
}
```

Unexpected internal errors return a generic message and a request ID; details remain in structured server logs.
