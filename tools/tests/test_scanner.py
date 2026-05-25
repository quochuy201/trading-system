"""Tests for the scanner module — same code path for backtest and live."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from scanner.filters import scan_universe


def _make_uptrend(symbol: str, days: int = 60, start_price: float = 100.0) -> pd.DataFrame:
    """Generate a stock in a realistic uptrend (pullbacks included so RSI stays in range)."""
    np.random.seed(42)
    prices = [start_price]
    for i in range(days - 1):
        # Uptrend with realistic pullbacks (some down days)
        change = np.random.uniform(-0.012, 0.018)  # slight upward bias
        prices.append(prices[-1] * (1 + change))

    rows = []
    for i, p in enumerate(prices):
        daily_range = p * 0.02  # 2% daily range
        vol = 3_000_000 + int(np.random.uniform(-500000, 1000000))
        if i == len(prices) - 1:
            vol = int(vol * 1.5)
        rows.append({
            "date": f"2026-01-{(i+1):02d}" if i < 28 else f"2026-02-{(i-27):02d}",
            "open": round(p - daily_range * 0.3, 2),
            "high": round(p + daily_range * 0.5, 2),
            "low": round(p - daily_range * 0.5, 2),
            "close": round(p, 2),
            "volume": vol,
        })
    return pd.DataFrame(rows)


def _make_downtrend(symbol: str, days: int = 60, start_price: float = 200.0) -> pd.DataFrame:
    """Generate a stock in a downtrend (should fail Filter 3: trend)."""
    np.random.seed(99)
    prices = [start_price]
    for _ in range(days - 1):
        prices.append(prices[-1] * (1 - np.random.uniform(0.002, 0.012)))

    rows = []
    for i, p in enumerate(prices):
        rows.append({
            "date": f"2026-01-{(i+1):02d}" if i < 28 else f"2026-02-{(i-27):02d}",
            "open": round(p * 1.002, 2),
            "high": round(p * 1.01, 2),
            "low": round(p * 0.99, 2),
            "close": round(p, 2),
            "volume": 3_000_000,
        })
    return pd.DataFrame(rows)


def _make_spy(days: int = 60, start_price: float = 500.0) -> pd.DataFrame:
    """Generate flat SPY (so relative strength is easy to measure)."""
    rows = []
    for i in range(days):
        rows.append({
            "date": f"2026-01-{(i+1):02d}" if i < 28 else f"2026-02-{(i-27):02d}",
            "open": start_price,
            "high": start_price * 1.005,
            "low": start_price * 0.995,
            "close": start_price,
            "volume": 50_000_000,
        })
    return pd.DataFrame(rows)


class TestScannerFilters:
    def test_uptrend_stock_passes(self):
        """A stock in a clean uptrend with volume should pass all filters."""
        stock_data = {"GOOD": _make_uptrend("GOOD")}
        spy = _make_spy()
        results = scan_universe(stock_data, spy)
        assert len(results) == 1
        assert results[0]["symbol"] == "GOOD"

    def test_downtrend_stock_filtered(self):
        """A stock in a downtrend should be filtered at layer 3 (trend)."""
        stock_data = {"BAD": _make_downtrend("BAD")}
        spy = _make_spy()
        results = scan_universe(stock_data, spy)
        assert len(results) == 0

    def test_spy_excluded_from_results(self):
        """SPY itself should never appear as a candidate."""
        stock_data = {"SPY": _make_spy(), "GOOD": _make_uptrend("GOOD")}
        spy = _make_spy()
        results = scan_universe(stock_data, spy)
        symbols = [r["symbol"] for r in results]
        assert "SPY" not in symbols

    def test_low_volume_filtered(self):
        """Stock with < 2M avg volume should fail Filter 1."""
        df = _make_uptrend("LOWVOL")
        df["volume"] = 500_000  # below 2M threshold
        stock_data = {"LOWVOL": df}
        spy = _make_spy()
        results = scan_universe(stock_data, spy)
        assert len(results) == 0

    def test_no_spy_skips_relative_strength(self):
        """Without SPY data, Filter 2 is skipped (more permissive)."""
        stock_data = {"TEST": _make_uptrend("TEST")}
        results = scan_universe(stock_data, spy_data=None)
        # Should still pass filters 1, 3, 4 even without RS check
        assert len(results) == 1

    def test_result_contains_required_fields(self):
        """Candidates must have all fields needed for AI DD."""
        stock_data = {"STOCK": _make_uptrend("STOCK")}
        spy = _make_spy()
        results = scan_universe(stock_data, spy)
        assert len(results) == 1
        c = results[0]
        required = ["symbol", "price", "atr", "atr_pct", "rvol", "rs_10d",
                    "rsi", "macd_bullish", "bb_pos", "sma20", "sma50"]
        for field in required:
            assert field in c, f"Missing field: {field}"

    def test_multiple_stocks_sorted_by_rs(self):
        """Results should be sorted by relative strength (strongest first)."""
        # Make two uptrending stocks with different rates
        fast = _make_uptrend("FAST", start_price=100)
        slow = _make_uptrend("SLOW", start_price=100)
        # Make FAST grow more in recent 10 days
        fast["close"].iloc[-10:] = fast["close"].iloc[-10:] * 1.05
        stock_data = {"FAST": fast, "SLOW": slow}
        spy = _make_spy()
        results = scan_universe(stock_data, spy)
        if len(results) == 2:
            assert results[0]["rs_10d"] >= results[1]["rs_10d"]
