# Threat Model

## Protected assets

- Workspaces reachable by AI CLI processes
- Provider credentials in the inherited process environment
- Custom provider registry
- Durable job history and output
- Operator authorization token
- Integrity of registered provider binaries

## Trust boundaries

1. Browser to HTTP service
2. HTTP service to provider executable
3. Provider executable to workspace and network
4. Service to SQLite state
5. Installation/update process to local filesystem

## Primary threats and controls

| Threat | Controls | Residual risk |
|---|---|---|
| Command injection | Structured argv, `shell=False`, strict command tokens | A provider can interpret its own arguments in unsafe ways |
| DNS rebinding / hostile Host | Host-header allowlist | Reverse proxies must preserve an allowed Host |
| Cross-site mutation | Same-origin checks and `Sec-Fetch-Site` rejection | Non-browser API clients do not send Origin and rely on bearer auth |
| Token leakage | Authorization header only; query tokens rejected | Browser session storage is accessible to same-origin scripts |
| Dangerous execution | Risk detection and exact confirmation phrases | Heuristics cannot understand every provider-specific action |
| Workspace escape | Canonical allowed-root validation | A process can follow links created after validation; use external sandboxing for hostile workloads |
| Environment injection | Exact/prefix allowlist and loader-variable denylist | Provider-specific variables must be added deliberately |
| Secret leakage in history | Sensitive argv redaction; environment omitted; environment values redacted from output across chunk boundaries | Secrets printed from inherited environment or files may still appear |
| Binary replacement | SHA-256 fingerprint and change warning; world-writable binaries rejected | A privileged attacker can replace both executable and local configuration |
| Resource exhaustion | request/output/body/time/concurrency/rate limits | Provider children may consume resources; add systemd/container cgroup limits externally |
| Restart ambiguity | active jobs marked orphaned | An independently daemonized child may survive; providers should not daemonize |

## Deployment recommendations

- Bind to loopback and use an SSH tunnel by default.
- For network exposure, require a strong `PANEL_TOKEN`, TLS, an explicit `PANEL_ALLOWED_HOSTS`, and firewall restrictions.
- Run under a dedicated unprivileged account.
- Keep `PANEL_ALLOW_ANY_CWD`, `PANEL_ALLOW_ANY_ENV`, and absolute binaries disabled.
- Use isolated worktrees or disposable workspaces for autonomous agents.
- Protect the state/config directories with mode `0700` and files with `0600`.
- Treat command output as potentially sensitive.

## Reporting

Do not publish exploitable vulnerabilities in a public issue. Follow the process in the repository `SECURITY.md`.
