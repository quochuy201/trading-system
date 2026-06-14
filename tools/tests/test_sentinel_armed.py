import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import monitor_sentinel
from armed_plans import ArmedPlan, ArmedPlanStore


def test_armed_trigger_fires_when_price_reaches_trigger(tmp_path, monkeypatch):
    store = ArmedPlanStore(path=tmp_path / "armed.json")
    store.arm(ArmedPlan(symbol="NVDA", direction="long", structure="long_call",
                        trigger_price=220.0, invalidation_price=215.0,
                        cutoff_et="23:59", rationale="x"))
    monkeypatch.setattr(monitor_sentinel, "_armed_store", lambda: store)
    monkeypatch.setattr(monitor_sentinel, "_underlying_price", lambda s: 221.0)

    reasons = monitor_sentinel._armed_plan_triggers()
    assert any("NVDA" in r and "entry_confirm" in r for r in reasons)


def test_armed_no_trigger_below_trigger_price(tmp_path, monkeypatch):
    store = ArmedPlanStore(path=tmp_path / "armed.json")
    store.arm(ArmedPlan(symbol="NVDA", direction="long", structure="long_call",
                        trigger_price=220.0, invalidation_price=215.0,
                        cutoff_et="23:59", rationale="x"))
    monkeypatch.setattr(monitor_sentinel, "_armed_store", lambda: store)
    monkeypatch.setattr(monitor_sentinel, "_underlying_price", lambda s: 218.0)

    assert monitor_sentinel._armed_plan_triggers() == []


def test_armed_invalidation_cancels_plan(tmp_path, monkeypatch):
    store = ArmedPlanStore(path=tmp_path / "armed.json")
    store.arm(ArmedPlan(symbol="NVDA", direction="long", structure="long_call",
                        trigger_price=220.0, invalidation_price=215.0,
                        cutoff_et="23:59", rationale="x"))
    monkeypatch.setattr(monitor_sentinel, "_armed_store", lambda: store)
    monkeypatch.setattr(monitor_sentinel, "_underlying_price", lambda s: 214.0)

    reasons = monitor_sentinel._armed_plan_triggers()
    assert reasons == []                      # invalidation does not wake the LLM
    assert store.list_active() == []          # it cancels the plan


def test_signature_distinguishes_two_armed_plans_same_symbol():
    r1 = "NVDA:entry_confirm@221.00:armed_aaa111"
    r2 = "NVDA:entry_confirm@221.00:armed_bbb222"
    assert monitor_sentinel._signature(r1) != monitor_sentinel._signature(r2)


def test_signature_unchanged_for_non_armed_reasons():
    # existing behavior must be preserved
    assert monitor_sentinel._signature("kill_switch_active") == "kill"
    assert monitor_sentinel._signature("NVDA:near_stop_0.83pct") == "NVDA:near"
