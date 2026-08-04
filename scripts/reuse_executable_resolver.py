#!/usr/bin/env python3
"""Route PATH canonicalization through the validated resolver."""

from pathlib import Path

path = Path("server.py")
text = path.read_text(encoding="utf-8")
old = '''        discovered = shutil.which(executable_name)
        discovered_resolved = str(Path(discovered).resolve()) if discovered else ""
'''
new = '''        discovered = shutil.which(executable_name)
        discovered_resolved = resolve_executable(executable_name) if discovered else ""
'''
if old not in text:
    raise SystemExit("run_capture canonicalization block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
