import json
import re
from pathlib import Path

import server
from version import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_and_release_versions_are_synchronized():
    assert server.APP_VERSION == __version__
    assert json.loads((ROOT / "package.json").read_text())["version"] == __version__

    openapi_head = "\n".join((ROOT / "openapi.yaml").read_text().splitlines()[:12])
    match = re.search(r"(?m)^  version:\s*([^\s]+)\s*$", openapi_head)
    assert match and match.group(1) == __version__

    dockerfile = (ROOT / "Dockerfile").read_text()
    assert f"ARG APP_VERSION={__version__}" in dockerfile

    compose = (ROOT / "compose.yaml").read_text()
    assert f"APP_VERSION: {__version__}" in compose
    assert f"image: zeaz-ai-command-center:{__version__}" in compose


def test_python_distribution_and_launchers_are_complete():
    pyproject = (ROOT / "pyproject.toml").read_text()
    assert 'dynamic = ["version"]' in pyproject
    assert 'version = {attr = "version.__version__"}' in pyproject
    for module in ("server", "help_parser", "storage", "gui", "version"):
        assert f'"{module}"' in pyproject
    assert 'zeaz-ai-command-center = "server:main"' in pyproject
    assert 'zeaz-ai-command-center-gui = "gui:main"' in pyproject

    installer = (ROOT / "install.sh").read_text()
    assert "gui.py" in installer
    assert "version.py" in installer
    assert '${APP_NAME}-gui' in installer
    assert "--upgrade" in installer
