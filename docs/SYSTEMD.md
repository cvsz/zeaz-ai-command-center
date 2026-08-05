# systemd User Service

ZEAZ AI Command Center installs an optional `systemd --user` unit with:

```bash
./install.sh --service --host=127.0.0.1 --port=8765
```

## Startup ownership

When an installed user unit is available, `zai` treats it as the authoritative local server and starts it with:

```bash
systemctl --user start ai-cli-command-center.service
```

Detached standalone startup is used only when no usable user unit exists. A standalone process is recorded in:

```text
~/.local/state/ai-cli-command-center/zai-server.pid
```

The record contains the PID, user ID, Linux process start-time token, resolved `server.py` path, endpoint, and wall-clock creation time. Before stopping a tracked process, both `zai` and the installer verify the current process owner, process start-time token, exact server path, host, and port from `/proc/<pid>`. The start-time token prevents a recycled PID from being mistaken for the original server process. A stale or mismatched record is removed without terminating the process.

During a service installation or upgrade, the installer stops only a matching tracked standalone process before enabling systemd. An unrelated listener on the configured port is never terminated automatically; service startup fails visibly instead.

`--no-start` preserves its strict behavior: it uses an already healthy endpoint but never starts systemd or a detached process.

## Provider executable PATH

The generated service uses this portable default PATH:

```text
%h/.local/bin:%h/bin:/usr/local/bin:/usr/bin:/bin
```

This allows provider launchers installed under `~/.local/bin`, such as `codex`, `qwen`, or `claude`, to be discovered by the service. The default is declared before `EnvironmentFile`, so an explicit `PATH=` entry in `~/.config/ai-cli-command-center/panel.env` overrides it for custom installations.

Do not enable `PANEL_ALLOW_ABSOLUTE_BINARIES` solely to work around a missing PATH entry. Provider executables should normally be resolved through PATH and then validated by the server's canonical-path and file-permission checks.

## Verify the running service environment

Restart the service after changing `panel.env`:

```bash
systemctl --user daemon-reload
systemctl --user restart ai-cli-command-center.service
```

Confirm the unit is healthy:

```bash
systemctl --user status ai-cli-command-center.service --no-pager
curl -fsS http://127.0.0.1:8765/healthz
```

Confirm the listener belongs to the service MainPID:

```bash
MAINPID="$(systemctl --user show ai-cli-command-center.service --property=MainPID --value)"
echo "MainPID=$MAINPID"
ss -ltnp 'sport = :8765'
```

Read PATH from the actual running process:

```bash
tr '\0' '\n' < "/proc/$MAINPID/environ" | sed -n 's/^PATH=/PATH=/p'
```

Verify a provider using the exact service PATH:

```bash
SERVICE_PATH="$(tr '\0' '\n' < "/proc/$MAINPID/environ" | sed -n 's/^PATH=//p')"
env -i HOME="$HOME" PATH="$SERVICE_PATH" /bin/sh -c '
  command -v codex
  readlink -f "$(command -v codex)"
  codex --version
'
```

## Custom provider directories

Add an absolute PATH to `panel.env` when providers are installed elsewhere:

```bash
PATH=/home/example/.local/bin:/home/example/custom-ai/bin:/usr/local/bin:/usr/bin:/bin
```

Then restart the service. Keep `panel.env` mode `0600` when it also contains API credentials:

```bash
chmod 600 ~/.config/ai-cli-command-center/panel.env
systemctl --user restart ai-cli-command-center.service
```
