# Standalone Global Public Deployment

This deployment publishes one ZEAZ AI Command Center instance through automatic HTTPS using only self-hosted, open-source components.

## Included

- ZEAZ AI Command Center 3.4.3;
- Caddy reverse proxy with automatic ACME TLS;
- HTTP/1.1, HTTP/2, and HTTP/3 edge support;
- loopback-free container networking without exposing the application port;
- bearer authentication enforced by the application;
- strict Host validation and HSTS;
- read-only root filesystems, dropped capabilities, and `no-new-privileges`;
- persistent SQLite state and workspace storage;
- optional read-only provider binary mount;
- verified scheduled SQLite backups with SHA-256 checksums;
- guarded restore and update workflows.

## Scope

This is a **single-instance public deployment**. It is suitable for one trusted operator or one trusted team using the existing application RBAC.

The repository also contains the PostgreSQL organization/RLS schema and the control-plane/tenant-agent architecture. Those foundations do not yet make this runtime a production multi-tenant control plane. Do not host mutually untrusted organizations in this single process until the tenant-aware API, agent protocol, and cross-tenant isolation tests are complete.

## Requirements

- Linux server with Docker Engine and Compose v2;
- public IPv4 or IPv6 connectivity;
- DNS `A`/`AAAA` record pointing to the server;
- inbound TCP 80 and TCP/UDP 443;
- an email address for ACME certificate notifications;
- enough local disk for state, workspaces, images, and backups.

No managed database, paid tunnel, paid certificate, or mandatory cloud platform is required. Hardware, electricity, connectivity, a domain, and optional provider/API usage remain external costs.

## Install

```bash
git clone https://github.com/cvsz/zeaz-ai-command-center.git
cd zeaz-ai-command-center/deploy/public
cp .env.example .env
```

Edit `.env`:

```dotenv
ZEAZ_DOMAIN=ai.your-domain.example
ACME_EMAIL=admin@your-domain.example
```

The installer creates a strong bearer token when `.env` does not exist. When you create `.env` manually, generate one with:

```bash
python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(64))
PY
```

Then install:

```bash
chmod +x install.sh update.sh restore.sh
./install.sh
```

Open:

```text
https://ai.your-domain.example
```

Use the `PANEL_TOKEN` value from `deploy/public/.env` as the bearer token in supported clients.

## Provider binaries

The public container discovers executables in:

```text
/providers/bin
```

Place compatible static executables under:

```text
deploy/public/providers/bin/
```

The directory is mounted read-only. Provider binaries must not be world-writable. Many provider CLIs require runtimes or configuration that are not present in the base image; for those providers, create a derived image or use the future outbound tenant agent instead of mounting arbitrary host runtime trees.

Provider credentials belong in a protected deployment environment, never in the browser or repository. Restrict `.env` to mode `0600`.

## Operations

```bash
docker compose ps
docker compose logs -f app caddy backup
docker compose restart app
```

Validate external health:

```bash
curl -fsS "https://${ZEAZ_DOMAIN}/healthz"
```

The application itself is not published as a host port. Only Caddy exposes ports 80 and 443.

## Backup

The backup sidecar creates a consistent SQLite snapshot every 24 hours by default and retains 14 days.

Create a backup immediately:

```bash
docker compose run --rm \
  -e ZEAZ_BACKUP_INTERVAL_SECONDS=0 \
  backup
```

List backups:

```bash
docker compose run --rm --entrypoint sh backup -c 'ls -lah /backups'
```

Copy backups off-host regularly. A backup stored on the same physical disk is not disaster recovery.

## Restore

First list available backup names, then run:

```bash
./restore.sh jobs-YYYYMMDDTHHMMSSZ.sqlite3
```

The workflow:

1. requires an explicit `RESTORE` confirmation;
2. stops the app and scheduled backup service;
3. verifies the selected SQLite database;
4. preserves the previous database as a pre-restore copy;
5. starts services and waits for a successful health check.

## Update

```bash
git pull --ff-only
cd deploy/public
./update.sh
```

The updater creates a verified backup before rebuilding and restarting the deployment.

## Firewall baseline

Expose only:

```text
22/tcp   SSH, preferably restricted by source or VPN
80/tcp   ACME challenge and HTTPS redirect
443/tcp  HTTPS
443/udp  HTTP/3
```

Do not expose application port 8765, Docker API ports, database ports, or monitoring endpoints publicly.

## Security checklist

- Use a unique 64-byte bearer token.
- Keep `.env` mode `0600`.
- Disable password SSH and direct root SSH.
- Apply OS and Docker security updates.
- Use a non-shared host for untrusted workloads.
- Keep `PANEL_ALLOWED_ROOTS=/workspace`.
- Do not enable arbitrary absolute binaries.
- Review all AI-generated diffs before merging or deploying.
- Copy backups to another machine or encrypted removable media.
- Monitor Caddy and application logs for repeated authentication failures.

## Removal

Stop services but preserve data:

```bash
docker compose down
```

Delete containers and all persistent volumes only when intentionally destroying the deployment:

```bash
docker compose down -v
```
