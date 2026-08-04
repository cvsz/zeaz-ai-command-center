# Building ZEAZ AI Command Center

## Ubuntu and Debian (PEP 668)

Recent Ubuntu and Debian releases mark the system Python installation as externally managed. Do not use `sudo pip`, and do not use `--break-system-packages` for this project.

Install the operating-system prerequisites:

```bash
sudo apt update
sudo apt install -y python3-full python3-venv
```

Then choose one of the supported workflows below.

## Recommended: automated isolated build

Run the build script directly:

```bash
./build.sh
```

When no virtual environment is active, the script creates `.venv-build`, installs the development toolchain there, runs the complete test suite, builds wheel and source distributions, installs the wheel into a second temporary environment, starts the packaged server, and verifies `/healthz` and `/`.

Artifacts are written to:

```text
dist/
```

To place the build environment somewhere else:

```bash
ZEAZ_BUILD_VENV=/path/to/build-venv ./build.sh
```

## Developer environment

Create and populate `.venv`:

```bash
make dev-setup
source .venv/bin/activate
```

Then run:

```bash
make validate
make build
make lifecycle
```

Equivalent manual commands:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
make build
```

## Install a built wheel

```bash
python3 -m venv .venv-install
.venv-install/bin/python -m pip install dist/zeaz_ai_command_center-*.whl
.venv-install/bin/zeaz-ai-command-center --host 127.0.0.1 --port 8765
```

## Troubleshooting

### `externally-managed-environment`

The command was executed against the operating system's Python installation. Create or activate a virtual environment, or run `./build.sh`, which handles the isolated build environment automatically.

### `No module named venv` or `ensurepip is not available`

Install the Ubuntu/Debian packages:

```bash
sudo apt install -y python3-full python3-venv
```

### First readiness probe reports connection refused

A newly started server may need a short startup interval before accepting connections. The build script retries readiness checks for up to 30 seconds and only fails after printing the packaged server log.
