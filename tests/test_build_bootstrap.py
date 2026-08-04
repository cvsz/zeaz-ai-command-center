from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_build_script_uses_isolated_virtualenv_and_quiet_readiness_retries():
    script = (ROOT / "build.sh").read_text()

    assert ".venv-build" in script
    assert "ZEAZ_BUILD_BOOTSTRAPPED" in script
    assert 'python3-full python3-venv' in script
    assert "--break-system-packages" not in script
    assert '"$port" 2>/dev/null' in script
    assert "Installed wheel server did not become ready" in script


def test_python_314_is_declared_and_tested():
    pyproject = (ROOT / "pyproject.toml").read_text()
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert 'Programming Language :: Python :: 3.14' in pyproject
    assert '"3.14"' in workflow
    assert "build.sh tests/lifecycle.sh" in workflow


def test_package_archive_excludes_build_virtualenv():
    makefile = (ROOT / "Makefile").read_text()

    assert "dev-setup:" in makefile
    assert "*/.venv-build/*" in makefile
