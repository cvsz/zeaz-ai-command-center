#!/usr/bin/env python3
"""Apply the trusted provider executable policy patch and its tests."""

from pathlib import Path

server_path = Path("server.py")
text = server_path.read_text(encoding="utf-8")

marker = "\ndef resolve_executable(executable: Any) -> str:\n"
replacement = '''

def allowed_executable_roots() -> list[Path]:
    """Return roots from which provider executables may be launched."""
    roots = list(allowed_roots())
    if sys.platform == "win32":
        for key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "APPDATA"):
            value = os.getenv(key, "").strip()
            if value:
                roots.append(Path(value).expanduser().resolve())
    else:
        roots.extend(
            Path(value).resolve()
            for value in ("/bin", "/sbin", "/usr/bin", "/usr/sbin", "/usr/local/bin", "/opt/homebrew/bin")
        )
    return list(dict.fromkeys(roots))


def _validate_runnable_executable(executable: Any) -> str:
    """Return a canonical executable path after root and mode checks."""
    path = Path(safe_text(executable, max_len=4096)).expanduser().resolve()
    if not path.is_absolute():
        raise ValueError(f"Executable is not runnable: {path}")
    for root in allowed_executable_roots():
        resolved_root = Path(root).resolve()
        if str(path).startswith(str(resolved_root) + os.sep) or path == resolved_root:
            break
    else:
        raise ValueError(
            "Executable is outside trusted roots: "
            + ", ".join(map(str, allowed_executable_roots()))
        )
    if not path.exists() or not path.is_file():
        raise ValueError(f"Executable is not runnable: {path}")
    if sys.platform != "win32" and not os.access(path, os.X_OK):
        raise ValueError(f"Executable is not runnable: {path}")
    metadata = path.stat()
    if metadata.st_mode & stat.S_IWOTH and os.getenv("PANEL_ALLOW_WORLD_WRITABLE_BINARIES", "0") != "1":
        raise ValueError("Refusing world-writable provider executable")
    return str(path)


def resolve_executable(executable: Any) -> str:
'''
if marker not in text:
    raise SystemExit("resolve_executable marker not found")
text = text.replace(marker, replacement, 1)

old_explicit = '''        path = Path(raw).expanduser().resolve()
        if not path.is_absolute() or not path.exists() or not path.is_file() or (sys.platform != "win32" and not os.access(path, os.X_OK)):
            raise ValueError(f"Executable is not runnable: {path}")
        return str(path)
'''
if old_explicit not in text:
    raise SystemExit("explicit executable block not found")
text = text.replace(old_explicit, "        return _validate_runnable_executable(raw)\n", 1)

old_path_return = '''    return str(Path(resolved).resolve())


def run_capture'''
if old_path_return not in text:
    raise SystemExit("PATH executable return block not found")
text = text.replace(
    old_path_return,
    '''    return _validate_runnable_executable(resolved)


def run_capture''',
    1,
)

old_capture = '''    executable = argv[0]
    if os.path.isabs(executable) and os.getenv("PANEL_ALLOW_ABSOLUTE_BINARIES", "0") != "1":
        raise ValueError(f"Absolute executable path rejected: {executable}")
    env = os.environ.copy()
'''
new_capture = '''    executable = argv[0]
    if os.path.isabs(executable):
        resolved_executable = _validate_runnable_executable(executable)
        executable_name = os.path.basename(executable)
        discovered = shutil.which(executable_name) if BINARY_RE.fullmatch(executable_name) else None
        discovered_resolved = _validate_runnable_executable(discovered) if discovered else ""
        if (
            discovered_resolved != resolved_executable
            and os.getenv("PANEL_ALLOW_ABSOLUTE_BINARIES", "0") != "1"
        ):
            raise ValueError(
                f"Absolute executable path rejected: {executable}; "
                "it is not the active executable resolved from PATH"
            )
    else:
        resolved_executable = resolve_executable(executable)
    argv = [resolved_executable, *argv[1:]]
    env = os.environ.copy()
'''
if old_capture not in text:
    raise SystemExit("run_capture policy block not found")
text = text.replace(old_capture, new_capture, 1)
server_path.write_text(text, encoding="utf-8")

Path("tests/test_executable_policy.py").write_text(
    '''import os
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
    target.write_text("#!/usr/bin/env python3\\nprint('codex-test')\\n", encoding="utf-8")
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
    executable.write_text("#!/usr/bin/env python3\\nprint('unexpected')\\n", encoding="utf-8")
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
    executable.write_text("#!/usr/bin/env python3\\nprint('unsafe')\\n", encoding="utf-8")
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
    executable.write_text("#!/usr/bin/env python3\\nprint('outside')\\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{outside}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("PANEL_ALLOWED_ROOTS", str(trusted))

    with pytest.raises(ValueError, match="outside trusted roots"):
        resolve_executable("provider")
''',
    encoding="utf-8",
)
