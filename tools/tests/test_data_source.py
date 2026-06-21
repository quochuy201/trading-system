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
