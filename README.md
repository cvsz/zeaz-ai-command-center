# AI CLI Command Center

A local web control panel that generates a structured command builder from any installed AI CLI's `--help` output.

Instead of hard-coding one provider, the server inspects the executable, parses commands/options/arguments, follows nested subcommands, and renders matching controls in the browser.

## Highlights

- Provider-agnostic: Codex, Claude Code, Gemini CLI, Qwen Code, Aider, OpenCode, Goose, Ollama, `llm`, and custom executables
- Auto-discovery of known AI CLIs available in `PATH`
- Custom provider registration from executable name, help arguments, and version arguments
- Recursive subcommand inspection: `provider command subcommand --help`
- Generated controls for:
  - boolean flags
  - value options
  - enumerated choices
  - repeatable and multi-value options
  - positional arguments
  - prompts
  - process-scoped environment overrides
- Parsed schema export as JSON
- Live output streaming, cancellation, exit status, and job history
- `shell=False` for help inspection and job execution
- Workspace allowlist
- Confirmation gates for destructive and dangerous execution
- Localhost-only by default; bearer token required for non-loopback binding
- Python standard-library runtime with no web framework dependency

## How generation works

1. Resolve an executable from `PATH`.
2. Run `<provider> --help` with a short timeout and no shell.
3. Parse `Usage`, `Commands`, `Options`, `Flags`, and `Arguments` sections.
4. Infer field types from patterns such as `<MODEL>`, `[FILE]`, `...`, and `possible values`.
5. When a command is selected, run `<provider> <command> --help` and generate the next layer.
6. Build an argv array from structured values and launch it directly with `subprocess.Popen(..., shell=False)`.

The parser is heuristic because CLI help text has no universal standard. The raw help and generated schema are always visible in the panel for inspection.

## Install on Ubuntu

```bash
unzip ai-cli-command-center-v2.0.0.zip
cd ai-cli-command-center
chmod +x install.sh start.sh uninstall.sh
./install.sh --service --port=8765
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

For a remote server, use an SSH tunnel from your workstation:

```bash
ssh -L 8765:127.0.0.1:8765 cvsz@zeaz-platform
```

Then open `http://127.0.0.1:8765` on the workstation.

## Run without installation

```bash
./start.sh --host 127.0.0.1 --port 8765
```

## Add any AI provider

In the UI, select **Inspect provider --help** and enter:

```text
Executable: my-ai-cli
Help arguments: --help
Version arguments: --version
```

The executable must be installed in `PATH`. Custom absolute paths are intentionally disabled by default. To permit them:

```bash
export PANEL_ALLOW_ABSOLUTE_BINARIES=1
```

A custom provider is stored in:

```text
~/.config/ai-cli-command-center/providers.json
```

Example registry entry:

```json
{
  "providers": [
    {
      "id": "my-ai",
      "name": "My AI CLI",
      "executable": "my-ai",
      "help_args": ["--help"],
      "version_args": ["--version"]
    }
  ]
}
```

## Supported help layouts

The parser targets common layouts produced by:

- Rust Clap
- Node Commander
- Python argparse
- Click and Typer
- Go Cobra
- Similar hand-written command help

Examples it recognizes:

```text
Commands:
  exec       Run non-interactively
  review     Review code
```

```text
Options:
  -m, --model <MODEL>     Select model
  --search                Enable search
  -s, --sandbox <MODE>    [possible values: read-only, workspace-write]
```

## Safety model

The panel is a local command launcher, not a security sandbox.

Controls included:

- No raw shell execution
- No command interpolation
- Executables resolved before launch
- Command paths restricted to simple command tokens
- Request size, help output, process output, and runtime limits
- Workspace roots restricted to the user's home and launch directory by default
- Dangerous flags require `I UNDERSTAND`
- Destructive commands require `CONFIRM`
- Environment override values are not returned in job history
- Non-loopback binding is refused without a token

To define workspace roots explicitly:

```bash
export PANEL_ALLOWED_ROOTS=/home/cvsz:/srv/projects
```

To remove the workspace restriction completely—not recommended:

```bash
export PANEL_ALLOW_ANY_CWD=1
```

To expose the server on a network interface:

```bash
export PANEL_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
./start.sh --host 0.0.0.0 --port 8765
```

Use a reverse proxy with TLS and keep the bearer token private.

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `PANEL_HOST` | `127.0.0.1` | Bind address |
| `PANEL_PORT` | `8765` | HTTP port |
| `PANEL_TOKEN` | empty | API bearer token |
| `PANEL_ALLOWED_ROOTS` | home + launch directory | Allowed working roots |
| `PANEL_ALLOW_ANY_CWD` | `0` | Disable workspace restriction |
| `PANEL_ALLOW_ABSOLUTE_BINARIES` | `0` | Permit custom absolute executable paths |
| `PANEL_HELP_TIMEOUT_SECONDS` | `20` | Help inspection timeout |
| `PANEL_JOB_TIMEOUT_SECONDS` | `21600` | Maximum job runtime |
| `PANEL_MAX_HELP_BYTES` | `2097152` | Help output cap |
| `PANEL_MAX_OUTPUT_BYTES` | `8388608` | Retained job output cap |

See `.env.example` for a ready-to-copy template.

## API overview

```text
GET    /api/info
GET    /api/providers
POST   /api/providers/probe
POST   /api/providers
DELETE /api/providers/{id}
GET    /api/providers/{id}/info
GET    /api/providers/{id}/schema?command=exec&command=subcommand
POST   /api/jobs
GET    /api/jobs
GET    /api/jobs/{id}?offset=0
POST   /api/jobs/{id}/stop
```

Example probe:

```bash
curl -sS http://127.0.0.1:8765/api/providers/probe \
  -H 'Content-Type: application/json' \
  -d '{"executable":"codex","help_args":"--help","version_args":"--version"}'
```

## Validate the source

Runtime has no third-party Python dependencies. Tests use `pytest`.

```bash
python3 -m pip install --user pytest
make check
make test
```

Validation coverage includes:

- Codex/Clap-style parsing
- Commander-style parsing
- choices and repeatable options
- custom provider probing
- structured argv generation
- destructive and dangerous confirmation gates
- Python, JavaScript, and shell syntax checks

## Upgrade from Codex Control Panel v1

The v2 application uses a new service and installation directory, so it can be tested alongside v1.

```bash
systemctl --user disable --now codex-control-panel.service 2>/dev/null || true
./install.sh --service --port=8765
```

The new package name and service are both `ai-cli-command-center`.
