# User Guide & Operations Manual

## Overview
AI CLI Command Center is a provider-agnostic, local-first web interface that discovers installed AI CLI executables (e.g. OpenAI Codex, Claude Code, Gemini CLI, Qwen Code, Aider, Ollama), parses their `--help` outputs in real-time, and auto-generates structured, interactive command builders.

## Features
- **Zero Configuration Discovery**: Auto-detects installed CLI binaries from `$PATH` or custom paths.
- **Dynamic Help Parsing**: Parses flags, subcommands, positional parameters, options, defaults, and env overrides.
- **Durable SQLite Execution Engine**: Background process execution with streamed output over Server-Sent Events (SSE).
- **Hardened Security Controls**: Unsandboxed or destructive commands require strict text confirmation (`CONFIRM` / `I UNDERSTAND`). Redacts secret tokens from job execution logs.
- **v2.2 Interactive Tools**: Workspace File Browser, Git Diff Viewer, Presets & Favorites, Downloadable Job Logs, and Schema Correction Overlays.
- **v3.0 Workflow Platform**: Durable Workflow DAG Engine, Model Context Protocol (MCP) Server Manager, and Ephemeral Git Worktree Sandboxes.

## Quick Start
```bash
python3 server.py --host 127.0.0.1 --port 8080
```
Open `http://127.0.0.1:8080` in your web browser.

## Version 3.0 Platform Operations
- **Durable Workflows**: Create multi-step execution chains via `/api/workflows` to run sequential AI jobs and pipelines.
- **MCP Tool Manager**: Register Model Context Protocol (MCP) servers via `/api/mcp` to expose system tools to external AI agents.
- **Git Worktree Isolation**: Create isolated git worktrees per task via `/api/worktrees` to eliminate workspace collisions.

## Configuration Options via Environment Variables
- `PANEL_TOKEN`: Bearer token for HTTP API authentication.
- `PANEL_ALLOW_ANY_CWD`: Set to `1` to allow targeting any working directory.
- `PANEL_ALLOW_ABSOLUTE_BINARIES`: Set to `1` to probe arbitrary binary locations.
- `PANEL_DATABASE_PATH`: Custom path for SQLite job storage database.
