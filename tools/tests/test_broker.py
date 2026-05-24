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

            def get_positions(self):
                return []

            def get_account(self):
                return {"equity": 100000}

            def get_market_data(self, symbol):
                return {"symbol": symbol, "bid": 150.0, "ask": 150.05}

            def get_historical_data(self, symbol, start, end, timeframe="1Day"):
                return []

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
