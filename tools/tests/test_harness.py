# tools/tests/test_harness.py
"""Tests for the v3 backtest harness (daily cycle + mechanical monitoring).

Covers the v3 API: start / advance_to_next_day / load_day_bars / step_bar,
plus the mechanical exit rules (stop, target, trailing, time) and event
detection. The pre-v3 advance_bar/record_decision API was removed in db878ef.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.harness import BacktestHarness
from persistence.repository import Repository

SLIP = 0.05 / 100  # harness default slippage_pct=0.05 (%)


def _save_daily(repo, symbol, dates, price=100.0):
    """Save flat daily bars for the given ISO dates (defines trading days)."""
    repo.save_price_bars([
        {
            "symbol": symbol, "timestamp": d,
            "open": price, "high": price + 1, "low": price - 1, "close": price,
            "volume": 1_000_000, "timeframe": "1Day",
        }
        for d in dates
    ])


def _save_hourly(repo, symbol, day, bars):
    """Save hourly bars for one day. bars = [(hour_utc, o, h, l, c), ...]."""
    repo.save_price_bars([
        {
            "symbol": symbol, "timestamp": f"{day}T{hour:02d}:00:00",
            "open": o, "high": h, "low": l, "close": c,
            "volume": 500_000, "timeframe": "1Hour",
        }
        for hour, o, h, l, c in bars
    ])


class TestHarnessLifecycle:
    def setup_method(self):
        self.repo = Repository(":memory:")

    def teardown_method(self):
        self.repo.close()

    def test_start_creates_run(self):
        _save_daily(self.repo, "SPY", ["2026-01-05", "2026-01-06"])
        harness = BacktestHarness(self.repo)
        run_id = harness.start(start_date="2026-01-05", end_date="2026-01-06",
                               symbols=["NVDA"], initial_capital=100000.0)
        assert run_id.startswith("bt-")
        run = self.repo.get_backtest_run(run_id)
        assert run["status"] == "running"

    def test_start_without_trading_days_raises(self):
        harness = BacktestHarness(self.repo)
        with pytest.raises(ValueError, match="No trading days"):
            harness.start(start_date="2026-01-05", end_date="2026-01-06")

    def test_advance_to_next_day_sequence(self):
        _save_daily(self.repo, "SPY", ["2026-01-05", "2026-01-06"])
        harness = BacktestHarness(self.repo)
        harness.start(start_date="2026-01-05", end_date="2026-01-06")

        d1 = harness.advance_to_next_day()
        assert d1["date"] == "2026-01-05"
        assert d1["day_number"] == 1 and d1["total_days"] == 2
        assert d1["open_count"] == 0

        d2 = harness.advance_to_next_day()
        assert d2["date"] == "2026-01-06"

        assert harness.advance_to_next_day() is None
        assert harness.is_done()

    def test_load_day_bars_filters_to_market_hours(self):
        _save_daily(self.repo, "SPY", ["2026-01-05"])
        # 13:00 UTC = pre-market; 14:00-20:00 UTC = market hours; 21:00 = after
        _save_hourly(self.repo, "NVDA", "2026-01-05", [
            (13, 99, 100, 98, 99),    # excluded
            (14, 100, 101, 99, 100),  # included
            (20, 100, 101, 99, 100),  # included
            (21, 100, 101, 99, 100),  # excluded
        ])
        harness = BacktestHarness(self.repo)
        harness.start(start_date="2026-01-05", end_date="2026-01-05")
        harness.advance_to_next_day()

        loaded = harness.load_day_bars(["NVDA"])
        assert loaded["symbols_loaded"] == {"NVDA": 2}

    def test_load_day_bars_requires_active_day(self):
        _save_daily(self.repo, "SPY", ["2026-01-05"])
        harness = BacktestHarness(self.repo)
        harness.start(start_date="2026-01-05", end_date="2026-01-05")
        result = harness.load_day_bars(["NVDA"])
        assert "error" in result

    def test_step_bar_day_complete_when_no_bars(self):
        _save_daily(self.repo, "SPY", ["2026-01-05"])
        harness = BacktestHarness(self.repo)
        harness.start(start_date="2026-01-05", end_date="2026-01-05")
        harness.advance_to_next_day()
        assert harness.step_bar()["status"] == "day_complete"


class TestMechanicalExits:
    """Each mechanical rule must fire without LLM involvement."""

    def setup_method(self):
        self.repo = Repository(":memory:")
        _save_daily(self.repo, "SPY", ["2026-01-05"])

    def teardown_method(self):
        self.repo.close()

    def _harness_with_bars(self, bars):
        harness = BacktestHarness(self.repo)
        harness.start(start_date="2026-01-05", end_date="2026-01-05")
        harness.advance_to_next_day()
        _save_hourly(self.repo, "NVDA", "2026-01-05", bars)
        harness.load_day_bars(["NVDA"])
        return harness

    def test_take_profit_exits_at_target_price(self):
        harness = self._harness_with_bars([
            (14, 100, 106, 99, 105),  # high touches target 105
        ])
        harness.enter_position("NVDA", "long", 100.0, 10, stop_loss=95.0,
                               take_profit=105.0, atr=2.0, reasoning="test")
        result = harness.step_bar()
        assert result["status"] == "exits"
        exit_info = result["exits"][0]
        assert exit_info["reason"] == "take_profit"
        assert exit_info["exit_price"] == 105.0   # exact target, not bar high
        assert exit_info["pnl"] == 50.0           # (105-100) * 10

    def test_stop_loss_exits_at_next_bar_open_after_close_below_stop(self):
        harness = self._harness_with_bars([
            (14, 100, 101, 93, 94),     # closes below stop 95 → flagged
            (15, 93.5, 94, 92, 93),     # exit at THIS bar's open (next-bar rule)
        ])
        harness.enter_position("NVDA", "long", 100.0, 10, stop_loss=95.0,
                               take_profit=200.0, atr=2.0, reasoning="test")
        r1 = harness.step_bar()
        assert "exits" not in r1  # no exit on the signal bar itself
        r2 = harness.step_bar()
        assert r2["status"] == "exits"
        exit_info = r2["exits"][0]
        assert exit_info["reason"] == "stop_loss"
        assert exit_info["exit_price"] == pytest.approx(93.5 * (1 - SLIP), abs=0.01)

    def test_time_stop_exits_after_max_hold_bars(self):
        harness = self._harness_with_bars([
            (14, 100, 101, 99, 100),
            (15, 100, 101, 99, 100),  # bars_held reaches 2 → time stop
        ])
        harness.enter_position("NVDA", "long", 100.0, 10, stop_loss=90.0,
                               take_profit=200.0, atr=2.0, reasoning="test",
                               time_stop_bars=2)
        harness.step_bar()
        r2 = harness.step_bar()
        assert r2["status"] == "exits"
        assert r2["exits"][0]["reason"] == "time_stop"

    def test_trailing_stop_arms_after_1r_and_exits_on_break(self):
        # entry 100, stop 95 (risk 5), atr 2 (2% → 1.5x trail multiplier)
        harness = self._harness_with_bars([
            (14, 100.5, 106.5, 100, 106),   # +1R reached → trail = 106-3 = 103
            (15, 105, 105.5, 104, 104.5),   # holds above trail
            (16, 104, 104.2, 102, 102.5),   # closes below trail 103 → flagged
            (17, 102.8, 103, 101, 102),     # exit at this bar's open
        ])
        harness.enter_position("NVDA", "long", 100.0, 10, stop_loss=95.0,
                               take_profit=200.0, atr=2.0, reasoning="test")
        for _ in range(3):
            r = harness.step_bar()
            assert "exits" not in r
        r4 = harness.step_bar()
        assert r4["status"] == "exits"
        exit_info = r4["exits"][0]
        assert exit_info["reason"] == "trailing_stop"
        assert exit_info["exit_price"] == pytest.approx(102.8 * (1 - SLIP), abs=0.01)

    def test_large_drop_emits_event_for_llm(self):
        harness = self._harness_with_bars([
            (14, 100, 100.5, 95.5, 96),  # -4% bar → LLM event, no auto-exit
        ])
        harness.enter_position("NVDA", "long", 100.0, 10, stop_loss=90.0,
                               take_profit=200.0, atr=2.0, reasoning="test")
        result = harness.step_bar()
        assert result["status"] == "events"
        assert any(e["type"] == "large_drop" for e in result["events"])
        assert "exits" not in result  # decision belongs to the LLM

    def test_duplicate_position_rejected(self):
        harness = self._harness_with_bars([(14, 100, 101, 99, 100)])
        harness.enter_position("NVDA", "long", 100.0, 10, stop_loss=95.0,
                               take_profit=105.0, atr=2.0, reasoning="test")
        result = harness.enter_position("NVDA", "long", 100.0, 5, stop_loss=95.0,
                                        take_profit=105.0, atr=2.0, reasoning="dup")
        assert "error" in result

    def test_manual_exit_records_pnl_and_r_multiple(self):
        harness = self._harness_with_bars([(14, 100, 101, 99, 100)])
        harness.enter_position("NVDA", "long", 100.0, 10, stop_loss=95.0,
                               take_profit=110.0, atr=2.0, reasoning="test")
        harness.step_bar()
        result = harness.exit_position("NVDA", 102.5, "llm_thesis_broken")
        assert result["pnl"] == 25.0                       # (102.5-100)*10
        assert result["r_multiple"] == pytest.approx(0.5)  # 2.5 / 5 risk
        assert harness.get_open_positions() == []


class TestFullRun:
    """End-to-end: multi-day run through the v3 daily cycle."""

    def setup_method(self):
        self.repo = Repository(":memory:")

    def teardown_method(self):
        self.repo.close()

    def test_two_day_run_with_take_profit(self):
        _save_daily(self.repo, "SPY", ["2026-01-05", "2026-01-06"])
        _save_hourly(self.repo, "NVDA", "2026-01-05", [
            (14, 100, 101, 99, 100.5),
            (15, 100.5, 102, 100, 101),
        ])
        _save_hourly(self.repo, "NVDA", "2026-01-06", [
            (14, 101, 106, 100.5, 105.5),  # target 105 hit
        ])

        harness = BacktestHarness(self.repo)
        harness.start(start_date="2026-01-05", end_date="2026-01-06",
                      symbols=["NVDA"], initial_capital=100000.0)

        # Day 1: enter, no exits
        harness.advance_to_next_day()
        harness.load_day_bars(["NVDA"])
        harness.enter_position("NVDA", "long", 100.0, 10, stop_loss=95.0,
                               take_profit=105.0, atr=2.0, reasoning="breakout")
        while harness.step_bar()["status"] not in ("day_complete",):
            pass
        assert len(harness.get_open_positions()) == 1

        # Day 2: position carries over, take profit fires
        day2 = harness.advance_to_next_day()
        assert day2["open_count"] == 1
        harness.load_day_bars(["NVDA"])
        result = harness.step_bar()
        assert result["status"] == "exits"
        assert result["exits"][0]["reason"] == "take_profit"

        # End of run
        assert harness.advance_to_next_day() is None
        assert harness.force_close_all() == []  # nothing left open

        results = harness.get_results()
        assert results["total_trades"] == 1
        assert results["winners"] == 1
        assert results["total_pnl"] == 50.0
        assert results["win_rate"] == 100.0
        assert results["final_equity"] == 100050.0
