"""get_market_data must return a consolidated price from the data source."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import server


class _FakeSource:
    def get_last_price(self, symbol):
        return 123.45


def test_get_market_data_uses_data_source(monkeypatch):
    monkeypatch.setattr(server, "get_data_source", lambda: _FakeSource(), raising=False)
    out = json.loads(server.get_market_data("AAPL"))
    assert out["symbol"] == "AAPL"
    assert out["price"] == 123.45
    assert out["mid"] == 123.45


def test_get_market_data_handles_missing(monkeypatch):
    class _None:
        def get_last_price(self, s): return None
    monkeypatch.setattr(server, "get_data_source", lambda: _None(), raising=False)
    out = json.loads(server.get_market_data("AAPL"))
    assert "error" in out


def test_get_market_data_handles_source_failure(monkeypatch):
    class _Boom:
        def get_last_price(self, s): raise RuntimeError("network down")
    monkeypatch.setattr(server, "get_data_source", lambda: _Boom(), raising=False)
    out = json.loads(server.get_market_data("AAPL"))
    assert "error" in out
