"""Tests for the refresh_market_data MCP tool (network-free, monkeypatched)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import server


class _Src:
    def get_daily_bars(self, symbols, start, end):
        return {symbols[0]: [{"symbol": symbols[0], "timestamp": "2026-06-19T00:00:00+00:00",
                              "open": 1, "high": 1, "low": 1, "close": 1, "volume": 9,
                              "timeframe": "1Day"}]}


def test_refresh_market_data(monkeypatch):
    monkeypatch.setattr(server, "get_data_source", lambda: _Src(), raising=False)
    monkeypatch.setattr(server, "_universe_symbols", lambda b: ["AAA"], raising=False)

    class _Repo:
        saved = []
        def save_price_bars(self, bars): _Repo.saved += bars
        def latest_price_date(self, s, tf="1Day"): return "2026-06-19T00:00:00+00:00"
    monkeypatch.setattr(server, "get_repo", lambda: _Repo())
    monkeypatch.setattr(server, "get_broker", lambda: object())

    out = json.loads(server.refresh_market_data("2026-06-20"))
    assert out["bars"] == 1
    assert out["refreshed"] == 1


def test_refresh_includes_daily_end_bar(monkeypatch):
    """The source contract is half-open [start, end); to fetch daily_end's own
    bar the tool must call the source with end = daily_end + 1 day. Otherwise
    every refresh lands one trading day short (the live data-staleness bug)."""
    class _RecSrc:
        seen = {}
        def get_daily_bars(self, symbols, start, end):
            _RecSrc.seen = {"start": start, "end": end}
            return {}
    monkeypatch.setattr(server, "get_data_source", lambda: _RecSrc(), raising=False)
    monkeypatch.setattr(server, "_universe_symbols", lambda b: ["AAA"], raising=False)

    class _Repo:
        def save_price_bars(self, bars): pass
        def latest_price_date(self, s, tf="1Day"): return "2026-06-22T00:00:00+00:00"
    monkeypatch.setattr(server, "get_repo", lambda: _Repo())
    monkeypatch.setattr(server, "get_broker", lambda: object())

    server.refresh_market_data("2026-06-22")
    # daily_end's own bar must be inside the half-open window -> exclusive end is the next day
    assert _RecSrc.seen["end"] == "2026-06-23"
