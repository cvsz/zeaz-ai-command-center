#!/usr/bin/env bash
set -euo pipefail

APP_NAME="ai-cli-command-center"
INSTALL_DIR="${HOME}/.local/share/${APP_NAME}"
BIN_DIR="${HOME}/.local/bin"
SERVICE_DIR="${HOME}/.config/systemd/user"
PORT="${PANEL_PORT:-8765}"
INSTALL_SERVICE=0

for arg in "$@"; do
  case "$arg" in
    --service) INSTALL_SERVICE=1 ;;
    --port=*) PORT="${arg#*=}" ;;
    --help)
      echo "Usage: ./install.sh [--service] [--port=8765]"
      exit 0
      ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
mkdir -p "$INSTALL_DIR" "$BIN_DIR"
cp -R server.py help_parser.py static pyproject.toml README.md start.sh uninstall.sh "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/start.sh" "$INSTALL_DIR/uninstall.sh"
cat > "$BIN_DIR/ai-cli-command-center" <<EOF
#!/usr/bin/env bash
exec python3 "$INSTALL_DIR/server.py" "\$@"
EOF
chmod +x "$BIN_DIR/ai-cli-command-center"

echo "Installed: $INSTALL_DIR"
echo "Launcher:  $BIN_DIR/ai-cli-command-center"

if [[ "$INSTALL_SERVICE" == "1" ]]; then
  mkdir -p "$SERVICE_DIR"
  cat > "$SERVICE_DIR/${APP_NAME}.service" <<EOF
[Unit]
Description=AI CLI Command Center
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $INSTALL_DIR/server.py --host 127.0.0.1 --port $PORT
WorkingDirectory=%h
Restart=on-failure
RestartSec=2
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now "${APP_NAME}.service"
  echo "Service started: systemctl --user status ${APP_NAME}"
fi

echo "Open: http://127.0.0.1:${PORT}"
