#!/usr/bin/env bash
# MCP launcher for Hermes profiles. TRADING_TOOL_GROUPS (set per profile via
# `hermes mcp add --env`) gates which tools server.py registers.
cd "$(dirname "$0")" && exec uv run python server.py
