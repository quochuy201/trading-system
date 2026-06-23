#!/usr/bin/env bash
# MCP launcher for Hermes profiles. TRADING_TOOL_GROUPS (set per profile via
# `hermes mcp add --env`) gates which tools server.py registers.
cd "$(dirname "$0")"
# Exec the prebuilt venv Python directly to keep the MCP stdio channel clean and
# fast — `uv run` can re-resolve/emit output and add latency that breaks the
# stdio handshake (gateway client timed out with "Connection closed"). Fall back
# to `uv run` only if the venv is missing.
if [ -x .venv/bin/python ]; then
  exec .venv/bin/python server.py
else
  exec uv run python server.py
fi
