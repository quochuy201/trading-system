"""Tests for get_daily_funnel assembly (scan + verdicts + orders + why_zero)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import server
from persistence.repository import Repository


def test_get_daily_funnel_zero_day(monkeypatch):
    class _Repo:
        def query_scan_funnel(self, date):
            return [{"scan_type": "swing", "scanned": 400, "passed": 11,
                     "passed_m": 6, "passed_r": 5, "data_stale": 0,
                     "as_of": "2026-06-18", "candidates": "[]"}]
        def query_decisions(self, **k): return []        # agent logged nothing
        def query_ledger(self, **k): return []           # no orders
    monkeypatch.setattr(server, "get_repo", lambda: _Repo())
    out = json.loads(server.get_daily_funnel("2026-06-22"))
    assert out["scan"]["passed"] == 11
    assert out["verdicts"]["entered"] == 0
    assert out["orders"] == 0
    assert "11 passed" in out["why_zero"] and "0 entered" in out["why_zero"]


def test_get_daily_funnel_counts_same_day_entries(monkeypatch):
    """Boundary: same-day decisions/orders must be found despite ISO timestamps.

    Decisions/orders are stored with full ISO timestamps (e.g.
    '2026-06-22T14:30:00'). A naive 'timestamp <= 2026-06-22' upper bound would
    exclude the whole day. This locks in the inclusive end-of-day boundary so a
    day that DID trade is never misreported as a zero day.
    """
    repo = Repository(":memory:")
    repo.save_scan_funnel({
        "date": "2026-06-22", "timestamp": "2026-06-22T06:40:00",
        "scan_type": "swing", "universe_size": 400, "loaded": 400,
        "scanned": 400, "passed": 3, "passed_m": 2, "passed_r": 1,
        "data_stale": 0, "as_of": "2026-06-22", "candidates": "[]"})
    repo.conn.execute(
        """INSERT INTO decisions (decision_id, timestamp, agent, action, symbol,
           rules_triggered, rules_considered, reasoning, sop_version, plan_id,
           market_context, violations)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        ("d1", "2026-06-22T14:30:00", "research", "enter", "NVDA",
         "[]", "[]", "momentum continuation", "v1", None, "{}", "[]"))
    repo.conn.execute(
        """INSERT INTO transaction_ledger (ledger_id, timestamp, action, symbol,
           status, platform) VALUES (?,?,?,?,?,?)""",
        ("l1", "2026-06-22T14:31:00", "buy", "NVDA", "filled", "paper"))
    repo.conn.commit()

    monkeypatch.setattr(server, "get_repo", lambda: repo)
    out = json.loads(server.get_daily_funnel("2026-06-22"))
    assert out["verdicts"]["entered"] == 1
    assert out["verdicts"]["enter_list"][0]["symbol"] == "NVDA"
    assert out["orders"] == 1
    assert "1 entered" in out["why_zero"]
