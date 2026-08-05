# Standalone Global Deployment Bootstrap

This directory contains the first executable foundation for the no-paid-dependency multi-tenant architecture.

It currently initializes:

- PostgreSQL 16;
- the `zeaz` schema;
- organization-scoped tables;
- forced Row-Level Security policies;
- durable jobs, leases, idempotency, events, artifacts, API keys, audit, and outbox tables;
- least-privilege, non-login database roles for the future control plane, scheduler, and backup process.

The control-plane and remote-agent services are implemented in later vertical slices described in `docs/GLOBAL-MULTITENANT-EXECUTION-PLAN.md`.

## Requirements

- Docker Engine with Compose v2, or a compatible Podman Compose setup;
- an existing Linux server;
- local disk space for PostgreSQL;
- no managed database or paid cloud service.

## Start

```bash
cd deploy/global
cp .env.example .env
python3 - <<'PY'
from pathlib import Path
import secrets

path = Path('.env')
text = path.read_text(encoding='utf-8')
text = text.replace(
    'replace-with-a-long-random-secret',
    secrets.token_urlsafe(48),
)
path.write_text(text, encoding='utf-8')
PY
chmod 600 .env
docker compose up -d
```

## Validate

```bash
docker compose ps
docker compose exec postgres \
  psql -U "${ZEAZ_DB_ADMIN_USER:-zeaz_admin}" \
       -d "${ZEAZ_DB_NAME:-zeaz}" \
       -c '\dt zeaz.*'

docker compose exec postgres \
  psql -U "${ZEAZ_DB_ADMIN_USER:-zeaz_admin}" \
       -d "${ZEAZ_DB_NAME:-zeaz}" \
       -c "SELECT schemaname, tablename, rowsecurity FROM pg_tables WHERE schemaname = 'zeaz' ORDER BY tablename;"
```

Expected result: all tenant tables exist and `rowsecurity` is true.

## Important initialization behavior

PostgreSQL runs files in `postgres/` only when the data directory is empty. Editing an initialization SQL file does not migrate an existing volume.

During development, reset the disposable bootstrap database with:

```bash
docker compose down -v
docker compose up -d
```

Never delete a production volume to apply a migration. Production deployments require the migration runner from execution-plan Slice 2.1.

## Network boundary

The database port binds to loopback only:

```text
127.0.0.1:55432
```

It must not be exposed directly to the public internet. Future control-plane containers connect through the internal Compose network. Administrative access should use SSH or WireGuard.

## Database role model

Initialization creates these group roles without login credentials:

- `zeaz_application` — tenant API data access, subject to forced RLS;
- `zeaz_scheduler` — job dispatch, lease, event, and outbox operations, subject to forced RLS;
- `zeaz_backup` — read-only backup access, subject to forced RLS.

Later deployment code creates login roles and grants membership without making application logins table owners or giving them `BYPASSRLS`.

## Cost boundary

This bootstrap requires no subscription service. It uses the existing host, local disk, Docker/Podman, and PostgreSQL. Hardware, electricity, internet connectivity, backup media, and an optional domain are not provided by the software.
