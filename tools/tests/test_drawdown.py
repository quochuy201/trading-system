"""Tests for drawdown and the daily equity snapshot (go-live-metrics Task 6b).

Without these, the governance gate's §4.4 circuit breakers are dead controls
that look alive: present, tested, logging OK, and unable to ever fire.

The rule every test here defends: a failure reports UNAVAILABLE, never 0.0.
A breaker reading "0% drawdown" because the fetch died is a disarmed breaker,
at exactly the moment we cannot see the account.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from audit.drawdown import (
    UNAVAILABLE,
    drawdown_pct,
    drawdowns_from_broker,
    write_daily_snapshot,
)
from persistence.repository import Repository


class _HistoryBroker:
    def __init__(self, equity=None, raises=False):
        self._equity = equity or []
        self._raises = raises

    def get_portfolio_history(self, period="1M", timeframe="1D"):
        if self._raises:
            raise ConnectionError("broker unreachable")
        return {"timestamps": list(range(len(self._equity))),
                "equity": list(self._equity)}


class TestDrawdownPct:
    def test_hand_computed_from_peak(self):
        # peak 110 in the window, latest 99 -> (110-99)/110 = 10%
        assert drawdown_pct([100, 110, 105, 99], 4) == pytest.approx(10.0)

    def test_window_only_looks_back_that_far(self):
        """A peak outside the window must not count against today."""
        equity = [200, 100, 101, 102, 103]
        assert drawdown_pct(equity, 5) == pytest.approx((200 - 103) / 200 * 100)
        assert drawdown_pct(equity, 3) == pytest.approx((103 - 103) / 103 * 100)

    def test_at_a_new_high_is_zero_and_that_is_a_real_measurement(self):
        assert drawdown_pct([100, 105, 110], 3) == 0.0

    def test_never_negative(self):
        assert drawdown_pct([100, 90, 120], 3) == 0.0

    def test_window_longer_than_history_uses_what_exists(self):
        """A young account still has a real drawdown — no warmup period."""
        assert drawdown_pct([100, 90], 20) == pytest.approx(10.0)

    def test_empty_series_is_none_not_zero(self):
        assert drawdown_pct([], 5) is None

    def test_non_positive_peak_is_none(self):
        assert drawdown_pct([0.0, 0.0], 2) is None


class TestDrawdownsFromBroker:
    def test_reports_each_window(self):
        equity = [100, 120, 118, 116, 114, 112, 110]
        result = drawdowns_from_broker(_HistoryBroker(equity), windows=(5, 20))
        assert result["drawdown_5d_pct"] == pytest.approx((118 - 110) / 118 * 100)
        assert result["drawdown_20d_pct"] == pytest.approx((120 - 110) / 120 * 100)
        assert result["points"] == 7

    def test_fetch_failure_is_unavailable_never_zero(self):
        """The regression that would silently disarm both breakers."""
        result = drawdowns_from_broker(_HistoryBroker(raises=True))
        assert result["drawdown_5d_pct"] == UNAVAILABLE
        assert result["drawdown_20d_pct"] == UNAVAILABLE
        assert result["drawdown_5d_pct"] != 0.0

    def test_empty_history_is_unavailable_never_zero(self):
        result = drawdowns_from_broker(_HistoryBroker([]))
        assert result["drawdown_5d_pct"] == UNAVAILABLE
        assert result["points"] == 0


class TestDailySnapshot:
    def test_writes_one_row(self):
        repo = Repository(":memory:")
        date = write_daily_snapshot(
            repo, {"equity": 107376.13, "cash": 93354.34, "daily_pnl": -12.0},
            [{"symbol": "NVDA", "quantity": 10}],
            as_of=datetime(2026, 8, 16, 13, 0),
        )
        assert date == "2026-08-16"
        rows = repo.conn.execute("SELECT * FROM portfolio_snapshots").fetchall()
        assert len(rows) == 1
        assert rows[0]["total_value"] == 107376.13
        assert rows[0]["date"] == "2026-08-16"
        repo.close()

    def test_same_day_replaces_rather_than_appends(self):
        """An EOD retry must not double the equity series."""
        repo = Repository(":memory:")
        when = datetime(2026, 8, 16, 13, 0)
        write_daily_snapshot(repo, {"equity": 100.0, "cash": 1.0}, [], as_of=when)
        write_daily_snapshot(repo, {"equity": 200.0, "cash": 2.0}, [], as_of=when)

        rows = repo.conn.execute("SELECT * FROM portfolio_snapshots").fetchall()
        assert len(rows) == 1
        assert rows[0]["total_value"] == 200.0  # latest wins
        repo.close()

    def test_different_days_are_separate_rows(self):
        repo = Repository(":memory:")
        write_daily_snapshot(repo, {"equity": 100.0}, [], as_of=datetime(2026, 8, 16))
        write_daily_snapshot(repo, {"equity": 110.0}, [], as_of=datetime(2026, 8, 17))
        assert repo.conn.execute(
            "SELECT COUNT(*) c FROM portfolio_snapshots").fetchone()["c"] == 2
        repo.close()


class TestAdapterParity:
    def test_both_adapters_return_the_same_shape(self):
        """Backtest and live must not diverge in the drawdown input."""
        from unittest.mock import MagicMock, patch

        with patch.dict("os.environ", {"ALPACA_API_KEY": "k", "ALPACA_SECRET_KEY": "s"}):
            with patch("broker.alpaca.TradingClient") as tc, \
                 patch("broker.alpaca.StockHistoricalDataClient"), \
                 patch("broker.alpaca.OptionHistoricalDataClient"):
                from broker.alpaca import AlpacaBrokerAdapter
                adapter = AlpacaBrokerAdapter()
        history = MagicMock()
        history.timestamp = [1, 2, 3]
        history.equity = [100.0, 110.0, 105.0]
        adapter.trading_client.get_portfolio_history.return_value = history
        alpaca_out = adapter.get_portfolio_history()

        from broker.simulation import SimulationBrokerAdapter
        sim = SimulationBrokerAdapter(Repository(":memory:"), initial_capital=100.0)
        sim.set_time(datetime(2026, 1, 5))
        sim_out = sim.get_portfolio_history()

        assert set(alpaca_out) == set(sim_out) == {"timestamps", "equity"}
        assert alpaca_out["equity"] == [100.0, 110.0, 105.0]
        assert sim_out["equity"] == [100.0]

    def test_null_equity_points_are_dropped_not_zeroed(self):
        """Alpaca returns null for a session with no activity. A 0.0 there
        reads as a total wipeout and would trip every breaker."""
        from unittest.mock import MagicMock, patch

        with patch.dict("os.environ", {"ALPACA_API_KEY": "k", "ALPACA_SECRET_KEY": "s"}):
            with patch("broker.alpaca.TradingClient") as tc, \
                 patch("broker.alpaca.StockHistoricalDataClient"), \
                 patch("broker.alpaca.OptionHistoricalDataClient"):
                from broker.alpaca import AlpacaBrokerAdapter
                adapter = AlpacaBrokerAdapter()
        history = MagicMock()
        history.timestamp = [1, 2, 3]
        history.equity = [100.0, None, 105.0]
        adapter.trading_client.get_portfolio_history.return_value = history

        out = adapter.get_portfolio_history()
        assert out["equity"] == [100.0, 105.0]
        assert 0.0 not in out["equity"]
        assert out["timestamps"] == [1, 3]
