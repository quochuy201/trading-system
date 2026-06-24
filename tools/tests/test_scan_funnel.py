"""Tests for scan_funnel persistence + assembly."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from persistence.repository import Repository


def _row(date="2026-06-22", **kw):
    base = dict(date=date, timestamp=f"{date}T06:40:00", scan_type="swing",
                universe_size=400, loaded=400, scanned=400, passed=11,
                passed_m=6, passed_r=5, data_stale=0, as_of="2026-06-18",
                candidates='[]')
    base.update(kw)
    return base


def test_save_and_query_scan_funnel():
    repo = Repository(":memory:")
    repo.save_scan_funnel(_row())
    rows = repo.query_scan_funnel("2026-06-22")
    assert len(rows) == 1
    assert rows[0]["passed_m"] == 6 and rows[0]["passed"] == 11
    assert rows[0]["as_of"] == "2026-06-18"
    assert repo.query_scan_funnel("2026-06-21") == []


def test_scan_swing_persists_funnel(monkeypatch):
    import server
    monkeypatch.setattr(server, "_universe_symbols", lambda b: ["AAA"], raising=False)

    class _Repo:
        saved = []
        def query_price_data(self, *a, **k): return []
        def latest_price_date(self, s, tf="1Day"): return "2026-06-18T00:00:00+00:00"
        def save_scan_funnel(self, row): _Repo.saved.append(row)
    monkeypatch.setattr(server, "get_repo", lambda: _Repo())
    monkeypatch.setattr(server, "get_broker", lambda: object())

    server.scan_swing_candidates("AAA")
    assert len(_Repo.saved) == 1
    row = _Repo.saved[0]
    assert row["scan_type"] == "swing"
    assert "passed" in row and "passed_m" in row and "as_of" in row
