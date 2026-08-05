#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ $# -ne 1 ]]; then
  echo "usage: $0 jobs-TIMESTAMP.sqlite3" >&2
  exit 2
fi

BACKUP_NAME="$(basename -- "$1")"
if [[ "$BACKUP_NAME" != "$1" || "$BACKUP_NAME" != jobs-*.sqlite3 ]]; then
  echo "Backup must be a jobs-TIMESTAMP.sqlite3 file name from the backup volume." >&2
  exit 2
fi

read -r -p "Stop ZEAZ and restore ${BACKUP_NAME}? Type RESTORE to continue: " confirmation
[[ "$confirmation" == "RESTORE" ]] || { echo "Restore cancelled."; exit 1; }

docker compose stop app backup
trap 'docker compose up -d app backup caddy >/dev/null 2>&1 || true' EXIT

docker compose --profile tools run --rm restore "$BACKUP_NAME"

docker compose up -d app backup caddy
trap - EXIT

for attempt in $(seq 1 60); do
  if docker compose exec -T app python3 -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=3).read()" \
    >/dev/null 2>&1; then
    echo "Restore completed and application health check passed."
    exit 0
  fi
  sleep 2
done

docker compose logs --tail=150 app
echo "Restored application did not become healthy." >&2
exit 1
