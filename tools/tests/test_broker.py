"""Tests for broker adapter and retry wrapper."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from broker.adapter import BrokerAdapter
from broker.retry import RetryConfig, with_retry
from models import TradeTransaction


# --- Retry Wrapper Tests ---


class TestRetryWrapper:
    def test_succeeds_first_try(self):
        fn = MagicMock(return_value="ok")
        wrapped = with_retry(fn, RetryConfig(max_retries=3, base_delay=0))
        assert wrapped() == "ok"
        assert fn.call_count == 1

    def test_retries_on_failure_then_succeeds(self):
        fn = MagicMock(side_effect=[ValueError("fail"), ValueError("fail"), "ok"])
        wrapped = with_retry(fn, RetryConfig(max_retries=3, base_delay=0))
        assert wrapped() == "ok"
        assert fn.call_count == 3

    def test_raises_after_max_retries(self):
        fn = MagicMock(side_effect=ValueError("always fails"))
        wrapped = with_retry(fn, RetryConfig(max_retries=2, base_delay=0))
        try:
            wrapped()
            assert False, "Should have raised"
        except ValueError as e:
            assert "always fails" in str(e)
        assert fn.call_count == 3  # initial + 2 retries

    def test_only_retries_specified_exceptions(self):
        fn = MagicMock(side_effect=TypeError("wrong type"))
        wrapped = with_retry(
            fn, RetryConfig(max_retries=3, base_delay=0),
            retryable=(ValueError,),
        )
        try:
            wrapped()
            assert False, "Should have raised"
        except TypeError:
            pass
        assert fn.call_count == 1  # no retry for TypeError

    def test_passes_args_through(self):
        fn = MagicMock(return_value="result")
        wrapped = with_retry(fn, RetryConfig(max_retries=1, base_delay=0))
        wrapped("a", "b", key="val")
        fn.assert_called_once_with("a", "b", key="val")


# --- BrokerAdapter ABC Tests ---


class TestBrokerAdapterABC:
    def test_cannot_instantiate_abc(self):
        try:
            BrokerAdapter()  # type: ignore
            assert False, "Should not instantiate ABC"
        except TypeError:
            pass

    def test_concrete_implementation(self):
        class FakeBroker(BrokerAdapter):
            def place_order(self, symbol, side, order_type, quantity, **kw):
                return TradeTransaction(symbol=symbol, side=side, quantity=quantity)

            def cancel_order(self, order_id):
                return True

            def get_account_activities(self, activity_type="FILL", page_token=None, page_size=100):
                return []

            def get_order(self, broker_order_id):
                return {"order_id": broker_order_id, "status": "unknown",
                        "symbol": "", "qty_requested": 0}

            def get_portfolio_history(self, period="1M", timeframe="1D"):
                return {"timestamps": [], "equity": []}

            def get_positions(self):
                return []

            def get_account(self):
                return {"equity": 100000}

            def get_market_data(self, symbol):
                return {"symbol": symbol, "bid": 150.0, "ask": 150.05}

            def get_historical_data(self, symbol, start, end, timeframe="1Day"):
                return []

            def get_option_chain(self, underlying, **kwargs):
                return []

            def get_option_snapshot(self, option_symbols):
                return []

            def get_option_historical_iv(self, underlying, lookback_days=252):
                return []

            def get_options_positions(self):
                return []

            def place_multileg_order(self, legs, order_type, **kwargs):
                return TradeTransaction(symbol="TEST", side="buy", quantity=1)

        broker = FakeBroker()
        tx = broker.place_order("AAPL", "buy", "market", 10)
        assert tx.symbol == "AAPL"
        assert tx.quantity == 10
        assert broker.cancel_order("123") is True
        assert broker.get_positions() == []


# --- AlpacaBrokerAdapter Tests (mocked SDK) ---


class TestAlpacaBrokerAdapter:
    def _make_adapter(self):
        """Create adapter with mocked clients."""
        with patch.dict("os.environ", {
            "ALPACA_API_KEY": "test-key",
            "ALPACA_SECRET_KEY": "test-secret",
        }):
            with patch("broker.alpaca.TradingClient") as mock_tc, \
                 patch("broker.alpaca.StockHistoricalDataClient") as mock_dc:
                from broker.alpaca import AlpacaBrokerAdapter
                adapter = AlpacaBrokerAdapter()
                adapter._mock_tc = mock_tc.return_value
                adapter._mock_dc = mock_dc.return_value
                return adapter

    def test_place_market_order(self):
        adapter = self._make_adapter()
        mock_order = MagicMock()
        mock_order.id = "order-123"
        mock_order.qty = "100"
        mock_order.filled_avg_price = "150.50"
        mock_order.status = MagicMock(value="filled")
        adapter.trading_client.submit_order.return_value = mock_order

        tx = adapter.place_order("AAPL", "buy", "market", 100)
        assert tx.symbol == "AAPL"
        assert tx.quantity == 100
        assert tx.price == 150.50
        assert tx.broker_order_id == "order-123"
        assert tx.status == "filled"

    def test_cancel_order_success(self):
        adapter = self._make_adapter()
        adapter.trading_client.cancel_order_by_id.return_value = None
        assert adapter.cancel_order("order-123") is True

    def test_cancel_order_failure(self):
        adapter = self._make_adapter()
        adapter.trading_client.cancel_order_by_id.side_effect = Exception("Not found")
        assert adapter.cancel_order("bad-id") is False

    def test_get_positions(self):
        adapter = self._make_adapter()
        mock_pos = MagicMock()
        mock_pos.symbol = "NVDA"
        mock_pos.qty = "50"
        mock_pos.side = MagicMock(value="long")
        mock_pos.avg_entry_price = "450.00"
        mock_pos.current_price = "460.00"
        mock_pos.unrealized_pl = "500.00"
        mock_pos.unrealized_plpc = "0.0222"
        adapter.trading_client.get_all_positions.return_value = [mock_pos]

        positions = adapter.get_positions()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "NVDA"
        assert positions[0]["quantity"] == 50
        assert positions[0]["unrealized_pnl"] == 500.0

    def test_get_account(self):
        adapter = self._make_adapter()
        mock_acct = MagicMock()
        mock_acct.equity = "100000"
        mock_acct.cash = "50000"
        mock_acct.buying_power = "200000"
        mock_acct.portfolio_value = "100000"
        mock_acct.last_equity = "99500"
        adapter.trading_client.get_account.return_value = mock_acct

        acct = adapter.get_account()
        assert acct["equity"] == 100000.0
        assert acct["cash"] == 50000.0
        assert acct["daily_pnl"] == 500.0

    def test_get_market_data(self):
        adapter = self._make_adapter()
        mock_quote = MagicMock()
        mock_quote.bid_price = 150.0
        mock_quote.ask_price = 150.10
        mock_quote.bid_size = 200
        mock_quote.ask_size = 300
        mock_quote.timestamp = datetime(2024, 6, 1, 10, 0, 0)
        adapter.data_client.get_stock_latest_quote.return_value = {"AAPL": mock_quote}

        data = adapter.get_market_data("AAPL")
        assert data["symbol"] == "AAPL"
        assert data["bid"] == 150.0
        assert data["ask"] == 150.10
        assert data["mid"] == 150.05


# --- calc_position_size (already wired in server.py) ---


class TestCalcPositionSize:
    def test_basic_calculation(self):
        """$100K account, 1% risk, entry $50, stop $48 → risk $2/share → qty 500"""
        import server
        result = json.loads(server.calc_position_size(100000, 1.0, 50.0, 48.0))
        assert result["quantity"] == 500
        assert result["risk_amount"] == 1000.0
        assert result["risk_per_share"] == 2.0

    def test_zero_risk_per_share(self):
        import server
        result = json.loads(server.calc_position_size(100000, 1.0, 50.0, 50.0))
        assert "error" in result


import json


# --- Fill source: account activities (go-live-metrics Task 2) ---
#
# The payload below is a REAL response captured from the paper account on
# 2026-08-16 (`GET /v2/account/activities/FILL`): one SHOP sell of 100 shares
# that the market filled in two executions. It is reproduced verbatim rather
# than invented, because the whole point of this task is that reality does not
# match the shape you would guess.
#
#   qty     80 + 20  = 100   <- correct position
#   cum_qty 80 + 100 = 180   <- what appending the cumulative field would claim
#
# 64 of the 250 real FILL activities in that account have qty != cum_qty, and
# 31 orders filled in more than one execution. This is not a hypothetical.
REAL_SHOP_PARTIAL_THEN_FILL = [
    {
        "id": "20260430093034923::2835c8e9-1716-4f93-927b-1775697aa30b",
        "activity_type": "FILL",
        "transaction_time": "2026-04-30T13:30:34.923781Z",
        "type": "partial_fill",
        "price": "120.5",
        "qty": "80",
        "side": "sell",
        "symbol": "SHOP",
        "leaves_qty": "20",
        "order_id": "b38bacd0-a880-491f-b157-9ae191fff583",
        "cum_qty": "80",
        "order_status": "partially_filled",
    },
    {
        "id": "20260430093247050::2d8d509b-7028-425a-bc4f-e3af9e186390",
        "activity_type": "FILL",
        "transaction_time": "2026-04-30T13:32:47.050985Z",
        "type": "fill",
        "price": "121.91",
        "qty": "20",
        "side": "sell",
        "symbol": "SHOP",
        "leaves_qty": "0",
        "order_id": "b38bacd0-a880-491f-b157-9ae191fff583",
        "cum_qty": "100",
        "order_status": "filled",
    },
]

ACTIVITY_KEYS = {
    "id", "order_id", "symbol", "side", "qty", "cum_qty", "price",
    "type", "transaction_time",
}


class TestAlpacaAccountActivities:
    def _adapter(self):
        return TestAlpacaBrokerAdapter()._make_adapter()

    def test_returns_per_execution_qty_never_cumulative(self):
        """The regression that motivates the whole table split.

        Summing `cum_qty` over an order's executions overstates the position;
        summing `qty` does not. Real numbers from a real order.
        """
        adapter = self._adapter()
        adapter.trading_client.get.return_value = REAL_SHOP_PARTIAL_THEN_FILL

        acts = adapter.get_account_activities("FILL")
        assert [a["qty"] for a in acts] == [80, 20]
        assert sum(a["qty"] for a in acts) == 100  # the true filled quantity
        assert sum(a["cum_qty"] for a in acts) == 180  # what we must never sum
        assert acts[0]["qty"] != acts[0]["cum_qty"] or acts[1]["qty"] != acts[1]["cum_qty"]

    def test_normalizes_broker_strings(self):
        """Alpaca sends every numeric as a string ("price": "8", "qty": "80")."""
        adapter = self._adapter()
        adapter.trading_client.get.return_value = REAL_SHOP_PARTIAL_THEN_FILL

        act = adapter.get_account_activities("FILL")[0]
        assert isinstance(act["qty"], int) and act["qty"] == 80
        assert isinstance(act["price"], float) and act["price"] == 120.5
        assert act["type"] == "partial_fill"
        assert act["id"] == "20260430093034923::2835c8e9-1716-4f93-927b-1775697aa30b"

    def test_fractional_qty_raises_rather_than_truncating(self):
        """A fractional share must never be silently floored into the position."""
        adapter = self._adapter()
        row = dict(REAL_SHOP_PARTIAL_THEN_FILL[0], qty="0.5")
        adapter.trading_client.get.return_value = [row]
        try:
            adapter.get_account_activities("FILL")
            assert False, "should have raised on a fractional quantity"
        except ValueError as e:
            assert "0.5" in str(e)

    def test_page_token_is_passed_through(self):
        adapter = self._adapter()
        adapter.trading_client.get.return_value = []

        adapter.get_account_activities("FILL", page_token="cursor-abc", page_size=50)
        path, params = adapter.trading_client.get.call_args[0]
        assert path == "/account/activities/FILL"
        assert params["page_token"] == "cursor-abc"
        assert params["page_size"] == 50
        assert params["direction"] == "asc"  # oldest-first, so the cursor advances

    def test_no_page_token_on_first_call(self):
        adapter = self._adapter()
        adapter.trading_client.get.return_value = []
        adapter.get_account_activities("FILL")
        _, params = adapter.trading_client.get.call_args[0]
        assert "page_token" not in params

    def test_empty_page_terminates(self):
        adapter = self._adapter()
        adapter.trading_client.get.return_value = []
        assert adapter.get_account_activities("FILL", page_token="end") == []

    def test_get_order_is_status_only(self):
        """get_order() must be structurally unusable as a fill source.

        Its cumulative filled_qty/filled_avg_price are what would double-count
        across polls, so they are not exposed at all.
        """
        adapter = self._adapter()
        mock_order = MagicMock()
        mock_order.id = "ord-1"
        mock_order.symbol = "SHOP"
        mock_order.qty = "100"
        mock_order.status = MagicMock(value="canceled")
        adapter.trading_client.get_order_by_id.return_value = mock_order

        result = adapter.get_order("ord-1")
        assert result["status"] == "canceled"
        for forbidden in ("filled_qty", "filled_avg_price", "price", "qty", "cum_qty"):
            assert forbidden not in result, f"{forbidden} would enable a double-count"


class TestSimulationAccountActivities:
    def _sim(self):
        from broker.simulation import SimulationBrokerAdapter
        from persistence.repository import Repository
        repo = Repository(":memory:")
        repo.save_price_bars([
            {"symbol": "AAPL", "timestamp": "2026-01-05T00:00:00", "open": 100.0,
             "high": 105.0, "low": 99.0, "close": 104.0, "volume": 1_000_000,
             "timeframe": "1Day"},
        ])
        sim = SimulationBrokerAdapter(repo, initial_capital=100_000.0, slippage_pct=0.0)
        sim.set_time(datetime(2026, 1, 5, 16, 0))
        return sim

    def test_records_the_executions_it_modelled(self):
        sim = self._sim()
        tx = sim.place_order("AAPL", "buy", "market", 10)
        assert tx.status == "filled"

        acts = sim.get_account_activities("FILL")
        assert len(acts) == 1
        assert acts[0]["order_id"] == tx.broker_order_id
        assert acts[0]["qty"] == 10
        assert acts[0]["price"] == tx.price

    def test_unfilled_order_produces_no_activity(self):
        """No fill, no row — the simulation must not invent an execution."""
        sim = self._sim()
        tx = sim.place_order("AAPL", "buy", "limit", 10, limit_price=1.0)
        assert tx.status == "pending"
        assert sim.get_account_activities("FILL") == []

    def test_activity_ids_are_deterministic_and_unique(self):
        sim = self._sim()
        sim.place_order("AAPL", "buy", "market", 5)
        sim.place_order("AAPL", "sell", "market", 5)
        ids = [a["id"] for a in sim.get_account_activities("FILL")]
        assert len(set(ids)) == 2
        assert all(not _looks_like_uuid(i) for i in ids), "ids must be reproducible"

    def test_pagination_by_cursor(self):
        sim = self._sim()
        for _ in range(3):
            sim.place_order("AAPL", "buy", "market", 1)
        first = sim.get_account_activities("FILL", page_size=2)
        assert len(first) == 2
        rest = sim.get_account_activities("FILL", page_token=first[-1]["id"], page_size=2)
        assert len(rest) == 1
        assert rest[0]["id"] not in {a["id"] for a in first}
        assert sim.get_account_activities("FILL", page_token=rest[-1]["id"]) == []

    def test_get_order_is_status_only(self):
        sim = self._sim()
        tx = sim.place_order("AAPL", "buy", "market", 10)
        result = sim.get_order(tx.broker_order_id)
        assert result["status"] == "filled"
        for forbidden in ("filled_qty", "filled_avg_price", "price", "qty", "cum_qty"):
            assert forbidden not in result

    def test_get_order_unknown_id(self):
        sim = self._sim()
        assert sim.get_order("SIM-999999")["status"] == "unknown"


class TestAdaptersAgreeOnShape:
    def test_activity_dicts_have_identical_keys(self):
        """Backtest and live must not diverge in the fill source's shape."""
        alpaca = TestAlpacaBrokerAdapter()._make_adapter()
        alpaca.trading_client.get.return_value = REAL_SHOP_PARTIAL_THEN_FILL
        alpaca_keys = set(alpaca.get_account_activities("FILL")[0].keys())

        sim = TestSimulationAccountActivities()._sim()
        sim.place_order("AAPL", "buy", "market", 10)
        sim_keys = set(sim.get_account_activities("FILL")[0].keys())

        assert alpaca_keys == sim_keys == ACTIVITY_KEYS

    def test_get_order_dicts_have_identical_keys(self):
        alpaca = TestAlpacaBrokerAdapter()._make_adapter()
        mock_order = MagicMock()
        mock_order.id, mock_order.symbol, mock_order.qty = "ord-1", "SHOP", "100"
        mock_order.status = MagicMock(value="canceled")
        alpaca.trading_client.get_order_by_id.return_value = mock_order

        sim = TestSimulationAccountActivities()._sim()
        tx = sim.place_order("AAPL", "buy", "market", 10)

        assert set(alpaca.get_order("ord-1")) == set(sim.get_order(tx.broker_order_id))


def _looks_like_uuid(s: str) -> bool:
    import re
    return bool(re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", s))
