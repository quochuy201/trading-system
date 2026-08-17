"""Tests for order-intent capture and fill reconciliation (go-live-metrics).

Task 3 lives here: `place_order` must record what we *intended* into `orders`
without changing a single thing about how the order is placed.
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from models import TradePlan, TradeTransaction
from persistence.db import get_connection, init_db
from persistence.repository import Repository


class _FakeBroker:
    """Stands in for the broker. Records calls so we can assert we changed none."""

    def __init__(self, status="accepted", price=0.0):
        self.calls = []
        self._status = status
        self._price = price
        self._n = 0

    def place_order(self, symbol, side, order_type, quantity,
                    limit_price=None, stop_price=None):
        self.calls.append(dict(
            symbol=symbol, side=side, order_type=order_type, quantity=quantity,
            limit_price=limit_price, stop_price=stop_price,
        ))
        self._n += 1
        order_id = f"brk-{self._n}"
        return TradeTransaction(
            transaction_id=order_id, symbol=symbol, side=side,
            order_type=order_type, quantity=quantity, price=self._price,
            broker_order_id=order_id, status=self._status,
        )


@pytest.fixture
def env(monkeypatch):
    """server wired to an in-memory repo and a fake broker."""
    import server
    repo = Repository(":memory:")
    broker = _FakeBroker()
    monkeypatch.setattr(server, "get_repo", lambda: repo)
    monkeypatch.setattr(server, "get_broker", lambda: broker)
    monkeypatch.setattr(server, "_log_to_ledger", lambda **kw: None)
    monkeypatch.setattr(server, "_kill_switch_state",
                        {"active": False, "triggered_at": None, "reason": None})
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    return server, repo, broker


def _orders(repo) -> list[sqlite3.Row]:
    return repo.conn.execute("SELECT * FROM orders").fetchall()


# --- Task 3: place_order records intent ---


def test_place_order_records_intent(env):
    server, repo, _ = env
    server.place_order("NVDA", "buy", "limit", 10, limit_price=215.0)

    rows = _orders(repo)
    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "NVDA"
    assert row["side"] == "buy"
    assert row["qty_requested"] == 10
    assert row["intended_price"] == 215.0
    assert row["terminal_status"] is None  # nothing terminal until reconciled
    assert row["broker_order_id"] == "brk-1"  # the join key for fills
    assert row["mode"] == "paper"
    assert row["submitted_at"]


def test_exactly_one_order_row_per_placement(env):
    server, repo, _ = env
    server.place_order("NVDA", "buy", "market", 10)
    server.place_order("NVDA", "buy", "market", 10)
    assert len(_orders(repo)) == 2


def test_duplicate_broker_order_id_does_not_destroy_the_first_order(env):
    """`broker_order_id` is UNIQUE. If a second placement ever reports an id we
    already hold, the existing order must survive — INSERT OR REPLACE would
    delete a real placement and nothing would notice."""
    server, repo, broker = env
    server.place_order("NVDA", "buy", "limit", 10, limit_price=215.0)
    broker._n = 0  # force the next placement to report the same broker id

    server.place_order("TSLA", "sell", "limit", 99, limit_price=400.0)

    rows = _orders(repo)
    assert len(rows) == 1
    assert rows[0]["symbol"] == "NVDA"  # the original, not overwritten
    assert rows[0]["qty_requested"] == 10


def test_gate_fields_stay_null_until_the_gate_ships(env):
    server, repo, _ = env
    server.place_order("NVDA", "buy", "market", 10)
    row = _orders(repo)[0]
    assert row["gate_verdict"] is None
    assert row["gate_rule_id"] is None


# --- Task 3: regime is inherited, never computed in the order path ---


def test_regime_inherited_from_plan(env):
    server, repo, _ = env
    repo.save_trade_plan(TradePlan(
        plan_id="p1", symbol="NVDA", side="buy", quantity=10,
        regime="RISK_ON",
    ))
    server.place_order("NVDA", "buy", "market", 10, plan_id="p1")
    assert _orders(repo)[0]["regime_at_entry"] == "RISK_ON"


def test_order_without_plan_has_null_regime(env):
    """Never fabricated — an ad-hoc order simply has no regime."""
    server, repo, _ = env
    server.place_order("NVDA", "buy", "market", 10)
    row = _orders(repo)[0]
    assert row["regime_at_entry"] is None
    assert row["plan_id"] is None


def test_plan_without_regime_yields_null(env):
    server, repo, _ = env
    repo.save_trade_plan(TradePlan(plan_id="p1", symbol="NVDA", side="buy", quantity=10))
    server.place_order("NVDA", "buy", "market", 10, plan_id="p1")
    assert _orders(repo)[0]["regime_at_entry"] is None


def test_order_path_makes_no_regime_call(env, monkeypatch):
    """A network call here would add a failure mode to the hot path — and
    would capture the submit-time regime, not the decision-time one."""
    server, repo, _ = env

    def _explode(*a, **k):
        raise AssertionError("place_order must not call get_market_regime")

    monkeypatch.setattr(server, "get_market_regime", _explode)
    server.place_order("NVDA", "buy", "market", 10)
    assert len(_orders(repo)) == 1


def test_order_path_source_has_no_regime_call():
    """Belt and braces: the call cannot be introduced without failing here."""
    import inspect
    import server
    source = inspect.getsource(server.place_order)
    assert "get_market_regime" not in source


# --- Task 3: intended_price is a real reference or NULL, never a guess ---


def test_market_order_borrows_the_plan_entry_signal(env):
    """A market entry has no limit price, but the plan's entry level IS the
    price the decision was made at — that is what slippage measures against."""
    server, repo, _ = env
    repo.save_trade_plan(TradePlan(
        plan_id="p1", symbol="NVDA", side="buy", quantity=10,
        entry_limit_price=210.0,
    ))
    server.place_order("NVDA", "buy", "market", 10, plan_id="p1")
    assert _orders(repo)[0]["intended_price"] == 210.0


def test_exit_order_does_not_borrow_the_entry_price(env):
    """Selling against a buy plan: the entry level is not this order's intent.
    A wrong reference price is worse than none — slippage would be nonsense."""
    server, repo, _ = env
    repo.save_trade_plan(TradePlan(
        plan_id="p1", symbol="NVDA", side="buy", quantity=10,
        entry_limit_price=210.0,
    ))
    server.place_order("NVDA", "sell", "market", 10, plan_id="p1")
    assert _orders(repo)[0]["intended_price"] is None


def test_explicit_limit_price_wins_over_the_plan(env):
    server, repo, _ = env
    repo.save_trade_plan(TradePlan(
        plan_id="p1", symbol="NVDA", side="buy", quantity=10,
        entry_limit_price=210.0,
    ))
    server.place_order("NVDA", "buy", "limit", 10, limit_price=215.0, plan_id="p1")
    assert _orders(repo)[0]["intended_price"] == 215.0


def test_stop_price_is_the_reference_for_a_stop_order(env):
    server, repo, _ = env
    server.place_order("NVDA", "sell", "stop", 10, stop_price=195.0)
    assert _orders(repo)[0]["intended_price"] == 195.0


def test_market_order_with_no_plan_has_null_intended_price(env):
    server, repo, _ = env
    server.place_order("NVDA", "buy", "market", 10)
    assert _orders(repo)[0]["intended_price"] is None


# --- Task 3 guardrail: recording must never affect trading ---


def test_bookkeeping_failure_does_not_block_the_order(env, monkeypatch):
    """The order reached the broker. Losing our own record must not turn that
    into an error the agent sees, or into a retry that double-submits."""
    server, repo, broker = env

    def _boom(order):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(repo, "save_order", _boom)

    result = json.loads(server.place_order("NVDA", "buy", "market", 10))
    assert result["broker_order_id"] == "brk-1"
    assert "error" not in result
    assert len(broker.calls) == 1  # placed exactly once


def test_broker_call_is_unchanged(env):
    """No new argument, no reordering, no extra call."""
    server, repo, broker = env
    repo.save_trade_plan(TradePlan(plan_id="p1", symbol="NVDA", side="buy", quantity=10))
    server.place_order("NVDA", "buy", "limit", 10, limit_price=215.0, plan_id="p1")
    assert broker.calls == [dict(
        symbol="NVDA", side="buy", order_type="limit", quantity=10,
        limit_price=215.0, stop_price=None,
    )]


def test_kill_switch_writes_no_order(env, monkeypatch):
    server, repo, broker = env
    monkeypatch.setattr(server, "_kill_switch_state",
                        {"active": True, "triggered_at": None, "reason": "daily loss"})

    result = json.loads(server.place_order("NVDA", "buy", "market", 10))
    assert result["error"] == "Kill switch is active"
    assert _orders(repo) == []
    assert broker.calls == []


def test_legacy_transactions_still_written(env):
    """`trade_transactions` keeps being written during cutover (Task 8)."""
    server, repo, _ = env
    repo.save_trade_plan(TradePlan(plan_id="p1", symbol="NVDA", side="buy", quantity=10))
    server.place_order("NVDA", "buy", "market", 10, plan_id="p1")
    assert len(repo.get_transactions_for_plan("p1")) == 1


# --- Task 3: trade_plans.regime migration ---


def test_regime_column_added_to_an_existing_trade_plans_table():
    """CREATE TABLE IF NOT EXISTS cannot add a column — this needs a real
    ALTER, and it must not disturb the rows already there."""
    conn = get_connection(":memory:")
    conn.executescript("""
        CREATE TABLE trade_plans (
            plan_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, strategy TEXT,
            sop_version TEXT, side TEXT NOT NULL, quantity INTEGER NOT NULL,
            entry_order_type TEXT, entry_limit_price REAL, take_profit REAL,
            stop_loss REAL, trailing_stop REAL, time_stop TEXT,
            risk_assessment TEXT, rationale TEXT, created_at TEXT NOT NULL
        );
    """)
    conn.execute(
        "INSERT INTO trade_plans (plan_id, symbol, side, quantity, created_at)"
        " VALUES ('old-1','NVDA','buy',10,'2026-01-01T00:00:00')"
    )
    conn.commit()

    init_db(conn)

    cols = [r["name"] for r in conn.execute("PRAGMA table_info(trade_plans)")]
    assert "regime" in cols
    row = conn.execute("SELECT * FROM trade_plans WHERE plan_id='old-1'").fetchone()
    assert row["symbol"] == "NVDA"  # pre-existing row untouched
    assert row["regime"] is None  # backfilled honestly as unknown

    init_db(conn)  # second pass must not raise "duplicate column"
    conn.close()


def test_regime_roundtrips_through_the_repository():
    repo = Repository(":memory:")
    repo.save_trade_plan(TradePlan(
        plan_id="p1", symbol="NVDA", side="buy", quantity=10, regime="RISK_OFF",
    ))
    assert repo.get_trade_plan("p1").regime == "RISK_OFF"
    repo.save_trade_plan(TradePlan(plan_id="p2", symbol="NVDA", side="buy", quantity=10))
    assert repo.get_trade_plan("p2").regime is None
    repo.close()
