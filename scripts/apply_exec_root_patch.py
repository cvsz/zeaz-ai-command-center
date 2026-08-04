#!/usr/bin/env python3
"""Apply trusted executable root containment and update regression tests."""

from pathlib import Path

server_path = Path("server.py")
text = server_path.read_text(encoding="utf-8")

marker = "\ndef _validate_runnable_executable(executable: Any) -> str:\n"
helper = '''
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

'''
if helper.strip() not in text:
    if marker not in text:
        raise SystemExit("executable validator marker not found")
    text = text.replace(marker, "\n" + helper + "def _validate_runnable_executable(executable: Any) -> str:\n", 1)

old = '''    path = Path(safe_text(executable, max_len=4096)).expanduser().resolve()
    if not path.is_absolute() or not path.exists() or not path.is_file():
        raise ValueError(f"Executable is not runnable: {path}")
'''
new = '''    path = Path(safe_text(executable, max_len=4096)).expanduser().resolve()
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
'''
if old not in text:
    raise SystemExit("validator body not found")
text = text.replace(old, new, 1)
server_path.write_text(text, encoding="utf-8")

test_path = Path("tests/test_executable_policy.py")
tests = test_path.read_text(encoding="utf-8")
replacements = {
    '    monkeypatch.setenv("PATH", f"{launcher_dir}{os.pathsep}{os.environ.get(\'PATH\', \'\')}")\n': '    monkeypatch.setenv("PATH", f"{launcher_dir}{os.pathsep}{os.environ.get(\'PATH\', \'\')}")\n    monkeypatch.setenv("PANEL_ALLOWED_ROOTS", str(tmp_path))\n',
    '    monkeypatch.delenv("PANEL_ALLOW_ABSOLUTE_BINARIES", raising=False)\n\n    with pytest.raises(ValueError, match="not the active executable resolved from PATH"):\n': '    monkeypatch.setenv("PANEL_ALLOWED_ROOTS", str(tmp_path))\n    monkeypatch.delenv("PANEL_ALLOW_ABSOLUTE_BINARIES", raising=False)\n\n    with pytest.raises(ValueError, match="not the active executable resolved from PATH"):\n',
    '    executable.chmod(0o755)\n    monkeypatch.delenv("PANEL_ALLOW_ABSOLUTE_BINARIES", raising=False)\n\n    with pytest.raises(ValueError, match="Absolute executable paths are disabled"):\n': '    executable.chmod(0o755)\n    monkeypatch.setenv("PANEL_ALLOWED_ROOTS", str(tmp_path))\n    monkeypatch.delenv("PANEL_ALLOW_ABSOLUTE_BINARIES", raising=False)\n\n    with pytest.raises(ValueError, match="Absolute executable paths are disabled"):\n',
    '    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get(\'PATH\', \'\')}")\n    monkeypatch.delenv("PANEL_ALLOW_WORLD_WRITABLE_BINARIES", raising=False)\n': '    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get(\'PATH\', \'\')}")\n    monkeypatch.setenv("PANEL_ALLOWED_ROOTS", str(tmp_path))\n    monkeypatch.delenv("PANEL_ALLOW_WORLD_WRITABLE_BINARIES", raising=False)\n',
}
for old_test, new_test in replacements.items():
    if old_test not in tests:
        raise SystemExit(f"test patch target not found: {old_test!r}")
    tests = tests.replace(old_test, new_test, 1)

tests += '''

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
'''
test_path.write_text(tests, encoding="utf-8")
