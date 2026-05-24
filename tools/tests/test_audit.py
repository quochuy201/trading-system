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
