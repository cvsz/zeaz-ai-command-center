# HTTP API

The stable compatibility surface remains under `/api`. All protected endpoints accept:

```http
Authorization: Bearer <PANEL_TOKEN>
```

The token is optional only when the service is bound to loopback without `PANEL_TOKEN`. URL query tokens are intentionally rejected.

## Operational endpoints

### `GET /healthz`

Public liveness response.

### `GET /readyz`

Public readiness response including SQLite health. It does not expose job content.

### `GET /api/info`

Runtime version, parser version, allowed roots, state paths, concurrency, and environment policy.

### `GET /api/metrics`

Prometheus text metrics for job status and configured concurrency.

## Providers

- `GET /api/providers`
- `GET /api/providers?all=1`
- `POST /api/providers/probe`
- `POST /api/providers`
- `DELETE /api/providers/{provider_id}`
- `GET /api/providers/{provider_id}/info`
- `GET /api/providers/{provider_id}/schema`
- `GET /api/providers/{provider_id}/schema?command=mcp&command=add&refresh=1`

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
  "timeout_seconds": 3600
}
```

Environment values are process-scoped, omitted from history, and checked by the environment policy.

### Inspect and list

- `GET /api/jobs`
- `GET /api/jobs/{job_id}?offset=0`

The `offset` is a byte offset. Responses include `next_offset` and `output_truncated`.

### Stream

`GET /api/jobs/{job_id}/events?offset=0`

Returns `text/event-stream` records:

```text
event: snapshot
data: {"id":"...","status":"running","output":"...","next_offset":42}
```

The stream closes after a terminal state.

### Stop and delete

- `POST /api/jobs/{job_id}/stop`
- `DELETE /api/jobs/{job_id}`

Only terminal jobs can be deleted.

## Error format

```json
{
  "error": "Human-readable message",
  "request_id": "0123456789abcdef"
}
```

Unexpected internal errors return a generic message and a request ID; details remain in structured server logs.
