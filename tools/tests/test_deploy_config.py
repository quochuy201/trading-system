"""Deploy config carries no dead keys (change: dead-config-cleanup).

Why this file exists: CLAUDE.md RULE 3. `setup/deploy/profile.yaml` carried an
`mcp_tools:` block, and `runs/equity.yaml` / `runs/options.yaml` carried
`risk_budget:` blocks. Nothing reads either. Config that looks authoritative but
is ignored is a trap: a session edits it, believes the system changed, and
nothing did. The `risk_budget` values also disagreed with `config.yaml`, making
a silent fourth risk-limit source.

These tests keep those keys gone, and keep what really is read: every other
profile key, and each run's `board` (read by `verify.sh` check 6).
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_DIR = REPO_ROOT / "setup" / "deploy"
PROFILE = DEPLOY_DIR / "profile.yaml"
RUNS_DIR = DEPLOY_DIR / "runs"


def _load(path: Path) -> dict:
    """Parse one YAML file; an empty file loads as ``{}``."""
    return yaml.safe_load(path.read_text()) or {}


def _run_configs() -> dict[str, dict]:
    """Load every run config, keyed by file stem (``"equity"``, ``"options"``).

    Files starting with ``_`` (e.g. ``_shared.yaml``) are skipped — the same
    selection `verify.sh` check 6 makes when it collects board names.
    """
    return {path.stem: _load(path)
            for path in sorted(RUNS_DIR.glob("*.yaml"))
            if not path.name.startswith("_")}


def test_profile_has_no_mcp_tools_and_every_other_key_unchanged():
    """Example 2: `mcp_tools` is gone; every other key keeps its value."""
    assert _load(PROFILE) == {
        "model": "deepseek-ai/deepseek-v4-flash",
        "fallback_model": "deepseek-ai/deepseek-v3",
        "discord": {"enabled": True},
        "api_server": {"enabled": True, "api_server_key": ""},
        "timezone": "America/Los_Angeles",
        "max_concurrent_agents": 4,
        "default_retry_attempts": 3,
    }


def test_no_run_config_has_risk_budget():
    """Example 3: no run config carries a `risk_budget` key."""
    with_risk_budget = [name for name, cfg in _run_configs().items()
                        if "risk_budget" in cfg]
    assert with_risk_budget == []


def test_every_run_config_still_declares_its_board():
    """Example 3: `board` survives, so verify.sh check 6 still finds both."""
    boards = {name: cfg.get("board") for name, cfg in _run_configs().items()}
    assert boards == {"equity": "equity", "options": "options"}
