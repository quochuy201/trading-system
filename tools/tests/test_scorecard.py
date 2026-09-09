"""Tests for the D5 go-live scorecard (go-live-metrics Task 9).

The scorecard reads `round_trips` and reports readiness against the D5 ladder.
The property that matters most: an unmeasurable criterion is *unknown*, never a
pass — so the verdict cannot read READY on partial evidence. See design §8
(honest-data rules) and BUILD-PLAN D5.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from audit.performance import (
    GO_LIVE_TRADES_FLOOR,
    go_live_scorecard,
)
from persistence.repository import Repository

_seq = 0


def _trip(repo, *, mode="paper", strategy="swing", r_multiple=1.0,
          regime="bull", net_pnl=100.0, reason=None):
    """Insert one round_trips row. r_multiple=None marks an R-excluded trip."""
    global _seq
    _seq += 1
    repo.conn.execute(
        """INSERT INTO round_trips
           (round_trip_id, content_hash, symbol, strategy, direction, quantity,
            net_pnl, r_multiple, r_uncomputable_reason, regime_at_entry, mode,
            fees_attributable)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,1)""",
        (f"rt-{_seq}", f"h-{_seq}", "NVDA", strategy, "long", 10,
         net_pnl, r_multiple, reason, regime, mode),
    )
    repo.conn.commit()


@pytest.fixture
def repo():
    return Repository(":memory:")


def test_empty_paper_is_not_ready(repo):
    """Acceptance: with no trades, trades read 0/floor and the verdict is NOT READY."""
    sc = go_live_scorecard(repo, "paper")
    assert sc["mode"] == "paper"
    assert sc["criteria"]["trades"]["value"] == 0
    assert sc["criteria"]["trades"]["floor"] == GO_LIVE_TRADES_FLOOR
    assert sc["criteria"]["trades"]["pass"] is False
    assert sc["verdict"] == "NOT READY"


def test_expectancy_is_none_not_zero_when_no_r(repo):
    """Honest-data rule 5: no R-computable trip ⇒ expectancy is null, never 0.0."""
    # Two closed trips that are structurally excluded from R (no order recorded).
    _trip(repo, r_multiple=None, reason="no_order_recorded")
    _trip(repo, r_multiple=None, reason="no_order_recorded")
    sc = go_live_scorecard(repo, "paper")
    assert sc["criteria"]["trades"]["value"] == 0        # R-computable count
    assert sc["r_excluded"] == 2                          # kept visible
    assert sc["criteria"]["expectancy_r"]["value"] is None
    assert sc["criteria"]["expectancy_r"]["pass"] is None  # unknown, not fail


def test_measurable_criteria_pass_but_unknowns_still_block_ready(repo):
    """The core fence: even when every *measurable* criterion passes, the
    verdict stays NOT READY because gate/D7/paper-vs-backtest are unknown."""
    for i in range(GO_LIVE_TRADES_FLOOR):
        _trip(repo, r_multiple=0.5, regime="bull" if i % 2 else "bear")
    sc = go_live_scorecard(repo, "paper")
    assert sc["criteria"]["trades"]["pass"] is True
    assert sc["criteria"]["expectancy_r"]["value"] == pytest.approx(0.5)
    assert sc["criteria"]["expectancy_r"]["pass"] is True
    assert sc["criteria"]["regimes"]["value"] == 2
    assert sc["criteria"]["regimes"]["pass"] is True
    # The unmeasurable three are unknown — never a pass.
    for key in ("paper_vs_backtest", "gate_live", "d7_edge"):
        assert sc["criteria"][key]["pass"] is None
        assert sc["criteria"][key]["status"] == "UNAVAILABLE"
    assert sc["verdict"] == "NOT READY"


def test_negative_expectancy_fails(repo):
    for _ in range(GO_LIVE_TRADES_FLOOR):
        _trip(repo, r_multiple=-0.3, regime="bull")
    sc = go_live_scorecard(repo, "paper")
    assert sc["criteria"]["expectancy_r"]["value"] < 0
    assert sc["criteria"]["expectancy_r"]["pass"] is False


def test_single_regime_fails_regime_criterion(repo):
    for _ in range(GO_LIVE_TRADES_FLOOR):
        _trip(repo, r_multiple=1.0, regime="bull")
    sc = go_live_scorecard(repo, "paper")
    assert sc["criteria"]["regimes"]["value"] == 1
    assert sc["criteria"]["regimes"]["pass"] is False


def test_modes_never_mix(repo):
    """paper and live are never summed — a live trip must not count for paper."""
    _trip(repo, mode="live", r_multiple=1.0, regime="bull")
    sc = go_live_scorecard(repo, "paper")
    assert sc["criteria"]["trades"]["value"] == 0
    assert sc["r_excluded"] == 0
    sc_live = go_live_scorecard(repo, "live")
    assert sc_live["criteria"]["trades"]["value"] == 1


def test_tool_returns_valid_json(monkeypatch, repo):
    """The MCP wrapper returns a JSON string with the verdict."""
    import server
    monkeypatch.setattr(server, "get_repo", lambda: repo)
    out = json.loads(server.get_go_live_scorecard("paper"))
    assert out["verdict"] == "NOT READY"
    assert out["criteria"]["trades"]["value"] == 0


def test_tool_never_raises(monkeypatch):
    """Observation-only tool: an internal failure returns {"error": ...}, never raises."""
    import server

    def _boom():
        raise RuntimeError("db exploded")

    monkeypatch.setattr(server, "get_repo", _boom)
    out = json.loads(server.get_go_live_scorecard("paper"))
    assert "error" in out
