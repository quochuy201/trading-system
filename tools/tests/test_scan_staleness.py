"""Scan tools must surface data staleness instead of a silent empty result."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import server


def test_scan_swing_reports_staleness(monkeypatch):
    # Force an empty universe load so we exercise only the staleness annotation.
    monkeypatch.setattr(server, "_universe_symbols", lambda b: ["AAA"], raising=False)

    class _Repo:
        def query_price_data(self, *a, **k): return []
        def latest_price_date(self, s, tf="1Day"): return "2026-06-12T00:00:00+00:00"
    monkeypatch.setattr(server, "get_repo", lambda: _Repo())

    class _Broker:  # no current_time → live branch uses utcnow()
        pass
    monkeypatch.setattr(server, "get_broker", lambda: _Broker())

    out = json.loads(server.scan_swing_candidates("AAA"))
    assert "data_stale" in out and "as_of" in out and "stale_count" in out


def test_scan_for_candidates_reports_staleness(monkeypatch):
    # Force an empty universe load so we exercise only the staleness annotation.
    monkeypatch.setattr(server, "_universe_symbols", lambda b: ["AAA"], raising=False)

    class _Repo:
        def query_price_data(self, *a, **k): return []
        def latest_price_date(self, s, tf="1Day"): return "2026-06-12T00:00:00+00:00"
    monkeypatch.setattr(server, "get_repo", lambda: _Repo())

    class _Broker:  # no current_time → live branch uses utcnow()
        pass
    monkeypatch.setattr(server, "get_broker", lambda: _Broker())

    out = json.loads(server.scan_for_candidates("AAA"))
    assert "data_stale" in out and "as_of" in out and "stale_count" in out
