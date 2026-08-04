#!/usr/bin/env python3
"""Configure the existing custom-provider test with an explicit trusted root."""

from pathlib import Path

path = Path("tests/test_server.py")
text = path.read_text(encoding="utf-8")
old = '''    monkeypatch.setenv("PANEL_ALLOW_ABSOLUTE_BINARIES", "1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
'''
new = '''    monkeypatch.setenv("PANEL_ALLOW_ABSOLUTE_BINARIES", "1")
    monkeypatch.setenv("PANEL_ALLOWED_ROOTS", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
'''
if old not in text:
    raise SystemExit("custom provider fixture target not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
