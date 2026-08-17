"""Tests for data models and persistence layer."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime

from models import (
    Fill,
    JournalEntry,
    Order,
    TradePlan,
    TradeTransaction,
    WorkflowCheckpoint,
    to_json,
    from_json,
)
from persistence.db import get_connection, init_db
from persistence.repository import Repository


# --- Model Serialization Tests ---


class TestModelSerialization:
    def test_trade_plan_roundtrip(self):
        plan = TradePlan(
            plan_id="abc123", symbol="AAPL", strategy="momentum",
            side="buy", quantity=100, take_profit=155.0, stop_loss=145.0,
            rationale="Strong RSI bounce",
        )
        json_str = to_json(plan)
        restored = from_json(TradePlan, json_str)
        assert restored.plan_id == "abc123"
        assert restored.symbol == "AAPL"
        assert restored.quantity == 100
        assert restored.take_profit == 155.0

    def test_trade_transaction_roundtrip(self):
        tx = TradeTransaction(
            transaction_id="tx001", plan_id="abc123", symbol="AAPL",
            side="buy", order_type="market", quantity=100, price=150.25,
            broker_order_id="BRK-001", status="filled",
        )
        json_str = to_json(tx)
        restored = from_json(TradeTransaction, json_str)
        assert restored.transaction_id == "tx001"
        assert restored.price == 150.25
        assert restored.status == "filled"

    def test_workflow_checkpoint_roundtrip(self):
        cp = WorkflowCheckpoint(
            workflow_run_id="wf001", status="MONITORING",
            sop_name="day-trade-momentum", sop_version="v1.0.0",
            checkpoint_data={"open_positions": ["AAPL"]},
        )
        json_str = to_json(cp)
        restored = from_json(WorkflowCheckpoint, json_str)
        assert restored.workflow_run_id == "wf001"
        assert restored.status == "MONITORING"
        assert restored.checkpoint_data == {"open_positions": ["AAPL"]}

    def test_journal_entry_roundtrip(self):
        entry = JournalEntry(
            plan_id="abc123", symbol="AAPL", strategy="momentum",
            pnl=250.0, pnl_pct=1.67, exit_reason="take_profit",
            entry_transactions=["tx001"], exit_transactions=["tx002"],
        )
        json_str = to_json(entry)
        restored = from_json(JournalEntry, json_str)
        assert restored.pnl == 250.0
        assert restored.entry_transactions == ["tx001"]

    def test_none_fields_serialize(self):
        plan = TradePlan(symbol="TSLA", side="buy", quantity=50)
        json_str = to_json(plan)
        restored = from_json(TradePlan, json_str)
        assert restored.entry_limit_price is None
        assert restored.trailing_stop is None
        assert restored.time_stop is None


# --- Database Schema Tests ---


class TestDatabase:
    def test_schema_creation(self):
        conn = get_connection(":memory:")
        init_db(conn)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = [t["name"] for t in tables]
        assert "trade_plans" in names
        assert "trade_transactions" in names
        assert "workflow_runs" in names
        assert "journal_entries" in names
        assert "price_data" in names
        conn.close()

    def test_schema_idempotent(self):
        conn = get_connection(":memory:")
        init_db(conn)
        init_db(conn)  # should not raise
        conn.close()


# --- Repository Tests ---


class TestRepository:
    def setup_method(self):
        self.repo = Repository(":memory:")

    def teardown_method(self):
        self.repo.close()

    def test_save_and_get_trade_plan(self):
        plan = TradePlan(
            plan_id="p001", symbol="NVDA", strategy="momentum",
            side="buy", quantity=50, take_profit=500.0, stop_loss=450.0,
        )
        self.repo.save_trade_plan(plan)
        result = self.repo.get_trade_plan("p001")
        assert result is not None
        assert result.symbol == "NVDA"
        assert result.quantity == 50

    def test_get_nonexistent_plan(self):
        assert self.repo.get_trade_plan("nonexistent") is None

    def test_list_trade_plans(self):
        for i, sym in enumerate(["AAPL", "AAPL", "TSLA"]):
            self.repo.save_trade_plan(TradePlan(
                plan_id=f"p{i}", symbol=sym, side="buy", quantity=10,
            ))
        all_plans = self.repo.list_trade_plans()
        assert len(all_plans) == 3
        aapl_plans = self.repo.list_trade_plans(symbol="AAPL")
        assert len(aapl_plans) == 2

    def test_save_and_get_transaction(self):
        # Need a plan first (foreign key)
        self.repo.save_trade_plan(TradePlan(plan_id="p001", symbol="AAPL", side="buy", quantity=10))
        tx = TradeTransaction(
            transaction_id="tx001", plan_id="p001", symbol="AAPL",
            side="buy", order_type="market", quantity=10, price=150.0,
            broker_order_id="BRK-1", status="filled",
        )
        self.repo.save_transaction(tx)
        result = self.repo.get_transaction("tx001")
        assert result is not None
        assert result.price == 150.0

    def test_get_transactions_for_plan(self):
        self.repo.save_trade_plan(TradePlan(plan_id="p001", symbol="AAPL", side="buy", quantity=10))
        for i in range(3):
            self.repo.save_transaction(TradeTransaction(
                transaction_id=f"tx{i}", plan_id="p001", symbol="AAPL",
                side="buy", order_type="market", quantity=10, price=150.0 + i,
                status="filled",
            ))
        txs = self.repo.get_transactions_for_plan("p001")
        assert len(txs) == 3

    def test_save_and_get_checkpoint(self):
        cp = WorkflowCheckpoint(
            workflow_run_id="wf001", status="SCANNING",
            sop_name="momentum", sop_version="v1.0.0",
        )
        self.repo.save_checkpoint(cp)
        result = self.repo.get_checkpoint("wf001")
        assert result is not None
        assert result.status == "SCANNING"

    def test_get_incomplete_workflows(self):
        self.repo.save_checkpoint(WorkflowCheckpoint(
            workflow_run_id="wf001", status="MONITORING",
        ))
        self.repo.save_checkpoint(WorkflowCheckpoint(
            workflow_run_id="wf002", status="COMPLETED",
        ))
        self.repo.save_checkpoint(WorkflowCheckpoint(
            workflow_run_id="wf003", status="EXECUTING",
        ))
        incomplete = self.repo.get_incomplete_workflows()
        ids = [w.workflow_run_id for w in incomplete]
        assert "wf001" in ids
        assert "wf003" in ids
        assert "wf002" not in ids

    def test_save_and_get_journal_entry(self):
        self.repo.save_trade_plan(TradePlan(plan_id="p001", symbol="AAPL", side="buy", quantity=10))
        entry = JournalEntry(
            plan_id="p001", symbol="AAPL", strategy="momentum",
            pnl=100.0, pnl_pct=0.67, exit_reason="take_profit",
        )
        self.repo.save_journal_entry(entry)
        entries = self.repo.get_journal_entries()
        assert len(entries) == 1
        assert entries[0].pnl == 100.0

    def test_journal_entries_since_filter(self):
        self.repo.save_trade_plan(TradePlan(plan_id="p001", symbol="AAPL", side="buy", quantity=10))
        old = JournalEntry(
            plan_id="p001", symbol="AAPL", pnl=50.0,
            timestamp=datetime(2024, 1, 1),
        )
        new = JournalEntry(
            plan_id="p001", symbol="AAPL", pnl=100.0,
            timestamp=datetime(2024, 6, 1),
        )
        self.repo.save_journal_entry(old)
        self.repo.save_journal_entry(new)
        recent = self.repo.get_journal_entries(since=datetime(2024, 3, 1))
        assert len(recent) == 1
        assert recent[0].pnl == 100.0

    def test_save_and_query_price_data(self):
        bars = [
            {"symbol": "AAPL", "timestamp": "2024-01-02T09:30:00",
             "open": 150.0, "high": 152.0, "low": 149.0, "close": 151.0,
             "volume": 1000000, "timeframe": "1Day"},
            {"symbol": "AAPL", "timestamp": "2024-01-03T09:30:00",
             "open": 151.0, "high": 153.0, "low": 150.0, "close": 152.5,
             "volume": 1200000, "timeframe": "1Day"},
        ]
        self.repo.save_price_bars(bars)
        result = self.repo.query_price_data("AAPL", "2024-01-01", "2024-01-04")
        assert len(result) == 2
        assert result[0]["close"] == 151.0


# --- Orders & Fills (go-live-metrics Task 1) ---


class TestOrdersAndFillsSchema:
    def test_both_tables_and_index_exist(self):
        conn = get_connection(":memory:")
        init_db(conn)
        names = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "orders" in names
        assert "fills" in names
        indexes = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()]
        assert "idx_fills_order" in indexes
        conn.close()

    def test_migration_is_a_noop_when_already_applied(self):
        """Re-running init_db must not raise and must not drop existing rows."""
        repo = Repository(":memory:")
        repo.save_order(Order(order_id="o1", symbol="AAPL", side="buy",
                              order_type="limit", qty_requested=10, mode="paper"))
        repo.insert_fill(Fill(fill_id="act-1", order_id="o1", symbol="AAPL",
                              side="buy", qty=10, price=150.0,
                              fill_type="fill", mode="paper"))
        init_db(repo.conn)  # second migration pass
        assert repo.get_order("o1") is not None
        assert len(repo.get_fills_for_order("o1")) == 1
        repo.close()


class TestOrderFillModels:
    def test_order_roundtrip(self):
        order = Order(
            order_id="o1", plan_id="p1", broker_order_id="brk-1", symbol="AAPL",
            side="buy", order_type="limit", qty_requested=100,
            intended_price=150.0, mode="paper", regime_at_entry="RISK_ON",
        )
        restored = from_json(Order, to_json(order))
        assert restored.order_id == "o1"
        assert restored.intended_price == 150.0
        assert restored.regime_at_entry == "RISK_ON"
        assert restored.terminal_status is None

    def test_fill_roundtrip(self):
        fill = Fill(
            fill_id="act-1", order_id="o1", symbol="AAPL", side="buy",
            qty=40, price=150.25, fill_type="partial_fill", mode="paper",
        )
        restored = from_json(Fill, to_json(fill))
        assert restored.fill_id == "act-1"
        assert restored.qty == 40
        assert restored.price == 150.25

    def test_fill_id_is_never_generated(self):
        """fill_id is the broker's activity id — dedup is structural.

        A default factory here would mint a fresh id per poll, turning every
        replay into a new row and silently destroying idempotency.
        """
        assert Fill().fill_id == ""


class TestOrderFillRepository:
    def setup_method(self):
        self.repo = Repository(":memory:")

    def teardown_method(self):
        self.repo.close()

    def _order(self, order_id="o1", **kw):
        params = dict(symbol="AAPL", side="buy", order_type="limit",
                      qty_requested=100, intended_price=150.0, mode="paper")
        params.update(kw)
        return Order(order_id=order_id, **params)

    def test_save_and_get_order(self):
        self.repo.save_order(self._order(plan_id="p1", broker_order_id="brk-1",
                                         regime_at_entry="RISK_ON"))
        result = self.repo.get_order("o1")
        assert result is not None
        assert result.symbol == "AAPL"
        assert result.qty_requested == 100
        assert result.intended_price == 150.0
        assert result.plan_id == "p1"
        assert result.regime_at_entry == "RISK_ON"
        assert result.terminal_status is None

    def test_order_nullables_stay_null(self):
        """No plan, no gate, no regime ⇒ NULL — never a fabricated value."""
        self.repo.save_order(self._order(intended_price=None))
        result = self.repo.get_order("o1")
        assert result is not None
        assert result.plan_id is None
        assert result.intended_price is None
        assert result.gate_verdict is None
        assert result.gate_rule_id is None
        assert result.regime_at_entry is None

    def test_get_nonexistent_order(self):
        assert self.repo.get_order("nope") is None

    def test_set_order_terminal(self):
        self.repo.save_order(self._order())
        self.repo.set_order_terminal("o1", "cancelled")
        result = self.repo.get_order("o1")
        assert result is not None
        assert result.terminal_status == "cancelled"

    def test_get_open_orders_excludes_terminal(self):
        self.repo.save_order(self._order("o1"))
        self.repo.save_order(self._order("o2"))
        self.repo.save_order(self._order("o3"))
        self.repo.set_order_terminal("o2", "filled")
        open_ids = sorted(o.order_id for o in self.repo.get_open_orders())
        assert open_ids == ["o1", "o3"]

    def test_insert_fill_is_idempotent(self):
        """Replaying the same broker execution is a PK conflict, not a new row."""
        self.repo.save_order(self._order())
        fill = Fill(fill_id="act-1", order_id="o1", symbol="AAPL", side="buy",
                    qty=100, price=150.25, fill_type="fill", mode="paper")
        assert self.repo.insert_fill(fill) is True
        assert self.repo.insert_fill(fill) is False
        assert len(self.repo.get_fills_for_order("o1")) == 1

    def test_insert_fill_never_overwrites(self):
        """fills is append-only: a re-insert must not mutate the stored row.

        INSERT OR REPLACE would delete-and-reinsert, silently rewriting history.
        """
        self.repo.save_order(self._order())
        self.repo.insert_fill(Fill(fill_id="act-1", order_id="o1", symbol="AAPL",
                                   side="buy", qty=100, price=150.25,
                                   fill_type="fill", mode="paper"))
        self.repo.insert_fill(Fill(fill_id="act-1", order_id="o1", symbol="AAPL",
                                   side="buy", qty=999, price=1.0,
                                   fill_type="fill", mode="paper"))
        fills = self.repo.get_fills_for_order("o1")
        assert len(fills) == 1
        assert fills[0].price == 150.25
        assert fills[0].qty == 100

    def test_partial_fills_are_separate_rows(self):
        """One row per execution — qty is THIS execution, never cumulative."""
        self.repo.save_order(self._order())
        self.repo.insert_fill(Fill(fill_id="act-1", order_id="o1", symbol="AAPL",
                                   side="buy", qty=40, price=150.00,
                                   fill_type="partial_fill", mode="paper",
                                   filled_at=datetime(2026, 8, 14, 9, 30)))
        self.repo.insert_fill(Fill(fill_id="act-2", order_id="o1", symbol="AAPL",
                                   side="buy", qty=60, price=150.50,
                                   fill_type="fill", mode="paper",
                                   filled_at=datetime(2026, 8, 14, 9, 31)))
        fills = self.repo.get_fills_for_order("o1")
        assert len(fills) == 2
        assert [f.fill_id for f in fills] == ["act-1", "act-2"]  # ordered by time
        assert sum(f.qty for f in fills) == 100

    def test_get_fills_for_order_isolates_orders(self):
        self.repo.save_order(self._order("o1"))
        self.repo.save_order(self._order("o2"))
        self.repo.insert_fill(Fill(fill_id="act-1", order_id="o1", symbol="AAPL",
                                   side="buy", qty=10, price=1.0,
                                   fill_type="fill", mode="paper"))
        self.repo.insert_fill(Fill(fill_id="act-2", order_id="o2", symbol="AAPL",
                                   side="buy", qty=10, price=1.0,
                                   fill_type="fill", mode="paper"))
        assert [f.fill_id for f in self.repo.get_fills_for_order("o1")] == ["act-1"]
        assert self.repo.get_fills_for_order("unknown") == []

    def test_no_fill_mutation_path_exists(self):
        """Append-only enforced by construction: no UPDATE/DELETE reaches fills."""
        import re
        import persistence.repository as repo_mod

        source = Path(repo_mod.__file__).read_text()
        assert not re.search(r"UPDATE\s+fills", source, re.IGNORECASE)
        assert not re.search(r"DELETE\s+FROM\s+fills", source, re.IGNORECASE)
        assert not re.search(r"INSERT\s+OR\s+REPLACE\s+INTO\s+fills", source, re.IGNORECASE)
        fill_methods = [m for m in dir(Repository) if "fill" in m and not m.startswith("_")]
        assert sorted(fill_methods) == ["get_fills_for_order", "insert_fill"]


class TestPriceDataHelpers:
    def test_latest_price_date_and_clear(self):
        from persistence.repository import Repository
        repo = Repository(":memory:")
        repo.save_price_bars([
            {"symbol": "AAA", "timestamp": "2026-06-12T00:00:00+00:00", "open": 1,
             "high": 1, "low": 1, "close": 1, "volume": 10, "timeframe": "1Day"},
            {"symbol": "AAA", "timestamp": "2026-06-18T00:00:00+00:00", "open": 1,
             "high": 1, "low": 1, "close": 1, "volume": 10, "timeframe": "1Day"},
        ])
        assert repo.latest_price_date("AAA") == "2026-06-18T00:00:00+00:00"
        assert repo.latest_price_date("ZZZ") is None
        assert repo.clear_price_data("1Day") == 2
        assert repo.latest_price_date("AAA") is None
