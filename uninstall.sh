#!/usr/bin/env bash
set -euo pipefail
APP_NAME="ai-cli-command-center"
systemctl --user disable --now "${APP_NAME}.service" 2>/dev/null || true
rm -f "${HOME}/.config/systemd/user/${APP_NAME}.service"
systemctl --user daemon-reload 2>/dev/null || true
rm -f "${HOME}/.local/bin/${APP_NAME}"
rm -rf "${HOME}/.local/share/${APP_NAME}"
echo "Removed ${APP_NAME}. Provider registry remains at ~/.config/${APP_NAME}/providers.json"
