#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "========================================="
echo "  ZEAZ AI Command Center Automated Builder "
echo "========================================="

echo "[1/4] Validating source code and test suite..."
python3 -m pytest

echo "[2/4] Building cross-platform Python wheel and source tarball..."
if [ -d ".venv" ]; then
    .venv/bin/python -m build
else
    python3 -m build
fi

echo "[3/4] Validating build artifacts in dist/..."
ls -lh dist/

echo "[4/4] Automated build finished successfully!"
