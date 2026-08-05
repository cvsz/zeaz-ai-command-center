# Public Release Scope

The standalone public deployment publishes the existing single-instance ZEAZ runtime through a hardened HTTPS edge.

It does not declare the PostgreSQL organization schema to be wired into the runtime, and it does not claim isolation between mutually untrusted tenants. The global multi-tenant control plane and outbound tenant agent remain separate vertical slices.

Release gates for this profile are:

- the application port is not published directly;
- bearer authentication is mandatory;
- the configured public Host is allowlisted;
- TLS and HSTS terminate at Caddy;
- containers use read-only root filesystems where practical;
- capabilities are dropped;
- persistent state and backups use distinct volumes;
- backup and restore perform SQLite integrity checks;
- CI validates Python, shell, Compose, Caddy, package, container, and lifecycle contracts.
