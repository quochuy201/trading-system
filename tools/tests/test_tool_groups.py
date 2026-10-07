"""TRADING_TOOL_GROUPS gating — each worker profile sees only its role's tools."""
import json
import os
import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).parent.parent

SNIPPET = (
    "import json, server; server._apply_tool_groups(); "
    "print(json.dumps(sorted(server.mcp._tool_manager._tools)))"
)


# Registered tools vs TOOL_GROUPS, before any gating. UNGROUPED_BY_DESIGN is
# reported as null when server.py does not define it, so a missing declaration
# fails the assertion with the sets visible instead of a subprocess traceback.
GROUPING_SNIPPET = (
    "import json, server; print(json.dumps({"
    "'registered': sorted(server.mcp._tool_manager._tools), "
    "'groups': {k: sorted(v) for k, v in server.TOOL_GROUPS.items()}, "
    "'ungrouped_by_design': sorted(server.UNGROUPED_BY_DESIGN) "
    "if hasattr(server, 'UNGROUPED_BY_DESIGN') else None}))"
)


def _tools_for(groups):
    env = {**os.environ, "TRADING_TOOL_GROUPS": groups}
    out = subprocess.run([sys.executable, "-c", SNIPPET], cwd=TOOLS_DIR,
                         env=env, capture_output=True, text=True, check=True)
    return set(json.loads(out.stdout.strip().splitlines()[-1]))


def _grouping():
    """Return the tool-group wiring of an ungated server.

    Keys: ``registered`` (sorted tool names), ``groups`` (group name -> sorted
    tool names, i.e. TOOL_GROUPS), ``ungrouped_by_design`` (sorted names, or
    ``None`` when server.py has no such name).
    """
    env = {**os.environ, "TRADING_TOOL_GROUPS": ""}
    out = subprocess.run([sys.executable, "-c", GROUPING_SNIPPET], cwd=TOOLS_DIR,
                         env=env, capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_unset_exposes_everything():
    assert len(_tools_for("")) == 63


def test_reporting_tools_scoped_to_role():
    assert "notify_analysis" in _tools_for("research")
    assert "notify_buy" in _tools_for("trader")
    assert "notify_sell" in _tools_for("monitor")
    # each role gets only its own reporting tool, not the others
    assert "notify_buy" not in _tools_for("research")
    assert "notify_sell" not in _tools_for("trader")
    assert "notify_analysis" not in _tools_for("monitor")


def test_research_has_scan_but_no_orders():
    tools = _tools_for("research")
    assert "scan_swing_candidates" in tools and "get_news" in tools
    assert "place_order" not in tools and "activate_kill_switch" not in tools


def test_trader_has_orders_but_no_scan():
    tools = _tools_for("trader")
    assert "place_order" in tools and "save_trade_plan" in tools
    assert "scan_swing_candidates" not in tools


def test_monitor_can_exit_but_not_plan():
    tools = _tools_for("monitor")
    assert "place_order" in tools and "get_positions" in tools
    assert "save_trade_plan" not in tools and "scan_for_candidates" not in tools


def test_risk_owns_kill_switch():
    tools = _tools_for("risk")
    assert {"activate_kill_switch", "clear_kill_switch"} <= tools
    assert "place_order" not in tools


def test_eod_has_funnel():
    tools = _tools_for("eod")
    assert "get_daily_funnel" in tools and "generate_performance_report" in tools
    assert "get_daily_funnel" not in _tools_for("trader")


def test_common_always_present():
    for g in ("research", "trader", "monitor", "risk", "eod"):
        assert {"check_kill_switch", "log_decision"} <= _tools_for(g)


# A tool in no group is unreachable by every role-scoped profile. That hid five
# options tools for 34 sessions, so "in no group" must be a declared decision.

def test_every_registered_tool_is_grouped_or_ungrouped_by_design():
    g = _grouping()
    grouped = set().union(*g["groups"].values())
    assert sorted(set(g["registered"]) - grouped) == g["ungrouped_by_design"]


def test_ungrouped_by_design_is_only_capture_iv_universe():
    # cron imports capture_iv_universe directly; no agent calls it
    assert _grouping()["ungrouped_by_design"] == ["capture_iv_universe"]


def test_reset_tuning_config_is_in_eod_group():
    # beside its siblings generate_tuning_config / get_tuning_config
    assert "reset_tuning_config" in _grouping()["groups"]["eod"]
