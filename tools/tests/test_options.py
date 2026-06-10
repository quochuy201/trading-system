"""Tests for options analysis pure functions (stdlib math only, no pandas/numpy)
and Alpaca options adapter methods (mocked SDK).
"""

import json
import math
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from analysis.options import (
    black_scholes_price,
    calc_expected_move,
    calc_hv,
    calc_iv_rank,
    calc_put_skew,
    implied_vol_from_price,
    parse_occ_symbol,
)


# ---------------------------------------------------------------------------
# parse_occ_symbol
# ---------------------------------------------------------------------------


class TestParseOccSymbol:
    def test_standard_call(self):
        result = parse_occ_symbol("AAPL250620C00230000")
        assert result["underlying"] == "AAPL"
        assert result["expiration"] == "250620"
        assert result["type"] == "C"
        assert result["strike"] == 230.0

    def test_standard_put(self):
        result = parse_occ_symbol("AAPL250620P00215000")
        assert result["underlying"] == "AAPL"
        assert result["expiration"] == "250620"
        assert result["type"] == "P"
        assert result["strike"] == 215.0

    def test_fractional_strike(self):
        # Strike 00012500 => 12.50
        result = parse_occ_symbol("SPXW250620C04500000")
        assert result["underlying"] == "SPXW"
        assert result["strike"] == 4500.0

    def test_fractional_cents(self):
        # Strike 00002050 => 2.05 (eight digits, divide by 1000)
        result = parse_occ_symbol("XYZ250101C00002050")
        assert result["underlying"] == "XYZ"
        assert abs(result["strike"] - 2.05) < 0.001

    def test_short_root(self):
        # Single-char root
        result = parse_occ_symbol("A250620C00050000")
        assert result["underlying"] == "A"
        assert result["strike"] == 50.0

    def test_long_root(self):
        result = parse_occ_symbol("GOOGL250620P00175000")
        assert result["underlying"] == "GOOGL"
        assert result["type"] == "P"
        assert result["strike"] == 175.0

    def test_zero_strike_invalid(self):
        # Zero-value strike should still parse without exception
        result = parse_occ_symbol("XYZ250620C00000000")
        assert result["strike"] == 0.0

    def test_expiration_format(self):
        result = parse_occ_symbol("TSLA251231C01000000")
        assert result["expiration"] == "251231"

    def test_returns_dict(self):
        result = parse_occ_symbol("MSFT250620C00400000")
        assert isinstance(result, dict)
        assert set(result.keys()) == {"underlying", "expiration", "type", "strike"}


# ---------------------------------------------------------------------------
# calc_iv_rank
# ---------------------------------------------------------------------------


class TestCalcIvRank:
    def test_midpoint(self):
        # current at midpoint → 50
        history = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = calc_iv_rank(30.0, history)
        assert abs(result - 50.0) < 0.01

    def test_at_max(self):
        history = [10.0, 30.0]
        result = calc_iv_rank(30.0, history)
        assert abs(result - 100.0) < 0.01

    def test_at_min(self):
        history = [10.0, 30.0]
        result = calc_iv_rank(10.0, history)
        assert abs(result - 0.0) < 0.01

    def test_above_max_clamped(self):
        history = [10.0, 30.0]
        result = calc_iv_rank(50.0, history)
        assert result == 100.0

    def test_below_min_clamped(self):
        history = [10.0, 30.0]
        result = calc_iv_rank(0.0, history)
        assert result == 0.0

    def test_returns_50_on_empty_history(self):
        result = calc_iv_rank(25.0, [])
        assert result == 50.0

    def test_returns_50_on_single_value(self):
        result = calc_iv_rank(25.0, [25.0])
        assert result == 50.0

    def test_returns_50_when_all_same(self):
        # All identical values → max == min → undefined, return 50
        result = calc_iv_rank(20.0, [20.0, 20.0, 20.0])
        assert result == 50.0

    def test_typical_range(self):
        # Verify formula: (current - min) / (max - min) * 100
        history = list(range(1, 101))  # 1..100
        result = calc_iv_rank(75.0, history)
        expected = (75 - 1) / (100 - 1) * 100
        assert abs(result - expected) < 0.01

    def test_result_in_0_to_100(self):
        history = [15.0, 25.0, 35.0]
        result = calc_iv_rank(20.0, history)
        assert 0.0 <= result <= 100.0


# ---------------------------------------------------------------------------
# calc_hv
# ---------------------------------------------------------------------------


class TestCalcHv:
    def _flat_closes(self, n, price=100.0):
        return [price] * n

    def test_returns_nan_insufficient_data(self):
        closes = self._flat_closes(5)
        result = calc_hv(closes, window=20)
        assert math.isnan(result)

    def test_returns_nan_on_empty(self):
        result = calc_hv([], window=20)
        assert math.isnan(result)

    def test_zero_hv_flat_price(self):
        # All same price → log returns all 0 → HV = 0
        closes = self._flat_closes(25, 100.0)
        result = calc_hv(closes, window=20)
        assert result == 0.0

    def test_positive_hv_varying_prices(self):
        import random
        random.seed(42)
        closes = [100.0]
        for _ in range(25):
            closes.append(closes[-1] * (1 + random.gauss(0, 0.01)))
        result = calc_hv(closes, window=20)
        assert result > 0.0

    def test_annualization(self):
        # HV is annualized with sqrt(252)
        # Manually compute: daily std of log-returns for last 20 bars * sqrt(252)
        closes = [100.0 * (1.01 ** i) for i in range(25)]
        result = calc_hv(closes, window=20)
        # Should be a positive float, roughly 1% daily * sqrt(252) ~ 15.87%
        assert result > 0.0
        assert result < 5.0  # sanity check not unreasonably large

    def test_exact_minimum_data(self):
        # window+1 closes should be sufficient
        closes = self._flat_closes(21, 100.0)
        result = calc_hv(closes, window=20)
        assert not math.isnan(result)

    def test_custom_window(self):
        closes = self._flat_closes(15, 100.0)
        result = calc_hv(closes, window=10)
        assert not math.isnan(result)


# ---------------------------------------------------------------------------
# calc_put_skew
# ---------------------------------------------------------------------------


def _make_contract(opt_type, delta, iv):
    return {"type": opt_type, "delta": delta, "iv": iv}


class TestCalcPutSkew:
    def test_basic_skew(self):
        chain = [
            _make_contract("put", 0.25, 0.35),
            _make_contract("call", 0.25, 0.20),
        ]
        # Points-difference per SOP: (0.35 - 0.20) * 100 = 15.0
        result = calc_put_skew(chain, target_delta=0.25)
        assert abs(result - 15.0) < 0.001

    def test_nearest_delta_match(self):
        chain = [
            _make_contract("put", 0.27, 0.30),   # close to 0.25
            _make_contract("put", 0.40, 0.25),   # further
            _make_contract("call", 0.22, 0.20),  # close to 0.25
            _make_contract("call", 0.10, 0.18),  # further
        ]
        # Should pick put@0.27 and call@0.22 → (0.30 - 0.20) * 100 = 10.0
        result = calc_put_skew(chain, target_delta=0.25)
        assert abs(result - 10.0) < 0.001

    def test_negative_skew_when_calls_richer(self):
        # Calls priced higher than puts → negative skew (SOP soft-gate warning)
        chain = [
            _make_contract("put", 0.25, 0.20),
            _make_contract("call", 0.25, 0.27),
        ]
        result = calc_put_skew(chain, target_delta=0.25)
        assert abs(result - (-7.0)) < 0.001

    def test_nan_when_no_put(self):
        chain = [_make_contract("call", 0.25, 0.20)]
        result = calc_put_skew(chain, target_delta=0.25)
        assert math.isnan(result)

    def test_nan_when_no_call(self):
        chain = [_make_contract("put", 0.25, 0.30)]
        result = calc_put_skew(chain, target_delta=0.25)
        assert math.isnan(result)

    def test_nan_empty_chain(self):
        result = calc_put_skew([], target_delta=0.25)
        assert math.isnan(result)

    def test_nan_outside_tolerance(self):
        # delta 0.50 is more than 0.10 away from target 0.25
        chain = [
            _make_contract("put", 0.50, 0.30),
            _make_contract("call", 0.50, 0.20),
        ]
        result = calc_put_skew(chain, target_delta=0.25)
        assert math.isnan(result)

    def test_at_tolerance_boundary(self):
        # delta exactly 0.10 away from 0.25 → boundary; treat as valid
        chain = [
            _make_contract("put", 0.35, 0.30),   # exactly at tolerance
            _make_contract("call", 0.15, 0.20),  # exactly at tolerance
        ]
        result = calc_put_skew(chain, target_delta=0.25)
        assert not math.isnan(result)

    def test_zero_call_iv_is_full_put_iv(self):
        # Points-difference has no division; call_iv=0 → skew is full put IV in pts
        chain = [
            _make_contract("put", 0.25, 0.30),
            _make_contract("call", 0.25, 0.0),
        ]
        result = calc_put_skew(chain, target_delta=0.25)
        assert abs(result - 30.0) < 0.001


# ---------------------------------------------------------------------------
# calc_expected_move
# ---------------------------------------------------------------------------


class TestCalcExpectedMove:
    def test_basic(self):
        # stock=100, iv=0.20, dte=30
        result = calc_expected_move(100.0, 0.20, 30)
        expected = 100.0 * 0.20 * math.sqrt(30 / 365)
        assert abs(result - expected) < 0.0001

    def test_dte_zero_returns_zero(self):
        result = calc_expected_move(100.0, 0.20, 0)
        assert result == 0.0

    def test_dte_negative_returns_zero(self):
        result = calc_expected_move(100.0, 0.20, -5)
        assert result == 0.0

    def test_scales_with_price(self):
        r1 = calc_expected_move(100.0, 0.20, 30)
        r2 = calc_expected_move(200.0, 0.20, 30)
        assert abs(r2 - 2 * r1) < 0.0001

    def test_scales_with_iv(self):
        r1 = calc_expected_move(100.0, 0.10, 30)
        r2 = calc_expected_move(100.0, 0.20, 30)
        assert abs(r2 - 2 * r1) < 0.0001

    def test_dte_1(self):
        result = calc_expected_move(150.0, 0.30, 1)
        expected = 150.0 * 0.30 * math.sqrt(1 / 365)
        assert abs(result - expected) < 0.0001


# ---------------------------------------------------------------------------
# black_scholes_price
# ---------------------------------------------------------------------------


class TestBlackScholesPrice:
    def test_call_price_positive(self):
        price = black_scholes_price(
            stock=100.0, strike=100.0, dte=30, rate=0.05, vol=0.20, option_type="call"
        )
        assert price > 0.0

    def test_put_price_positive(self):
        price = black_scholes_price(
            stock=100.0, strike=100.0, dte=30, rate=0.05, vol=0.20, option_type="put"
        )
        assert price > 0.0

    def test_call_put_parity(self):
        # Put-call parity: C - P = S - K * e^(-r*T)
        S, K, dte, r, vol = 100.0, 100.0, 30, 0.05, 0.20
        T = dte / 365
        call = black_scholes_price(S, K, dte, r, vol, "call")
        put = black_scholes_price(S, K, dte, r, vol, "put")
        parity = S - K * math.exp(-r * T)
        assert abs((call - put) - parity) < 0.01

    def test_deep_itm_call(self):
        # Deep ITM call ~ intrinsic value
        price = black_scholes_price(
            stock=200.0, strike=100.0, dte=1, rate=0.05, vol=0.20, option_type="call"
        )
        # Approximately S - K*e(-rT) ~ 100
        assert price > 95.0

    def test_deep_otm_call_near_zero(self):
        # Deep OTM call ~ 0
        price = black_scholes_price(
            stock=50.0, strike=200.0, dte=1, rate=0.05, vol=0.20, option_type="call"
        )
        assert price < 0.001

    def test_accepts_case_insensitive_type(self):
        # Both "call" and "C" should work
        p1 = black_scholes_price(100.0, 100.0, 30, 0.05, 0.20, "call")
        p2 = black_scholes_price(100.0, 100.0, 30, 0.05, 0.20, "C")
        assert abs(p1 - p2) < 1e-10

    def test_at_expiry_dte_zero_call(self):
        # At expiry: call = max(S-K, 0)
        price = black_scholes_price(
            stock=110.0, strike=100.0, dte=0, rate=0.05, vol=0.20, option_type="call"
        )
        assert abs(price - 10.0) < 0.01

    def test_at_expiry_dte_zero_put_otm(self):
        # OTM put at expiry = 0
        price = black_scholes_price(
            stock=110.0, strike=100.0, dte=0, rate=0.05, vol=0.20, option_type="put"
        )
        assert price < 0.01

    def test_longer_dte_higher_price(self):
        short = black_scholes_price(100.0, 100.0, 7, 0.05, 0.20, "call")
        long_ = black_scholes_price(100.0, 100.0, 60, 0.05, 0.20, "call")
        assert long_ > short


# ---------------------------------------------------------------------------
# implied_vol_from_price
# ---------------------------------------------------------------------------


class TestImpliedVolFromPrice:
    def _round_trip(self, vol, stock=100.0, strike=100.0, dte=30, rate=0.05, opt_type="call"):
        """Generate BS price, then invert to recover vol."""
        price = black_scholes_price(stock, strike, dte, rate, vol, opt_type)
        recovered = implied_vol_from_price(price, stock, strike, dte, rate, opt_type)
        return recovered

    def test_round_trip_atm_call(self):
        recovered = self._round_trip(0.25)
        assert abs(recovered - 0.25) < 1e-4

    def test_round_trip_otm_call(self):
        price = black_scholes_price(100.0, 110.0, 30, 0.05, 0.30, "call")
        iv = implied_vol_from_price(price, 100.0, 110.0, 30, 0.05, "call")
        assert abs(iv - 0.30) < 1e-4

    def test_round_trip_put(self):
        price = black_scholes_price(100.0, 100.0, 30, 0.05, 0.20, "put")
        iv = implied_vol_from_price(price, 100.0, 100.0, 30, 0.05, "put")
        assert abs(iv - 0.20) < 1e-4

    def test_nan_on_impossible_price(self):
        # Option price of 0 for an ITM call is impossible → NaN
        iv = implied_vol_from_price(0.0, 110.0, 100.0, 30, 0.05, "call")
        assert math.isnan(iv)

    def test_nan_on_negative_price(self):
        iv = implied_vol_from_price(-5.0, 100.0, 100.0, 30, 0.05, "call")
        assert math.isnan(iv)

    def test_various_vols(self):
        for vol in [0.10, 0.20, 0.40, 0.80, 1.50]:
            recovered = self._round_trip(vol)
            assert abs(recovered - vol) < 1e-3, f"Failed for vol={vol}: got {recovered}"

    def test_high_strike_otm_put(self):
        # OTM put with known vol
        price = black_scholes_price(100.0, 90.0, 45, 0.04, 0.22, "put")
        iv = implied_vol_from_price(price, 100.0, 90.0, 45, 0.04, "put")
        assert abs(iv - 0.22) < 1e-4


# ---------------------------------------------------------------------------
# AlpacaBrokerAdapter — options methods (mocked SDK)
# ---------------------------------------------------------------------------


def _make_alpaca_adapter():
    """Construct AlpacaBrokerAdapter with all Alpaca SDK clients mocked."""
    with patch.dict("os.environ", {
        "ALPACA_API_KEY": "test-key",
        "ALPACA_SECRET_KEY": "test-secret",
    }):
        with patch("broker.alpaca.TradingClient"), \
             patch("broker.alpaca.StockHistoricalDataClient"), \
             patch("broker.alpaca.OptionHistoricalDataClient"):
            from broker.alpaca import AlpacaBrokerAdapter
            adapter = AlpacaBrokerAdapter()
            # Replace clients with plain MagicMocks for easy stubbing
            adapter.trading_client = MagicMock()
            adapter.data_client = MagicMock()
            adapter.option_data_client = MagicMock()
            return adapter


def _make_snapshot(bid, ask, iv, delta=0.45, gamma=0.03, theta=-0.05, vega=0.12, rho=0.01, trade_size=100):
    """Build a mock OptionsSnapshot as returned by Alpaca SDK."""
    snap = MagicMock()
    snap.latest_quote.bid_price = bid
    snap.latest_quote.ask_price = ask
    snap.implied_volatility = iv
    snap.greeks.delta = delta
    snap.greeks.gamma = gamma
    snap.greeks.theta = theta
    snap.greeks.vega = vega
    snap.greeks.rho = rho
    snap.latest_trade.size = trade_size
    return snap


class TestAlpacaOptionsAdapter:
    """Tests for the 5 options adapter methods on AlpacaBrokerAdapter."""

    # --- get_option_chain ---

    def test_get_option_chain_shape(self):
        """Verify that get_option_chain returns dicts with all required keys."""
        adapter = _make_alpaca_adapter()

        symbol = "AAPL260620C00230000"
        snap = _make_snapshot(bid=2.50, ask=2.60, iv=0.28)
        adapter.option_data_client.get_option_chain.return_value = {symbol: snap}

        result = adapter.get_option_chain("AAPL")

        assert len(result) == 1
        row = result[0]
        # All required keys present
        required_keys = {
            "symbol", "underlying", "strike", "type", "expiration",
            "dte", "bid", "ask", "mid", "volume", "open_interest", "iv", "greeks",
        }
        assert required_keys.issubset(set(row.keys()))

        assert row["symbol"] == symbol
        assert row["underlying"] == "AAPL"
        assert row["strike"] == 230.0
        assert row["type"] == "C"
        assert row["bid"] == 2.50
        assert row["ask"] == 2.60
        assert abs(row["mid"] - 2.55) < 0.001
        assert row["iv"] == 0.28
        assert isinstance(row["greeks"], dict)
        assert "delta" in row["greeks"]
        assert row["greeks"]["delta"] == 0.45

    def test_get_option_chain_filters_call_type(self):
        """ContractType.CALL is passed when option_type='call'."""
        adapter = _make_alpaca_adapter()
        adapter.option_data_client.get_option_chain.return_value = {}

        adapter.get_option_chain("AAPL", option_type="call")

        call_args = adapter.option_data_client.get_option_chain.call_args
        req = call_args[0][0]
        from alpaca.trading.enums import ContractType
        assert req.type == ContractType.CALL

    def test_get_option_chain_empty_response(self):
        """Empty chain response returns empty list."""
        adapter = _make_alpaca_adapter()
        adapter.option_data_client.get_option_chain.return_value = {}

        result = adapter.get_option_chain("AAPL")
        assert result == []

    # --- get_option_snapshot ---

    def test_get_option_snapshot_shape(self):
        """Verify snapshot returns same shape as chain."""
        adapter = _make_alpaca_adapter()

        symbol = "TSLA260620P00220000"
        snap = _make_snapshot(bid=1.80, ask=1.90, iv=0.35, delta=-0.35)
        adapter.option_data_client.get_option_snapshot.return_value = {symbol: snap}

        result = adapter.get_option_snapshot([symbol])

        assert len(result) == 1
        row = result[0]
        assert row["symbol"] == symbol
        assert row["underlying"] == "TSLA"
        assert row["type"] == "P"
        assert row["strike"] == 220.0
        assert row["greeks"]["delta"] == -0.35

    def test_get_option_snapshot_empty_list(self):
        """Passing empty list returns empty without API call."""
        adapter = _make_alpaca_adapter()

        result = adapter.get_option_snapshot([])

        assert result == []
        adapter.option_data_client.get_option_snapshot.assert_not_called()

    # --- get_options_positions ---

    def test_get_options_positions_filters_options(self):
        """Only positions with 'option' in asset_class are returned."""
        adapter = _make_alpaca_adapter()

        # Equity position — should be excluded
        eq_pos = MagicMock()
        eq_pos.symbol = "AAPL"
        eq_pos.asset_class = "us_equity"

        # Option position — should be included
        opt_pos = MagicMock()
        opt_pos.symbol = "AAPL260620C00230000"
        opt_pos.asset_class = "us_option"
        opt_pos.qty = "2"
        opt_pos.side = MagicMock(value="long")
        opt_pos.avg_entry_price = "2.50"
        opt_pos.current_price = "3.10"
        opt_pos.unrealized_pl = "120.0"
        opt_pos.unrealized_plpc = "0.24"

        adapter.trading_client.get_all_positions.return_value = [eq_pos, opt_pos]
        # Stub snapshot enrichment
        adapter.option_data_client.get_option_snapshot.return_value = {}

        result = adapter.get_options_positions()

        assert len(result) == 1
        row = result[0]
        assert row["symbol"] == "AAPL260620C00230000"
        assert row["underlying"] == "AAPL"
        assert row["strike"] == 230.0
        assert row["type"] == "C"
        assert row["quantity"] == 2
        assert row["entry_price"] == 2.50
        assert row["current_price"] == 3.10
        assert row["unrealized_pnl"] == 120.0
        assert abs(row["unrealized_pnl_pct"] - 24.0) < 0.001

    def test_get_options_positions_empty_account(self):
        """No positions returns empty list."""
        adapter = _make_alpaca_adapter()
        adapter.trading_client.get_all_positions.return_value = []

        result = adapter.get_options_positions()
        assert result == []

    # --- place_multileg_order ---

    def test_place_multileg_order(self):
        """Verify OrderClass.MLEG and OptionLegRequest construction."""
        adapter = _make_alpaca_adapter()

        mock_order = MagicMock()
        mock_order.id = "mleg-order-001"
        mock_order.qty = "2"
        mock_order.filled_avg_price = "1.50"
        mock_order.status = MagicMock(value="accepted")
        adapter.trading_client.submit_order.return_value = mock_order

        legs = [
            {"symbol": "AAPL260620C00230000", "side": "buy_to_open", "ratio_qty": 1},
            {"symbol": "AAPL260620C00240000", "side": "sell_to_open", "ratio_qty": 1},
        ]
        tx = adapter.place_multileg_order(legs, order_type="limit", limit_price=1.50)

        assert adapter.trading_client.submit_order.called
        call_args = adapter.trading_client.submit_order.call_args
        order_req = call_args[0][0]

        from alpaca.trading.enums import OrderClass
        from alpaca.trading.requests import LimitOrderRequest
        assert order_req.order_class == OrderClass.MLEG
        assert len(order_req.legs) == 2
        assert isinstance(order_req, LimitOrderRequest)
        assert order_req.limit_price == 1.50

        assert tx.broker_order_id == "mleg-order-001"
        assert tx.status == "accepted"

    def test_place_multileg_order_invalid_side(self):
        """Invalid leg side raises ValueError."""
        adapter = _make_alpaca_adapter()

        legs = [{"symbol": "AAPL260620C00230000", "side": "bad_side", "ratio_qty": 1}]
        try:
            adapter.place_multileg_order(legs, order_type="limit")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "bad_side" in str(e)

    def test_place_multileg_order_qty_passthrough(self):
        """qty is forwarded to the order request (not hardcoded to 1)."""
        adapter = _make_alpaca_adapter()

        mock_order = MagicMock()
        mock_order.id = "mleg-order-002"
        mock_order.qty = "3"
        mock_order.filled_avg_price = "1.03"
        mock_order.status = MagicMock(value="accepted")
        adapter.trading_client.submit_order.return_value = mock_order

        legs = [
            {"symbol": "QQQ260620P00650000", "side": "sell_to_open", "ratio_qty": 1},
            {"symbol": "QQQ260620P00640000", "side": "buy_to_open", "ratio_qty": 1},
        ]
        tx = adapter.place_multileg_order(legs, order_type="limit", limit_price=1.03, qty=3)

        order_req = adapter.trading_client.submit_order.call_args[0][0]
        assert int(order_req.qty) == 3
        assert tx.quantity == 6  # 3 spreads x 2 legs (ratio 1 each)

    def test_place_multileg_order_qty_default_is_one(self):
        """Omitting qty keeps the old single-spread behavior."""
        adapter = _make_alpaca_adapter()

        mock_order = MagicMock()
        mock_order.id = "mleg-order-003"
        mock_order.qty = "1"
        mock_order.filled_avg_price = None
        mock_order.status = MagicMock(value="submitted")
        adapter.trading_client.submit_order.return_value = mock_order

        legs = [
            {"symbol": "QQQ260620P00650000", "side": "sell_to_open", "ratio_qty": 1},
            {"symbol": "QQQ260620P00640000", "side": "buy_to_open", "ratio_qty": 1},
        ]
        adapter.place_multileg_order(legs, order_type="limit", limit_price=1.03)

        order_req = adapter.trading_client.submit_order.call_args[0][0]
        assert int(order_req.qty) == 1

    def test_place_multileg_order_qty_invalid_raises(self):
        """qty < 1 raises ValueError before any broker call."""
        adapter = _make_alpaca_adapter()
        legs = [{"symbol": "QQQ260620P00650000", "side": "sell_to_open", "ratio_qty": 1}]
        try:
            adapter.place_multileg_order(legs, order_type="limit", limit_price=1.0, qty=0)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "qty" in str(e)
        assert not adapter.trading_client.submit_order.called


# ---------------------------------------------------------------------------
# TestMcpToolIntegration — test MCP tools in server.py with mocked broker
# ---------------------------------------------------------------------------


class TestMcpToolIntegration:
    """Test MCP tools with mocked broker — verify JSON shapes and behavior."""

    def _setup(self):
        """Patch server globals with mock broker and in-memory repo."""
        import server
        mock_broker = MagicMock()
        server._broker = mock_broker
        server._kill_switch_state = {"active": False, "triggered_at": None, "reason": None}
        server._harness = None
        from persistence.repository import Repository
        repo = Repository(":memory:")
        server._repo = repo
        return mock_broker, repo

    # --- place_multileg_order ---

    def test_place_multileg_order_kill_switch_blocks(self):
        """Kill switch active → returns error JSON without calling broker."""
        import server
        mock_broker, repo = self._setup()
        server._kill_switch_state = {"active": True, "triggered_at": "2026-06-02T10:00:00", "reason": "daily loss limit breached"}

        legs_json = '[{"symbol":"AAPL260620C00230000","side":"buy_to_open","ratio_qty":1}]'
        result = server.place_multileg_order(legs_json, "limit", 1.50)

        data = json.loads(result)
        assert "error" in data
        assert "Kill switch is active" in data["error"]
        mock_broker.place_multileg_order.assert_not_called()

    def test_place_multileg_order_success(self):
        """Successful multi-leg order returns correct JSON shape."""
        import server
        from models import TradePlan, TradeTransaction
        mock_broker, repo = self._setup()

        # Save a matching plan so the FK constraint is satisfied
        plan = TradePlan(plan_id="plan-opts-001", symbol="AAPL", strategy="vertical_spread")
        repo.save_trade_plan(plan)

        tx = TradeTransaction(
            transaction_id="tx-mleg-001",
            plan_id="",
            symbol="AAPL",
            side="buy",
            order_type="limit",
            quantity=1,
            price=1.50,
            broker_order_id="broker-mleg-xyz",
            status="submitted",
        )
        mock_broker.place_multileg_order.return_value = tx
        # _log_to_ledger calls get_account via get_broker(); mock it
        mock_broker.get_account.return_value = {"equity": 100000, "cash": 90000, "buying_power": 180000}

        legs = [
            {"symbol": "AAPL260620C00230000", "side": "buy_to_open", "ratio_qty": 1},
            {"symbol": "AAPL260620C00240000", "side": "sell_to_open", "ratio_qty": 1},
        ]
        legs_json = json.dumps(legs)
        result = server.place_multileg_order(legs_json, "limit", 1.50, "plan-opts-001")

        data = json.loads(result)
        assert data["transaction_id"] == "tx-mleg-001"
        assert data["plan_id"] == "plan-opts-001"
        assert data["order_class"] == "mleg"
        assert data["status"] == "submitted"
        assert data["broker_order_id"] == "broker-mleg-xyz"
        assert isinstance(data["legs"], list)
        assert len(data["legs"]) == 2
        # qty defaults to 1 and is forwarded to the broker
        assert data["qty"] == 1
        assert mock_broker.place_multileg_order.call_args.kwargs["qty"] == 1

    def test_place_multileg_order_qty_forwarded(self):
        """Agent-computed qty reaches the broker adapter."""
        import server
        from models import TradeTransaction
        mock_broker, repo = self._setup()

        tx = TradeTransaction(
            transaction_id="tx-mleg-002", plan_id="", symbol="QQQ", side="sell",
            order_type="limit", quantity=6, price=1.03,
            broker_order_id="broker-mleg-abc", status="submitted",
        )
        mock_broker.place_multileg_order.return_value = tx
        mock_broker.get_account.return_value = {"equity": 100000, "cash": 90000, "buying_power": 180000}

        legs_json = json.dumps([
            {"symbol": "QQQ260620P00650000", "side": "sell_to_open", "ratio_qty": 1},
            {"symbol": "QQQ260620P00640000", "side": "buy_to_open", "ratio_qty": 1},
        ])
        result = server.place_multileg_order(legs_json, "limit", 1.03, "", 3)

        data = json.loads(result)
        assert "error" not in data, f"Unexpected error: {data}"
        assert data["qty"] == 3
        assert mock_broker.place_multileg_order.call_args.kwargs["qty"] == 3

    def test_place_multileg_order_qty_invalid_rejected(self):
        """qty < 1 → error JSON, broker never called."""
        import server
        mock_broker, repo = self._setup()

        legs_json = '[{"symbol":"QQQ260620P00650000","side":"sell_to_open","ratio_qty":1}]'
        result = server.place_multileg_order(legs_json, "limit", 1.03, "", 0)

        data = json.loads(result)
        assert "error" in data
        assert "qty" in data["error"]
        mock_broker.place_multileg_order.assert_not_called()

    def test_place_multileg_order_invalid_json(self):
        """Invalid legs JSON string → returns error with 'Invalid legs JSON'."""
        import server
        mock_broker, repo = self._setup()

        result = server.place_multileg_order("not-valid-json{{{", "limit", 1.50)

        data = json.loads(result)
        assert "error" in data
        assert "Invalid legs JSON" in data["error"]
        mock_broker.place_multileg_order.assert_not_called()

    # --- get_options_positions ---

    def test_get_options_positions_empty(self):
        """Broker returns no option positions → tool returns '[]'."""
        import server
        mock_broker, repo = self._setup()
        mock_broker.get_options_positions.return_value = []

        result = server.get_options_positions()

        data = json.loads(result)
        assert data == []

    # --- calc_iv_rank ---

    def test_calc_iv_rank_insufficient_history(self):
        """When bootstrap returns no IV history the tool returns an insufficient-data error."""
        import server
        mock_broker, repo = self._setup()

        # Provide a minimal chain: one ATM call at delta ~0.50
        chain = [{
            "symbol": "AAPL260620C00230000",
            "underlying": "AAPL",
            "strike": 230.0,
            "type": "C",
            "expiration": "260620",
            "dte": 18,
            "bid": 2.50,
            "ask": 2.60,
            "mid": 2.55,
            "volume": 100,
            "open_interest": 0,
            "iv": 0.30,
            "greeks": {"delta": 0.50, "gamma": 0.03, "theta": -0.05, "vega": 0.12, "rho": 0.01},
        }]
        mock_broker.get_option_chain.return_value = chain
        # Bootstrap returns empty IV history
        mock_broker.get_option_historical_iv.return_value = []
        mock_broker.get_account.return_value = {"equity": 100000, "cash": 90000, "buying_power": 180000}

        result = server.calc_iv_rank("AAPL")

        data = json.loads(result)
        assert "error" in data
        assert "Insufficient IV history" in data["error"]

    def test_calc_iv_rank_success(self):
        """With 70 IV data points in repo, calc_iv_rank returns a valid rank JSON."""
        import server
        mock_broker, repo = self._setup()

        # Pre-populate repo with 70 IV data points for AAPL
        from datetime import date, timedelta
        base = date(2025, 1, 1)
        for i in range(70):
            day = (base + timedelta(days=i)).isoformat()
            iv_val = 0.20 + (i / 1000)  # slight upward drift, range ~0.20–0.27
            repo.save_iv_data("AAPL", day, iv_val, "test")

        # Current chain: ATM call with IV = 0.25
        chain = [{
            "symbol": "AAPL260620C00230000",
            "underlying": "AAPL",
            "strike": 230.0,
            "type": "C",
            "expiration": "260620",
            "dte": 18,
            "bid": 2.50,
            "ask": 2.60,
            "mid": 2.55,
            "volume": 100,
            "open_interest": 0,
            "iv": 0.25,
            "greeks": {"delta": 0.50, "gamma": 0.03, "theta": -0.05, "vega": 0.12, "rho": 0.01},
        }]
        mock_broker.get_option_chain.return_value = chain
        mock_broker.get_account.return_value = {"equity": 100000, "cash": 90000, "buying_power": 180000}

        result = server.calc_iv_rank("AAPL")

        data = json.loads(result)
        assert "error" not in data, f"Unexpected error: {data}"
        assert data["symbol"] == "AAPL"
        assert "iv_rank" in data
        assert 0.0 <= data["iv_rank"] <= 100.0
        assert "current_iv" in data
        assert "iv_high_52w" in data
        assert "iv_low_52w" in data
        assert "data_points" in data
        assert data["data_points"] >= 60

    # --- calc_hv ---

    def test_calc_hv_success(self):
        """calc_hv with 252 bars returns valid hv JSON."""
        import server
        mock_broker, repo = self._setup()

        # Build 252 bars with steadily increasing close (zero-return HV test uses random)
        import random
        random.seed(99)
        closes = [100.0]
        for _ in range(251):
            closes.append(closes[-1] * (1 + random.gauss(0, 0.01)))
        bars = [{"close": c} for c in closes]
        mock_broker.get_historical_data.return_value = bars

        result = server.calc_hv("AAPL", 20)

        data = json.loads(result)
        assert "error" not in data, f"Unexpected error: {data}"
        assert data["symbol"] == "AAPL"
        assert "hv20" in data
        assert data["hv20"] > 0.0
        assert data["window"] == 20
        assert data["period_days"] == 252

    # --- get_options_chain IV cache ---

    def test_get_options_chain_caches_iv(self):
        """Calling get_options_chain should opportunistically cache ATM IV in repo."""
        import server
        mock_broker, repo = self._setup()

        chain = [{
            "symbol": "AAPL260620C00230000",
            "underlying": "AAPL",
            "strike": 230.0,
            "type": "C",
            "expiration": "260620",
            "dte": 18,
            "bid": 2.50,
            "ask": 2.60,
            "mid": 2.55,
            "volume": 100,
            "open_interest": 0,
            "iv": 0.28,
            "greeks": {"delta": 0.50, "gamma": 0.03, "theta": -0.05, "vega": 0.12, "rho": 0.01},
        }]
        mock_broker.get_option_chain.return_value = chain

        server.get_options_chain("AAPL")

        # Verify that IV was cached in repo
        count = repo.count_iv_history("AAPL")
        assert count > 0, "Expected at least one IV data point cached after get_options_chain"
