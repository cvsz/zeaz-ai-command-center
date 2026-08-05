#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

[[ -f .env ]] || { echo "Missing deploy/public/.env" >&2; exit 1; }

echo "Creating an immediate verified backup..."
docker compose run --rm \
  -e ZEAZ_BACKUP_INTERVAL_SECONDS=0 \
  backup

echo "Pulling base images and rebuilding the application..."
docker compose pull caddy
docker compose build --pull app

echo "Applying the update..."
docker compose up -d --remove-orphans app caddy backup

for attempt in $(seq 1 60); do
  if docker compose exec -T app python3 -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=3).read()" \
    >/dev/null 2>&1; then
    echo "Update completed and health check passed."
    docker compose ps
    exit 0
  fi
  sleep 2
done

docker compose logs --tail=150 app caddy
echo "Updated application did not become healthy. Restore the latest backup if required." >&2
exit 1
