#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

BASE_PYTHON="${PYTHON:-python3}"
BUILD_VENV="${ZEAZ_BUILD_VENV:-${SCRIPT_DIR}/.venv-build}"

# Debian/Ubuntu mark the system interpreter as externally managed (PEP 668).
# Build inside a dedicated project virtualenv instead of modifying system Python.
if [[ "${ZEAZ_BUILD_BOOTSTRAPPED:-0}" != "1" && -z "${VIRTUAL_ENV:-}" && "${ZEAZ_BUILD_SKIP_BOOTSTRAP:-0}" != "1" ]]; then
  if [[ ! -x "${BUILD_VENV}/bin/python" ]]; then
    echo "Preparing isolated build environment at ${BUILD_VENV}..."
    if ! "${BASE_PYTHON}" -m venv "${BUILD_VENV}"; then
      cat >&2 <<'EOF'
Unable to create the build virtual environment.
On Debian/Ubuntu install the venv support first:
  sudo apt update
  sudo apt install -y python3-full python3-venv
EOF
      exit 2
    fi
  fi

  "${BUILD_VENV}/bin/python" -m pip install --disable-pip-version-check --upgrade pip
  "${BUILD_VENV}/bin/python" -m pip install --disable-pip-version-check -e '.[dev]'

  exec env \
    ZEAZ_BUILD_BOOTSTRAPPED=1 \
    PYTHON="${BUILD_VENV}/bin/python" \
    "${BASH_SOURCE[0]}" "$@"
fi

PYTHON="${BASE_PYTHON}"
VERSION="$(${PYTHON} -c 'from version import __version__; print(__version__)')"

echo "========================================="
echo " ZEAZ AI Command Center Builder v${VERSION}"
echo "========================================="

${PYTHON} - <<'PY'
import importlib.util
import sys

missing = [name for name in ("build", "pytest") if importlib.util.find_spec(name) is None]
if missing:
    print("Missing build dependencies: " + ", ".join(missing), file=sys.stderr)
    print("Activate a virtualenv and install them with: python -m pip install -e '.[dev]'", file=sys.stderr)
    raise SystemExit(2)
PY

echo "[1/5] Cleaning previous build artifacts..."
rm -rf build dist *.egg-info

echo "[2/5] Validating source and test suite..."
${PYTHON} -m pytest
${PYTHON} -m py_compile server.py help_parser.py storage.py gui.py version.py

echo "[3/5] Building wheel and source distribution..."
${PYTHON} -m build --wheel --sdist

echo "[4/5] Installing and starting wheel in an isolated environment..."
wheel="$(find dist -maxdepth 1 -type f -name '*.whl' -print -quit)"
[[ -n "${wheel}" ]] || { echo "Wheel artifact not found" >&2; exit 1; }
venv_dir="$(mktemp -d)"
server_pid=""
cleanup() {
  if [[ -n "$server_pid" ]] && kill -0 "$server_pid" 2>/dev/null; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  rm -rf "$venv_dir"
}
trap cleanup EXIT
${PYTHON} -m venv "${venv_dir}"
"${venv_dir}/bin/python" -m pip install --disable-pip-version-check --no-deps "${wheel}"
"${venv_dir}/bin/zeaz-ai-command-center" --help >/dev/null
"${venv_dir}/bin/python" - <<PY
from importlib.metadata import version
from importlib.util import find_spec
from pathlib import Path

assert version("zeaz-ai-command-center") == "${VERSION}"
assert find_spec("gui") is not None
assert find_spec("version") is not None
static_spec = find_spec("static")
assert static_spec is not None and static_spec.submodule_search_locations
static_dir = Path(next(iter(static_spec.submodule_search_locations)))
for asset in ("index.html", "styles.css", "app.js"):
    assert (static_dir / asset).is_file(), asset
PY

port="$(${venv_dir}/bin/python - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)"
mkdir -p "${venv_dir}/home"
HOME="${venv_dir}/home" \
XDG_CONFIG_HOME="${venv_dir}/home/.config" \
XDG_STATE_HOME="${venv_dir}/home/.local/state" \
  "${venv_dir}/bin/zeaz-ai-command-center" --host 127.0.0.1 --port "$port" \
  >"${venv_dir}/server.log" 2>&1 &
server_pid=$!

for attempt in $(seq 1 30); do
  if "${venv_dir}/bin/python" -c '
import sys
import urllib.error
import urllib.request

port = sys.argv[1]
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as health:
        if health.status != 200:
            raise SystemExit(1)
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as page:
        body = page.read()
        if page.status != 200 or b"AI CLI Command Center" not in body:
            raise SystemExit(1)
except (OSError, urllib.error.URLError):
    raise SystemExit(1)
' "$port" 2>/dev/null; then
    break
  fi
  if ! kill -0 "$server_pid" 2>/dev/null; then
    cat "${venv_dir}/server.log" >&2
    echo "Installed wheel server exited unexpectedly" >&2
    exit 1
  fi
  if [[ "$attempt" == "30" ]]; then
    cat "${venv_dir}/server.log" >&2
    echo "Installed wheel server did not become ready" >&2
    exit 1
  fi
  sleep 1
done
kill "$server_pid"
wait "$server_pid" || true
server_pid=""

echo "[5/5] Build artifacts:"
ls -lh dist/
echo "Automated build finished successfully."
