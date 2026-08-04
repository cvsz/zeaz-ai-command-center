# ZEAZ AI Command Center

## 🌟 Introduction

**ZEAZ AI Command Center** is a secure, local-first web control panel and execution engine for modern AI CLI tools (including OpenAI Codex, Claude Code, Gemini CLI, Qwen Code, ShellGPT, Aider, Ollama, and custom binaries).

Instead of requiring manual command-line typing or maintaining hardcoded CLI definitions, the Command Center automatically scans your OS environment, parses `--help` outputs in real time using a heuristic parser, auto-generates interactive Web UI command builders, and executes commands safely via direct `subprocess` calls (`shell=False`) with live output streaming.

A **Windows 11 Fluent Design GUI** desktop client is also available for full-featured native access to all operations.

---

## 🎬 Live Demo & Feature Walkthrough

```text
 ┌─────────────────────────────────────────────────────────────────────────────────┐
 │ ZEAZ AI COMMAND CENTER v3.4                                  [⚡ Update via GitHub] │
 ├──────────────────────────┬──────────────────────────────────────────────────────┤
 │ 🤖 PROVIDERS             │ ⚙️ COMMAND BUILDER                                   │
 │  • OpenAI Codex          │  Target Directory: [/home/cvsz/project]               │
 │  • Claude Code           │  Subcommand: [run]                                    │
 │  • Gemini CLI            │  Prompt: "Refactor database connection pool"          │
 │  • ShellGPT              │  [▶ Run Command]   [💾 Save Preset]                   │
 ├──────────────────────────┼──────────────────────────────────────────────────────┤
 │ 📂 WORKSPACE BROWSER     │ 📺 LIVE TERMINAL STREAM                              │
 │  [DIR] src/              │  [19:35:01] Initializing process PTY...              │
 │        server.py         │  [19:35:02] Analyzing AST and dependencies...        │
 └──────────────────────────┴──────────────────────────────────────────────────────┘
```

### Key Workflow Overview:
1. **Automated Discovery**: Launch the server and all installed AI tools are automatically detected.
2. **Interactive Builder**: Select options, positional arguments, or prompts in generated UI controls.
3. **Durable Execution**: Stream live output over SSE, download logs, and monitor execution state in real-time.
4. **v3.0 Workflows & Sandboxing**: Execute multi-step DAG workflows, manage MCP servers, or spawn ephemeral Git worktrees.
5. **v3.4 Desktop GUI**: Launch the native Windows 11 Fluent Design client for full-featured desktop access.

---

## 📖 How To Use Guide

### Step 1: Quick Start Launch
Run the server locally using Python:
```bash
python3 server.py --host 127.0.0.1 --port 8765
```
Open `http://127.0.0.1:8765` in your browser.

### Step 2: Desktop GUI (Windows 11 / Linux / macOS)
Launch the native desktop client:
```bash
python3 gui.py
```
The GUI connects to the same server API and provides a Windows 11 Fluent Design experience with 15 pages covering all features: Dashboard, Jobs, Workflows, Templates, Presets, Analytics, Providers, Users, API Keys, Webhooks, Notifications, MCP Servers, Audit Log, Scheduler, and Settings.

### Step 3: Selecting an AI Provider
1. Click any installed AI provider (e.g. **Claude Code**, **OpenAI Codex**, **Gemini CLI**) in the left sidebar.
2. The panel probes `--help` and renders all available flags, subcommands, and options automatically.

### Step 4: Configuring & Executing Commands
1. **Set Working Directory**: Enter the target project path in **Working Directory**.
2. **Fill Parameters**: Select subcommands, enter prompts, or pass positional arguments.
3. **Run Command**: Click **Run command** to launch. Output streams in real-time under **Process stream**.

### Step 5: Using v2.2 & v3.0 Advanced Tools
- **Presets & Favorites**: Click **Save preset** to save reusable command configurations.
- **Download Logs**: Click **Download log** in historical job windows to export full terminal output.
- **Git Diff & File Browser**: Expand **Workspace File Browser** or **Git Diff Viewer** to inspect uncommitted changes.
- **Workflows & MCP Servers**: Use **+ Workflow**, **+ MCP Server**, or **+ Ephemeral Worktree** under the Workflow Platform section.

### Step 6: Using v3.1–v3.4 Advanced Features
- **Analytics Dashboard**: View execution duration, success/failure rates, and provider usage at `/api/analytics` or in the GUI Analytics page.
- **Grafana & Prometheus**: Open `http://127.0.0.1:3000` for pre-built dashboards and alerting rules.
- **Notifications**: Configure Slack, Discord, or email alerts via `/api/notifications` or the GUI Notifications page.
- **Scheduled Workflows**: Create calendar-scheduled workflows via `/api/schedules` or the GUI Scheduler page.
- **API Keys**: Create scoped API keys via `/api/keys` or the GUI API Keys page.
- **Webhooks**: Configure outgoing webhooks with HMAC-SHA256 signing via `/api/webhooks` or the GUI Webhooks page.
- **Bulk Operations**: Bulk stop/delete jobs via `/api/jobs/bulk/stop` and `/api/jobs/bulk/delete`.

---

## Highlights

- Dynamic provider and nested subcommand discovery
- Heuristic parser for Clap, Cobra, Commander, Click/Typer, argparse, Symfony-style, and hand-written help
- Generated fields for flags, values, choices, defaults, environment hints, repeatable options, positionals, and prompts
- Direct `subprocess` argv execution with `shell=False`
- Workspace allowlist, environment allowlist, risk confirmation, and raw-argument policy
- SHA-256 provider binary fingerprinting and change warnings
- Durable SQLite job history with restart recovery
- Server-Sent Event output streaming, cancellation, timeout, and process-group cleanup
- Sensitive argv redaction and process-environment output redaction
- Bearer header authentication, Host validation, same-origin mutation checks, rate limiting, and security headers
- Health, readiness, Prometheus metrics, and structured JSON logs
- Rootless Docker image, hardened systemd user service, CI, CodeQL, and Dependabot
- Python standard-library runtime with no web-framework dependency
- **Windows 11 Fluent Design GUI** with 15 pages, live SSE event feed, and full CRUD for all resources
- **Job analytics** with success/failure rates, duration percentiles, and per-provider breakdowns
- **Grafana dashboards** and Prometheus alerting rules
- **Slack, Discord, email notifications** on job/workflow events
- **Circuit breaker**, rate limiting, and graceful degradation under load
- **Job retry policies** with configurable backoff (linear, exponential, fixed)
- **Priority queuing** (urgent, normal, background tiers)
- **API versioning** with /api/v1/ prefix and X-API-Version header
- **Scoped API keys** with create, list, revoke, and auth middleware
- **Outgoing webhooks** with HMAC-SHA256 signing and event filtering
- **Bulk job operations** and unified SSE event stream
- **Database backup/restore** with JSON snapshot export/import
- **Tamper-evident audit log** with SHA-256 chain verification
- **GitLab and Bitbucket** provider integrations
- **Calendar-scheduled workflows** with cron support

## Architecture

```text
AI CLI --help
    │
    ▼
heuristic-v3 parser ──► generated browser controls
                              │
                              ▼
structured JSON request ──► validated argv list
                              │
                              ▼
                     subprocess shell=False
                              │
                  ┌───────────┴───────────┐
                  ▼                       ▼
            SSE live output        SQLite durable jobs
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
              Grafana/Prometheus  Notifications     Desktop GUI
              (v3.1)             (v3.1)            (v3.4)
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/THREAT-MODEL.md](docs/THREAT-MODEL.md).

## Requirements

- Python 3.10 or newer
- SQLite 3.24 or newer through Python's `sqlite3`
- One or more AI CLI executables available in `PATH`
- Windows 11 / Linux / macOS (Ubuntu, macOS, Windows 11 fully supported)
- tkinter (bundled with Python on Windows/macOS; `sudo apt install python3-tk` on Ubuntu)

## Install on Ubuntu

```bash
git clone https://github.com/cvsz/zeaz-ai-command-center.git
cd zeaz-ai-command-center
chmod +x install.sh start.sh uninstall.sh
make validate
./install.sh --service --host=127.0.0.1 --port=8765
```

Check the service:

```bash
systemctl --user status ai-cli-command-center
journalctl --user -u ai-cli-command-center -f
```

Open locally:

```text
http://127.0.0.1:8765
```

For a remote server, keep the service on loopback and use an SSH tunnel:

```bash
ssh -L 8765:127.0.0.1:8765 cvsz@zeaz-platform
```

Then open `http://127.0.0.1:8765` on the workstation.

## Run without installation

```bash
cp .env.example .env
./start.sh --host 127.0.0.1 --port 8765
```

## Desktop GUI

```bash
python3 gui.py
```

The GUI connects to the server at `http://127.0.0.1:8765` by default. Configure the server URL and bearer token in the Settings page. Features:

- **Dashboard**: Health stats, load metrics, recent jobs
- **Jobs**: Create/stop/delete/retry, status filter, bulk operations, output viewer
- **Workflows, Templates, Presets**: Full CRUD with dialogs
- **Analytics**: Success/failure rates, duration stats, provider breakdown
- **Providers**: Circuit breaker, rate limits, health probes
- **Admin**: Users, API Keys, Webhooks, Notifications, MCP Servers, Audit Log, Scheduler
- **Settings**: Connection config, auth, database backup/restore
- **Live Events**: Bottom panel with real-time SSE feed, auto-refresh on active page

## Add any AI CLI provider

Open **Inspect provider --help** and enter:

```text
Executable: my-ai-cli
Help arguments: --help
Version arguments: --version
```

The executable must be in `PATH`. Absolute paths are disabled by default. A custom provider is stored in:

```text
~/.config/ai-cli-command-center/providers.json
```

Registration records the executable SHA-256. The provider status API warns if the binary changes later.

Example provider registry:

```json
{
  "providers": [
    {
      "id": "my-ai",
      "name": "My AI CLI",
      "executable": "my-ai",
      "help_args": ["--help"],
      "version_args": ["--version"],
      "registered_fingerprint": {
        "sha256": "..."
      }
    }
  ]
}
```

## Help generation

The server:

1. Resolves the executable from `PATH`.
2. Rejects world-writable executables by default.
3. Runs `<provider> --help` with a timeout and output limit.
4. Parses usage, commands, options, arguments, choices, defaults, aliases, environment hints, deprecation, and risk markers.
5. Follows nested selections by running `<provider> <command> ... --help`.
6. Caches generated schemas for five minutes.
7. Keeps raw help in every schema for inspection and export.

Help text has no universal standard, so generated schemas are heuristic rather than authoritative. Review the argv preview before execution.

## Durable jobs

SQLite state defaults to:

```text
~/.local/state/ai-cli-command-center/jobs.sqlite3
```

Persisted fields include redacted argv, timestamps, status, return code, risk, errors, timeout, retry policy, priority, and bounded output. Environment values are never stored. Active records become `orphaned` after a server restart rather than being resumed unsafely.

Output streams over:

```text
GET /api/jobs/{job_id}/events?offset=0
```

The UI falls back to a final snapshot if a stream disconnects.

## Security model

The application is a command launcher, not a complete sandbox.

Default controls:

- Loopback binding
- Bearer header required for non-loopback exposure
- Query-string tokens rejected
- Host-header allowlist and cross-site mutation rejection
- No shell interpolation or expansion
- Canonical allowed workspace roots
- Exact/prefix environment allowlist with dangerous loader variables blocked
- World-writable provider binaries rejected
- Destructive commands require `CONFIRM`
- Dangerous/unsandboxed commands require `I UNDERSTAND`
- Request, help, output, runtime, retention, concurrency, and rate limits
- Sensitive option values redacted from job history
- Environment override values omitted from history and redacted from output where detected
- CSP, frame denial, no-sniff, referrer, and permissions headers
- Generic internal errors paired with request IDs in structured logs
- Multi-user RBAC with API key and TOTP MFA authentication
- PBKDF2-HMAC-SHA256 password hashing with per-user salt and 600k iterations
- Tamper-evident audit log with SHA-256 chain verification

For autonomous or untrusted workloads, run providers inside an external VM/container sandbox and use disposable workspaces.

## Environment policy

Allowed by default:

- Common AI provider prefixes such as `OPENAI_`, `ANTHROPIC_`, `GOOGLE_`, `GEMINI_`, `OLLAMA_`, `HF_`, `AZURE_`, `AWS_`, `OPENROUTER_`, and others
- Standard proxy and CA variables

Add an exact key:

```bash
export PANEL_ENV_ALLOWLIST=MY_PROVIDER_TOKEN,MY_REGION
```

Add a prefix:

```bash
export PANEL_ENV_PREFIX_ALLOWLIST=ZEAZ_,CUSTOM_AI_
```

Dangerous variables such as `LD_PRELOAD`, `BASH_ENV`, `NODE_OPTIONS`, `PYTHONPATH`, and `GIT_SSH_COMMAND` remain blocked even when broad environment mode is enabled.

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `PANEL_HOST` | `127.0.0.1` | Bind address |
| `PANEL_PORT` | `8765` | HTTP port |
| `PANEL_TOKEN` | empty | Bearer token; mandatory off loopback |
| `PANEL_ALLOWED_HOSTS` | loopback hosts | Accepted Host values |
| `PANEL_ALLOWED_ROOTS` | home + launch directory | Writable workspace boundary |
| `PANEL_ALLOW_ANY_CWD` | `0` | Disable workspace restriction |
| `PANEL_ALLOW_ABSOLUTE_BINARIES` | `0` | Permit provider absolute paths |
| `PANEL_ALLOW_WORLD_WRITABLE_BINARIES` | `0` | Permit unsafe executable ownership mode |
| `PANEL_ALLOW_RAW_ARGS` | `1` | Allow advanced argv items not parsed from help |
| `PANEL_ALLOW_ANY_ENV` | `0` | Allow environment keys except hard denylist |
| `PANEL_ENV_ALLOWLIST` | empty | Extra exact environment names |
| `PANEL_ENV_PREFIX_ALLOWLIST` | empty | Extra environment prefixes |
| `PANEL_DATABASE_PATH` | XDG state path | SQLite database |
| `PANEL_POSTGRES_URL` | empty | PostgreSQL connection URL for enterprise storage adapter |
| `PANEL_MAX_CONCURRENT_JOBS` | `4` | Simultaneous provider processes |
| `PANEL_JOB_TIMEOUT_SECONDS` | `21600` | Default job timeout |
| `PANEL_MAX_JOB_TIMEOUT_SECONDS` | `86400` | Maximum user-selected timeout |
| `PANEL_MAX_RETAINED_JOBS` | `500` | Durable history count |
| `PANEL_JOB_RETENTION_DAYS` | `30` | Terminal-job retention |
| `PANEL_MAX_OUTPUT_BYTES` | `8388608` | Output retained per job |
| `PANEL_HELP_TIMEOUT_SECONDS` | `20` | Help inspection timeout |
| `PANEL_MAX_HELP_BYTES` | `2097152` | Help output cap |
| `PANEL_USE_PTY` | `0` | Enable pseudo-terminal master-slave allocation (`1`) |
| `PANEL_SANDBOX_DRIVER` | empty | Container sandbox wrapper driver (`bwrap`, `docker`) |
| `PANEL_RATE_LIMIT_PER_MINUTE` | `240` | API requests per source IP |
| `PANEL_LOG_FORMAT` | `json` | `json` or `text` |
| `PANEL_ENABLE_HSTS` | `0` | Add HSTS behind HTTPS-only proxy |

See [.env.example](.env.example).

## API and operations

### Operational
```text
GET  /healthz
GET  /readyz
GET  /api/version
GET  /api/info
GET  /api/metrics
GET  /api/load
GET  /api/analytics
GET  /api/schemas
```

### Providers
```text
GET    /api/providers
POST   /api/providers/probe
POST   /api/providers
DELETE /api/providers/{id}
GET    /api/providers/{id}/info
GET    /api/providers/{id}/schema
POST   /api/providers/{id}/overlay
```

### Jobs
```text
POST   /api/jobs
POST   /api/jobs/bulk
POST   /api/jobs/bulk/stop
POST   /api/jobs/bulk/delete
GET    /api/jobs
GET    /api/jobs/{id}
GET    /api/jobs/{id}/events
POST   /api/jobs/{id}/stop
POST   /api/jobs/{id}/retry
POST   /api/jobs/{id}/input
DELETE /api/jobs/{id}
```

### Presets, Templates, Workflows, MCP, Worktrees
```text
GET /api/presets | POST /api/presets | DELETE /api/presets/{id}
GET /api/templates | POST /api/templates | DELETE /api/templates/{id}
GET /api/workflows | POST /api/workflows | DELETE /api/workflows/{id}
GET /api/mcp | POST /api/mcp | DELETE /api/mcp/{id}
GET /api/worktrees | POST /api/worktrees | DELETE /api/worktrees/{id}
```

### Schedules, Notifications, Webhooks, API Keys
```text
GET /api/schedules | POST /api/schedules | DELETE /api/schedules/{id}
GET /api/notifications | POST /api/notifications | DELETE /api/notifications/{id}
GET /api/webhooks | POST /api/webhooks | DELETE /api/webhooks/{id}
GET /api/keys | POST /api/keys | DELETE /api/keys/{id}
```

### Users, MFA, Auth
```text
GET  /api/users | POST /api/users
POST /api/mfa/setup | POST /api/mfa/verify
```

### Resilience & Observability
```text
GET  /api/circuit-breaker
POST /api/circuit-breaker/{id}/reset
GET  /api/health-probes
POST /api/health-probes/{id}/enable
GET  /api/provider-limits | POST /api/provider-limits
GET  /api/retry-policies
```

### Audit, Backup, Events
```text
GET  /api/audit
GET  /api/audit/verify
GET  /api/backup | POST /api/restore
GET  /api/events
```

### Git Integration
```text
GET  /api/files | GET /api/diff
GET  /api/github/pulls | POST /api/github/pulls
GET  /api/gitlab/merges | POST /api/gitlab/merges
GET  /api/bitbucket/pulls | POST /api/bitbucket/pulls
```

### Self-Update
```text
POST /api/update
```

Detailed API documentation is in [docs/API.md](docs/API.md) and [openapi.yaml](openapi.yaml).

## Docker

The supplied container is rootless and read-only. It does not bundle provider CLIs.

```bash
mkdir -p workspace
export PANEL_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
docker compose up --build -d
```

Build a derived image to install the required AI CLI providers.

### Observability Stack (Grafana + Prometheus)

Docker Compose includes optional Grafana and Prometheus services:

```bash
docker compose up --build -d
```

- **Prometheus**: `http://127.0.0.1:9090`
- **Grafana**: `http://127.0.0.1:3000` (default admin/admin)

Pre-built dashboards and alerting rules are in `grafana/`.

## Validation

```bash
python3 -m pip install --user pytest ruff
make validate
```

Validation covers parser formats and metadata, structured argv, risk gates, environment policy, secret redaction, SQLite persistence and orphan recovery, HTTP authentication, Host/origin security, Python/JavaScript/Bash syntax, and container build in CI.

## Upgrade from v2.0

```bash
git pull --ff-only
make validate
./install.sh --service --host=127.0.0.1 --port=8765
```

The installer backs up the previous application directory. v2.1+ creates durable state under the XDG state directory. The existing provider registry remains compatible. Query-string token links are intentionally no longer accepted; enter the token when prompted or send it as an Authorization header.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [API](docs/API.md)
- [User Guide](docs/USER-GUIDE.md)
- [Deployment](docs/DEPLOYMENT.md)
- [Threat model](docs/THREAT-MODEL.md)
- [Security policy](SECURITY.md)
- [Roadmap](ROADMAP.md)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

## License

MIT
