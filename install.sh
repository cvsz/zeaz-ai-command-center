#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

APP_NAME="ai-cli-command-center"
INSTALL_DIR="${HOME}/.local/share/${APP_NAME}"
BIN_DIR="${HOME}/.local/bin"
CONFIG_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/${APP_NAME}"
STATE_DIR="${XDG_STATE_HOME:-${HOME}/.local/state}/${APP_NAME}"
SERVICE_DIR="${HOME}/.config/systemd/user"
PORT="${PANEL_PORT:-8765}"
HOST="${PANEL_HOST:-127.0.0.1}"
INSTALL_SERVICE=0
START_SERVICE=1
UPGRADE_ONLY=0

usage() {
  cat <<EOF
Usage: ./install.sh [OPTIONS]

Options:
  --service          Install and enable a systemd user service
  --no-start         Install the service without starting it
  --upgrade          Require an existing installation and replace it safely
  --port=8765        HTTP port
  --host=127.0.0.1   Bind host
  -h, --help         Show this help
EOF
}

for arg in "$@"; do
  case "$arg" in
    --service) INSTALL_SERVICE=1 ;;
    --no-start) START_SERVICE=0 ;;
    --upgrade) UPGRADE_ONLY=1 ;;
    --port=*) PORT="${arg#*=}" ;;
    --host=*) HOST="${arg#*=}" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "$PORT" =~ ^[0-9]+$ ]] && (( PORT >= 1 && PORT <= 65535 )) || {
  echo "Invalid port: $PORT" >&2
  exit 2
}
[[ -n "$HOST" && "$HOST" != *[[:space:]]* ]] || {
  echo "Invalid host: $HOST" >&2
  exit 2
}
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
python3 -c 'import sqlite3; assert sqlite3.sqlite_version_info >= (3, 24, 0)' || {
  echo "Python sqlite3 with SQLite 3.24+ is required" >&2
  exit 1
}
APP_VERSION="$(python3 -c 'from version import __version__; print(__version__)')"

required_files=(
  server.py help_parser.py storage.py gui.py zai.py version.py pyproject.toml
  README.md CHANGELOG.md LICENSE start.sh uninstall.sh .env.example
)
for path in "${required_files[@]}" static examples docs; do
  [[ -e "$path" ]] || { echo "Required source path is missing: $path" >&2; exit 1; }
done

if [[ "$UPGRADE_ONLY" == "1" && ! -f "$INSTALL_DIR/server.py" ]]; then
  echo "Cannot upgrade: no installation found at $INSTALL_DIR" >&2
  exit 1
fi

mkdir -p "$(dirname "$INSTALL_DIR")" "$BIN_DIR" "$CONFIG_DIR" "$STATE_DIR"
chmod 700 "$CONFIG_DIR" "$STATE_DIR"

stage="$(mktemp -d "${INSTALL_DIR}.staging.XXXXXX")"
backup=""
cleanup() {
  [[ ! -d "$stage" ]] || rm -rf "$stage"
}
trap cleanup EXIT

install -m 600 server.py help_parser.py storage.py gui.py zai.py version.py pyproject.toml README.md CHANGELOG.md LICENSE "$stage/"
install -m 700 start.sh uninstall.sh "$stage/"
install -m 600 .env.example "$stage/"
cp -R static examples docs "$stage/"
find "$stage/static" "$stage/examples" "$stage/docs" -type f -exec chmod 600 {} +
find "$stage/static" "$stage/examples" "$stage/docs" -type d -exec chmod 700 {} +

if [[ -d "$INSTALL_DIR" ]]; then
  backup="${INSTALL_DIR}.backup-$(date +%Y%m%d%H%M%S)-$$"
  mv "$INSTALL_DIR" "$backup"
fi
if ! mv "$stage" "$INSTALL_DIR"; then
  [[ -z "$backup" || ! -d "$backup" ]] || mv "$backup" "$INSTALL_DIR"
  echo "Installation failed; previous version restored" >&2
  exit 1
fi
stage=""

cat > "$BIN_DIR/${APP_NAME}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec python3 "$INSTALL_DIR/server.py" "\$@"
EOF
cat > "$BIN_DIR/${APP_NAME}-gui" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec python3 "$INSTALL_DIR/gui.py" "\$@"
EOF
cat > "$BIN_DIR/zai" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec python3 "$INSTALL_DIR/zai.py" "\$@"
EOF
chmod 700 "$BIN_DIR/${APP_NAME}" "$BIN_DIR/${APP_NAME}-gui" "$BIN_DIR/zai"

if [[ ! -f "$CONFIG_DIR/panel.env" ]]; then
  install -m 600 .env.example "$CONFIG_DIR/panel.env"
fi

printf 'Installed:  %s\n' "$INSTALL_DIR"
printf 'Server:     %s\n' "$BIN_DIR/${APP_NAME}"
printf 'CLI:        %s\n' "$BIN_DIR/zai"
printf 'GUI:        %s\n' "$BIN_DIR/${APP_NAME}-gui"
printf 'Config:     %s\n' "$CONFIG_DIR/panel.env"
printf 'State:      %s\n' "$STATE_DIR"
[[ -z "$backup" ]] || printf 'Backup:     %s\n' "$backup"

if [[ "$INSTALL_SERVICE" == "1" ]]; then
  command -v systemctl >/dev/null || { echo "systemctl is required for --service" >&2; exit 1; }
  mkdir -p "$SERVICE_DIR"
  systemctl --user stop "${APP_NAME}.service" 2>/dev/null || true
  cat > "$SERVICE_DIR/${APP_NAME}.service" <<EOF
[Unit]
Description=AI CLI Command Center ${APP_VERSION}
Documentation=https://github.com/cvsz/zeaz-ai-command-center
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 "$INSTALL_DIR/server.py" --host "$HOST" --port "$PORT"
WorkingDirectory=%h
EnvironmentFile=-%h/.config/$APP_NAME/panel.env
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=2
TimeoutStopSec=20
UMask=0077
NoNewPrivileges=true
RestrictSUIDSGID=true
LockPersonality=true

# Keep the default systemd --user unit portable. PrivateTmp=,
# ProtectSystem=, ProtectKernelTunables=, ProtectKernelModules= and
# ProtectControlGroups= require mount namespace or capability operations that
# are unavailable in some VMs, containers, WSL hosts and restricted sessions.

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user reset-failed "${APP_NAME}.service" 2>/dev/null || true
  if [[ "$START_SERVICE" == "1" ]]; then
    systemctl --user enable --now "${APP_NAME}.service"
    echo "Service:    active (systemctl --user status ${APP_NAME})"
  else
    systemctl --user enable "${APP_NAME}.service"
    echo "Service:    installed but not started"
  fi
fi

echo "Version:    ${APP_VERSION}"
echo "Dashboard:  zai dashboard"
echo "Run AI:     zai \"your command\""
