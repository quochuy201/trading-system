# tools/tests/test_week_runner.py
"""Mechanics tests for scripts/week_runner.py (fill rules, stop ordering,
intrabar targets, session time stops). No strategy logic tested here —
parameters come from plans, as in production use."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

_spec = importlib.util.spec_from_file_location(
    "week_runner", Path(__file__).parent.parent / "scripts" / "week_runner.py")
wr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wr)


class TestTryFill:
    def _plan(self, **kw):
        base = {"entry_type": "limit", "limit_price": 100.0,
                "gap_up_max_pct": 5.0, "gap_down_max_pct": 3.0}
        base.update(kw)
        return base

    def test_limit_fills_at_open_when_open_below_limit(self):
        bars = [("t1", 98.0, 101.0, 97.0, 100.0, 1)]
        px, ts, skip = wr._try_fill(self._plan(), bars, prev_close=103.0)
        assert px == 98.0 and skip is None

    def test_limit_fills_at_limit_when_low_touches(self):
        bars = [("t1", 101.0, 102.0, 99.5, 101.5, 1)]
        px, ts, skip = wr._try_fill(self._plan(), bars, prev_close=103.0)
        assert px == 100.0 and skip is None

    def test_limit_no_fill_when_low_above_limit(self):
        bars = [("t1", 101.0, 102.0, 100.5, 101.5, 1)]
        px, ts, skip = wr._try_fill(self._plan(), bars, prev_close=103.0)
        assert px is None and skip == "limit_not_reached"

    def test_market_open_gap_up_skipped(self):
        bars = [("t1", 106.0, 107.0, 105.0, 106.5, 1)]
        plan = self._plan(entry_type="market_open")
        px, ts, skip = wr._try_fill(plan, bars, prev_close=100.0)
        assert px is None and "gap_up" in skip

    def test_market_open_gap_down_skipped(self):
        bars = [("t1", 96.5, 97.0, 96.0, 96.8, 1)]
        plan = self._plan(entry_type="market_open")
        px, ts, skip = wr._try_fill(plan, bars, prev_close=100.0)
        assert px is None and "gap_down" in skip

    def test_market_open_fills_with_slippage(self):
        bars = [("t1", 101.0, 102.0, 100.0, 101.5, 1)]
        plan = self._plan(entry_type="market_open")
        px, ts, skip = wr._try_fill(plan, bars, prev_close=100.0)
        assert px == pytest.approx(101.0 * 1.0005)


class TestDayLoopMechanics:
    """End-to-end run-day mechanics against a temp DB + temp state."""

    def setup_method(self):
        import sqlite3, tempfile, os
        self.tmp = tempfile.mkdtemp()
        self.db = str(Path(self.tmp) / "t.db")
        self.state = Path(self.tmp) / "state.json"
        wr.DB = self.db
        wr.STATE = self.state
        conn = sqlite3.connect(self.db)
        conn.execute("""create table price_data
            (symbol text, timestamp text, open real, high real, low real,
             close real, volume real, timeframe text)""")
        self.conn = conn

    def _bar(self, sym, date, o, h, l, c, tf="1Day"):
        self.conn.execute("insert into price_data values (?,?,?,?,?,?,?,?)",
                          (sym, f"{date}T05:00:00", o, h, l, c, 1e6, tf))
        self.conn.commit()

    def _init_state(self, plan=None):
        s = {"capital": 100000.0, "cash": 100000.0, "bar_mode": "daily",
             "open": [], "closed": [], "pending_plans": plan or [],
             "pending_exits": [], "log": []}
        self.state.write_text(json.dumps(s))

    def _plan(self, **kw):
        base = {"date": "2025-06-02", "symbol": "XYZ", "engine": "R",
                "entry_type": "limit", "limit_price": 97.0, "stop_price": None,
                "stop_atr_mult": 2.5, "atr10": 2.0, "target_fill_pct": 4.0,
                "target_price": None, "target_close_pct": None,
                "time_stop_sessions": 4, "trail": False, "risk_pct": 1.0,
                "notional_cap_pct": 10.0, "gap_up_max_pct": None,
                "gap_down_max_pct": None, "reason": "test"}
        base.update(kw)
        return base

    def _run(self, date):
        class A: pass
        a = A(); a.date = date
        wr.cmd_run_day(a)

    def test_fill_relative_stop_and_target(self, capsys):
        self._bar("XYZ", "2025-06-02", 98.0, 99.0, 96.0, 97.5)  # fills @97
        self._init_state([self._plan()])
        self._run("2025-06-02")
        s = json.loads(self.state.read_text())
        pos = s["open"][0]
        assert pos["fill_price"] == 97.0
        assert pos["stop_price"] == pytest.approx(97.0 - 2.5 * 2.0)   # fill-relative
        assert pos["target_price"] == pytest.approx(97.0 * 1.04)

    def test_intrabar_target_exit(self, capsys):
        self._bar("XYZ", "2025-06-02", 98.0, 99.0, 96.0, 97.5)
        self._bar("XYZ", "2025-06-03", 98.0, 102.0, 97.5, 101.0)  # high >= 100.88
        self._init_state([self._plan()])
        self._run("2025-06-02"); self._run("2025-06-03")
        s = json.loads(self.state.read_text())
        assert len(s["closed"]) == 1
        t = s["closed"][0]
        assert t["reason"] == "take_profit"
        assert t["exit"] == pytest.approx(97.0 * 1.04)

    def test_close_based_stop_exits_next_open(self, capsys):
        self._bar("XYZ", "2025-06-02", 98.0, 99.0, 96.0, 97.5)   # fill 97, stop 92
        self._bar("XYZ", "2025-06-03", 95.0, 95.5, 90.0, 91.0)   # CLOSES below stop
        self._bar("XYZ", "2025-06-04", 90.5, 92.0, 89.0, 91.5)   # exit at THIS open
        self._init_state([self._plan()])
        for d in ("2025-06-02", "2025-06-03", "2025-06-04"):
            self._run(d)
        s = json.loads(self.state.read_text())
        t = s["closed"][0]
        assert t["reason"] == "stop_loss"
        assert t["exit"] == pytest.approx(90.5 * (1 - wr.SLIPPAGE))
        # intraday wick through stop on 06-03 (low 90 < 92) did NOT exit that day
        assert t["ts"].startswith("2025-06-04")

    def test_session_time_stop_queues_then_exits_next_open(self, capsys):
        self._bar("XYZ", "2025-06-02", 98.0, 99.0, 96.0, 97.5)
        for i, d in enumerate(["2025-06-03", "2025-06-04", "2025-06-05", "2025-06-06"]):
            self._bar("XYZ", d, 97.0, 98.0, 96.5, 97.2)
        self._init_state([self._plan(time_stop_sessions=2, target_fill_pct=None)])
        for d in ["2025-06-02", "2025-06-03", "2025-06-04"]:
            self._run(d)
        s = json.loads(self.state.read_text())
        assert len(s["closed"]) == 1
        t = s["closed"][0]
        assert t["reason"] == "time_stop_next_open"
        assert t["ts"].startswith("2025-06-04")  # sessions 1,2 then exit next open

    def test_pending_exit_survives_missing_data_day(self, capsys):
        self._bar("XYZ", "2025-06-02", 98.0, 99.0, 96.0, 97.5)
        self._bar("XYZ", "2025-06-03", 97.0, 98.0, 96.5, 97.2)
        # no bar for 06-04 (e.g. holiday/missing) ; bar resumes 06-05
        self._bar("XYZ", "2025-06-05", 96.0, 97.0, 95.0, 96.5)
        self._init_state([self._plan(time_stop_sessions=2, target_fill_pct=None)])
        for d in ["2025-06-02", "2025-06-03", "2025-06-04", "2025-06-05"]:
            self._run(d)
        s = json.loads(self.state.read_text())
        assert len(s["closed"]) == 1  # exit executed on 06-05, not silently dropped
        assert s["closed"][0]["ts"].startswith("2025-06-05")


class TestPlanReasonGuard:
    """Plans without a DD reason must be rejected (run-5 regression:
    two un-vetted entries slipped in when a degraded session planned
    with empty --reason)."""

    def setup_method(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.state = Path(self.tmp) / "state.json"
        wr.STATE = self.state
        self.state.write_text(json.dumps(
            {"capital": 100000.0, "cash": 100000.0, "bar_mode": "daily",
             "open": [], "closed": [], "pending_plans": [],
             "pending_exits": [], "log": []}))

    def _plan_args(self, reason):
        class A: pass
        a = A()
        a.date = "2025-06-02"; a.symbol = "XYZ"; a.engine = "M"
        a.entry_type = "market_open"; a.limit_price = None
        a.stop_price = None; a.stop_atr_mult = 2.5; a.atr10 = 2.0
        a.target_fill_pct = None; a.target_price = None
        a.target_close_pct = None; a.time_stop_sessions = 20
        a.trail = 1; a.risk_pct = 1.0; a.notional_cap_pct = 10.0
        a.gap_up_max_pct = 5.0; a.gap_down_max_pct = 3.0
        a.reason = reason
        return a

    def test_empty_reason_rejected(self, capsys):
        wr.cmd_plan(self._plan_args(""))
        out = json.loads(capsys.readouterr().out)
        assert "error" in out
        s = json.loads(self.state.read_text())
        assert s["pending_plans"] == []

    def test_whitespace_reason_rejected(self, capsys):
        wr.cmd_plan(self._plan_args("   "))
        out = json.loads(capsys.readouterr().out)
        assert "error" in out
        s = json.loads(self.state.read_text())
        assert s["pending_plans"] == []

    def test_real_reason_accepted(self, capsys):
        wr.cmd_plan(self._plan_args("WB M rank1: roc50 34.3 rsi3 19.9 pullback"))
        out = json.loads(capsys.readouterr().out)
        assert out.get("planned") == "XYZ"
        s = json.loads(self.state.read_text())
        assert len(s["pending_plans"]) == 1
