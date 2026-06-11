"""Mechanics tests for the param-sweep harness (strategy params live in configs)."""
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "param_sweep", Path(__file__).parent.parent / "scripts" / "param_sweep.py")
ps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ps)

CFG = {
    "m_on": True, "m_roc50_min": 10.0, "m_rs10_min": 2.0,
    "m_pullback_rsi3_max": 50.0, "m_pullback_atr_dist": 1.0,
    "m_chase_atr_mult": 2.5, "m_atr_pct_min": 1.5, "m_atr_pct_max": 6.0,
    "m_ext_spy_max": 3.0,
    "r_on": True, "r_rsi3_max": 10.0, "r_drop3_min": 6.0, "r_atr_pct_min": 2.5,
    "r_target_low_floor": 2.5, "r_target_low_atr": 0.5,
    "r_target_med_floor": 4.0, "r_target_med_atr": 1.0,
    "r_target_high_floor": 5.0, "r_target_high_atr": 1.5,
}

METRIC = {  # passes M gates, fails R (rsi3 too high)
    "symbol": "X", "price": 100.0, "dollar_vol20": 60e6, "atr10": 3.0,
    "atr10_pct": 3.0, "sma25": 98.0, "sma50": 95.0, "sma150": 90.0,
    "roc50": 15.0, "rs_10d": 3.0, "drop_3d": 1.0, "rsi3": 40.0,
    "pct_from_10d_high": -3.0, "mom_5d": 1.0,
}
REG = {"tr_atr": 1.0, "vs_sma50": 1.0, "trend": "up"}


def test_r_target_tiers():
    # low vol: max(2.5, 0.5*atr_pct); med: max(4, 1*); high: max(5, 1.5*)
    assert ps.r_target_pct(0.5, 4.0, CFG) == 2.5
    assert ps.r_target_pct(0.5, 8.0, CFG) == 4.0
    assert ps.r_target_pct(1.0, 6.0, CFG) == 6.0
    assert ps.r_target_pct(1.5, 2.0, CFG) == 5.0


def test_gates_m_pass_r_fail():
    assert ps.gates(METRIC, CFG, REG) == {"M"}


def test_gates_m_blocked_in_down_trend():
    assert ps.gates(METRIC, CFG, {**REG, "trend": "down"}) == set()


def test_gates_r_washout():
    m = {**METRIC, "rsi3": 5.0, "drop_3d": 7.0, "roc50": -5.0}
    eng = ps.gates(m, CFG, REG)
    assert "R" in eng and "M" not in eng  # roc50 fails M


def test_gates_extension_throttle():
    assert ps.gates(METRIC, CFG, {**REG, "vs_sma50": 3.5}) == set()
