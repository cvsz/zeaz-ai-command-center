# GitHub Environments

The repository uses three GitHub deployment environments:

| Environment | Purpose | Recommended source |
| --- | --- | --- |
| `development` | Integration and operator testing | Feature branches or manual runs |
| `staging` | Release-candidate validation | `main` |
| `production` | Production deployment approval boundary | Protected `main` only |

## Environment variables

Configure these values under **Settings → Environments → _environment_ → Environment variables**.

| Variable | Development default | Staging default | Production default |
| --- | --- | --- | --- |
| `PANEL_HOST` | `127.0.0.1` | `127.0.0.1` | `127.0.0.1` |
| `PANEL_PORT` | `8765` | `8765` | `8765` |
| `PANEL_ALLOWED_HOSTS` | `localhost,127.0.0.1,::1` | deployment hostname | production hostname |
| `PANEL_ALLOWED_ROOTS` | test workspace | staging workspace | production workspace |
| `PANEL_ENABLE_HSTS` | `0` | `1` when HTTPS-only | `1` when HTTPS-only |
| `PANEL_LOG_LEVEL` | `DEBUG` | `INFO` | `INFO` |
| `PANEL_LOG_FORMAT` | `text` | `json` | `json` |
| `DEPLOY_HOST` | optional | staging server | production server |
| `DEPLOY_PORT` | `22` | `22` | `22` |
| `DEPLOY_USER` | optional | service account | service account |
| `DEPLOY_PATH` | optional | application directory | application directory |

Keep host-specific values in GitHub environment variables rather than committing them to `.env` files.

## Environment secrets

Configure these under **Environment secrets**. Never commit their values.

- `PANEL_TOKEN` — bearer token used when the service is exposed beyond loopback.
- `DEPLOY_SSH_KEY` — optional private key for a future automated deployment job.
- `DEPLOY_KNOWN_HOSTS` — optional pinned SSH host-key entry.

The permanent environment contract workflow checks configuration without displaying secret values.

## Protection recommendations

### development

- No required reviewer.
- Allow manual runs from feature branches.
- Do not store production credentials.

### staging

- Restrict deployment branches to `main`.
- Add a short wait timer only when operationally useful.
- Use credentials that cannot access production.

### production

- Restrict deployment branches to protected `main`.
- Require at least one reviewer other than the deploy initiator.
- Enable prevent-self-review.
- Store only production-scoped credentials.
- Keep deployment concurrency at one.

## Validate an environment

Open **Actions → Environment Contract → Run workflow**, choose the environment, and run it. The workflow validates required variables, numeric port values, host policy, and whether a token is present when the service binds beyond loopback.

This workflow does not deploy or print secrets.
