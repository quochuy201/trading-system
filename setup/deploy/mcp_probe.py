#!/usr/bin/env python3
"""Enumerate the MCP tools a deployed profile can actually reach.

Reachability, not presence. The tools existing in ``server.py`` proves nothing —
five options tools sat in the repo, registered, and unusable by the agent for 34
sessions. So this spawns the server command **exactly as the profile registered
it** and completes a real MCP handshake, which exercises the launcher script, the
venv, and any ``TRADING_TOOL_GROUPS`` gating carried on the registration.

Deliberately does not shell out to the ``hermes`` CLI: it has no
tool-enumeration subcommand, and a verifier must still work while the CLI is
mid-upgrade.

Usage:
    mcp_probe.py --config <profile config.yaml> [--server trading-tools]
    mcp_probe.py --command <path> [--arg X ...] [--env K=V ...]

Output (stdout, always JSON):
    {"ok": true,  "server": "trading-tools", "tools": ["get_account", ...]}
    {"ok": false, "server": "trading-tools", "error": "..."}

Exit code is 0 when the handshake succeeded, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import selectors
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "2024-11-05"
DEFAULT_TIMEOUT = 60.0

logger = logging.getLogger(__name__)


class ProbeError(Exception):
    """Handshake could not be completed."""


class _Connection:
    """A line-delimited JSON-RPC conversation with an MCP stdio server."""

    def __init__(self, proc: subprocess.Popen, deadline: float):
        self._proc = proc
        self._deadline = deadline
        self._selector = selectors.DefaultSelector()
        self._selector.register(proc.stdout, selectors.EVENT_READ)
        self._buffer = ""

    def send(self, message: dict[str, Any]) -> None:
        self._proc.stdin.write((json.dumps(message) + "\n").encode())
        self._proc.stdin.flush()

    def await_response(self, request_id: int) -> dict[str, Any]:
        """Read until the response with ``request_id`` arrives.

        Notifications and log messages are skipped — a server is free to emit
        them before answering.
        """
        while True:
            message = self._read_message()
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise ProbeError(f"server returned error: {message['error']}")
            return message.get("result") or {}

    def _read_message(self) -> dict[str, Any]:
        while True:
            line, _, rest = self._buffer.partition("\n")
            if _:
                self._buffer = rest
                line = line.strip()
                if not line:
                    continue
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    # Not every line on stdio is protocol traffic; skip noise.
                    continue
            self._buffer += self._read_chunk()

    def _read_chunk(self) -> str:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise ProbeError("timed out waiting for the server to respond")
        if self._proc.poll() is not None:
            raise ProbeError(
                f"server exited with code {self._proc.returncode} before responding"
            )
        if not self._selector.select(timeout=min(remaining, 1.0)):
            return ""
        # os.read on the raw fd, not stdout.read(n): a buffered read blocks
        # until it has n bytes, which outlives the deadline and hangs the probe.
        chunk = os.read(self._proc.stdout.fileno(), 65536)
        if not chunk:
            raise ProbeError("server closed its output stream before responding")
        return chunk.decode("utf-8", errors="replace")


def list_tools(command: str, args: list[str], env: dict[str, str],
               timeout: float = DEFAULT_TIMEOUT) -> list[str]:
    """Return the tool names the server exposes over a real MCP handshake."""
    if not Path(command).exists():
        raise ProbeError(f"registered command does not exist: {command}")

    child_env = {**os.environ, **env}
    logger.info("probe spawning command=%s args=%s env_keys=%s",
                command, args, sorted(env))
    try:
        proc = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=0, env=child_env,
        )
    except OSError as exc:
        raise ProbeError(f"could not spawn {command}: {exc}") from exc

    try:
        conn = _Connection(proc, deadline=time.monotonic() + timeout)
        conn.send({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "deployment-verify", "version": "1"},
            },
        })
        conn.await_response(1)
        conn.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        tools: list[str] = []
        cursor: str | None = None
        request_id = 1
        while True:
            request_id += 1
            params = {"cursor": cursor} if cursor else {}
            conn.send({"jsonrpc": "2.0", "id": request_id,
                       "method": "tools/list", "params": params})
            result = conn.await_response(request_id)
            tools.extend(t["name"] for t in result.get("tools", []) if "name" in t)
            cursor = result.get("nextCursor")
            if not cursor:
                logger.info("probe reached %d tools via %s", len(tools), command)
                return sorted(tools)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def registration_from_config(config_path: Path, server: str) -> tuple[str, list[str], dict[str, str]]:
    """Read a server's registration out of a Hermes ``config.yaml``.

    Hermes stores stdio servers under ``mcp_servers: {<name>: {command, args, env}}``.
    """
    import yaml

    if not config_path.exists():
        raise ProbeError(f"profile config not found: {config_path}")
    config = yaml.safe_load(config_path.read_text()) or {}
    servers = config.get("mcp_servers") or {}
    if not isinstance(servers, dict) or server not in servers:
        raise ProbeError(
            f"no MCP server '{server}' registered in {config_path} "
            "— the agent has no trading tools"
        )
    entry = servers[server] or {}
    if entry.get("enabled") is False:
        raise ProbeError(f"MCP server '{server}' is registered but disabled")
    command = entry.get("command")
    if not command:
        raise ProbeError(
            f"MCP server '{server}' has no stdio command (remote servers unsupported)"
        )
    env = {str(k): str(v) for k, v in (entry.get("env") or {}).items()}
    return command, [str(a) for a in (entry.get("args") or [])], env


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Hermes profile config.yaml")
    parser.add_argument("--server", default="trading-tools")
    parser.add_argument("--command", help="probe this command instead of a registration")
    parser.add_argument("--arg", action="append", default=[], dest="args")
    parser.add_argument("--env", action="append", default=[],
                        help="KEY=VALUE passed to the server")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    opts = parser.parse_args()

    try:
        if opts.command:
            env = dict(pair.split("=", 1) for pair in opts.env)
            command, args = opts.command, list(opts.args)
        elif opts.config:
            command, args, env = registration_from_config(opts.config, opts.server)
        else:
            raise ProbeError("one of --config or --command is required")
        tools = list_tools(command, args, env, timeout=opts.timeout)
    except ProbeError as exc:
        json.dump({"ok": False, "server": opts.server, "error": str(exc)}, sys.stdout)
        print()
        return 1

    json.dump({"ok": True, "server": opts.server, "tools": tools}, sys.stdout)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
