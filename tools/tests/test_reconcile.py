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


def test_legacy_table_untouched(env):
    """Task 8 fence: no metric is ever sourced from `trade_transactions`.

    The legacy table keeps its rows — including a priced one that is really the
    plan's intended limit, not an execution (the exact shape the fill-capture
    bug left behind). The go-live path (fills -> round_trips ->
    v_performance_current) must ignore it entirely: given a broker with no
    executions, reconciliation yields zero fills and zero round trips even
    though the legacy table is populated. If any code path read the legacy
    rows into the metric path, `fills`/`round_trips` would be non-empty here.
    """
    server, repo, _ = env
    from audit.performance import current_performance
    from audit.round_trips import rebuild_round_trips

    # Seed the legacy table: a zero-price row and a priced row that is really
    # the plan's intent (APLD 35.47 == entry_limit_price, per design §6).
    repo.save_trade_plan(TradePlan(plan_id="p1", symbol="AAPL", side="buy", quantity=10))
    repo.save_trade_plan(TradePlan(plan_id="p2", symbol="APLD", side="buy", quantity=5))
    repo.save_transaction(TradeTransaction(
        plan_id="p1", symbol="AAPL", side="buy", order_type="limit",
        quantity=10, price=0.0, broker_order_id="legacy-1", status="filled"))
    repo.save_transaction(TradeTransaction(
        plan_id="p2", symbol="APLD", side="buy", order_type="limit",
        quantity=5, price=35.47, broker_order_id="legacy-2", status="filled"))
    assert repo.conn.execute(
        "SELECT COUNT(*) FROM trade_transactions").fetchone()[0] == 2

    # Reconcile from a broker with NO executions, then rebuild + read metrics.
    _sync(_ActivityBroker(activities=[]), repo)
    rebuild_round_trips(repo)

    # The legacy rows influence nothing downstream.
    assert repo.conn.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 0
    assert repo.conn.execute("SELECT COUNT(*) FROM round_trips").fetchone()[0] == 0
    assert current_performance(repo) == []


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


# --- Task 4: sync_fills() — cursor-based import of broker executions ---


class _ActivityBroker:
    """Serves a fixed activity list with real cursor pagination.

    Mirrors the live feed's contract, which was read off the paper account
    before this was written: oldest-first, `page_token` is the id of the last
    row already consumed, an empty list ends the walk.
    """

    def __init__(self, activities, orders=None):
        self.activities = activities
        self.orders = orders or {}
        self.activity_calls = []
        self.order_calls = []

    def get_account_activities(self, activity_type="FILL", page_token=None,
                               page_size=100):
        self.activity_calls.append((activity_type, page_token, page_size))
        ids = [a["id"] for a in self.activities]
        start = (ids.index(page_token) + 1) if page_token in ids else 0
        if page_token and page_token not in ids:
            return []
        return [dict(a) for a in self.activities[start:start + page_size]]

    def get_order(self, broker_order_id):
        self.order_calls.append(broker_order_id)
        return self.orders.get(broker_order_id, {
            "order_id": broker_order_id, "status": "unknown",
            "symbol": "", "qty_requested": 0,
        })


def _act(i, order="brk-1", qty=10, cum=None, price=100.0, kind="fill",
         symbol="NVDA", side="buy", when=None):
    """One activity shaped like the live feed (ids are '<stamp>::<uuid>')."""
    return {
        "id": f"2026043009{i:04d}::act-{i}",
        "order_id": order,
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "cum_qty": cum if cum is not None else qty,
        "price": price,
        "type": kind,
        "transaction_time": when or f"2026-04-30T13:{i:02d}:00.000000Z",
    }


def _sync(broker, repo, **kw):
    from audit.reconcile import sync_fills
    return sync_fills(broker, repo, mode="paper", **kw)


def test_sync_fills_imports_executions():
    repo = Repository(":memory:")
    broker = _ActivityBroker([_act(1), _act(2, order="brk-2")])

    result = _sync(broker, repo)
    assert result["inserted"] == 2
    assert result["failed"] == 0
    rows = repo.conn.execute("SELECT * FROM fills ORDER BY fill_id").fetchall()
    assert [r["broker_order_id"] for r in rows] == ["brk-1", "brk-2"]
    assert rows[0]["mode"] == "paper"
    repo.close()


def test_sync_fills_is_idempotent():
    """Running twice must not duplicate a single execution.

    This is a primary-key conflict, not a dedup branch — the guarantee holds
    even if this function is called concurrently or the cursor is lost.
    """
    repo = Repository(":memory:")
    broker = _ActivityBroker([_act(1), _act(2)])

    first = _sync(broker, repo)
    repo.set_sync_cursor("fills:FILL", None)  # worst case: cursor lost entirely
    second = _sync(broker, repo)

    assert first["inserted"] == 2
    assert second["inserted"] == 0 and second["skipped"] == 2
    assert repo.conn.execute("SELECT COUNT(*) c FROM fills").fetchone()["c"] == 2
    repo.close()


def test_partial_then_completing_fill_sums_to_order_qty():
    """The double-count regression, with the real numbers from order b38bacd0.

    qty sums to 100 (the true position); cum_qty would sum to 180.
    """
    repo = Repository(":memory:")
    broker = _ActivityBroker([
        _act(1, order="b38bacd0", qty=80, cum=80, price=120.50, kind="partial_fill"),
        _act(2, order="b38bacd0", qty=20, cum=100, price=121.91, kind="fill"),
    ])

    _sync(broker, repo)

    fills = repo.get_fills_for_order("b38bacd0")
    assert len(fills) == 2
    assert sum(f.qty for f in fills) == 100
    assert [f.fill_type for f in fills] == ["partial_fill", "fill"]
    repo.close()


def test_cursor_advances_and_resumes():
    repo = Repository(":memory:")
    broker = _ActivityBroker([_act(i) for i in range(1, 6)])

    first = _sync(broker, repo, page_size=2)
    assert first["inserted"] == 5
    assert repo.get_sync_cursor("fills:FILL") == broker.activities[-1]["id"]

    broker.activities.append(_act(6))
    second = _sync(broker, repo, page_size=2)
    assert second["inserted"] == 1  # only the new one
    assert second["skipped"] == 0   # resumed, did not re-walk
    repo.close()


def test_rewinding_the_cursor_backfills_through_the_same_path():
    """No separate import script: history comes back by moving the cursor."""
    repo = Repository(":memory:")
    broker = _ActivityBroker([_act(i) for i in range(1, 4)])
    _sync(broker, repo)
    repo.conn.execute("DELETE FROM fills")  # simulate a lost derived copy
    repo.conn.commit()

    repo.set_sync_cursor("fills:FILL", None)
    again = _sync(broker, repo)

    assert again["inserted"] == 3
    assert repo.conn.execute("SELECT COUNT(*) c FROM fills").fetchone()["c"] == 3
    repo.close()


def test_one_bad_record_does_not_abort_the_batch():
    repo = Repository(":memory:")
    bad = _act(2)
    bad["transaction_time"] = "not-a-timestamp"
    broker = _ActivityBroker([_act(1), bad, _act(3)])

    result = _sync(broker, repo)

    assert result["inserted"] == 2
    assert result["failed"] == 1
    assert repo.conn.execute("SELECT COUNT(*) c FROM fills").fetchone()["c"] == 2
    repo.close()


def test_bad_record_does_not_wedge_the_cursor():
    """The cursor must move past a failure, or the sync retries it forever."""
    repo = Repository(":memory:")
    bad = _act(1)
    bad["transaction_time"] = "not-a-timestamp"
    broker = _ActivityBroker([bad, _act(2)])

    _sync(broker, repo)
    assert repo.get_sync_cursor("fills:FILL") == broker.activities[-1]["id"]
    repo.close()


def test_sync_fills_never_calls_get_order():
    """A fill may not be derived from a cumulative status snapshot."""
    repo = Repository(":memory:")
    broker = _ActivityBroker([_act(1), _act(2)])
    _sync(broker, repo)
    assert broker.order_calls == []
    repo.close()


def test_sync_fills_requests_oldest_first_from_the_cursor():
    repo = Repository(":memory:")
    broker = _ActivityBroker([_act(1)])
    _sync(broker, repo, page_size=50)
    assert broker.activity_calls[0] == ("FILL", None, 50)
    repo.close()


def test_empty_feed_is_not_an_error():
    repo = Repository(":memory:")
    result = _sync(_ActivityBroker([]), repo)
    assert result == {"inserted": 0, "skipped": 0, "failed": 0, "pages": 0,
                      "cursor": None}
    repo.close()


def test_page_limit_stops_a_feed_that_never_ends():
    """A broker that keeps returning rows must not spin forever."""
    class _Endless:
        def get_account_activities(self, activity_type="FILL", page_token=None,
                                   page_size=100):
            n = int((page_token or "0::x").split("::")[0]) + 1
            return [dict(_act(n), id=f"{n}::act")]

    repo = Repository(":memory:")
    result = _sync(_Endless(), repo, max_pages=5)
    assert result["pages"] == 5
    repo.close()


# --- Task 4: sync_orders_terminal() — status only, never a fill ---


def _sync_terminal(broker, repo):
    from audit.reconcile import sync_orders_terminal
    return sync_orders_terminal(broker, repo)


def _order(repo, order_id="o1", broker_order_id="brk-1", **kw):
    from models import Order
    params = dict(symbol="NVDA", side="buy", order_type="limit",
                  qty_requested=100, mode="paper")
    params.update(kw)
    repo.save_order(Order(order_id=order_id, broker_order_id=broker_order_id,
                          **params))


def test_cancelled_order_gets_terminal_status_with_no_fill():
    """Cancelled orders never appear in the FILL feed — this is the only way
    they ever stop being 'open'."""
    repo = Repository(":memory:")
    _order(repo)
    broker = _ActivityBroker([], orders={"brk-1": {"status": "canceled"}})

    result = _sync_terminal(broker, repo)

    assert result["closed"] == 1
    assert repo.get_order("o1").terminal_status == "cancelled"  # spelling normalised
    assert repo.conn.execute("SELECT COUNT(*) c FROM fills").fetchone()["c"] == 0
    assert repo.get_open_orders() == []
    repo.close()


def test_still_open_order_is_left_alone():
    repo = Repository(":memory:")
    _order(repo)
    broker = _ActivityBroker([], orders={"brk-1": {"status": "new"}})

    assert _sync_terminal(broker, repo)["closed"] == 0
    assert repo.get_order("o1").terminal_status is None
    repo.close()


def test_rejected_and_expired_are_terminal():
    repo = Repository(":memory:")
    _order(repo, "o1", "brk-1")
    _order(repo, "o2", "brk-2")
    broker = _ActivityBroker([], orders={
        "brk-1": {"status": "rejected"}, "brk-2": {"status": "expired"},
    })

    _sync_terminal(broker, repo)

    assert repo.get_order("o1").terminal_status == "rejected"
    assert repo.get_order("o2").terminal_status == "expired"
    repo.close()


def test_one_failed_lookup_does_not_stop_the_batch():
    repo = Repository(":memory:")
    _order(repo, "o1", "brk-1")
    _order(repo, "o2", "brk-2")

    class _Flaky(_ActivityBroker):
        def get_order(self, broker_order_id):
            if broker_order_id == "brk-1":
                raise RuntimeError("broker timeout")
            return {"status": "canceled"}

    result = _sync_terminal(_Flaky([]), repo)

    assert result["failed"] == 1 and result["closed"] == 1
    assert repo.get_order("o1").terminal_status is None
    assert repo.get_order("o2").terminal_status == "cancelled"
    repo.close()


def test_terminal_sync_reads_only_status():
    """get_order() carries no qty or price, so no fill can come from it."""
    repo = Repository(":memory:")
    _order(repo)
    broker = _ActivityBroker([], orders={
        "brk-1": {"status": "filled", "filled_qty": "100",
                  "filled_avg_price": "150.25"},  # must be ignored
    })

    _sync_terminal(broker, repo)

    assert repo.get_order("o1").terminal_status == "filled"
    assert repo.conn.execute("SELECT COUNT(*) c FROM fills").fetchone()["c"] == 0
    repo.close()


# --- Task 4: the join key ---


def test_fills_join_orders_on_broker_order_id():
    """The whole point of the rename: this join must return rows.

    `fills.broker_order_id` holds the broker's id and `orders.order_id` holds
    ours, so joining those two matches nothing — the defect CLAUDE.md records.
    """
    repo = Repository(":memory:")
    _order(repo, order_id="our-id-1", broker_order_id="brk-1",
           intended_price=120.00)
    _sync(_ActivityBroker([_act(1, order="brk-1", qty=80, price=120.50)]), repo)

    joined = repo.conn.execute("""
        SELECT f.qty, f.price, o.order_id, o.intended_price
        FROM fills f JOIN orders o ON f.broker_order_id = o.broker_order_id
    """).fetchall()
    assert len(joined) == 1
    assert joined[0]["order_id"] == "our-id-1"
    assert joined[0]["price"] == 120.50 and joined[0]["intended_price"] == 120.00

    naive = repo.conn.execute(
        "SELECT 1 FROM fills f JOIN orders o ON f.broker_order_id = o.order_id"
    ).fetchall()
    assert naive == [], "the wrong join must match nothing — that is the bug"
    repo.close()


def test_fill_survives_for_an_order_we_never_recorded():
    """Backfilled history and positions opened outside this system still land.

    Translating the broker id to ours at insert time would drop these or force
    an invented `orders` row.
    """
    repo = Repository(":memory:")
    _sync(_ActivityBroker([_act(1, order="unknown-brk")]), repo)
    assert len(repo.get_fills_for_order("unknown-brk")) == 1
    repo.close()


def test_legacy_order_id_column_is_renamed_on_an_existing_db():
    repo = Repository(":memory:")
    repo.conn.execute("DROP TABLE fills")
    repo.conn.executescript("""
        CREATE TABLE fills (
            fill_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, symbol TEXT NOT NULL,
            side TEXT NOT NULL, qty INTEGER NOT NULL, price REAL NOT NULL,
            fill_type TEXT NOT NULL, filled_at TEXT NOT NULL, mode TEXT NOT NULL
        );
        CREATE INDEX idx_fills_order ON fills(order_id);
    """)
    repo.conn.commit()

    init_db(repo.conn)

    cols = {r["name"] for r in repo.conn.execute("PRAGMA table_info(fills)")}
    assert "broker_order_id" in cols and "order_id" not in cols
    idx = {r["name"] for r in repo.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_fills_broker_order" in idx and "idx_fills_order" not in idx
    init_db(repo.conn)  # idempotent
    repo.close()


def test_rename_refuses_to_touch_a_populated_legacy_table():
    """fills is append-only; no migration of it should ever be silent."""
    repo = Repository(":memory:")
    repo.conn.execute("DROP TABLE fills")
    repo.conn.executescript("""
        CREATE TABLE fills (
            fill_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, symbol TEXT NOT NULL,
            side TEXT NOT NULL, qty INTEGER NOT NULL, price REAL NOT NULL,
            fill_type TEXT NOT NULL, filled_at TEXT NOT NULL, mode TEXT NOT NULL
        );
        INSERT INTO fills VALUES ('f1','brk-1','NVDA','buy',10,1.0,'fill','t','paper');
    """)
    repo.conn.commit()

    with pytest.raises(RuntimeError, match="refusing to auto-rename"):
        init_db(repo.conn)
    repo.close()
