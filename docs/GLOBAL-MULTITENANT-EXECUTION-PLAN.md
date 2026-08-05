# Standalone Global Multi-Tenant Execution Plan

## Objective

Deliver a self-hosted, globally reachable, multi-tenant ZEAZ platform with no mandatory paid platform dependencies. Use the operator's existing server for the control plane and tenant-owned machines for AI execution.

The implementation must preserve local/offline mode and must not expose provider credentials to browsers or the shared control plane.

## Delivery rules

- One pull request per complete vertical slice.
- Every slice includes schema/API/runtime tests, upgrade notes, security review, and validation evidence.
- Never merge a partial tenant boundary.
- Tenant isolation tests are required before feature tests are considered complete.
- All mutating operations are idempotent or carry an idempotency key.
- Backward compatibility remains unless an explicit migration is documented.
- Provider SDKs and credentials stay behind agent adapters.
- The control plane never executes tenant-provided shell strings.

## Target repository structure

```text
zeaz-ai-command-center/
├── zeaz/
│   ├── control_plane/
│   │   ├── api/
│   │   ├── auth/
│   │   ├── organizations/
│   │   ├── projects/
│   │   ├── agents/
│   │   ├── jobs/
│   │   ├── artifacts/
│   │   ├── audit/
│   │   └── db/
│   ├── agent/
│   │   ├── enrollment/
│   │   ├── protocol/
│   │   ├── execution/
│   │   ├── providers/
│   │   └── state/
│   ├── shared/
│   │   ├── contracts/
│   │   ├── crypto/
│   │   ├── policy/
│   │   └── telemetry/
│   └── legacy/
│       └── local_runtime/
├── deploy/global/
├── migrations/
├── static/
└── tests/
    ├── isolation/
    ├── control_plane/
    ├── agent/
    ├── protocol/
    └── deployment/
```

## Phase 0 — Stabilize the existing runtime

### Slice 0.1 — Portable systemd provider PATH

Scope:

- include user-local binary directories in the generated systemd service environment;
- preserve explicit operator override;
- validate provider discovery from the service process;
- add installer regression tests.

Done when:

- Codex is discovered through PATH after install, upgrade, and reboot;
- arbitrary absolute binaries remain disabled;
- service and shell resolve the same trusted executable.

### Slice 0.2 — Systemd-first `zai` lifecycle

Scope:

- prefer the installed user service;
- use standalone startup only when no service exists;
- track standalone PID and process ownership;
- clean stale PID records safely;
- prevent duplicate port listeners.

Done when:

- `zai`, installer upgrade, service restart, and uninstall cannot leave competing owned servers;
- unrelated listeners are never terminated.

## Phase 1 — Package and contract extraction

### Slice 1.1 — Python package layout

Scope:

- introduce `zeaz.control_plane`, `zeaz.agent`, and `zeaz.shared` packages;
- move code without behavior changes;
- retain existing console commands and local mode;
- define dependency direction rules.

Done when:

- legacy tests pass unchanged;
- import boundaries prevent the control plane from importing provider execution implementations.

### Slice 1.2 — Versioned protocol contracts

Scope:

- define JSON schemas/dataclasses for enrollment, heartbeat, job dispatch, job events, cancellation, and credential rotation;
- include protocol version negotiation;
- canonicalize payload serialization for signatures.

Done when:

- malformed, oversized, unknown-version, expired, and replayed messages are rejected by tests.

## Phase 2 — PostgreSQL tenant foundation

### Slice 2.1 — Migration runner and database roles

Scope:

- add deterministic migrations;
- create owner, migration, application, scheduler, and backup roles;
- application roles do not own tables and do not receive `BYPASSRLS`;
- implement transaction-scoped organization/user context.

Done when:

- a clean database can be initialized from one command;
- migration rollback/recovery behavior is documented;
- missing organization context fails closed.

### Slice 2.2 — RLS isolation suite

Scope:

- test every tenant table with two organizations;
- cover SELECT, INSERT, UPDATE, DELETE, joins, subqueries, exports, and API keys;
- test connection-pool context reset.

Done when:

- no test can read or mutate a second organization's resources;
- context cannot leak between pooled connections.

### Slice 2.3 — PostgreSQL queue and outbox

Scope:

- `FOR UPDATE SKIP LOCKED` claims;
- leases, expiry, retries, dead-letter state;
- idempotency keys;
- transactional outbox;
- scheduler recovery after crash.

Done when:

- concurrent schedulers do not dispatch the same job twice;
- retries survive restart;
- duplicate client submissions return the original job.

## Phase 3 — Identity and organization management

### Slice 3.1 — Local authentication

Scope:

- memory-hard password hashing;
- session cookies;
- CSRF protection;
- login throttling and account lockout;
- TOTP MFA and recovery codes;
- secure logout and session revocation.

Done when:

- session fixation, CSRF, brute-force, and cookie-policy tests pass;
- secrets and recovery codes are never logged.

### Slice 3.2 — Organizations and memberships

Scope:

- organization create/read/update;
- invite tokens that can be copied manually without SMTP;
- owner/admin/operator/developer/viewer/auditor roles;
- owner transfer and last-owner protections;
- organization switcher context.

Done when:

- one user can belong to multiple organizations without mixed data;
- suspended membership loses access immediately.

### Slice 3.3 — Project-level grants

Scope:

- projects and repository metadata;
- member/project grants;
- provider and workflow allowlists;
- retention/concurrency policy;
- project-to-agent binding.

Done when:

- organization membership alone does not bypass project restrictions.

## Phase 4 — Agent identity and connectivity

### Slice 4.1 — Enrollment

Scope:

- short-lived single-use token;
- agent-generated keypair;
- atomic token consumption;
- organization binding;
- owner-only credential storage;
- revocation and rotation.

Done when:

- expired, reused, wrong-organization, and race-consumed tokens fail;
- private keys never reach the control plane.

### Slice 4.2 — Outbound agent session

Scope:

- authenticated outbound connection;
- heartbeat and capability advertisement;
- reconnect cursor;
- bounded messages;
- server and agent version negotiation;
- connection replacement rules.

Done when:

- agents behind NAT can connect without inbound ports;
- reconnect does not lose terminal job events.

### Slice 4.3 — Agent administration

Scope:

- list/status/disable/revoke/rotate;
- capacity and provider inventory;
- project binding;
- audit events for all lifecycle changes.

Done when:

- revoked agents cannot reconnect or claim jobs.

## Phase 5 — Remote job execution

### Slice 5.1 — Signed job dispatch

Scope:

- structured argv payload;
- organization/project/agent binding;
- policy snapshot;
- expiry and idempotency;
- control-plane signature;
- agent verification.

Done when:

- altered, replayed, expired, or misrouted jobs are rejected before execution.

### Slice 5.2 — Local provider execution adapter

Scope:

- reuse existing provider discovery and fingerprint logic;
- PATH-based executable resolution;
- workspace roots;
- environment policy;
- process groups, timeout, cancellation, and redaction;
- local durable agent journal.

Done when:

- Codex and Ollama jobs execute remotely without sending provider credentials to the control plane.

### Slice 5.3 — Event streaming and recovery

Scope:

- monotonic job event sequence;
- output chunks with limits;
- reconnect/resume;
- terminal-state reconciliation;
- orphan detection and lease expiry.

Done when:

- agent or control-plane restart cannot produce silent job loss;
- duplicate events are harmless.

## Phase 6 — Tenant-aware web experience

### Slice 6.1 — Organization shell

Scope:

- login and MFA pages;
- organization switcher;
- navigation and permission-aware controls;
- UTC storage and user timezone rendering;
- English and Thai locale foundation.

Done when:

- URLs and API calls always carry resolved organization context;
- unauthorized controls are absent and server enforcement remains authoritative.

### Slice 6.2 — Projects, agents, and jobs

Scope:

- project CRUD;
- agent enrollment flow;
- provider inventory;
- job submission/cancel/retry;
- live output and job history;
- pagination and tenant-scoped filters.

Done when:

- two browser sessions in different organizations cannot cross-view events or identifiers.

### Slice 6.3 — Members, roles, API keys, and audit

Scope:

- invite/member lifecycle;
- project grants;
- scoped API key creation and revocation;
- audit search/export;
- organization settings and quotas.

Done when:

- every UI mutation produces a complete audit event.

## Phase 7 — Artifacts and workflows

### Slice 7.1 — Tenant artifact store

Scope:

- generated tenant-prefixed paths;
- checksums;
- per-organization quotas;
- authorized upload/download;
- retention cleanup;
- path traversal tests.

Done when:

- artifacts cannot be addressed by user-supplied filesystem paths;
- quota enforcement is transactional.

### Slice 7.2 — Multi-step workflows

Scope:

- tenant-scoped templates;
- DAG validation;
- approval gates;
- step retries;
- agent capability placement;
- immutable workflow-run snapshot.

Done when:

- workflow policy cannot change underneath an active run;
- approval is scoped to organization, project, and workflow step.

## Phase 8 — Standalone global deployment

### Slice 8.1 — Docker Compose bundle

Services:

- reverse proxy;
- control-plane API;
- scheduler;
- PostgreSQL;
- optional Prometheus and Grafana;
- local artifact volume;
- backup job.

Done when:

- one command initializes a fresh installation;
- secrets are generated or explicitly required;
- all state is on named volumes or configured host paths;
- health checks and restart policies are present.

### Slice 8.2 — Private WireGuard deployment

Scope:

- server configuration template;
- peer provisioning and revocation;
- VPN-only administration;
- firewall guidance;
- no-domain operation.

Done when:

- a remote user and remote agent operate through WireGuard without a paid tunnel service.

### Slice 8.3 — Optional public HTTPS deployment

Scope:

- reverse proxy configuration;
- automatic certificate option when a domain is available;
- security headers;
- trusted proxy handling;
- request/body/rate limits;
- invite-only registration.

Done when:

- direct backend ports are not publicly reachable;
- client IP and scheme handling are tested behind the proxy.

## Phase 9 — Operations and release

### Slice 9.1 — Backup and restore

Scope:

- PostgreSQL dump;
- artifact archive;
- encrypted backup option;
- retention rotation;
- restore into a clean installation;
- documented recovery objectives.

Done when:

- automated restore validation succeeds using production-like data.

### Slice 9.2 — Upgrade and rollback

Scope:

- preflight checks;
- schema compatibility gates;
- database backup before migration;
- rolling stateless service update;
- explicit rollback rules;
- agent protocol compatibility window.

Done when:

- an upgrade interruption does not corrupt state;
- old compatible agents remain connected during the support window.

### Slice 9.3 — Security release gate

Required evidence:

- tenant isolation test report;
- threat model;
- dependency and container scans;
- secret scan;
- authentication test report;
- agent protocol fuzz/property tests;
- backup restore report;
- load and failure-injection report;
- signed release artifacts and checksums.

## No-paid-dependency policy

Mandatory runtime components must be self-hostable and available without per-user or per-request fees. The baseline may use:

- Linux;
- Python and open-source Python packages;
- PostgreSQL;
- Docker/Podman Compose;
- a self-hosted reverse proxy;
- WireGuard;
- local filesystem storage;
- Prometheus/Grafana as optional components.

The baseline must not require:

- managed database;
- hosted queue;
- paid identity provider;
- paid email provider;
- paid tunnel;
- paid object storage;
- hosted observability;
- paid billing provider;
- central provider API keys.

Optional integrations may be added behind adapters and disabled by default.

## Initial release acceptance test

1. Create Organization A and Organization B.
2. Add different users, projects, agents, and API keys.
3. Enroll an agent for each organization from separate networks.
4. Execute a Codex or Ollama job in each organization.
5. Attempt cross-tenant reads and mutations through UI, API, API key, event stream, artifact URL, and direct database application role.
6. Restart control plane, scheduler, database, and agents during active jobs.
7. Retry duplicate submissions with the same idempotency key.
8. Revoke one agent and verify immediate rejection.
9. Back up and restore into a clean host.
10. Verify every mutation and denial in the audit log.

Release is blocked if any tenant boundary, credential boundary, idempotency, or recovery test fails.