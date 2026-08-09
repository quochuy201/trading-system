"""Negative tests for `setup/deploy/verify.sh`.

A verifier that has never been observed failing is not evidence — it is the
thing that let "everything looks fine" stand for 34 sessions while five options
tools were unreachable. So every check gets a test that deliberately breaks its
condition and asserts the script FAILS, naming the right reason.

This caught a real one during development: checks 4 and 5 crashed and reported
`ok`, because empty output was read as "no problems found".

Isolation: every test builds a throwaway profile under `tmp_path` and passes it
via `--hermes-home`. Nothing here reads or writes the real `~/.hermes`.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY = REPO_ROOT / "setup" / "deploy" / "verify.sh"
LAUNCHER = REPO_ROOT / "tools" / "run_mcp.sh"


def _head_sha() -> str:
    out = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


def build_profile(home: Path, registration_env: dict[str, str] | None = None,
                  command: str | None = None) -> Path:
    """Build a profile that `verify.sh` should pass.

    Args:
        home: Fake HERMES_HOME root; created if absent.
        registration_env: Extra env recorded on the MCP registration, e.g.
            ``{"TRADING_TOOL_GROUPS": "eod"}`` to narrow what the agent reaches.
        command: Override the registered server command; defaults to the repo's
            real launcher so checks 1-3 exercise production wiring.

    Returns:
        Path to the profile directory.
    """
    profile = home / "profiles" / "trading"
    (profile / "scripts").mkdir(parents=True, exist_ok=True)
    (profile / "cron").mkdir(parents=True, exist_ok=True)

    entry: dict[str, object] = {"command": command or str(LAUNCHER)}
    if registration_env:
        entry["env"] = dict(registration_env)
    (profile / "config.yaml").write_text(
        json.dumps({"mcp_servers": {"trading-tools": entry}})  # JSON is valid YAML
    )

    shutil.copytree(REPO_ROOT / "skills", profile / "skills", dirs_exist_ok=True)
    shutil.copy(REPO_ROOT / "OPERATING_MANUAL.md", profile / "OPERATING_MANUAL.md")
    (profile / "PROVENANCE.md").write_text(f"- **Git SHA:** {_head_sha()}\n")

    script = profile / "scripts" / "trading-data-refresh.sh"
    script.write_text("#!/usr/bin/env bash\nexit 0\n")
    script.chmod(0o755)
    (profile / "cron" / "jobs.json").write_text(json.dumps(
        {"jobs": [{"name": "trading-data-refresh", "script": script.name}]}
    ))

    for board in ("equity", "options"):
        board_db = home / "kanban" / "boards" / board / "kanban.db"
        board_db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(board_db) as conn:
            conn.execute("create table if not exists tasks (id text primary key)")

    return profile


def run_verify(home: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(VERIFY), "hermes", "--profile", "trading",
         "--hermes-home", str(home), "--repo-root", str(REPO_ROOT)],
        capture_output=True, text=True,
    )


# ── the positive case ───────────────────────────────────────────────────────

def test_intact_profile_passes(tmp_path):
    build_profile(tmp_path)
    result = run_verify(tmp_path)
    assert result.returncode == 0, result.stdout
    assert "verification passed" in result.stdout


# ── one negative per check ──────────────────────────────────────────────────

def test_unspawnable_mcp_command_fails(tmp_path):
    """Check 1: registered command that cannot start."""
    build_profile(tmp_path, command=str(tmp_path / "does-not-exist.sh"))
    result = run_verify(tmp_path)
    assert result.returncode != 0
    assert "does not exist" in result.stdout


def test_unregistered_mcp_server_fails(tmp_path):
    """Check 1: no registration at all — the agent would have no trading tools."""
    profile = build_profile(tmp_path)
    (profile / "config.yaml").write_text(json.dumps({"mcp_servers": {}}))
    result = run_verify(tmp_path)
    assert result.returncode != 0
    assert "no MCP server" in result.stdout


def test_narrowed_tool_groups_fails(tmp_path):
    """Checks 3/4: gating the registration hides tools the skills promise."""
    build_profile(tmp_path, registration_env={"TRADING_TOOL_GROUPS": "eod"})
    result = run_verify(tmp_path)
    assert result.returncode != 0
    assert "options tools unreachable" in result.stdout
    assert "declares unreachable tools" in result.stdout


def test_missing_skill_fails(tmp_path):
    """Check 4: a repo skill absent from the deployed profile."""
    profile = build_profile(tmp_path)
    shutil.rmtree(profile / "skills" / "trader")
    result = run_verify(tmp_path)
    assert result.returncode != 0
    assert "skill missing from profile: trader" in result.stdout


def test_missing_cron_store_fails(tmp_path):
    """Check 5: nothing scheduled at all."""
    profile = build_profile(tmp_path)
    (profile / "cron" / "jobs.json").unlink()
    result = run_verify(tmp_path)
    assert result.returncode != 0
    assert "nothing is scheduled" in result.stdout


def test_cron_script_not_found_fails(tmp_path):
    """Check 5: the 06-23 failure — a cron pointing at a script that isn't there."""
    profile = build_profile(tmp_path)
    (profile / "scripts" / "trading-data-refresh.sh").unlink()
    result = run_verify(tmp_path)
    assert result.returncode != 0
    assert "script not found" in result.stdout


def test_board_without_tasks_table_fails(tmp_path):
    """Check 6: a board file that exists but is empty — the dispatcher no-ops."""
    build_profile(tmp_path)
    board_db = tmp_path / "kanban" / "boards" / "equity" / "kanban.db"
    board_db.unlink()
    board_db.touch()
    result = run_verify(tmp_path)
    assert result.returncode != 0
    assert "no tasks table" in result.stdout


def test_missing_board_fails(tmp_path):
    """Check 6: board never created."""
    build_profile(tmp_path)
    shutil.rmtree(tmp_path / "kanban" / "boards" / "options")
    result = run_verify(tmp_path)
    assert result.returncode != 0
    assert "board 'options' missing" in result.stdout


def test_missing_operating_manual_fails(tmp_path):
    """Check 7: the agent would run with no risk constitution."""
    profile = build_profile(tmp_path)
    (profile / "OPERATING_MANUAL.md").unlink()
    result = run_verify(tmp_path)
    assert result.returncode != 0
    assert "risk constitution" in result.stdout


def test_absent_provenance_fails(tmp_path):
    """Check 8: cannot tell which commit the runtime came from."""
    profile = build_profile(tmp_path)
    (profile / "PROVENANCE.md").unlink()
    result = run_verify(tmp_path)
    assert result.returncode != 0
    assert "no provenance stamp" in result.stdout


def test_stale_provenance_fails(tmp_path):
    """Check 8: runtime deployed from an older commit than the repo."""
    profile = build_profile(tmp_path)
    (profile / "PROVENANCE.md").write_text("- **Git SHA:** " + "0" * 40 + "\n")
    result = run_verify(tmp_path)
    assert result.returncode != 0
    assert "runtime is stale" in result.stdout


# ── check 9 warns, never fails (D-DEP2) ─────────────────────────────────────

def test_runtime_only_skill_warns_without_failing(tmp_path):
    """Deleting `options-trader` would remove the only running options logic."""
    profile = build_profile(tmp_path)
    runtime_only = profile / "skills" / "options-trader"
    runtime_only.mkdir()
    (runtime_only / "SKILL.md").write_text(textwrap.dedent("""\
        ---
        name: options-trader
        requires_tools: [get_options_chain]
        ---
    """))
    result = run_verify(tmp_path)
    assert result.returncode == 0, result.stdout
    assert "runtime-only skill 'options-trader'" in result.stdout
    assert runtime_only.exists(), "verify.sh must never delete a runtime-only skill"
