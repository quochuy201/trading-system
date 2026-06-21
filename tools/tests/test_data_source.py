"""Tests for the MarketDataSource adapter (offline — no network)."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.source import YFinanceSource, get_data_source, MarketDataSource


def test_normalize_bars_shapes_rows_and_format():
    idx = pd.to_datetime(["2026-06-17", "2026-06-18"])
    df = pd.DataFrame(
        {"Open": [10.0, 11.0], "High": [10.5, 11.5], "Low": [9.5, 10.5],
         "Close": [10.2, 11.2], "Volume": [1000, 2000]}, index=idx)
    rows = YFinanceSource()._normalize_bars(df, "TEST")
    assert len(rows) == 2
    assert rows[0] == {
        "symbol": "TEST", "timestamp": "2026-06-17T00:00:00+00:00",
        "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.2,
        "volume": 1000.0, "timeframe": "1Day"}


def test_normalize_bars_skips_nan_close():
    idx = pd.to_datetime(["2026-06-17", "2026-06-18"])
    df = pd.DataFrame(
        {"Open": [10.0, float("nan")], "High": [10.5, float("nan")],
         "Low": [9.5, float("nan")], "Close": [10.2, float("nan")],
         "Volume": [1000, float("nan")]}, index=idx)
    rows = YFinanceSource()._normalize_bars(df, "TEST")
    assert len(rows) == 1


def test_factory_default_is_yfinance():
    src = get_data_source()
    assert isinstance(src, MarketDataSource)
    assert isinstance(src, YFinanceSource)


def test_factory_unknown_raises():
    import pytest
    with pytest.raises(ValueError):
        get_data_source("bloomberg")


def test_get_daily_bars_single_symbol_multiindex(monkeypatch):
    """get_daily_bars must handle a MultiIndex DataFrame for a single-symbol list.

    yfinance 1.4.x always returns MultiIndex columns when group_by='ticker' is
    used, even for a single ticker.  The previous `else df` branch passed the
    raw MultiIndex frame to _normalize_bars, causing KeyError: 'Close'.
    """
    idx = pd.to_datetime(["2026-06-17"])
    columns = pd.MultiIndex.from_tuples(
        [("SPY", "Open"), ("SPY", "High"), ("SPY", "Low"),
         ("SPY", "Close"), ("SPY", "Volume")]
    )
    fake_df = pd.DataFrame(
        [[560.0, 562.0, 558.0, 561.0, 100_000.0]],
        index=idx,
        columns=columns,
    )

    monkeypatch.setattr("yfinance.download", lambda *a, **k: fake_df)

    result = YFinanceSource().get_daily_bars(["SPY"], "2026-06-17", "2026-06-18")

    assert list(result.keys()) == ["SPY"]
    bars = result["SPY"]
    assert len(bars) == 1
    bar = bars[0]
    assert set(bar.keys()) == {"symbol", "timestamp", "open", "high", "low", "close", "volume", "timeframe"}
    assert bar["symbol"] == "SPY"
    assert bar["close"] == 561.0
    assert bar["open"] == 560.0
    assert bar["timeframe"] == "1Day"
