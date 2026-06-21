"""load_price_cache must write 1Day bars from the data source, not the broker."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import data.cache as cache
from persistence.repository import Repository


class _FakeSource:
    def get_daily_bars(self, symbols, start, end):
        return {"AAA": [{"symbol": "AAA", "timestamp": "2026-06-18T00:00:00+00:00",
                         "open": 1, "high": 1, "low": 1, "close": 2,
                         "volume": 5, "timeframe": "1Day"}]}


def test_load_price_cache_uses_data_source(monkeypatch):
    monkeypatch.setattr(cache, "get_data_source", lambda: _FakeSource())
    repo = Repository(":memory:")
    summary = cache.load_price_cache(None, repo, ["AAA"], "2026-01-01", "2026-06-20")
    assert summary["bars_loaded"] == 1
    assert repo.latest_price_date("AAA") == "2026-06-18T00:00:00+00:00"
