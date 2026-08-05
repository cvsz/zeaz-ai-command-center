# Repository Governance

This document records the repository governance policy for `cvsz/zeaz-ai-command-center`.

## Protected branch

The default branch is `main`.

GitHub repository ruleset:

- Name: `main-production-protection`
- Ruleset ID: `20441602`
- Enforcement: `active`
- Target: branch
- Target branch: default branch (`main`)
- Management URL: `https://github.com/cvsz/zeaz-ai-command-center/rules/20441602`

## Enforced rules

The ruleset enforces the following controls on `main`:

- Branch deletion is blocked.
- Non-fast-forward updates and force pushes are blocked.
- Changes must be merged through a pull request.
- All review conversations must be resolved before merge.
- The pull-request branch must be up to date with `main`.
- Required CI checks must pass before merge.

The repository owner `cvsz` may bypass the ruleset only through the pull-request flow. Direct protected-branch updates are not part of the normal development process.

## Required checks

The following status checks are required:

- `Python 3.10`
- `Python 3.11`
- `Python 3.12`
- `Python 3.13`
- `Python 3.14`
- `Frontend and shell validation`
- `Container build`
- `Install, build, upgrade, uninstall`
- `Build and start container`

## Development workflow

Use one complete vertical slice per pull request.

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/<vertical-slice>

# Implement and validate the complete slice.
make validate

git add .
git commit -m "feat: <description>"
git push -u origin HEAD

gh pr create --fill --base main
gh pr checks --watch
```

Merge only after all required checks pass and all conversations are resolved.

Preferred merge command:

```bash
gh pr merge --squash --delete-branch
```

## Review policy

The current required approval count is `0` because the repository is primarily maintained by one owner. Increase this to at least `1` when an independent maintainer or review team is available.

Security-sensitive changes should still receive explicit review when possible, especially changes involving:

- authentication and authorization;
- tenant isolation and PostgreSQL row-level security;
- command execution and sandboxing;
- provider credentials and secret handling;
- agent enrollment and signing keys;
- deployment, backup, and recovery;
- GitHub App permissions and webhook processing.

## Change control

Changes to this governance policy or the active GitHub ruleset should be recorded in a pull request. Emergency bypasses must be documented with the reason, affected commits, validation performed, and any follow-up remediation.
