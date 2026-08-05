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
    for module in ("server", "help_parser", "storage", "gui", "zai", "version"):
        assert f'"{module}"' in pyproject
    assert 'packages = ["static"]' in pyproject
    assert 'static = ["*.html", "*.css", "*.js"]' in pyproject
    assert (ROOT / "static" / "__init__.py").is_file()
    for asset in ("index.html", "styles.css", "app.js"):
        assert (ROOT / "static" / asset).is_file()
    assert 'zeaz-ai-command-center = "server:main"' in pyproject
    assert 'zeaz-ai-command-center-gui = "gui:main"' in pyproject
    assert 'zai = "zai:main"' in pyproject

    installer = (ROOT / "install.sh").read_text()
    assert "gui.py" in installer
    assert "zai.py" in installer
    assert "version.py" in installer
    assert '${APP_NAME}-gui' in installer
    assert '$BIN_DIR/zai' in installer
    assert "--upgrade" in installer

    uninstaller = (ROOT / "uninstall.sh").read_text()
    assert '"${HOME}/.local/bin/zai"' in uninstaller


def test_user_service_avoids_capability_and_namespace_dependent_sandboxing():
    installer = (ROOT / "install.sh").read_text()
    service_template = installer.split('cat > "$SERVICE_DIR/${APP_NAME}.service" <<EOF', 1)[1].split("\nEOF", 1)[0]

    assert "NoNewPrivileges=true" in service_template
    assert "UMask=0077" in service_template
    assert "PrivateTmp=true" not in service_template
    assert "ProtectKernelTunables=true" not in service_template
    assert "ProtectKernelModules=true" not in service_template
    assert "ProtectControlGroups=true" not in service_template
    assert "ProtectSystem=strict" not in service_template
    assert 'systemctl --user reset-failed "${APP_NAME}.service"' in installer


def test_user_service_path_includes_user_local_provider_bins_and_remains_overridable():
    installer = (ROOT / "install.sh").read_text()
    service_template = installer.split('cat > "$SERVICE_DIR/${APP_NAME}.service" <<EOF', 1)[1].split("\nEOF", 1)[0]

    default_path = "Environment=PATH=%h/.local/bin:%h/bin:/usr/local/bin:/usr/bin:/bin"
    environment_file = "EnvironmentFile=-%h/.config/$APP_NAME/panel.env"

    assert default_path in service_template
    assert environment_file in service_template
    assert service_template.index(default_path) < service_template.index(environment_file)


def test_installer_retires_only_a_verified_tracked_standalone_server():
    installer = (ROOT / "install.sh").read_text()

    assert 'stop_owned_standalone() {' in installer
    assert 'local pid_file="$STATE_DIR/zai-server.pid"' in installer
    assert 'recorded_uid = int(record.get("uid", -1))' in installer
    assert 'recorded_start_ticks = int(record.get("start_ticks", -1))' in installer
    assert 'recorded_start_ticks < 0' in installer
    assert 'server_path != expected_server' in installer
    assert 'def process_start_ticks() -> int | None:' in installer
    assert 'process_start_ticks() != recorded_start_ticks' in installer
    assert 'proc_dir.stat().st_uid != current_uid' in installer
    assert 'server_path in argv' in installer
    assert 'argument_value(argv, "--host") == host' in installer
    assert 'argument_value(argv, "--port") == port' in installer
    assert 'os.kill(pid, signal.SIGTERM)' in installer
    assert 'os.kill(pid, signal.SIGKILL)' in installer
    assert installer.index("stop_owned_standalone\n") < installer.index(
        'cat > "$SERVICE_DIR/${APP_NAME}.service" <<EOF'
    )
