# tools/tests/test_registry.py
"""Guard: every strategy id in config.yaml resolves to an existing SOP directory."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
CONFIG = ROOT / "config.yaml"


def _all_strategy_entries() -> list[dict]:
    cfg = yaml.safe_load(CONFIG.read_text())
    strat = cfg.get("strategies", {})
    return list(strat.get("enabled", [])) + list(strat.get("disabled", []))


def test_strategies_block_present():
    cfg = yaml.safe_load(CONFIG.read_text())
    assert "strategies" in cfg, "config.yaml missing strategies: registry"
    assert "enabled" in cfg["strategies"]


def test_every_strategy_id_resolves_to_sop_dir():
    for entry in _all_strategy_entries():
        sid = entry["id"]
        sop_dir = ROOT / "sops" / sid
        assert sop_dir.is_dir(), f"strategy id '{sid}' has no sops/{sid}/ directory"


def test_every_enabled_strategy_has_market_and_sop():
    cfg = yaml.safe_load(CONFIG.read_text())
    for entry in cfg["strategies"]["enabled"]:
        assert entry.get("market"), f"{entry} missing 'market'"
        assert entry.get("sop"), f"{entry} missing 'sop'"
