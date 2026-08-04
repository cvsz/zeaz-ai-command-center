# `zai` CLI and Dashboard

`zai` is the compact terminal client for ZEAZ AI Command Center. It sends jobs through the same HTTP API used by the web application, so executions remain visible in the Dashboard and are stored in the same SQLite history.

## Install or upgrade

```bash
git pull --ff-only
./install.sh --upgrade --service --host=127.0.0.1 --port=8765
```

The installer creates three launchers:

```text
ai-cli-command-center       Server
ai-cli-command-center-gui   Desktop GUI
zai                         Terminal client
```

Ensure `~/.local/bin` is in `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Open the Dashboard

```bash
zai
zai dashboard
```

The CLI checks `/healthz`. When the local server is not running, it starts the installed server in the background and writes startup logs to:

```text
~/.local/state/ai-cli-command-center/zai-server.log
```

Open no browser and only verify/start the Dashboard:

```bash
zai dashboard --no-open
```

Return a machine-readable Dashboard summary:

```bash
zai dashboard --json --no-open
```

## Run an AI command

```bash
zai "Run tests and fix failures"
zai "Review this repository for security issues"
```

The default provider is `codex`; its `exec` subcommand is selected automatically. Output is streamed back to the terminal while the job remains available in the Dashboard.

Select a provider or model:

```bash
zai --provider codex --model gpt-5.6 "Refactor the database layer"
zai --provider gemini "Explain this architecture"
zai --provider claude "Review the current diff"
```

Run against another workspace:

```bash
zai --cwd ~/projects/example "Run the test suite"
```

Submit without waiting:

```bash
zai --no-wait "Run the long migration"
```

Use JSON output:

```bash
zai --json "Inspect the repository"
```

## Configuration

The CLI reads values in this order:

1. Command-line options
2. Environment variables
3. `~/.config/ai-cli-command-center/panel.env`
4. Built-in local defaults

Supported CLI environment variables:

| Variable | Purpose | Default |
|---|---|---|
| `ZAI_URL` | Command Center base URL | Derived from `PANEL_HOST` and `PANEL_PORT` |
| `ZAI_TOKEN` | Bearer token | `PANEL_TOKEN` |
| `ZAI_PROVIDER` | Default provider ID | `codex` |

Examples:

```bash
export ZAI_URL=http://127.0.0.1:8765
export ZAI_TOKEN='replace-with-panel-token'
export ZAI_PROVIDER=codex
```

Tokens are sent only in the `Authorization: Bearer` header. Query-string tokens are not used.

## Advanced provider arguments

Override the inferred provider command path:

```bash
zai --provider codex --command-path exec "Fix lint failures"
```

Pass additional raw provider arguments:

```bash
zai --provider codex --raw-arg=--full-auto "Complete the task"
```

Dangerous or destructive operations remain subject to the Command Center server policies and confirmation requirements.

## Troubleshooting

Check the service:

```bash
systemctl --user status ai-cli-command-center
journalctl --user -u ai-cli-command-center -n 100 --no-pager
```

Check the auto-start log:

```bash
tail -n 100 ~/.local/state/ai-cli-command-center/zai-server.log
```

Check CLI configuration:

```bash
zai --help
```
