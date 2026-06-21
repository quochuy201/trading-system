"""Tests for data validation (pure / in-memory)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.validate import find_price_anomalies, is_stale, freshness_report


def _bars(closes, symbol="X"):
    return [{"symbol": symbol, "timestamp": f"2026-06-{10+i:02d}T00:00:00+00:00",
             "close": c} for i, c in enumerate(closes)]


def test_find_price_anomalies_flags_split_cliff():
    out = find_price_anomalies(_bars([1348.0, 91.7, 90.0]))  # 15:1 split look-alike
    assert len(out) == 1
    assert out[0]["symbol"] == "X"
    assert out[0]["pct"] > 90


def test_find_price_anomalies_clean_series():
    assert find_price_anomalies(_bars([100, 101, 99, 102])) == []


def test_is_stale():
    assert is_stale("2026-06-12", "2026-06-20", max_age_days=3) is True
    assert is_stale("2026-06-18", "2026-06-19", max_age_days=3) is False
    assert is_stale(None, "2026-06-19") is True


class _StubRepo:
    def __init__(self, dates):
        self._d = dates
    def latest_price_date(self, symbol, timeframe="1Day"):
        return self._d.get(symbol)


def test_freshness_report_detects_patchwork():
    repo = _StubRepo({"SPY": "2026-06-18T00:00:00+00:00",
                      "AAPL": "2026-06-18T00:00:00+00:00",
                      "PM": "2026-06-12T00:00:00+00:00",
                      "ZZZ": None})
    rep = freshness_report(repo, ["SPY", "AAPL", "PM", "ZZZ"])
    assert rep["freshest"] == "2026-06-18"
    assert rep["n_fresh"] == 2
    assert rep["stale"] == ["PM"]
    assert rep["missing"] == ["ZZZ"]
    assert rep["aligned"] is False


def test_is_stale_boundary_equals_max_age():
    # gap of exactly 3 days with max_age_days=3 → within tolerance, not stale
    assert is_stale("2026-06-15", "2026-06-18", max_age_days=3) is False
    assert is_stale("2026-06-15", "2026-06-19", max_age_days=3) is True


def test_find_price_anomalies_empty():
    assert find_price_anomalies([]) == []


def test_freshness_report_all_missing():
    class _Repo:
        def latest_price_date(self, s, timeframe="1Day"): return None
    rep = freshness_report(_Repo(), ["AAA", "BBB"])
    assert rep["freshest"] is None
    assert rep["missing"] == ["AAA", "BBB"]
    assert rep["aligned"] is False
