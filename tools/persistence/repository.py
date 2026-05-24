"""Repository layer — CRUD operations for all models."""

import json
import sqlite3
from datetime import datetime, timezone

from models import (
    JournalEntry,
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
             trailing_stop, time_stop, risk_assessment, rationale, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                plan.plan_id, plan.symbol, plan.strategy, plan.sop_version,
                plan.side, plan.quantity, plan.entry_order_type,
                plan.entry_limit_price, plan.take_profit, plan.stop_loss,
                plan.trailing_stop,
                plan.time_stop.isoformat() if plan.time_stop else None,
                json.dumps(plan.risk_assessment), plan.rationale,
                plan.created_at.isoformat(),
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
