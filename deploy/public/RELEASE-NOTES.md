# ZEAZ AI Command Center — Global Public Profile

This release packages the existing ZEAZ AI Command Center runtime with a self-hosted public HTTPS deployment profile.

## Highlights

- Automatic TLS through Caddy and ACME.
- The application port remains private to the Compose network.
- Required bearer authentication, Host allowlisting, HSTS, and security headers.
- Rootless application process with read-only root filesystem, dropped capabilities, and `no-new-privileges`.
- Persistent SQLite state and workspace volumes.
- Optional read-only provider binary mount.
- Scheduled, integrity-checked SQLite backups with SHA-256 manifests.
- Guarded restore and pre-update backup workflows.
- CI validation for Compose, Caddy, Python, shell, containers, packaging, and lifecycle behavior.

## Trust boundary

This profile deploys one application instance for one trusted operator or trusted team. It is not the completed untrusted multi-tenant control plane. PostgreSQL RLS, organization schemas, and the control-plane/agent architecture are foundations for later vertical slices.

Do not place mutually untrusted organizations in this process until the tenant-aware API, remote-agent protocol, and cross-tenant isolation suite are complete.

## Installation

See `deploy/public/README.md` in the source archive.

Required inputs are a Linux server, Docker Compose v2, a public DNS record, ports 80/443, and an ACME contact email. No paid tunnel, managed database, or paid certificate is required.
