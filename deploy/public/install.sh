#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker Engine is required." >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  cp .env.example .env
  python3 - <<'PY'
from pathlib import Path
import secrets

path = Path('.env')
text = path.read_text(encoding='utf-8')
text = text.replace(
    'replace-with-at-least-48-random-bytes',
    secrets.token_urlsafe(64),
)
path.write_text(text, encoding='utf-8')
PY
  chmod 600 .env
  echo "Created deploy/public/.env with a random PANEL_TOKEN."
fi

set -a
# shellcheck disable=SC1091
source ./.env
set +a

case "${ZEAZ_DOMAIN:-}" in
  ""|ai.example.com|localhost|127.0.0.1)
    echo "Set ZEAZ_DOMAIN in deploy/public/.env to a public DNS name." >&2
    exit 1
    ;;
esac

if [[ -z "${ACME_EMAIL:-}" || "$ACME_EMAIL" == "admin@example.com" ]]; then
  echo "Set ACME_EMAIL in deploy/public/.env." >&2
  exit 1
fi

if [[ -z "${PANEL_TOKEN:-}" || ${#PANEL_TOKEN} -lt 48 ]]; then
  echo "PANEL_TOKEN must contain at least 48 characters." >&2
  exit 1
fi

mkdir -p workspace providers/bin
chmod 700 workspace providers providers/bin

if ! getent hosts "$ZEAZ_DOMAIN" >/dev/null 2>&1; then
  echo "Warning: $ZEAZ_DOMAIN does not resolve from this host yet." >&2
fi

echo "Validating deployment configuration..."
docker compose config --quiet

echo "Building ZEAZ ${ZEAZ_VERSION:-3.4.3}..."
docker compose build --pull app

echo "Starting HTTPS edge, application, and backup service..."
docker compose up -d --remove-orphans app caddy backup

for attempt in $(seq 1 60); do
  if docker compose exec -T app python3 -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=3).read()" \
    >/dev/null 2>&1; then
    echo "Application health check passed."
    break
  fi
  if [[ "$attempt" == "60" ]]; then
    docker compose ps
    docker compose logs --tail=100 app caddy
    echo "Application did not become healthy." >&2
    exit 1
  fi
  sleep 2
done

cat <<EOF

ZEAZ public deployment is running.
URL: https://${ZEAZ_DOMAIN}

Next checks:
  docker compose ps
  docker compose logs -f app caddy
  curl -fsS https://${ZEAZ_DOMAIN}/healthz

The bearer token remains in:
  ${ROOT_DIR}/.env
EOF
