# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 2.1.x | Yes |
| 2.0.x | Security fixes only during migration |
| < 2.0 | No |

## Reporting a vulnerability

Please report vulnerabilities privately to the repository owner through GitHub's private vulnerability reporting feature when available. Include:

- affected version and commit
- deployment model
- reproducible steps or proof of concept
- impact and affected assets
- suggested mitigation, if known

Do not include production credentials, private source code, or customer data. Please avoid public issues until a fix or coordinated disclosure plan is available.

## Security assumptions

This application launches local executables. It does not make an untrusted AI CLI safe by itself. Operators remain responsible for provider provenance, operating-system permissions, external sandboxing, network controls, and workspace backups.
