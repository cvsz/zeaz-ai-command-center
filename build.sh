#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"
PYTHON="${PYTHON:-python3}"
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
    print("Install them with: python3 -m pip install -e '.[dev]'", file=sys.stderr)
    raise SystemExit(2)
PY

echo "[1/5] Cleaning previous build artifacts..."
rm -rf build dist *.egg-info

echo "[2/5] Validating source and test suite..."
${PYTHON} -m pytest
${PYTHON} -m py_compile server.py help_parser.py storage.py gui.py version.py

echo "[3/5] Building wheel and source distribution..."
${PYTHON} -m build --wheel --sdist

echo "[4/5] Installing wheel into an isolated environment..."
wheel="$(find dist -maxdepth 1 -type f -name '*.whl' -print -quit)"
[[ -n "${wheel}" ]] || { echo "Wheel artifact not found" >&2; exit 1; }
venv_dir="$(mktemp -d)"
trap 'rm -rf "${venv_dir}"' EXIT
${PYTHON} -m venv "${venv_dir}"
"${venv_dir}/bin/python" -m pip install --disable-pip-version-check --no-deps "${wheel}"
"${venv_dir}/bin/zeaz-ai-command-center" --help >/dev/null
"${venv_dir}/bin/python" - <<PY
from importlib.metadata import version
from importlib.util import find_spec
assert version("zeaz-ai-command-center") == "${VERSION}"
assert find_spec("gui") is not None
assert find_spec("version") is not None
PY

echo "[5/5] Build artifacts:"
ls -lh dist/
echo "Automated build finished successfully."
