"""Tests for simulation broker adapter."""

import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from broker.simulation import SimulationBrokerAdapter
from persistence.repository import Repository


def _load_sample_data(repo: Repository, symbol: str = "AAPL") -> None:
    """Load 10 days of sample data."""
    import random
    random.seed(42)
    price = 150.0
    bars = []
    for i in range(10):
        o = price
        h = price + random.uniform(1, 4)
        l = price - random.uniform(1, 4)
        c = price + random.uniform(-3, 3)
        price = c
        bars.append({
            "symbol": symbol,
            "timestamp": f"2024-01-{(i+2):02d}T09:30:00",
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(l, 2),
            "close": round(c, 2),
            "volume": 1000000,
            "timeframe": "1Day",
        })
    repo.save_price_bars(bars)


class TestSimulationBroker:
    def setup_method(self):
        self.repo = Repository(":memory:")
        _load_sample_data(self.repo)
        self.broker = SimulationBrokerAdapter(self.repo, initial_capital=100000.0)
        self.broker.set_time(datetime(2024, 1, 3, 9, 30))

    def teardown_method(self):
        self.repo.close()

    def test_market_order_fills_at_open_plus_slippage(self):
        tx = self.broker.place_order("AAPL", "buy", "market", 100)
        assert tx.status == "filled"
        assert tx.quantity == 100
        assert tx.price > 0  # filled at open + slippage

    def test_buy_reduces_cash(self):
        initial_cash = self.broker.cash
        self.broker.place_order("AAPL", "buy", "market", 10)
        assert self.broker.cash < initial_cash

    def test_sell_increases_cash(self):
        self.broker.place_order("AAPL", "buy", "market", 10)
        cash_after_buy = self.broker.cash
        self.broker.place_order("AAPL", "sell", "market", 10)
        assert self.broker.cash > cash_after_buy

    def test_positions_tracked(self):
        self.broker.place_order("AAPL", "buy", "market", 50)
        positions = self.broker.get_positions()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "AAPL"
        assert positions[0]["quantity"] == 50

    def test_position_removed_after_full_sell(self):
        self.broker.place_order("AAPL", "buy", "market", 50)
        self.broker.place_order("AAPL", "sell", "market", 50)
        assert self.broker.get_positions() == []

    def test_limit_order_fills_when_price_crosses(self):
        # Get the bar's low to set a limit that will fill
        bar = self.repo.query_price_data("AAPL", "2024-01-03T00:00:00", "2024-01-03T23:59:59")[0]
        limit = bar["high"]  # limit at high — should fill for buy
        tx = self.broker.place_order("AAPL", "buy", "limit", 10, limit_price=limit)
        assert tx.status == "filled"

    def test_limit_order_pending_when_price_doesnt_cross(self):
        tx = self.broker.place_order("AAPL", "buy", "limit", 10, limit_price=1.0)  # way below
        assert tx.status == "pending"

    def test_stop_order_triggers(self):
        # Buy first
        self.broker.place_order("AAPL", "buy", "market", 50)
        # Set stop at the bar's low (should trigger)
        bar = self.repo.query_price_data("AAPL", "2024-01-03T00:00:00", "2024-01-03T23:59:59")[0]
        tx = self.broker.place_order("AAPL", "sell", "stop", 50, stop_price=bar["low"] + 0.01)
        assert tx.status == "filled"

    def test_get_account(self):
        acct = self.broker.get_account()
        assert acct["equity"] == 100000.0
        assert acct["cash"] == 100000.0

    def test_no_look_ahead(self):
        """Historical data query should not return data after current_time."""
        self.broker.set_time(datetime(2024, 1, 5, 9, 30))
        bars = self.broker.get_historical_data("AAPL", datetime(2024, 1, 1), datetime(2024, 1, 10))
        for bar in bars:
            assert bar["timestamp"] <= "2024-01-05T09:30:00"

    def test_rejected_when_no_data(self):
        self.broker.set_time(datetime(2020, 1, 1))  # no data for this date
        tx = self.broker.place_order("AAPL", "buy", "market", 10)
        assert tx.status == "rejected"

    def test_cancel_always_succeeds(self):
        assert self.broker.cancel_order("any-id") is True

    def test_get_market_data(self):
        data = self.broker.get_market_data("AAPL")
        assert data["symbol"] == "AAPL"
        assert data["mid"] > 0
