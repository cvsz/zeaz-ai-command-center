#!/usr/bin/env python3
"""Apply the reviewed provider executable policy patch to server.py."""

from pathlib import Path

path = Path("server.py")
text = path.read_text(encoding="utf-8")

marker = "\ndef resolve_executable(executable: Any) -> str:\n"
helper = '''
def _validate_runnable_executable(executable: Any) -> str:
    """Return a canonical executable path after runtime safety checks.

    Absolute-path authorization is intentionally enforced by the caller that
    accepts external configuration. Internal callers may receive the canonical
    path produced by ``resolve_executable`` and must not reject it a second time.
    """
    path = Path(safe_text(executable, max_len=4096)).expanduser().resolve()
    if not path.is_absolute() or not path.exists() or not path.is_file():
        raise ValueError(f"Executable is not runnable: {path}")
    if sys.platform != "win32" and not os.access(path, os.X_OK):
        raise ValueError(f"Executable is not runnable: {path}")
    metadata = path.stat()
    if metadata.st_mode & stat.S_IWOTH and os.getenv("PANEL_ALLOW_WORLD_WRITABLE_BINARIES", "0") != "1":
        raise ValueError("Refusing world-writable provider executable")
    return str(path)

'''
if helper.strip() not in text:
    if marker not in text:
        raise SystemExit("resolve_executable marker not found")
    text = text.replace(marker, "\n" + helper + "def resolve_executable(executable: Any) -> str:\n", 1)

old_explicit = '''        path = Path(raw).expanduser().resolve()
        if not path.is_absolute() or not path.exists() or not path.is_file() or (sys.platform != "win32" and not os.access(path, os.X_OK)):
            raise ValueError(f"Executable is not runnable: {path}")
        return str(path)
'''
new_explicit = '''        return _validate_runnable_executable(raw)
'''
if old_explicit not in text:
    raise SystemExit("explicit executable validation block not found")
text = text.replace(old_explicit, new_explicit, 1)

old_path_return = '''    return str(Path(resolved).resolve())


def run_capture'''
new_path_return = '''    return _validate_runnable_executable(resolved)


def run_capture'''
if old_path_return not in text:
    raise SystemExit("PATH executable return block not found")
text = text.replace(old_path_return, new_path_return, 1)

old_capture = '''    executable = argv[0]
    if os.path.isabs(executable) and os.getenv("PANEL_ALLOW_ABSOLUTE_BINARIES", "0") != "1":
        raise ValueError(f"Absolute executable path rejected: {executable}")
    env = os.environ.copy()
'''
new_capture = '''    executable = argv[0]
    if os.path.isabs(executable):
        resolved_executable = _validate_runnable_executable(executable)
        discovered = shutil.which(Path(executable).name)
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

path.write_text(text, encoding="utf-8")
