"""Structured logging for backtest decisions."""

import json
import uuid
from datetime import datetime, timezone

from persistence.repository import Repository


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class BacktestLogger:
    def __init__(self, repo: Repository):
        self.repo = repo

    def create_run(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
        timeframe: str,
        initial_capital: float,
        sop_version: str = "",
        skill_versions: dict | None = None,
        config_snapshot: dict | None = None,
    ) -> str:
        run_id = f"bt-{_new_id()}"
        self.repo.save_backtest_run({
            "run_id": run_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "symbols": json.dumps(symbols),
            "start_date": start_date,
            "end_date": end_date,
            "timeframe": timeframe,
            "initial_capital": initial_capital,
            "sop_version": sop_version,
            "skill_versions": json.dumps(skill_versions or {}),
            "config_snapshot": json.dumps(config_snapshot or {}),
        })
        return run_id

    def log_decision(
        self,
        run_id: str,
        bar_index: int,
        timestamp: str,
        symbol: str,
        phase: str,
        input_state: dict,
        tools_called: list[str],
        rules_evaluated: list[dict],
        score: float | None,
        decision: str,
        reasoning: str,
        trade_plan: dict | None,
        workflow_valid: bool,
        violation_details: str = "",
    ) -> str:
        decision_id = f"bd-{_new_id()}"
        self.repo.save_backtest_decision({
            "decision_id": decision_id,
            "run_id": run_id,
            "bar_index": bar_index,
            "timestamp": timestamp,
            "symbol": symbol,
            "phase": phase,
            "input_state": json.dumps(input_state),
            "tools_called": json.dumps(tools_called),
            "rules_evaluated": json.dumps(rules_evaluated),
            "score": score,
            "decision": decision,
            "reasoning": reasoning,
            "trade_plan": json.dumps(trade_plan) if trade_plan else None,
            "workflow_valid": 1 if workflow_valid else 0,
            "violation_details": violation_details or None,
        })
        return decision_id

    def complete_run(
        self,
        run_id: str,
        final_equity: float,
        total_pnl: float,
        total_trades: int,
        win_rate: float,
        expectancy: float,
        max_drawdown: float,
    ) -> None:
        run = self.repo.get_backtest_run(run_id)
        self.repo.update_backtest_run(
            run_id,
            status="completed",
            completed_at=datetime.now(timezone.utc).isoformat(),
            final_equity=final_equity,
            total_pnl=total_pnl,
            total_pnl_pct=round(total_pnl / run["initial_capital"] * 100, 2),
            total_trades=total_trades,
            win_rate=win_rate,
            expectancy=expectancy,
            max_drawdown=max_drawdown,
        )

    def export_jsonl(self, run_id: str) -> list[str]:
        decisions = self.repo.get_backtest_decisions(run_id)
        lines = []
        for d in decisions:
            record = {
                "run_id": d["run_id"],
                "bar": d["bar_index"],
                "timestamp": d["timestamp"],
                "symbol": d["symbol"],
                "phase": d["phase"],
                "input_state": json.loads(d["input_state"]),
                "tools_called": json.loads(d["tools_called"]),
                "rules_evaluated": json.loads(d["rules_evaluated"]) if d["rules_evaluated"] else [],
                "score": d["score"],
                "decision": d["decision"],
                "reasoning": d["reasoning"],
                "trade_plan": json.loads(d["trade_plan"]) if d["trade_plan"] else None,
                "workflow_valid": bool(d["workflow_valid"]),
                "outcome": None,
            }
            if d.get("outcome_label"):
                record["outcome"] = {
                    "pnl": d["outcome_pnl"],
                    "pnl_pct": d["outcome_pnl_pct"],
                    "r_multiple": d["outcome_r_multiple"],
                    "exit_bar": d["outcome_exit_bar"],
                    "exit_price": d["outcome_exit_price"],
                    "exit_reason": d["outcome_exit_reason"],
                    "label": d["outcome_label"],
                }
            lines.append(json.dumps(record))
        return lines
