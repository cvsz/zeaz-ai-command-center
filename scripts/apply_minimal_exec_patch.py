#!/usr/bin/env python3
"""Replace executable handling with a minimal canonical PATH comparison."""

from pathlib import Path

server_path = Path("server.py")
text = server_path.read_text(encoding="utf-8")
start = text.index("\ndef allowed_executable_roots() -> list[Path]:\n")
end = text.index("\ndef fingerprint_executable(path: str) -> dict[str, Any]:\n", start)
replacement = '''
def resolve_executable(executable: Any) -> str:
    raw = safe_text(executable, max_len=4096).strip()
    if not raw:
        raise ValueError("Executable is required")
    if "/" in raw or "\\\\" in raw:
        if os.getenv("PANEL_ALLOW_ABSOLUTE_BINARIES", "0") != "1":
            raise ValueError("Absolute executable paths are disabled; set PANEL_ALLOW_ABSOLUTE_BINARIES=1 to enable")
        path = Path(raw).expanduser().resolve()
        if not path.is_absolute() or not path.exists() or not path.is_file() or (sys.platform != "win32" and not os.access(path, os.X_OK)):
            raise ValueError(f"Executable is not runnable: {path}")
        return str(path)
    if not BINARY_RE.fullmatch(raw):
        raise ValueError("Executable name contains unsupported characters")
    resolved = shutil.which(raw)
    if not resolved:
        raise ValueError(f"Executable not found in PATH: {raw}")
    return str(Path(resolved).resolve())


def run_capture(argv: list[str], *, cwd: Path | str | None = None, timeout: int = HELP_TIMEOUT_SECONDS) -> tuple[int, str]:
    if not argv:
        raise ValueError("Empty command")
    executable = argv[0]
    if os.path.isabs(executable):
        executable_name = os.path.basename(executable)
        if not BINARY_RE.fullmatch(executable_name):
            raise ValueError(f"Absolute executable path rejected: {executable}")
        discovered_resolved = resolve_executable(executable_name)
        if executable == discovered_resolved:
            resolved_executable = discovered_resolved
        elif os.getenv("PANEL_ALLOW_ABSOLUTE_BINARIES", "0") == "1":
            resolved_executable = resolve_executable(executable)
        else:
            raise ValueError(
                f"Absolute executable path rejected: {executable}; "
                "it is not the active executable resolved from PATH"
            )
    else:
        resolved_executable = resolve_executable(executable)
    argv = [resolved_executable, *argv[1:]]
    env = os.environ.copy()
    env.setdefault("TERM", "dumb")
    env.setdefault("NO_COLOR", "1")
    env.setdefault("CLICOLOR", "0")
    result = subprocess.run(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
        env=env,
        shell=False,
    )
    output = result.stdout[:MAX_HELP_BYTES].decode("utf-8", errors="replace")
    if len(result.stdout) > MAX_HELP_BYTES:
        output += "\\n[command-center] Help output truncated."
    return result.returncode, output

'''
server_path.write_text(text[:start] + "\n" + replacement + text[end:], encoding="utf-8")

Path("tests/test_executable_policy.py").write_text(
    '''"""Regression tests for canonical PATH-resolved provider execution."""

import os
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
    monkeypatch.delenv("PANEL_ALLOW_ABSOLUTE_BINARIES", raising=False)

    resolved = resolve_executable("codex")
    assert resolved == str(target.resolve())

    code, output = run_capture([resolved, "--version"])
    assert code == 0
    assert output.strip() == "codex-test"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX executable bit required")
def test_run_capture_rejects_absolute_path_not_resolved_from_path(tmp_path: Path, monkeypatch):
    executable = tmp_path / "rogue-provider"
    executable.write_text("#!/usr/bin/env python3\\nprint('unexpected')\\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.delenv("PANEL_ALLOW_ABSOLUTE_BINARIES", raising=False)

    with pytest.raises(ValueError, match="not the active executable resolved from PATH"):
        run_capture([str(executable)])


def test_resolve_explicit_absolute_path_still_requires_opt_in(tmp_path: Path, monkeypatch):
    executable = tmp_path / "custom-provider"
    executable.write_text("provider", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.delenv("PANEL_ALLOW_ABSOLUTE_BINARIES", raising=False)

    with pytest.raises(ValueError, match="Absolute executable paths are disabled"):
        resolve_executable(str(executable))
''',
    encoding="utf-8",
)
