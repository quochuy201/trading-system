"""Repository layer — CRUD operations for all models."""

import json
import sqlite3
from datetime import datetime, timezone

from models import (
    Fill,
    JournalEntry,
    Order,
    TradePlan,
    TradeTransaction,
    WorkflowCheckpoint,
)
from persistence.db import get_connection, init_db


class Repository:
    """Database repository for trading system models."""

    def __init__(self, db_path: str | None = None):
        self.conn = get_connection(db_path)
        init_db(self.conn)

    def close(self):
        self.conn.close()

    # --- Trade Plans ---

    def save_trade_plan(self, plan: TradePlan) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO trade_plans
            (plan_id, symbol, strategy, sop_version, side, quantity,
             entry_order_type, entry_limit_price, take_profit, stop_loss,
             trailing_stop, time_stop, risk_assessment, rationale, created_at,
             regime)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                plan.plan_id, plan.symbol, plan.strategy, plan.sop_version,
                plan.side, plan.quantity, plan.entry_order_type,
                plan.entry_limit_price, plan.take_profit, plan.stop_loss,
                plan.trailing_stop,
                plan.time_stop.isoformat() if plan.time_stop else None,
                json.dumps(plan.risk_assessment), plan.rationale,
                plan.created_at.isoformat(), plan.regime,
            ),
        )
        self.conn.commit()

    def get_trade_plan(self, plan_id: str) -> TradePlan | None:
        row = self.conn.execute(
            "SELECT * FROM trade_plans WHERE plan_id = ?", (plan_id,)
        ).fetchone()
        if not row:
            return None
        return TradePlan(
            plan_id=row["plan_id"], symbol=row["symbol"],
            strategy=row["strategy"], sop_version=row["sop_version"],
            side=row["side"], quantity=row["quantity"],
            entry_order_type=row["entry_order_type"],
            entry_limit_price=row["entry_limit_price"],
            take_profit=row["take_profit"], stop_loss=row["stop_loss"],
            trailing_stop=row["trailing_stop"],
            time_stop=datetime.fromisoformat(row["time_stop"]) if row["time_stop"] else None,
            risk_assessment=json.loads(row["risk_assessment"]) if row["risk_assessment"] else {},
            rationale=row["rationale"],
            created_at=datetime.fromisoformat(row["created_at"]),
            regime=row["regime"],
        )

    def list_trade_plans(self, symbol: str | None = None) -> list[TradePlan]:
        sql = "SELECT plan_id FROM trade_plans"
        params: tuple = ()
        if symbol:
            sql += " WHERE symbol = ?"
            params = (symbol,)
        sql += " ORDER BY created_at DESC"
        rows = self.conn.execute(sql, params).fetchall()
        return [self.get_trade_plan(r["plan_id"]) for r in rows]  # type: ignore

    # --- Trade Transactions ---

    def save_transaction(self, tx: TradeTransaction) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO trade_transactions
            (transaction_id, plan_id, symbol, side, order_type, quantity,
             price, broker_order_id, status, timestamp)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                tx.transaction_id, tx.plan_id, tx.symbol, tx.side,
                tx.order_type, tx.quantity, tx.price,
                tx.broker_order_id, tx.status, tx.timestamp.isoformat(),
            ),
        )
        self.conn.commit()

    def get_transaction(self, transaction_id: str) -> TradeTransaction | None:
        row = self.conn.execute(
            "SELECT * FROM trade_transactions WHERE transaction_id = ?",
            (transaction_id,),
        ).fetchone()
        if not row:
            return None
        return TradeTransaction(
            transaction_id=row["transaction_id"], plan_id=row["plan_id"],
            symbol=row["symbol"], side=row["side"],
            order_type=row["order_type"], quantity=row["quantity"],
            price=row["price"], broker_order_id=row["broker_order_id"],
            status=row["status"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
        )

    def get_transactions_for_plan(self, plan_id: str) -> list[TradeTransaction]:
        rows = self.conn.execute(
            "SELECT transaction_id FROM trade_transactions WHERE plan_id = ? ORDER BY timestamp",
            (plan_id,),
        ).fetchall()
        return [self.get_transaction(r["transaction_id"]) for r in rows]  # type: ignore

    # --- Orders (intent) ---

    def save_order(self, order: Order) -> None:
        """Record a submitted order.

        Args:
            order: The order as submitted. `mode` and `symbol` must be set;
                nullable fields (plan_id, gate_*, regime_at_entry) stay NULL
                when unknown rather than being defaulted to a value.

        Returns:
            None.

        Raises:
            sqlite3.IntegrityError: order_id already stored, or another order
                already claims this broker_order_id. Deliberately not
                INSERT OR REPLACE — that would silently delete the earlier
                order, losing a real placement from the metrics with nothing
                to notice it. The caller logs and continues.
        """
        self.conn.execute(
            """INSERT INTO orders
            (order_id, plan_id, broker_order_id, symbol, side, order_type,
             qty_requested, intended_price, submitted_at, terminal_status,
             gate_verdict, gate_rule_id, regime_at_entry, mode)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                order.order_id, order.plan_id, order.broker_order_id,
                order.symbol, order.side, order.order_type,
                order.qty_requested, order.intended_price,
                order.submitted_at.isoformat(), order.terminal_status,
                order.gate_verdict, order.gate_rule_id, order.regime_at_entry,
                order.mode,
            ),
        )
        self.conn.commit()

    def _row_to_order(self, row: sqlite3.Row) -> Order:
        return Order(
            order_id=row["order_id"], plan_id=row["plan_id"],
            broker_order_id=row["broker_order_id"], symbol=row["symbol"],
            side=row["side"], order_type=row["order_type"],
            qty_requested=row["qty_requested"],
            intended_price=row["intended_price"],
            submitted_at=datetime.fromisoformat(row["submitted_at"]),
            terminal_status=row["terminal_status"],
            gate_verdict=row["gate_verdict"], gate_rule_id=row["gate_rule_id"],
            regime_at_entry=row["regime_at_entry"], mode=row["mode"],
        )

    def get_order(self, order_id: str) -> Order | None:
        """Load one order by our own order_id. Returns None if absent."""
        row = self.conn.execute(
            "SELECT * FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        return self._row_to_order(row) if row else None

    def set_order_terminal(self, order_id: str, terminal_status: str) -> None:
        """Mark an order terminal.

        Args:
            order_id: Our order id.
            terminal_status: filled | partially_filled | cancelled | rejected |
                expired | unknown_historical.

        Returns:
            None. Unknown order_id is a no-op — reconciliation must never
            fail on a record it has not seen yet.
        """
        self.conn.execute(
            "UPDATE orders SET terminal_status = ? WHERE order_id = ?",
            (terminal_status, order_id),
        )
        self.conn.commit()

    def get_open_orders(self) -> list[Order]:
        """Orders with no terminal status yet, oldest first."""
        rows = self.conn.execute(
            "SELECT * FROM orders WHERE terminal_status IS NULL ORDER BY submitted_at"
        ).fetchall()
        return [self._row_to_order(r) for r in rows]

    # --- Fills (reality, append-only) ---

    def insert_fill(self, fill: Fill) -> bool:
        """Append one broker execution. Idempotent by primary key.

        Args:
            fill: The execution. `fill_id` must be the broker's activity id —
                a locally minted id would defeat the PK collision that makes
                replaying the activity feed safe.

        Returns:
            True if the row was inserted, False if this fill_id was already
            stored. INSERT OR IGNORE, never REPLACE: a re-insert must not
            rewrite the stored execution.

        Raises:
            ValueError: fill_id is empty.
        """
        if not fill.fill_id:
            raise ValueError(
                "fill_id is required and must be the broker's activity id; "
                "refusing to store a fill we cannot deduplicate"
            )
        cur = self.conn.execute(
            """INSERT OR IGNORE INTO fills
            (fill_id, broker_order_id, symbol, side, qty, price, fill_type,
             filled_at, mode)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                fill.fill_id, fill.broker_order_id, fill.symbol, fill.side,
                fill.qty, fill.price, fill.fill_type,
                fill.filled_at.isoformat(), fill.mode,
            ),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def get_fills_for_order(self, broker_order_id: str) -> list[Fill]:
        """All executions for one BROKER order id, in execution order.

        Args:
            broker_order_id: The broker's order id — the value the activity
                feed reports, i.e. `orders.broker_order_id`, NOT our own
                `orders.order_id`.

        Returns:
            Fills oldest-first. [] when the order has none, including for an
            order we never recorded (backfilled history, or a position opened
            outside this system).
        """
        rows = self.conn.execute(
            "SELECT * FROM fills WHERE broker_order_id = ? ORDER BY filled_at, fill_id",
            (broker_order_id,),
        ).fetchall()
        return [self._row_to_fill(r) for r in rows]

    @staticmethod
    def _row_to_fill(row: sqlite3.Row) -> Fill:
        return Fill(
            fill_id=row["fill_id"], broker_order_id=row["broker_order_id"],
            symbol=row["symbol"], side=row["side"], qty=row["qty"],
            price=row["price"], fill_type=row["fill_type"],
            filled_at=datetime.fromisoformat(row["filled_at"]),
            mode=row["mode"],
        )

    def get_all_fills(self) -> list[Fill]:
        """Every stored execution, oldest first.

        The input to the round-trip rebuild, which is why it reads the whole
        table: trips are a function of the complete fill history, not of a
        window of it.
        """
        rows = self.conn.execute(
            "SELECT * FROM fills ORDER BY filled_at, fill_id"
        ).fetchall()
        return [self._row_to_fill(r) for r in rows]

    # --- Sync cursors ---

    def get_sync_cursor(self, key: str) -> str | None:
        """Where an incremental sync last got to. None = never run."""
        row = self.conn.execute(
            "SELECT value FROM sync_state WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_sync_cursor(self, key: str, value: str | None) -> None:
        """Record sync progress.

        Args:
            key: Stream name, e.g. "fills:FILL".
            value: The broker's id of the last consumed item. None rewinds the
                stream to the beginning, which re-imports through the same code
                path rather than a separate backfill script.

        Returns:
            None.
        """
        self.conn.execute(
            """INSERT OR REPLACE INTO sync_state (key, value, updated_at)
            VALUES (?,?,?)""",
            (key, value, datetime.now(timezone.utc).replace(tzinfo=None).isoformat()),
        )
        self.conn.commit()

    # --- Workflow Checkpoints ---

    def save_checkpoint(self, cp: WorkflowCheckpoint) -> None:
        cp.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        self.conn.execute(
            """INSERT OR REPLACE INTO workflow_runs
            (workflow_run_id, status, sop_name, sop_version,
             checkpoint_data, error, started_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (
                cp.workflow_run_id, cp.status, cp.sop_name, cp.sop_version,
                json.dumps(cp.checkpoint_data), cp.error,
                cp.started_at.isoformat(), cp.updated_at.isoformat(),
            ),
        )
        self.conn.commit()

    def get_checkpoint(self, workflow_run_id: str) -> WorkflowCheckpoint | None:
        row = self.conn.execute(
            "SELECT * FROM workflow_runs WHERE workflow_run_id = ?",
            (workflow_run_id,),
        ).fetchone()
        if not row:
            return None
        return WorkflowCheckpoint(
            workflow_run_id=row["workflow_run_id"], status=row["status"],
            sop_name=row["sop_name"], sop_version=row["sop_version"],
            checkpoint_data=json.loads(row["checkpoint_data"]) if row["checkpoint_data"] else {},
            error=row["error"],
            started_at=datetime.fromisoformat(row["started_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def get_incomplete_workflows(self) -> list[WorkflowCheckpoint]:
        rows = self.conn.execute(
            "SELECT workflow_run_id FROM workflow_runs WHERE status NOT IN ('COMPLETED', 'FAILED')"
        ).fetchall()
        return [self.get_checkpoint(r["workflow_run_id"]) for r in rows]  # type: ignore

    # --- Journal Entries ---

    def save_journal_entry(self, entry: JournalEntry) -> None:
        self.conn.execute(
            """INSERT INTO journal_entries
            (plan_id, symbol, strategy, sop_version, entry_transactions,
             exit_transactions, pnl, pnl_pct, rationale, exit_reason,
             lessons, timestamp)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                entry.plan_id, entry.symbol, entry.strategy, entry.sop_version,
                json.dumps(entry.entry_transactions),
                json.dumps(entry.exit_transactions),
                entry.pnl, entry.pnl_pct, entry.rationale,
                entry.exit_reason, entry.lessons,
                entry.timestamp.isoformat(),
            ),
        )
        self.conn.commit()

    def get_journal_entries(self, since: datetime | None = None) -> list[JournalEntry]:
        sql = "SELECT * FROM journal_entries"
        params: tuple = ()
        if since:
            sql += " WHERE timestamp >= ?"
            params = (since.isoformat(),)
        sql += " ORDER BY timestamp DESC"
        rows = self.conn.execute(sql, params).fetchall()
        return [
            JournalEntry(
                plan_id=r["plan_id"], symbol=r["symbol"],
                strategy=r["strategy"], sop_version=r["sop_version"],
                entry_transactions=json.loads(r["entry_transactions"]) if r["entry_transactions"] else [],
                exit_transactions=json.loads(r["exit_transactions"]) if r["exit_transactions"] else [],
                pnl=r["pnl"], pnl_pct=r["pnl_pct"],
                rationale=r["rationale"], exit_reason=r["exit_reason"],
                lessons=r["lessons"],
                timestamp=datetime.fromisoformat(r["timestamp"]),
            )
            for r in rows
        ]

    # --- Price Data ---

    def save_price_bars(self, bars: list[dict]) -> None:
        self.conn.executemany(
            """INSERT OR REPLACE INTO price_data
            (symbol, timestamp, open, high, low, close, volume, timeframe)
            VALUES (?,?,?,?,?,?,?,?)""",
            [
                (b["symbol"], b["timestamp"], b["open"], b["high"],
                 b["low"], b["close"], b["volume"], b["timeframe"])
                for b in bars
            ],
        )
        self.conn.commit()

    def query_price_data(
        self, symbol: str, start: str, end: str, timeframe: str = "1Day"
    ) -> list[dict]:
        rows = self.conn.execute(
            """SELECT * FROM price_data
            WHERE symbol = ? AND timeframe = ? AND timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp""",
            (symbol, timeframe, start, end),
        ).fetchall()
        return [dict(r) for r in rows]

    def latest_price_date(self, symbol: str, timeframe: str = "1Day") -> str | None:
        """Return the max timestamp stored for a symbol/timeframe, or None."""
        row = self.conn.execute(
            "SELECT MAX(timestamp) AS mx FROM price_data WHERE symbol = ? AND timeframe = ?",
            (symbol, timeframe),
        ).fetchone()
        return row["mx"] if row and row["mx"] else None

    def clear_price_data(self, timeframe: str = "1Day") -> int:
        """Delete all bars of a timeframe (used before a clean re-load). Returns rows deleted."""
        cur = self.conn.execute("DELETE FROM price_data WHERE timeframe = ?", (timeframe,))
        self.conn.commit()
        return cur.rowcount

    # --- Decision Audit ---

    def save_decision(self, d: "DecisionLogEntry") -> None:
        from models import DecisionLogEntry  # noqa: F811
        self.conn.execute(
            """INSERT OR REPLACE INTO decisions
            (decision_id, timestamp, agent, action, symbol, rules_triggered,
             rules_considered, reasoning, sop_version, plan_id, market_context, violations)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (d.decision_id, d.timestamp.isoformat(), d.agent, d.action, d.symbol,
             json.dumps(d.rules_triggered), json.dumps(d.rules_considered),
             d.reasoning, d.sop_version, d.plan_id,
             json.dumps(d.market_context), json.dumps(d.violations)),
        )
        self.conn.commit()

    def query_decisions(
        self, symbol: str = "", agent: str = "", action: str = "",
        sop_version: str = "", start_date: str = "", end_date: str = "",
        has_violation: bool | None = None, limit: int = 50,
    ) -> list[dict]:
        sql = "SELECT * FROM decisions WHERE 1=1"
        params: list = []
        if symbol:
            sql += " AND symbol = ?"
            params.append(symbol)
        if agent:
            sql += " AND agent = ?"
            params.append(agent)
        if action:
            sql += " AND action = ?"
            params.append(action)
        if sop_version:
            sql += " AND sop_version = ?"
            params.append(sop_version)
        if start_date:
            sql += " AND timestamp >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND timestamp <= ?"
            params.append(end_date)
        if has_violation is True:
            sql += " AND violations != '[]'"
        elif has_violation is False:
            sql += " AND (violations = '[]' OR violations IS NULL)"
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["rules_triggered"] = json.loads(d["rules_triggered"] or "[]")
            d["rules_considered"] = json.loads(d["rules_considered"] or "[]")
            d["market_context"] = json.loads(d["market_context"] or "{}")
            d["violations"] = json.loads(d["violations"] or "[]")
            results.append(d)
        return results

    # --- Transaction Ledger ---

    def save_ledger_entry(self, e: "LedgerEntry") -> None:
        from models import LedgerEntry  # noqa: F811
        self.conn.execute(
            """INSERT OR REPLACE INTO transaction_ledger
            (ledger_id, timestamp, action, symbol, quantity, order_type, price,
             total_cost, fees, status, broker_order_id, account_equity, account_cash,
             buying_power, pnl, pnl_pct, entry_price, plan_id, decision_id,
             sop_version, platform, trigger, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (e.ledger_id, e.timestamp.isoformat(), e.action, e.symbol, e.quantity,
             e.order_type, e.price, e.total_cost, e.fees, e.status,
             e.broker_order_id, e.account_equity, e.account_cash, e.buying_power,
             e.pnl, e.pnl_pct, e.entry_price, e.plan_id, e.decision_id,
             e.sop_version, e.platform, e.trigger, e.notes),
        )
        self.conn.commit()

    def query_ledger(
        self, symbol: str = "", action: str = "", start_date: str = "",
        end_date: str = "", sop_version: str = "", platform: str = "",
        trigger: str = "", limit: int = 50,
    ) -> list[dict]:
        sql = "SELECT * FROM transaction_ledger WHERE 1=1"
        params: list = []
        if symbol:
            sql += " AND symbol = ?"
            params.append(symbol)
        if action:
            sql += " AND action = ?"
            params.append(action)
        if start_date:
            sql += " AND timestamp >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND timestamp <= ?"
            params.append(end_date)
        if sop_version:
            sql += " AND sop_version = ?"
            params.append(sop_version)
        if platform:
            sql += " AND platform = ?"
            params.append(platform)
        if trigger:
            sql += " AND trigger = ?"
            params.append(trigger)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # --- Performance Reports ---

    def save_report(self, r: "PerformanceReport") -> None:
        from models import PerformanceReport  # noqa: F811
        self.conn.execute(
            """INSERT OR REPLACE INTO performance_reports
            (report_id, report_type, start_date, end_date, sop_version, metrics, generated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (r.report_id, r.report_type, r.start_date.isoformat(),
             r.end_date.isoformat(), r.sop_version,
             json.dumps(r.metrics), r.generated_at.isoformat()),
        )
        self.conn.commit()

    def get_reports(
        self, report_type: str = "", start_date: str = "", end_date: str = "", limit: int = 20
    ) -> list[dict]:
        sql = "SELECT * FROM performance_reports WHERE 1=1"
        params: list = []
        if report_type:
            sql += " AND report_type = ?"
            params.append(report_type)
        if start_date:
            sql += " AND start_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND end_date <= ?"
            params.append(end_date)
        sql += " ORDER BY generated_at DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["metrics"] = json.loads(d["metrics"] or "{}")
            results.append(d)
        return results

    # --- Backtest ---

    def save_backtest_run(self, run: dict) -> None:
        self.conn.execute(
            """INSERT INTO backtest_runs
            (run_id, started_at, symbols, start_date, end_date, timeframe,
             initial_capital, sop_version, skill_versions, config_snapshot, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (run["run_id"], run["started_at"], run["symbols"],
             run["start_date"], run["end_date"], run["timeframe"],
             run["initial_capital"], run.get("sop_version"),
             run.get("skill_versions"), run.get("config_snapshot"), "running"),
        )
        self.conn.commit()

    def get_backtest_run(self, run_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM backtest_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return dict(row) if row else None

    def update_backtest_run(self, run_id: str, **fields) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [run_id]
        self.conn.execute(f"UPDATE backtest_runs SET {sets} WHERE run_id = ?", vals)
        self.conn.commit()

    def save_backtest_decision(self, d: dict) -> None:
        self.conn.execute(
            """INSERT INTO backtest_decisions
            (decision_id, run_id, bar_index, timestamp, symbol, phase,
             input_state, tools_called, rules_evaluated, score, decision,
             reasoning, trade_plan, workflow_valid, violation_details)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (d["decision_id"], d["run_id"], d["bar_index"], d["timestamp"],
             d["symbol"], d["phase"], d["input_state"], d["tools_called"],
             d["rules_evaluated"], d.get("score"), d["decision"],
             d["reasoning"], d.get("trade_plan"), d["workflow_valid"],
             d.get("violation_details")),
        )
        self.conn.commit()

    def get_backtest_decisions(self, run_id: str, symbol: str = "", limit: int = 10000) -> list[dict]:
        query = "SELECT * FROM backtest_decisions WHERE run_id = ?"
        params: list = [run_id]
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        query += " ORDER BY bar_index LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def update_backtest_decision(self, decision_id: str, **fields) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [decision_id]
        self.conn.execute(f"UPDATE backtest_decisions SET {sets} WHERE decision_id = ?", vals)
        self.conn.commit()

    def save_backtest_trade(self, t: dict) -> None:
        self.conn.execute(
            """INSERT INTO backtest_trades
            (trade_id, run_id, symbol, side, entry_bar, entry_timestamp,
             entry_price, entry_quantity, entry_decision_id)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (t["trade_id"], t["run_id"], t["symbol"], t["side"],
             t["entry_bar"], t["entry_timestamp"], t["entry_price"],
             t["entry_quantity"], t["entry_decision_id"]),
        )
        self.conn.commit()

    def update_backtest_trade(self, trade_id: str, **fields) -> None:
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [trade_id]
        self.conn.execute(f"UPDATE backtest_trades SET {sets} WHERE trade_id = ?", vals)
        self.conn.commit()

    def get_backtest_trades(self, run_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM backtest_trades WHERE run_id = ? ORDER BY entry_bar", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # --- IV History ---

    def save_iv_data(self, symbol: str, date: str, iv: float, source: str = "snapshot") -> None:
        """Cache a single IV data point. Idempotent (INSERT OR IGNORE)."""
        self.conn.execute(
            "INSERT OR IGNORE INTO iv_history (symbol, date, iv, source) VALUES (?, ?, ?, ?)",
            (symbol, date, iv, source),
        )
        self.conn.commit()

    def save_iv_data_batch(self, rows: list[dict]) -> None:
        """Batch insert IV data points. Each row: {symbol, date, iv, source}."""
        self.conn.executemany(
            "INSERT OR IGNORE INTO iv_history (symbol, date, iv, source) VALUES (:symbol, :date, :iv, :source)",
            rows,
        )
        self.conn.commit()

    def query_iv_history(self, symbol: str, min_days: int = 60) -> list[float]:
        """Return list of historical IV values, sorted ascending by date.
        Returns empty list if fewer than min_days data points exist."""
        rows = self.conn.execute(
            "SELECT iv FROM iv_history WHERE symbol = ? ORDER BY date ASC",
            (symbol,),
        ).fetchall()
        if len(rows) < min_days:
            return []
        return [r["iv"] for r in rows]

    def count_iv_history(self, symbol: str) -> int:
        """Return number of cached IV data points for a symbol."""
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM iv_history WHERE symbol = ?",
            (symbol,),
        ).fetchone()
        return row["cnt"] if row else 0

    def save_scan_funnel(self, row: dict) -> None:
        """Persist one scan-funnel record (mechanical scan stats for a run)."""
        self.conn.execute(
            """INSERT INTO scan_funnel
            (date, timestamp, scan_type, universe_size, loaded, scanned, passed,
             passed_m, passed_r, data_stale, as_of, candidates)
            VALUES (:date, :timestamp, :scan_type, :universe_size, :loaded, :scanned,
             :passed, :passed_m, :passed_r, :data_stale, :as_of, :candidates)""",
            row,
        )
        self.conn.commit()

    def query_scan_funnel(self, date: str) -> list[dict]:
        """All scan-funnel records for a date (newest first)."""
        rows = self.conn.execute(
            "SELECT * FROM scan_funnel WHERE date = ? ORDER BY timestamp DESC", (date,)
        ).fetchall()
        return [dict(r) for r in rows]
