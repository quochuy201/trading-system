"""Tests for decision audit models and repository methods."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import unittest
from datetime import datetime, timezone

from models import DecisionLogEntry, LedgerEntry, PerformanceReport, to_json, from_json
from persistence.repository import Repository


class TestAuditModels(unittest.TestCase):

    def test_decision_log_entry_roundtrip(self):
        d = DecisionLogEntry(
            decision_id="dec001", agent="trader", action="enter",
            symbol="NVDA", rules_triggered=["RSI_OVERSOLD", "VOLUME_CONFIRM"],
            rules_considered=["MACD_CROSS"], reasoning="Strong setup",
            sop_version="v1.0.0", plan_id="plan-001",
            market_context={"price": 220.5, "rsi": 28},
        )
        j = to_json(d)
        restored = from_json(DecisionLogEntry, j)
        assert restored.decision_id == "dec001"
        assert restored.rules_triggered == ["RSI_OVERSOLD", "VOLUME_CONFIRM"]
        assert restored.market_context["price"] == 220.5

    def test_ledger_entry_roundtrip(self):
        e = LedgerEntry(
            ledger_id="led001", action="buy", symbol="AAPL",
            quantity=10, order_type="market", price=303.50,
            total_cost=3035.0, status="filled", broker_order_id="abc123",
            account_equity=100000.0, account_cash=96965.0, buying_power=193930.0,
            platform="alpaca_paper", trigger="agent", sop_version="v1.0.0",
        )
        j = to_json(e)
        restored = from_json(LedgerEntry, j)
        assert restored.ledger_id == "led001"
        assert restored.total_cost == 3035.0
        assert restored.platform == "alpaca_paper"
        assert restored.pnl is None

    def test_ledger_entry_sell_with_pnl(self):
        e = LedgerEntry(
            action="sell", symbol="AAPL", quantity=10, price=310.0,
            total_cost=3100.0, status="filled", entry_price=303.50,
            pnl=65.0, pnl_pct=2.14, platform="alpaca_paper",
        )
        assert e.pnl == 65.0
        assert e.entry_price == 303.50

    def test_performance_report_roundtrip(self):
        r = PerformanceReport(
            report_id="rpt001", report_type="daily", sop_version="v1.0.0",
            metrics={"win_rate": 0.6, "profit_factor": 1.8, "total_pnl": 500.0},
        )
        j = to_json(r)
        restored = from_json(PerformanceReport, j)
        assert restored.metrics["win_rate"] == 0.6


class TestAuditRepository(unittest.TestCase):

    def setUp(self):
        self.repo = Repository(db_path=":memory:")

    def tearDown(self):
        self.repo.close()

    def test_save_and_query_decision(self):
        d = DecisionLogEntry(
            decision_id="dec001", agent="trader", action="enter",
            symbol="NVDA", rules_triggered=["STOP_HIT"],
            reasoning="Stop triggered", sop_version="v1.0.0",
        )
        self.repo.save_decision(d)
        results = self.repo.query_decisions(symbol="NVDA")
        assert len(results) == 1
        assert results[0]["decision_id"] == "dec001"
        assert results[0]["rules_triggered"] == ["STOP_HIT"]

    def test_query_decisions_filters(self):
        for i, action in enumerate(["enter", "hold", "hold", "exit"]):
            d = DecisionLogEntry(
                decision_id=f"dec{i}", agent="monitor", action=action,
                symbol="AAPL", sop_version="v1.0.0",
            )
            self.repo.save_decision(d)
        assert len(self.repo.query_decisions(action="hold")) == 2
        assert len(self.repo.query_decisions(action="exit")) == 1
        assert len(self.repo.query_decisions(symbol="NVDA")) == 0

    def test_query_decisions_violation_filter(self):
        d1 = DecisionLogEntry(decision_id="clean", agent="trader", action="enter",
                              symbol="X", violations=[])
        d2 = DecisionLogEntry(decision_id="bad", agent="trader", action="exit",
                              symbol="X", violations=["PANIC_SELL"])
        self.repo.save_decision(d1)
        self.repo.save_decision(d2)
        assert len(self.repo.query_decisions(has_violation=True)) == 1
        assert len(self.repo.query_decisions(has_violation=False)) == 1

    def test_save_and_query_ledger(self):
        e = LedgerEntry(
            ledger_id="led001", action="buy", symbol="NVDA",
            quantity=10, price=220.0, total_cost=2200.0,
            status="filled", platform="alpaca_paper", trigger="agent",
        )
        self.repo.save_ledger_entry(e)
        results = self.repo.query_ledger(symbol="NVDA")
        assert len(results) == 1
        assert results[0]["total_cost"] == 2200.0

    def test_query_ledger_filters(self):
        for i, (action, trigger) in enumerate([
            ("buy", "agent"), ("sell", "agent"), ("sell", "kill_switch"), ("cancel", "agent")
        ]):
            e = LedgerEntry(
                ledger_id=f"led{i}", action=action, symbol="AAPL",
                status="filled", platform="alpaca_paper", trigger=trigger,
            )
            self.repo.save_ledger_entry(e)
        assert len(self.repo.query_ledger(action="sell")) == 2
        assert len(self.repo.query_ledger(trigger="kill_switch")) == 1
        assert len(self.repo.query_ledger(action="cancel")) == 1

    def test_save_and_get_report(self):
        r = PerformanceReport(
            report_id="rpt001", report_type="daily", sop_version="v1.0.0",
            metrics={"win_rate": 0.6, "total_trades": 5},
        )
        self.repo.save_report(r)
        results = self.repo.get_reports(report_type="daily")
        assert len(results) == 1
        assert results[0]["metrics"]["win_rate"] == 0.6

    def test_tables_created_idempotently(self):
        """Verify new tables exist alongside old ones."""
        cursor = self.repo.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = [r[0] for r in cursor.fetchall()]
        assert "decisions" in tables
        assert "transaction_ledger" in tables
        assert "performance_reports" in tables
        # Old tables still exist
        assert "trade_plans" in tables
        assert "trade_transactions" in tables


class TestPerformanceCalculator(unittest.TestCase):

    def setUp(self):
        self.repo = Repository(db_path=":memory:")

    def tearDown(self):
        self.repo.close()

    def _add_sell(self, symbol, pnl, pnl_pct=0, sop="v1.0.0"):
        e = LedgerEntry(
            action="sell", symbol=symbol, quantity=10, price=100,
            total_cost=1000, status="filled", platform="alpaca_paper",
            pnl=pnl, pnl_pct=pnl_pct, sop_version=sop,
        )
        self.repo.save_ledger_entry(e)

    def test_basic_metrics(self):
        """3 wins, 2 losses → correct win rate, PF, expectancy."""
        for pnl in [100, 200, 150, -80, -120]:
            self._add_sell("AAPL", pnl)
        from audit.performance import calc_performance
        m = calc_performance(self.repo)
        assert m["total_trades"] == 5
        assert m["win_rate"] == 0.6
        assert m["total_pnl"] == 250.0
        assert m["avg_winner"] == 150.0
        assert m["avg_loser"] == -100.0
        assert m["profit_factor"] == round(450 / 200, 2)
        assert m["expectancy"] == 50.0

    def test_max_drawdown(self):
        """Drawdown calculated from cumulative P&L curve."""
        # +100, +50, -200, +300 → peak=150, trough=-50, dd=200
        for pnl in [100, 50, -200, 300]:
            self._add_sell("X", pnl)
        from audit.performance import calc_performance
        m = calc_performance(self.repo)
        assert m["max_drawdown"] == 200.0

    def test_empty_returns_zeroes(self):
        from audit.performance import calc_performance
        m = calc_performance(self.repo)
        assert m["total_trades"] == 0
        assert m["win_rate"] == 0

    def test_group_by_symbol(self):
        self._add_sell("AAPL", 100)
        self._add_sell("AAPL", -50)
        self._add_sell("NVDA", 200)
        from audit.performance import calc_performance
        m = calc_performance(self.repo)
        assert m["by_symbol"]["AAPL"]["trades"] == 2
        assert m["by_symbol"]["NVDA"]["total_pnl"] == 200.0

    def test_group_by_sop_version(self):
        self._add_sell("X", 100, sop="v1.0.0")
        self._add_sell("X", -50, sop="v1.0.0")
        self._add_sell("X", 200, sop="v1.1.0")
        from audit.performance import calc_performance
        m = calc_performance(self.repo)
        assert m["by_sop_version"]["v1.0.0"]["trades"] == 2
        assert m["by_sop_version"]["v1.1.0"]["total_pnl"] == 200.0


class TestComplianceScorer(unittest.TestCase):

    def setUp(self):
        self.repo = Repository(db_path=":memory:")

    def tearDown(self):
        self.repo.close()

    def _make_plan(self, plan_id="p1", stop=215.0, target=235.0):
        from models import TradePlan
        plan = TradePlan(plan_id=plan_id, symbol="NVDA", side="buy",
                         stop_loss=stop, take_profit=target)
        self.repo.save_trade_plan(plan)

    def test_panic_sell_detected(self):
        """Exit above stop without valid rule = PANIC_SELL."""
        self._make_plan()
        d = DecisionLogEntry(
            decision_id="d1", agent="monitor", action="exit", symbol="NVDA",
            rules_triggered=["FEAR_SIGNAL"], plan_id="p1",
            market_context={"price": 220.0},  # above stop of 215
        )
        self.repo.save_decision(d)
        from audit.compliance import score_decisions
        result = score_decisions(self.repo)
        assert result["by_type"].get("PANIC_SELL", 0) == 1

    def test_no_panic_sell_when_stop_hit(self):
        """Exit below stop with STOP_HIT rule = no violation."""
        self._make_plan()
        d = DecisionLogEntry(
            decision_id="d1", agent="monitor", action="exit", symbol="NVDA",
            rules_triggered=["STOP_HIT"], plan_id="p1",
            market_context={"price": 214.0},
        )
        self.repo.save_decision(d)
        from audit.compliance import score_decisions
        result = score_decisions(self.repo)
        assert result["compliance_rate"] == 1.0

    def test_early_exit_detected(self):
        """Exit below target without valid rule = EARLY_EXIT."""
        self._make_plan()
        d = DecisionLogEntry(
            decision_id="d1", agent="trader", action="exit", symbol="NVDA",
            rules_triggered=["VOLUME_DROP"], plan_id="p1",
            market_context={"price": 225.0},  # below target of 235
        )
        self.repo.save_decision(d)
        from audit.compliance import score_decisions
        result = score_decisions(self.repo)
        assert "EARLY_EXIT" in result["by_type"]

    def test_untagged_decision_detected(self):
        """Enter/exit with empty rules = UNTAGGED_DECISION."""
        d = DecisionLogEntry(
            decision_id="d1", agent="trader", action="enter", symbol="AAPL",
            rules_triggered=[],
        )
        self.repo.save_decision(d)
        from audit.compliance import score_decisions
        result = score_decisions(self.repo)
        assert result["by_type"].get("UNTAGGED_DECISION", 0) == 1

    def test_rule_conflict_detected(self):
        """Contradicting rules in same decision = RULE_CONFLICT."""
        d = DecisionLogEntry(
            decision_id="d1", agent="monitor", action="exit", symbol="X",
            rules_triggered=["STOP_HIT", "TAKE_PROFIT"],
        )
        self.repo.save_decision(d)
        from audit.compliance import score_decisions
        result = score_decisions(self.repo)
        assert result["by_type"].get("RULE_CONFLICT", 0) == 1

    def test_clean_decision_no_violations(self):
        """Hold with valid reasoning = no violations."""
        d = DecisionLogEntry(
            decision_id="d1", agent="monitor", action="hold", symbol="NVDA",
            rules_triggered=["PRICE_ABOVE_STOP", "BELOW_TARGET"],
            reasoning="Holding within range",
        )
        self.repo.save_decision(d)
        from audit.compliance import score_decisions
        result = score_decisions(self.repo)
        assert result["compliance_rate"] == 1.0
        assert result["violations"] == []


if __name__ == "__main__":
    unittest.main()


# --- go-live-metrics Task 7: v_performance_current + snapshot log ---
#
# The view answers everything that is a pure aggregate of round_trips, on read,
# so no job has to run and the answer can never be stale. Two properties matter
# more than the arithmetic: paper and live are never summed, and an unknown is
# NULL rather than a confident zero.

from datetime import datetime as _dt

import pytest as _pytest

from audit.performance import (
    current_performance,
    max_drawdown_r,
    path_metrics,
    sharpe,
    write_performance_snapshot,
)
from persistence.repository import Repository as _Repo


def _trip(repo, rt_id, *, mode="paper", strategy="swing", net_pnl=100.0,
          r=1.0, slippage=None, symbol="NVDA", exit_at="2026-01-01T00:00:00"):
    """Insert a round trip directly — this suite tests the aggregation, not
    the pairing (that is test_round_trips.py)."""
    repo.conn.execute(
        """INSERT INTO round_trips
        (round_trip_id, content_hash, symbol, strategy, direction, quantity,
         entry_price, exit_price, exit_at, gross_pnl, total_fees,
         fees_attributable, net_pnl, r_multiple, slippage, mode)
        VALUES (?,?,?,?,'long',100,10.0,11.0,?,?,0.0,0,?,?,?,?)""",
        (rt_id, "h" + rt_id, symbol, strategy, exit_at, net_pnl, net_pnl, r,
         slippage, mode),
    )
    repo.conn.commit()


class TestPerformanceView:
    def test_known_expectancy_is_exact(self):
        """R of +2, -1, +3, 0 -> expectancy 1.0. Hand-computed."""
        repo = _Repo(":memory:")
        for i, r in enumerate([2.0, -1.0, 3.0, 0.0]):
            _trip(repo, f"t{i}", r=r, net_pnl=r * 100)
        row = current_performance(repo)[0]
        assert row["total_trades"] == 4
        assert row["expectancy_r"] == _pytest.approx(1.0)
        assert row["r_computable_trades"] == 4
        assert row["r_excluded"] == 0
        repo.close()

    def test_null_r_excluded_from_expectancy_but_counted_as_a_trade(self):
        """A trade we cannot score is still a trade that happened."""
        repo = _Repo(":memory:")
        _trip(repo, "a", r=2.0, net_pnl=200.0)
        _trip(repo, "b", r=None, net_pnl=50.0)
        row = current_performance(repo)[0]
        assert row["total_trades"] == 2
        assert row["expectancy_r"] == _pytest.approx(2.0)  # the NULL is not a 0
        assert row["r_computable_trades"] == 1
        assert row["r_excluded"] == 1
        repo.close()

    def test_paper_and_live_are_never_summed(self):
        repo = _Repo(":memory:")
        _trip(repo, "p1", mode="paper", net_pnl=100.0, r=1.0)
        _trip(repo, "l1", mode="live", net_pnl=-500.0, r=-2.0)
        rows = {r["mode"]: r for r in current_performance(repo)}
        assert set(rows) == {"paper", "live"}
        assert rows["paper"]["total_net_pnl"] == 100.0
        assert rows["live"]["total_net_pnl"] == -500.0
        assert current_performance(repo, mode="paper") == [rows["paper"]]
        repo.close()

    def test_null_net_pnl_does_not_understate_win_rate(self):
        """F10. `SUM(net_pnl > 0)` alone yields NULL for a NULL-P&L row, which
        would drag the rate down. COUNT(net_pnl) drops it from BOTH sides."""
        repo = _Repo(":memory:")
        _trip(repo, "w", net_pnl=100.0, r=1.0)
        _trip(repo, "l", net_pnl=-50.0, r=-1.0)
        _trip(repo, "u", net_pnl=None, r=None)
        row = current_performance(repo)[0]
        assert row["total_trades"] == 3
        assert row["win_rate"] == _pytest.approx(0.5)  # 1 of 2 scoreable, not 1 of 3
        repo.close()

    def test_empty_set_returns_nothing_rather_than_zeros(self):
        repo = _Repo(":memory:")
        assert current_performance(repo) == []
        repo.close()

    def test_all_losses_gives_a_profit_factor_of_zero(self):
        """Zero here is a real measurement — made nothing, lost something —
        and must NOT be confused with the undefined case below."""
        repo = _Repo(":memory:")
        _trip(repo, "a", net_pnl=-10.0, r=-1.0)
        row = current_performance(repo)[0]
        assert row["profit_factor"] == _pytest.approx(0.0)
        assert row["total_net_pnl"] == -10.0
        repo.close()

    def test_no_losses_gives_null_profit_factor_not_a_crash(self):
        """Nothing to divide by. NULLIF turns the zero denominator into NULL —
        'undefined' — rather than raising or reporting a confident number."""
        repo = _Repo(":memory:")
        _trip(repo, "a", net_pnl=100.0, r=1.0)
        row = current_performance(repo)[0]
        assert row["profit_factor"] is None
        assert row["win_rate"] == _pytest.approx(1.0)
        repo.close()

    def test_no_wins_and_no_losses_does_not_divide_by_zero(self):
        repo = _Repo(":memory:")
        _trip(repo, "a", net_pnl=0.0, r=0.0)
        row = current_performance(repo)[0]
        assert row["profit_factor"] is None
        assert row["win_rate"] == _pytest.approx(0.0)
        repo.close()

    def test_strategies_are_grouped_separately(self):
        repo = _Repo(":memory:")
        _trip(repo, "s1", strategy="swing", r=2.0)
        _trip(repo, "m1", strategy="momentum", r=-1.0)
        rows = {r["strategy"]: r for r in current_performance(repo)}
        assert rows["swing"]["expectancy_r"] == _pytest.approx(2.0)
        assert rows["momentum"]["expectancy_r"] == _pytest.approx(-1.0)
        repo.close()

    def test_view_needs_no_job_to_run(self):
        """Insert a trip and read immediately — no rebuild, no refresh."""
        repo = _Repo(":memory:")
        _trip(repo, "a", r=1.5)
        assert current_performance(repo)[0]["expectancy_r"] == _pytest.approx(1.5)
        _trip(repo, "b", r=2.5)
        assert current_performance(repo)[0]["expectancy_r"] == _pytest.approx(2.0)
        repo.close()


class TestPathDependentMetrics:
    def test_max_drawdown_hand_computed(self):
        # cumulative: 100, 60, 160, 110 -> peak 160, trough 110 -> 50
        assert max_drawdown_r([100.0, -40.0, 100.0, -50.0]) == _pytest.approx(50.0)

    def test_a_curve_that_only_rises_has_no_drawdown(self):
        assert max_drawdown_r([10.0, 20.0, 30.0]) == 0.0

    def test_empty_series_is_unknown_not_zero(self):
        assert max_drawdown_r([]) is None

    def test_sharpe_needs_dispersion(self):
        assert sharpe([1.0]) is None            # one point
        assert sharpe([2.0, 2.0, 2.0]) is None  # zero variance is undefined
        assert sharpe([1.0, 2.0, 3.0]) == _pytest.approx(2.0 / 1.0)

    def test_path_metrics_respects_exit_order_and_mode(self):
        repo = _Repo(":memory:")
        _trip(repo, "a", net_pnl=100.0, r=1.0, exit_at="2026-01-01T00:00:00")
        _trip(repo, "b", net_pnl=-40.0, r=-0.5, exit_at="2026-01-02T00:00:00")
        _trip(repo, "z", mode="live", net_pnl=-9999.0, r=-9.0,
              exit_at="2026-01-03T00:00:00")

        paper = path_metrics(repo, "paper")
        assert paper["trades"] == 2
        assert paper["max_drawdown"] == _pytest.approx(40.0)
        assert path_metrics(repo, "live")["max_drawdown"] == _pytest.approx(9999.0)
        repo.close()


class TestSnapshotLog:
    def test_writes_one_row_per_strategy(self):
        repo = _Repo(":memory:")
        _trip(repo, "s1", strategy="swing", r=2.0, net_pnl=200.0)
        _trip(repo, "m1", strategy="momentum", r=-1.0, net_pnl=-100.0)

        assert write_performance_snapshot(repo, "paper",
                                          as_of=_dt(2026, 8, 16)) == 2
        rows = repo.conn.execute(
            "SELECT * FROM performance_metrics ORDER BY strategy").fetchall()
        assert [r["strategy"] for r in rows] == ["momentum", "swing"]
        assert rows[1]["expectancy_r"] == _pytest.approx(2.0)
        assert rows[1]["mode"] == "paper"
        assert rows[0]["snapshot_at"].startswith("2026-08-16")
        repo.close()

    def test_snapshot_records_the_exclusion_count(self):
        repo = _Repo(":memory:")
        _trip(repo, "a", r=2.0, net_pnl=200.0)
        _trip(repo, "b", r=None, net_pnl=50.0)
        write_performance_snapshot(repo, "paper")
        row = repo.conn.execute("SELECT * FROM performance_metrics").fetchone()
        assert row["total_trades"] == 2 and row["r_excluded"] == 1
        repo.close()

    def test_no_trips_writes_nothing_and_does_not_raise(self):
        repo = _Repo(":memory:")
        assert write_performance_snapshot(repo, "paper") == 0
        repo.close()

    def test_the_log_is_append_only_history_not_a_cache(self):
        """Two days of snapshots must both survive — this is a record of what
        the numbers WERE, unlike the view which is what they ARE."""
        repo = _Repo(":memory:")
        _trip(repo, "a", r=1.0)
        write_performance_snapshot(repo, "paper", as_of=_dt(2026, 8, 15))
        write_performance_snapshot(repo, "paper", as_of=_dt(2026, 8, 16))
        assert repo.conn.execute(
            "SELECT COUNT(*) c FROM performance_metrics").fetchone()["c"] == 2
        repo.close()
