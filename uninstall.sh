#!/usr/bin/env bash
set -euo pipefail
APP_NAME="ai-cli-command-center"
PURGE=0
[[ "${1:-}" == "--purge" ]] && PURGE=1
systemctl --user disable --now "${APP_NAME}.service" 2>/dev/null || true
rm -f "${HOME}/.config/systemd/user/${APP_NAME}.service"
systemctl --user daemon-reload 2>/dev/null || true
rm -f "${HOME}/.local/bin/${APP_NAME}"
rm -rf "${HOME}/.local/share/${APP_NAME}" "${HOME}/.local/share/${APP_NAME}".backup-*
if [[ "$PURGE" == "1" ]]; then
  rm -rf "${XDG_CONFIG_HOME:-${HOME}/.config}/${APP_NAME}"
  rm -rf "${XDG_STATE_HOME:-${HOME}/.local/state}/${APP_NAME}"
  echo "Removed ${APP_NAME}, configuration, and durable job history"
else
  echo "Removed ${APP_NAME}; configuration and durable job history were preserved"
  echo "Run $0 --purge to remove all persisted data"
fi
