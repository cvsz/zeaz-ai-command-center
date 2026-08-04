"""Regression tests for provider discovery, root containment, and executable trust boundaries."""

import os
import stat
import sys
from pathlib import Path

import pytest

from server import resolve_executable, run_capture


@pytest.mark.skipif(sys.platform == "win32", reason="symlink executable semantics differ on Windows")
def test_run_capture_accepts_canonical_target_resolved_from_path(tmp_path: Path, monkeypatch):
    release_dir = tmp_path / ".codex" / "packages" / "standalone" / "releases" / "0.146.0-test" / "bin"
    release_dir.mkdir(parents=True)
    target = release_dir / "codex"
    target.write_text("#!/usr/bin/env python3\nprint('codex-test')\n", encoding="utf-8")
    target.chmod(0o755)

    launcher_dir = tmp_path / ".local" / "bin"
    launcher_dir.mkdir(parents=True)
    (launcher_dir / "codex").symlink_to(target)

    monkeypatch.setenv("PATH", f"{launcher_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("PANEL_ALLOWED_ROOTS", str(tmp_path))
    monkeypatch.delenv("PANEL_ALLOW_ABSOLUTE_BINARIES", raising=False)

    resolved = resolve_executable("codex")
    assert resolved == str(target.resolve())

    code, output = run_capture([resolved, "--version"])
    assert code == 0
    assert output.strip() == "codex-test"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX executable bit required")
def test_run_capture_rejects_untrusted_absolute_path(tmp_path: Path, monkeypatch):
    executable = tmp_path / "rogue-provider"
    executable.write_text("#!/usr/bin/env python3\nprint('unexpected')\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("PANEL_ALLOWED_ROOTS", str(tmp_path))
    monkeypatch.delenv("PANEL_ALLOW_ABSOLUTE_BINARIES", raising=False)

    with pytest.raises(ValueError, match="not the active executable resolved from PATH"):
        run_capture([str(executable)])


def test_resolve_explicit_absolute_path_still_requires_opt_in(tmp_path: Path, monkeypatch):
    executable = tmp_path / "custom-provider"
    executable.write_text("provider", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("PANEL_ALLOWED_ROOTS", str(tmp_path))
    monkeypatch.delenv("PANEL_ALLOW_ABSOLUTE_BINARIES", raising=False)

    with pytest.raises(ValueError, match="Absolute executable paths are disabled"):
        resolve_executable(str(executable))


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits required")
def test_world_writable_path_provider_is_rejected(tmp_path: Path, monkeypatch):
    executable = tmp_path / "provider"
    executable.write_text("#!/usr/bin/env python3\nprint('unsafe')\n", encoding="utf-8")
    executable.chmod(stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("PANEL_ALLOWED_ROOTS", str(tmp_path))
    monkeypatch.delenv("PANEL_ALLOW_WORLD_WRITABLE_BINARIES", raising=False)

    with pytest.raises(ValueError, match="world-writable"):
        resolve_executable("provider")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX executable bit required")
def test_executable_outside_trusted_roots_is_rejected(tmp_path: Path, monkeypatch):
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    executable = outside / "provider"
    executable.write_text("#!/usr/bin/env python3\nprint('outside')\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{outside}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("PANEL_ALLOWED_ROOTS", str(trusted))

    with pytest.raises(ValueError, match="outside trusted roots"):
        resolve_executable("provider")
