"""Tests for data cache and technical analysis tools."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from persistence.repository import Repository
from data.cache import load_price_cache, query_price_cache
from analysis.indicators import calc_technical_indicators


def _sample_bars(symbol: str, n: int = 60) -> list[dict]:
    """Generate n days of synthetic price data."""
    import random
    random.seed(42)
    bars = []
    price = 150.0
    for i in range(n):
        change = random.uniform(-3, 3)
        o = price
        h = price + abs(change) + random.uniform(0, 2)
        l = price - abs(change) - random.uniform(0, 2)
        c = price + change
        price = c
        bars.append({
            "symbol": symbol,
            "timestamp": f"2024-01-{(i+1):02d}T09:30:00",
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(l, 2),
            "close": round(c, 2),
            "volume": random.randint(500000, 3000000),
            "timeframe": "1Day",
        })
    return bars


# --- Price Cache Tests ---


class TestPriceCache:
    def setup_method(self):
        self.repo = Repository(":memory:")

    def teardown_method(self):
        self.repo.close()

    def test_load_price_cache(self):
        mock_broker = MagicMock()
        mock_broker.get_historical_data.return_value = _sample_bars("AAPL", 5)

        result = load_price_cache(
            mock_broker, self.repo, ["AAPL"], "2024-01-01", "2024-01-10"
        )
        assert result["bars_loaded"] == 5
        assert result["symbols"] == ["AAPL"]
        mock_broker.get_historical_data.assert_called_once()

    def test_load_multiple_symbols(self):
        mock_broker = MagicMock()
        mock_broker.get_historical_data.side_effect = [
            _sample_bars("AAPL", 3),
            _sample_bars("MSFT", 3),
        ]

        result = load_price_cache(
            mock_broker, self.repo, ["AAPL", "MSFT"], "2024-01-01", "2024-01-05"
        )
        assert result["bars_loaded"] == 6
        assert mock_broker.get_historical_data.call_count == 2

    def test_query_price_cache(self):
        self.repo.save_price_bars(_sample_bars("AAPL", 10))
        bars = query_price_cache(self.repo, "AAPL", "2024-01-01", "2024-01-15")
        assert len(bars) == 10
        assert bars[0]["symbol"] == "AAPL"

    def test_query_empty_cache(self):
        bars = query_price_cache(self.repo, "AAPL", "2024-01-01", "2024-01-15")
        assert bars == []


# --- Technical Indicators Tests ---


class TestTechnicalIndicators:
    def setup_method(self):
        self.repo = Repository(":memory:")
        self.repo.save_price_bars(_sample_bars("AAPL", 60))

    def teardown_method(self):
        self.repo.close()

    def test_basic_indicators(self):
        result = calc_technical_indicators(
            self.repo, "AAPL", "2024-01-01", "2024-03-15"
        )
        assert "error" not in result
        assert "rsi" in result
        assert "macd" in result
        assert "sma_20" in result
        assert "atr" in result
        assert "volume_ratio" in result
        assert 0 <= result["rsi"] <= 100
        assert result["atr"] > 0
        assert result["volume_ratio"] > 0

    def test_sma_values(self):
        result = calc_technical_indicators(
            self.repo, "AAPL", "2024-01-01", "2024-03-15"
        )
        assert result["sma_20"] > 0
        assert result["sma_50"] > 0
        # SMA200 should be None with only 60 bars
        assert result["sma_200"] is None

    def test_insufficient_data(self):
        repo = Repository(":memory:")
        repo.save_price_bars(_sample_bars("XYZ", 5))
        result = calc_technical_indicators(repo, "XYZ", "2024-01-01", "2024-01-10")
        assert "error" in result
        repo.close()

    def test_above_sma_flags(self):
        result = calc_technical_indicators(
            self.repo, "AAPL", "2024-01-01", "2024-03-15"
        )
        assert isinstance(result["above_sma20"], bool)
        assert isinstance(result["above_sma50"], bool)
