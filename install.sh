#!/usr/bin/env bash
set -euo pipefail

APP_NAME="ai-cli-command-center"
APP_VERSION="3.4.1"
INSTALL_DIR="${HOME}/.local/share/${APP_NAME}"
BIN_DIR="${HOME}/.local/bin"
CONFIG_DIR="${XDG_CONFIG_HOME:-${HOME}/.config}/${APP_NAME}"
STATE_DIR="${XDG_STATE_HOME:-${HOME}/.local/state}/${APP_NAME}"
SERVICE_DIR="${HOME}/.config/systemd/user"
PORT="${PANEL_PORT:-8765}"
HOST="${PANEL_HOST:-127.0.0.1}"
INSTALL_SERVICE=0
START_SERVICE=1

usage() {
  cat <<EOF
Usage: ./install.sh [OPTIONS]

Options:
  --service          Install and enable a systemd user service
  --no-start         Install the service without starting it
  --port=8765        HTTP port
  --host=127.0.0.1   Bind host
  -h, --help         Show this help
EOF
}

for arg in "$@"; do
  case "$arg" in
    --service) INSTALL_SERVICE=1 ;;
    --no-start) START_SERVICE=0 ;;
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
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
python3 -c 'import sqlite3; assert sqlite3.sqlite_version_info >= (3, 24, 0)' || {
  echo "Python sqlite3 with SQLite 3.24+ is required" >&2
  exit 1
}

mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$CONFIG_DIR" "$STATE_DIR"
chmod 700 "$CONFIG_DIR" "$STATE_DIR"

if [[ -d "$INSTALL_DIR" && -f "$INSTALL_DIR/server.py" ]]; then
  backup="${INSTALL_DIR}.backup-$(date +%Y%m%d%H%M%S)"
  cp -a "$INSTALL_DIR" "$backup"
  echo "Backup:    $backup"
fi

rm -rf "$INSTALL_DIR/static" "$INSTALL_DIR/examples" "$INSTALL_DIR/docs"
install -m 600 server.py help_parser.py storage.py pyproject.toml README.md CHANGELOG.md LICENSE "$INSTALL_DIR/"
install -m 700 start.sh uninstall.sh "$INSTALL_DIR/"
cp -R static examples docs "$INSTALL_DIR/"
find "$INSTALL_DIR/static" "$INSTALL_DIR/examples" "$INSTALL_DIR/docs" -type f -exec chmod 600 {} +
find "$INSTALL_DIR/static" "$INSTALL_DIR/examples" "$INSTALL_DIR/docs" -type d -exec chmod 700 {} +

cat > "$BIN_DIR/${APP_NAME}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec python3 "$INSTALL_DIR/server.py" "\$@"
EOF
chmod 700 "$BIN_DIR/${APP_NAME}"

if [[ ! -f "$CONFIG_DIR/panel.env" ]]; then
  install -m 600 .env.example "$CONFIG_DIR/panel.env"
fi

printf 'Installed:  %s\n' "$INSTALL_DIR"
printf 'Launcher:   %s\n' "$BIN_DIR/${APP_NAME}"
printf 'Config:     %s\n' "$CONFIG_DIR/panel.env"
printf 'State:      %s\n' "$STATE_DIR"

if [[ "$INSTALL_SERVICE" == "1" ]]; then
  command -v systemctl >/dev/null || { echo "systemctl is required for --service" >&2; exit 1; }
  mkdir -p "$SERVICE_DIR"
  cat > "$SERVICE_DIR/${APP_NAME}.service" <<EOF
[Unit]
Description=AI CLI Command Center ${APP_VERSION}
Documentation=https://github.com/cvsz/zeaz-ai-command-center
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $INSTALL_DIR/server.py --host $HOST --port $PORT
WorkingDirectory=%h
EnvironmentFile=-%h/.config/$APP_NAME/panel.env
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=2
TimeoutStopSec=20
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  if [[ "$START_SERVICE" == "1" ]]; then
    systemctl --user enable --now "${APP_NAME}.service"
    echo "Service:    active (systemctl --user status ${APP_NAME})"
  else
    systemctl --user enable "${APP_NAME}.service"
    echo "Service:    installed but not started"
  fi
fi

echo "Version:    ${APP_VERSION}"
echo "Open:       http://${HOST}:${PORT}"
