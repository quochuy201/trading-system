import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from armed_plans import ArmedPlan, ArmedPlanStore


def _store(tmp_path):
    return ArmedPlanStore(path=tmp_path / "armed.json")


def test_arm_and_list(tmp_path):
    s = _store(tmp_path)
    p = ArmedPlan(symbol="NVDA", direction="long", structure="long_call",
                  trigger_price=220.0, invalidation_price=215.0,
                  cutoff_et="11:00", rationale="breakout")
    s.arm(p)
    active = s.list_active()
    assert len(active) == 1
    assert active[0].symbol == "NVDA"
    assert active[0].status == "armed"


def test_cancel_marks_inactive(tmp_path):
    s = _store(tmp_path)
    p = ArmedPlan(symbol="AMD", direction="long", structure="call_debit",
                  trigger_price=170.0, invalidation_price=166.0,
                  cutoff_et="11:00", rationale="squeeze break")
    s.arm(p)
    assert s.cancel(p.plan_id, reason="cutoff passed") is True
    assert s.list_active() == []
    assert s.get(p.plan_id).cancel_reason == "cutoff passed"


def test_fill_marks_filled(tmp_path):
    s = _store(tmp_path)
    p = ArmedPlan(symbol="MSFT", direction="long", structure="long_call",
                  trigger_price=400.0, invalidation_price=394.0,
                  cutoff_et="11:00", rationale="pullback hold")
    s.arm(p)
    s.fill(p.plan_id)
    assert s.list_active() == []
    persisted = ArmedPlanStore(path=s.path).get(p.plan_id)
    assert persisted.status == "filled"


def test_persists_across_instances(tmp_path):
    path = tmp_path / "armed.json"
    s1 = ArmedPlanStore(path=path)
    s1.arm(ArmedPlan(symbol="NVDA", direction="long", structure="long_call",
                     trigger_price=220.0, invalidation_price=215.0,
                     cutoff_et="11:00", rationale="x"))
    s2 = ArmedPlanStore(path=path)
    assert len(s2.list_active()) == 1


def test_get_missing_returns_none(tmp_path):
    s = _store(tmp_path)
    assert s.get("armed_nosuchid") is None


def test_set_status_missing_plan_returns_false(tmp_path):
    s = _store(tmp_path)
    assert s.fill("armed_nosuchid") is False
    assert s.cancel("armed_nosuchid") is False
