# Contributing

## Development setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
make validate
```

Runtime code must remain compatible with Python 3.10+ and should avoid third-party runtime dependencies unless there is a clear security or maintainability benefit.

## Change requirements

- Preserve structured argv execution and `shell=False`.
- Add golden help samples for parser changes.
- Add tests for security-policy changes and failure paths.
- Do not persist environment values or unredacted sensitive argv.
- Keep API compatibility unless the change is explicitly versioned.
- Update README/docs and `CHANGELOG.md` for user-visible changes.

## Pull requests

Keep each PR focused on one complete vertical slice. Include validation commands and note security, migration, rollback, and compatibility implications.
