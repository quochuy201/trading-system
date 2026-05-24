# Backtest Engine v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a backtest harness that forces the agent through the full skill workflow bar-by-bar, logs structured decisions to SQLite, validates workflow compliance, and exports JSONL for training pipelines.

**Architecture:** Four new modules (WorkflowValidator, BacktestLogger, OutcomeLabeler, BacktestHarness) + schema additions to db.py + new MCP tools in server.py. Builds on the existing SimulationBroker which already handles temporal data isolation.

**Tech Stack:** Python 3.11+, SQLite, existing MCP server (FastMCP), existing SimulationBrokerAdapter, pytest.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `tools/backtest/validator.py` | NEW — WorkflowValidator: tracks tool calls per bar, validates required steps |
| `tools/backtest/logger.py` | NEW — BacktestLogger: writes structured decision records to SQLite |
| `tools/backtest/labeler.py` | NEW — OutcomeLabeler: retroactively labels decisions with P&L outcomes |
| `tools/backtest/harness.py` | NEW — BacktestHarness: orchestrates the full run (batch + interactive) |
| `tools/backtest/engine.py` | EXISTING — keep `run_replay`, `step_through` for backward compat |
| `tools/persistence/db.py` | MODIFY — add 3 new tables (backtest_runs, backtest_decisions, backtest_trades) |
| `tools/persistence/repository.py` | MODIFY — add CRUD methods for new tables |
| `tools/server.py` | MODIFY — add 6 new MCP tools |
| `tools/tests/test_validator.py` | NEW — tests for WorkflowValidator |
| `tools/tests/test_backtest_logger.py` | NEW — tests for BacktestLogger |
| `tools/tests/test_labeler.py` | NEW — tests for OutcomeLabeler |
| `tools/tests/test_harness.py` | NEW — integration tests for BacktestHarness |

---

### Task 1: Add Backtest Tables to Database Schema

**Files:**
- Modify: `tools/persistence/db.py`
- Test: `tools/tests/test_models_and_persistence.py`

- [ ] **Step 1: Write the failing test**

```python
# In tools/tests/test_models_and_persistence.py — add at the bottom

def test_backtest_tables_exist():
    """Verify backtest tables are created by init_db."""
    from persistence.db import get_connection, init_db
    conn = get_connection(":memory:")
    init_db(conn)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'backtest_%'")
    tables = {row[0] for row in cursor.fetchall()}
    assert tables == {"backtest_runs", "backtest_decisions", "backtest_trades"}
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_models_and_persistence.py::test_backtest_tables_exist -v`
Expected: FAIL — tables don't exist yet

- [ ] **Step 3: Add schema to db.py**

Append to the `SCHEMA` string in `tools/persistence/db.py` (before the closing `"""`):

```sql
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    symbols TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    initial_capital REAL NOT NULL,
    final_equity REAL,
    total_pnl REAL,
    total_pnl_pct REAL,
    total_trades INTEGER,
    win_rate REAL,
    expectancy REAL,
    max_drawdown REAL,
    sop_version TEXT,
    skill_versions TEXT,
    config_snapshot TEXT,
    status TEXT DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS backtest_decisions (
    decision_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    bar_index INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    phase TEXT NOT NULL,
    input_state TEXT NOT NULL,
    tools_called TEXT NOT NULL,
    rules_evaluated TEXT,
    score REAL,
    decision TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    trade_plan TEXT,
    workflow_valid INTEGER NOT NULL,
    violation_details TEXT,
    outcome_pnl REAL,
    outcome_pnl_pct REAL,
    outcome_r_multiple REAL,
    outcome_exit_bar INTEGER,
    outcome_exit_price REAL,
    outcome_exit_reason TEXT,
    outcome_label TEXT,
    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id)
);

CREATE TABLE IF NOT EXISTS backtest_trades (
    trade_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_bar INTEGER NOT NULL,
    entry_timestamp TEXT NOT NULL,
    entry_price REAL NOT NULL,
    entry_quantity INTEGER NOT NULL,
    entry_decision_id TEXT NOT NULL,
    exit_bar INTEGER,
    exit_timestamp TEXT,
    exit_price REAL,
    exit_reason TEXT,
    exit_decision_id TEXT,
    pnl REAL,
    pnl_pct REAL,
    r_multiple REAL,
    hold_bars INTEGER,
    max_favorable_excursion REAL,
    max_adverse_excursion REAL,
    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id)
);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools && uv run --extra dev pytest tests/test_models_and_persistence.py::test_backtest_tables_exist -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/persistence/db.py tools/tests/test_models_and_persistence.py
git commit -m "feat: add backtest schema tables (runs, decisions, trades)"
```

---

### Task 2: WorkflowValidator

**Files:**
- Create: `tools/backtest/validator.py`
- Create: `tools/tests/test_validator.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/tests/test_validator.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.validator import WorkflowValidator


class TestWorkflowValidator:
    def setup_method(self):
        self.validator = WorkflowValidator()

    def test_research_valid_when_all_tools_called(self):
        self.validator.record_tool_call("calc_technical_indicators")
        self.validator.record_tool_call("get_market_data")
        result = self.validator.validate("research", "skip")
        assert result["valid"] is True
        assert result["missing"] == []

    def test_research_invalid_when_missing_indicators(self):
        self.validator.record_tool_call("get_market_data")
        result = self.validator.validate("research", "enter")
        assert result["valid"] is False
        assert "calc_technical_indicators" in result["missing"]

    def test_trader_valid_when_all_risk_checks_called(self):
        self.validator.record_tool_call("check_kill_switch")
        self.validator.record_tool_call("check_daily_limits")
        self.validator.record_tool_call("check_portfolio_risk")
        self.validator.record_tool_call("calc_position_size")
        result = self.validator.validate("trader", "enter")
        assert result["valid"] is True

    def test_trader_invalid_missing_kill_switch(self):
        self.validator.record_tool_call("check_daily_limits")
        self.validator.record_tool_call("check_portfolio_risk")
        self.validator.record_tool_call("calc_position_size")
        result = self.validator.validate("trader", "enter")
        assert result["valid"] is False
        assert "check_kill_switch" in result["missing"]

    def test_monitor_hold_valid(self):
        self.validator.record_tool_call("get_positions")
        self.validator.record_tool_call("get_market_data")
        result = self.validator.validate("monitor", "hold")
        assert result["valid"] is True

    def test_reset_clears_state(self):
        self.validator.record_tool_call("get_market_data")
        self.validator.reset()
        result = self.validator.validate("research", "skip")
        assert result["valid"] is False

    def test_get_calls_returns_recorded_tools(self):
        self.validator.record_tool_call("get_market_data")
        self.validator.record_tool_call("calc_technical_indicators")
        assert set(self.validator.get_calls()) == {"get_market_data", "calc_technical_indicators"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_validator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backtest.validator'`

- [ ] **Step 3: Implement WorkflowValidator**

```python
# tools/backtest/validator.py
"""Validates that the agent called required tools before making a decision."""

REQUIRED_TOOLS = {
    "research": {
        "enter": ["calc_technical_indicators", "get_market_data"],
        "skip": ["calc_technical_indicators", "get_market_data"],
    },
    "trader": {
        "enter": ["check_kill_switch", "check_daily_limits", "check_portfolio_risk", "calc_position_size"],
    },
    "monitor": {
        "hold": ["get_positions", "get_market_data"],
        "exit": ["get_positions", "get_market_data"],
    },
}


class WorkflowValidator:
    def __init__(self):
        self._calls: list[str] = []

    def record_tool_call(self, tool_name: str) -> None:
        self._calls.append(tool_name)

    def validate(self, phase: str, decision: str) -> dict:
        required = REQUIRED_TOOLS.get(phase, {}).get(decision, [])
        called_set = set(self._calls)
        missing = [t for t in required if t not in called_set]
        return {
            "valid": len(missing) == 0,
            "missing": missing,
            "required": required,
            "called": list(called_set),
        }

    def get_calls(self) -> list[str]:
        return list(self._calls)

    def reset(self) -> None:
        self._calls = []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools && uv run --extra dev pytest tests/test_validator.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tools/backtest/validator.py tools/tests/test_validator.py
git commit -m "feat: add WorkflowValidator for backtest workflow enforcement"
```

---

### Task 3: BacktestLogger

**Files:**
- Create: `tools/backtest/logger.py`
- Modify: `tools/persistence/repository.py`
- Create: `tools/tests/test_backtest_logger.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/tests/test_backtest_logger.py
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.logger import BacktestLogger
from persistence.repository import Repository


class TestBacktestLogger:
    def setup_method(self):
        self.repo = Repository(":memory:")
        self.logger = BacktestLogger(self.repo)

    def teardown_method(self):
        self.repo.close()

    def test_create_run(self):
        run_id = self.logger.create_run(
            symbols=["NVDA", "AAPL"],
            start_date="2026-01-01",
            end_date="2026-05-01",
            timeframe="1Day",
            initial_capital=100000.0,
            sop_version="v1.0.0",
        )
        assert run_id is not None
        run = self.repo.get_backtest_run(run_id)
        assert run["symbols"] == '["NVDA", "AAPL"]'
        assert run["status"] == "running"

    def test_log_decision(self):
        run_id = self.logger.create_run(
            symbols=["NVDA"], start_date="2026-01-01",
            end_date="2026-05-01", timeframe="1Day",
            initial_capital=100000.0,
        )
        decision_id = self.logger.log_decision(
            run_id=run_id,
            bar_index=10,
            timestamp="2026-01-15",
            symbol="NVDA",
            phase="research",
            input_state={"price": 220.5, "rsi": 65.2, "atr": 4.5},
            tools_called=["calc_technical_indicators", "get_market_data"],
            rules_evaluated=[{"rule": "RSI_RANGE", "passed": True, "value": "65.2 in [50,75]"}],
            score=82.0,
            decision="enter",
            reasoning="Breakout on volume",
            trade_plan={"entry": 220.5, "stop": 215.0, "target": 232.0},
            workflow_valid=True,
        )
        assert decision_id is not None
        decisions = self.repo.get_backtest_decisions(run_id)
        assert len(decisions) == 1
        assert decisions[0]["decision"] == "enter"
        assert decisions[0]["workflow_valid"] == 1

    def test_complete_run(self):
        run_id = self.logger.create_run(
            symbols=["NVDA"], start_date="2026-01-01",
            end_date="2026-05-01", timeframe="1Day",
            initial_capital=100000.0,
        )
        self.logger.complete_run(
            run_id=run_id,
            final_equity=105000.0,
            total_pnl=5000.0,
            total_trades=8,
            win_rate=0.625,
            expectancy=106.0,
            max_drawdown=420.0,
        )
        run = self.repo.get_backtest_run(run_id)
        assert run["status"] == "completed"
        assert run["final_equity"] == 105000.0

    def test_export_jsonl(self):
        run_id = self.logger.create_run(
            symbols=["NVDA"], start_date="2026-01-01",
            end_date="2026-05-01", timeframe="1Day",
            initial_capital=100000.0,
        )
        self.logger.log_decision(
            run_id=run_id, bar_index=1, timestamp="2026-01-02",
            symbol="NVDA", phase="research",
            input_state={"price": 200.0}, tools_called=["get_market_data"],
            rules_evaluated=[], score=None, decision="skip",
            reasoning="No setup", trade_plan=None, workflow_valid=True,
        )
        lines = self.logger.export_jsonl(run_id)
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["decision"] == "skip"
        assert record["symbol"] == "NVDA"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_backtest_logger.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Add repository methods for backtest tables**

Add these methods to `tools/persistence/repository.py`:

```python
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
```

- [ ] **Step 4: Implement BacktestLogger**

```python
# tools/backtest/logger.py
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
        self.repo.update_backtest_run(
            run_id,
            status="completed",
            completed_at=datetime.now(timezone.utc).isoformat(),
            final_equity=final_equity,
            total_pnl=total_pnl,
            total_pnl_pct=round(total_pnl / self.repo.get_backtest_run(run_id)["initial_capital"] * 100, 2),
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
            if d["outcome_label"]:
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd tools && uv run --extra dev pytest tests/test_backtest_logger.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add tools/backtest/logger.py tools/persistence/repository.py tools/tests/test_backtest_logger.py
git commit -m "feat: add BacktestLogger with structured decision recording and JSONL export"
```

---

### Task 4: OutcomeLabeler

**Files:**
- Create: `tools/backtest/labeler.py`
- Create: `tools/tests/test_labeler.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/tests/test_labeler.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.labeler import OutcomeLabeler


class TestOutcomeLabeler:
    def test_good_entry_label(self):
        label = OutcomeLabeler.label_entry(r_multiple=2.0)
        assert label == "GOOD_ENTRY"

    def test_bad_entry_label(self):
        label = OutcomeLabeler.label_entry(r_multiple=-1.0)
        assert label == "BAD_ENTRY"

    def test_neutral_entry_positive(self):
        label = OutcomeLabeler.label_entry(r_multiple=0.8)
        assert label == "NEUTRAL"

    def test_neutral_entry_small_loss(self):
        label = OutcomeLabeler.label_entry(r_multiple=-0.3)
        assert label == "NEUTRAL"

    def test_good_exit_price_reversed(self):
        label = OutcomeLabeler.label_exit(
            exit_pnl=500.0,
            price_after_exit_moved=−200.0,  # price dropped after exit
        )
        assert label == "GOOD_EXIT"

    def test_early_exit_price_continued(self):
        label = OutcomeLabeler.label_exit(
            exit_pnl=500.0,
            price_after_exit_moved=800.0,  # price continued up significantly
        )
        assert label == "EARLY_EXIT"

    def test_expected_loss_at_stop(self):
        label = OutcomeLabeler.label_exit(
            exit_pnl=-200.0,
            price_after_exit_moved=0.0,
            exited_at_planned_stop=True,
        )
        assert label == "EXPECTED_LOSS"

    def test_bad_exit_below_stop(self):
        label = OutcomeLabeler.label_exit(
            exit_pnl=-500.0,
            price_after_exit_moved=0.0,
            exited_at_planned_stop=False,
        )
        assert label == "BAD_EXIT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_labeler.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement OutcomeLabeler**

```python
# tools/backtest/labeler.py
"""Retroactively labels backtest decisions with outcome quality."""


class OutcomeLabeler:
    @staticmethod
    def label_entry(r_multiple: float) -> str:
        if r_multiple >= 1.5:
            return "GOOD_ENTRY"
        elif r_multiple <= -0.5:
            return "BAD_ENTRY"
        return "NEUTRAL"

    @staticmethod
    def label_exit(
        exit_pnl: float,
        price_after_exit_moved: float,
        exited_at_planned_stop: bool = False,
    ) -> str:
        if exit_pnl < 0:
            if exited_at_planned_stop:
                return "EXPECTED_LOSS"
            return "BAD_EXIT"
        # Profitable exit
        if price_after_exit_moved > exit_pnl:
            return "EARLY_EXIT"
        return "GOOD_EXIT"

    @staticmethod
    def compute_r_multiple(entry_price: float, exit_price: float, stop_price: float, side: str = "long") -> float:
        if side == "long":
            risk = entry_price - stop_price
            reward = exit_price - entry_price
        else:
            risk = stop_price - entry_price
            reward = entry_price - exit_price
        if risk <= 0:
            return 0.0
        return round(reward / risk, 2)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools && uv run --extra dev pytest tests/test_labeler.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tools/backtest/labeler.py tools/tests/test_labeler.py
git commit -m "feat: add OutcomeLabeler for retroactive decision quality labeling"
```

---

### Task 5: BacktestHarness (Core Orchestration)

**Files:**
- Create: `tools/backtest/harness.py`
- Create: `tools/tests/test_harness.py`

- [ ] **Step 1: Write the failing test**

```python
# tools/tests/test_harness.py
import sys
import json
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.harness import BacktestHarness
from persistence.repository import Repository


def _load_sample_bars(repo, symbol="NVDA", days=20):
    """Load synthetic daily bars."""
    import random
    random.seed(123)
    price = 200.0
    bars = []
    for i in range(days):
        o = price
        h = price + random.uniform(1, 5)
        l = price - random.uniform(1, 5)
        c = price + random.uniform(-3, 4)
        price = c
        bars.append({
            "symbol": symbol,
            "timestamp": f"2026-01-{(i+2):02d}",
            "open": round(o, 2), "high": round(h, 2),
            "low": round(l, 2), "close": round(c, 2),
            "volume": 5000000 + random.randint(-1000000, 3000000),
            "timeframe": "1Day",
        })
    repo.save_price_bars(bars)


class TestBacktestHarness:
    def setup_method(self):
        self.repo = Repository(":memory:")
        _load_sample_bars(self.repo, "NVDA", 20)

    def teardown_method(self):
        self.repo.close()

    def test_harness_creates_run(self):
        harness = BacktestHarness(self.repo)
        run_id = harness.start(
            symbols=["NVDA"],
            start_date="2026-01-02",
            end_date="2026-01-21",
            timeframe="1Day",
            initial_capital=100000.0,
        )
        assert run_id.startswith("bt-")
        run = self.repo.get_backtest_run(run_id)
        assert run["status"] == "running"

    def test_harness_advance_bar_returns_data(self):
        harness = BacktestHarness(self.repo)
        harness.start(symbols=["NVDA"], start_date="2026-01-02",
                      end_date="2026-01-21", timeframe="1Day", initial_capital=100000.0)
        bar_data = harness.advance_bar()
        assert bar_data is not None
        assert "timestamp" in bar_data
        assert "close" in bar_data
        assert bar_data["bar_index"] == 0

    def test_harness_log_decision_records(self):
        harness = BacktestHarness(self.repo)
        run_id = harness.start(symbols=["NVDA"], start_date="2026-01-02",
                               end_date="2026-01-21", timeframe="1Day", initial_capital=100000.0)
        harness.advance_bar()
        harness.record_decision(
            symbol="NVDA", phase="research", decision="skip",
            reasoning="No setup", input_state={"price": 200.0},
            tools_called=["calc_technical_indicators", "get_market_data"],
            rules_evaluated=[], score=None, trade_plan=None,
        )
        decisions = self.repo.get_backtest_decisions(run_id)
        assert len(decisions) == 1
        assert decisions[0]["decision"] == "skip"

    def test_harness_workflow_validation(self):
        harness = BacktestHarness(self.repo)
        run_id = harness.start(symbols=["NVDA"], start_date="2026-01-02",
                               end_date="2026-01-21", timeframe="1Day", initial_capital=100000.0)
        harness.advance_bar()
        # Record decision WITHOUT required tools
        harness.record_decision(
            symbol="NVDA", phase="research", decision="enter",
            reasoning="Looks good", input_state={"price": 200.0},
            tools_called=[],  # missing required tools!
            rules_evaluated=[], score=80, trade_plan={"entry": 200, "stop": 195, "target": 210},
        )
        decisions = self.repo.get_backtest_decisions(run_id)
        assert decisions[0]["workflow_valid"] == 0  # violation detected

    def test_harness_done_after_all_bars(self):
        harness = BacktestHarness(self.repo)
        harness.start(symbols=["NVDA"], start_date="2026-01-02",
                      end_date="2026-01-21", timeframe="1Day", initial_capital=100000.0)
        count = 0
        while True:
            bar = harness.advance_bar()
            if bar is None:
                break
            harness.record_decision(
                symbol="NVDA", phase="research", decision="skip",
                reasoning="No setup", input_state={"price": bar["close"]},
                tools_called=["calc_technical_indicators", "get_market_data"],
                rules_evaluated=[], score=None, trade_plan=None,
            )
            count += 1
        assert count == 20
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_harness.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement BacktestHarness**

```python
# tools/backtest/harness.py
"""Backtest harness — orchestrates bar-by-bar execution with workflow enforcement."""

from datetime import datetime

from broker.simulation import SimulationBrokerAdapter
from backtest.validator import WorkflowValidator
from backtest.logger import BacktestLogger
from persistence.repository import Repository


class BacktestHarness:
    def __init__(self, repo: Repository):
        self.repo = repo
        self.logger = BacktestLogger(repo)
        self.validator = WorkflowValidator()
        self.broker: SimulationBrokerAdapter | None = None
        self.run_id: str | None = None
        self._bars: list[dict] = []
        self._bar_index: int = 0
        self._symbols: list[str] = []
        self._current_bar: dict | None = None

    def start(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
        timeframe: str = "1Day",
        initial_capital: float = 100000.0,
        sop_version: str = "",
    ) -> str:
        self._symbols = symbols
        # Load bars for the first symbol (multi-symbol: interleave later)
        all_bars = []
        for sym in symbols:
            bars = self.repo.query_price_data(sym, start_date, end_date, timeframe)
            all_bars.extend(bars)
        # Sort by timestamp for chronological replay
        all_bars.sort(key=lambda b: b["timestamp"])
        # Deduplicate by timestamp (one bar per timestamp for single-symbol v1)
        seen = set()
        self._bars = []
        for bar in all_bars:
            key = (bar["symbol"], bar["timestamp"])
            if key not in seen:
                seen.add(key)
                self._bars.append(bar)

        self._bar_index = 0

        self.broker = SimulationBrokerAdapter(
            repo=self.repo,
            initial_capital=initial_capital,
            slippage_pct=0.05,
            timeframe=timeframe,
        )

        self.run_id = self.logger.create_run(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            timeframe=timeframe,
            initial_capital=initial_capital,
            sop_version=sop_version,
        )
        return self.run_id

    def advance_bar(self) -> dict | None:
        if self._bar_index >= len(self._bars):
            return None

        bar = self._bars[self._bar_index]
        self._current_bar = bar
        self._bar_index += 1

        # Advance simulation clock
        ts = bar["timestamp"]
        try:
            self.broker.set_time(datetime.fromisoformat(ts))
        except (ValueError, TypeError):
            self.broker.set_time(datetime.strptime(str(ts), "%Y-%m-%d"))

        # Reset validator for this bar
        self.validator.reset()

        return {
            "bar_index": self._bar_index - 1,
            "timestamp": bar["timestamp"],
            "symbol": bar["symbol"],
            "open": bar["open"],
            "high": bar["high"],
            "low": bar["low"],
            "close": bar["close"],
            "volume": bar.get("volume", 0),
            "remaining": len(self._bars) - self._bar_index,
        }

    def record_tool_call(self, tool_name: str) -> None:
        self.validator.record_tool_call(tool_name)

    def record_decision(
        self,
        symbol: str,
        phase: str,
        decision: str,
        reasoning: str,
        input_state: dict,
        tools_called: list[str],
        rules_evaluated: list[dict],
        score: float | None = None,
        trade_plan: dict | None = None,
    ) -> str:
        # Record tools that were passed in (for cases where tracking is external)
        for tool in tools_called:
            self.validator.record_tool_call(tool)

        # Validate workflow
        validation = self.validator.validate(phase, decision)

        return self.logger.log_decision(
            run_id=self.run_id,
            bar_index=self._bar_index - 1,
            timestamp=self._current_bar["timestamp"] if self._current_bar else "",
            symbol=symbol,
            phase=phase,
            input_state=input_state,
            tools_called=tools_called,
            rules_evaluated=rules_evaluated,
            score=score,
            decision=decision,
            reasoning=reasoning,
            trade_plan=trade_plan,
            workflow_valid=validation["valid"],
            violation_details=", ".join(validation["missing"]) if not validation["valid"] else "",
        )

    def get_broker(self) -> SimulationBrokerAdapter:
        return self.broker

    def get_run_id(self) -> str:
        return self.run_id

    def is_done(self) -> bool:
        return self._bar_index >= len(self._bars)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools && uv run --extra dev pytest tests/test_harness.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tools/backtest/harness.py tools/tests/test_harness.py
git commit -m "feat: add BacktestHarness with bar-by-bar orchestration and workflow enforcement"
```

---

### Task 6: MCP Tools for Backtest

**Files:**
- Modify: `tools/server.py`

- [ ] **Step 1: Write the failing test (manual verification)**

Since MCP tools are tested via integration, verify the existing test suite still passes first:

Run: `cd tools && uv run --extra dev pytest tests/ -v`
Expected: All existing tests PASS

- [ ] **Step 2: Add new MCP tools to server.py**

Add after the existing backtest tools section in `tools/server.py`:

```python
# --- Backtest v2 Tools ---

_harness = None


@mcp.tool()
def start_backtest_v2(
    symbols: str, start_date: str, end_date: str,
    timeframe: str = "1Day", initial_capital: float = 100000.0,
    sop_version: str = "",
) -> str:
    """Initialize a backtest run with workflow enforcement and structured logging.

    When to use: Starting a new backtest session. This sets up the simulation broker,
    creates an audit trail, and prepares bar-by-bar stepping.

    Sample input: start_backtest_v2("NVDA,AAPL", "2026-01-01", "2026-05-01", "1Day", 100000.0, "v1.0.0")

    Expected output:
    {"run_id": "bt-abc123def456", "status": "ready", "total_bars": 84, "symbols": ["NVDA", "AAPL"]}
    """
    from backtest.harness import BacktestHarness
    global _harness, _broker

    symbol_list = [s.strip() for s in symbols.split(",")]

    # Pre-load data if not cached
    from data.cache import load_price_cache as _load
    _load(get_broker(), get_repo(), symbol_list, start_date, end_date, timeframe)

    _harness = BacktestHarness(get_repo())
    run_id = _harness.start(
        symbols=symbol_list,
        start_date=start_date,
        end_date=end_date,
        timeframe=timeframe,
        initial_capital=initial_capital,
        sop_version=sop_version,
    )

    # Swap global broker to simulation
    _broker = _harness.get_broker()

    return json.dumps({
        "run_id": run_id,
        "status": "ready",
        "total_bars": len(_harness._bars),
        "symbols": symbol_list,
    })


@mcp.tool()
def next_backtest_bar() -> str:
    """Advance the backtest by one bar. Returns the new bar's OHLCV data and portfolio state.

    When to use: During an interactive backtest, call this to move to the next time period.
    Then use calc_technical_indicators, get_market_data, etc. to analyze and decide.

    Sample input: next_backtest_bar()

    Expected output:
    {"bar_index": 5, "timestamp": "2026-01-08", "symbol": "NVDA", "open": 215.2,
     "high": 220.1, "low": 213.8, "close": 218.5, "volume": 52000000, "remaining": 79,
     "account": {"equity": 100500, "cash": 100500, "positions": 0}}

    Returns {"done": true, "run_id": "..."} when all bars processed.
    """
    global _harness
    if _harness is None:
        return json.dumps({"error": "No backtest active. Call start_backtest_v2 first."})

    bar = _harness.advance_bar()
    if bar is None:
        return json.dumps({"done": True, "run_id": _harness.get_run_id()})

    account = _harness.get_broker().get_account()
    bar["account"] = {
        "equity": round(account["equity"], 2),
        "cash": round(account["cash"], 2),
        "positions": len(_harness.get_broker().positions),
    }
    return json.dumps(bar, default=str)


@mcp.tool()
def log_backtest_decision(
    symbol: str, phase: str, decision: str, reasoning: str,
    input_state: str, tools_called: str, rules_evaluated: str = "[]",
    score: float | None = None, trade_plan: str = "",
) -> str:
    """Log a decision made at the current backtest bar. Validates workflow compliance.

    When to use: After analyzing the current bar, log your decision (enter/skip/hold/exit)
    with full reasoning. The system validates you called required tools first.

    Sample input: log_backtest_decision("NVDA", "research", "skip", "RSI overbought at 78",
                  '{"price": 220.5, "rsi": 78}', '["calc_technical_indicators", "get_market_data"]')

    Expected output:
    {"decision_id": "bd-abc123", "workflow_valid": true, "violations": []}

    If workflow violated:
    {"decision_id": "bd-abc123", "workflow_valid": false, "violations": ["calc_technical_indicators"]}
    """
    global _harness
    if _harness is None:
        return json.dumps({"error": "No backtest active. Call start_backtest_v2 first."})

    decision_id = _harness.record_decision(
        symbol=symbol,
        phase=phase,
        decision=decision,
        reasoning=reasoning,
        input_state=json.loads(input_state),
        tools_called=json.loads(tools_called),
        rules_evaluated=json.loads(rules_evaluated),
        score=score,
        trade_plan=json.loads(trade_plan) if trade_plan else None,
    )

    # Get validation result
    validation = _harness.validator.validate(phase, decision)
    return json.dumps({
        "decision_id": decision_id,
        "workflow_valid": validation["valid"],
        "violations": validation["missing"],
    })


@mcp.tool()
def get_backtest_results(run_id: str) -> str:
    """Get the full results for a completed backtest run.

    When to use: After a backtest completes, retrieve trades, metrics, and decision summary.

    Sample input: get_backtest_results("bt-abc123def456")

    Expected output:
    {"run": {...}, "trades": [...], "decision_count": 84, "workflow_violations": 2}
    """
    repo = get_repo()
    run = repo.get_backtest_run(run_id)
    if not run:
        return json.dumps({"error": f"Run {run_id} not found"})
    trades = repo.get_backtest_trades(run_id)
    decisions = repo.get_backtest_decisions(run_id)
    violations = sum(1 for d in decisions if d["workflow_valid"] == 0)

    return json.dumps({
        "run": dict(run),
        "trades": trades,
        "decision_count": len(decisions),
        "workflow_violations": violations,
    }, default=str)


@mcp.tool()
def export_backtest_jsonl(run_id: str) -> str:
    """Export all decisions from a backtest run as a JSONL file for training pipelines.

    When to use: After a backtest, export structured decision logs for prompt engineering or fine-tuning.

    Sample input: export_backtest_jsonl("bt-abc123def456")

    Expected output:
    {"file": "/path/to/exports/bt-abc123def456.jsonl", "records": 84}
    """
    from pathlib import Path
    global _harness

    repo = get_repo()
    logger = BacktestLogger(repo) if _harness is None else _harness.logger

    lines = logger.export_jsonl(run_id)
    exports_dir = Path(__file__).parent.parent / "exports"
    exports_dir.mkdir(exist_ok=True)
    path = exports_dir / f"{run_id}.jsonl"
    path.write_text("\n".join(lines))

    return json.dumps({"file": str(path), "records": len(lines)})
```

- [ ] **Step 3: Add missing import at top of server.py**

Add `from backtest.logger import BacktestLogger` near the other imports at the top of server.py.

- [ ] **Step 4: Run full test suite**

Run: `cd tools && uv run --extra dev pytest tests/ -v`
Expected: All tests PASS (existing + new)

- [ ] **Step 5: Commit**

```bash
git add tools/server.py
git commit -m "feat: add backtest v2 MCP tools (start, next_bar, log_decision, results, export)"
```

---

### Task 7: Integration Test — Full Backtest Run

**Files:**
- Modify: `tools/tests/test_harness.py`

- [ ] **Step 1: Add integration test**

Add to `tools/tests/test_harness.py`:

```python
class TestBacktestIntegration:
    """End-to-end test: simulate a simple strategy through the harness."""

    def setup_method(self):
        self.repo = Repository(":memory:")
        _load_sample_bars(self.repo, "NVDA", 30)

    def teardown_method(self):
        self.repo.close()

    def test_full_run_with_simple_strategy(self):
        """A trivial strategy: buy when price > SMA5, sell when price < SMA5."""
        from backtest.harness import BacktestHarness
        from backtest.labeler import OutcomeLabeler

        harness = BacktestHarness(self.repo)
        run_id = harness.start(
            symbols=["NVDA"],
            start_date="2026-01-02",
            end_date="2026-01-31",
            timeframe="1Day",
            initial_capital=100000.0,
        )

        prices = []
        in_position = False
        entry_price = 0.0
        entry_bar = 0
        entry_decision_id = ""
        trades_completed = 0

        while True:
            bar = harness.advance_bar()
            if bar is None:
                break

            prices.append(bar["close"])
            sma5 = sum(prices[-5:]) / min(len(prices), 5)

            if not in_position and len(prices) >= 5 and bar["close"] > sma5:
                # Buy signal
                decision_id = harness.record_decision(
                    symbol="NVDA", phase="research", decision="enter",
                    reasoning=f"Price {bar['close']:.2f} > SMA5 {sma5:.2f}",
                    input_state={"price": bar["close"], "sma5": round(sma5, 2)},
                    tools_called=["calc_technical_indicators", "get_market_data"],
                    rules_evaluated=[{"rule": "ABOVE_SMA5", "passed": True}],
                    score=75.0,
                    trade_plan={"entry": bar["close"], "stop": bar["close"] * 0.97, "target": bar["close"] * 1.06},
                )
                # Simulate fill
                harness.get_broker().place_order("NVDA", "buy", "market", 100)
                in_position = True
                entry_price = bar["close"]
                entry_bar = bar["bar_index"]
                entry_decision_id = decision_id

            elif in_position and bar["close"] < sma5:
                # Sell signal
                harness.record_decision(
                    symbol="NVDA", phase="monitor", decision="exit",
                    reasoning=f"Price {bar['close']:.2f} < SMA5 {sma5:.2f}",
                    input_state={"price": bar["close"], "sma5": round(sma5, 2)},
                    tools_called=["get_positions", "get_market_data"],
                    rules_evaluated=[{"rule": "BELOW_SMA5", "passed": True}],
                )
                harness.get_broker().place_order("NVDA", "sell", "market", 100)
                in_position = False
                trades_completed += 1

            else:
                action = "hold" if in_position else "skip"
                phase = "monitor" if in_position else "research"
                tools = (["get_positions", "get_market_data"] if in_position
                         else ["calc_technical_indicators", "get_market_data"])
                harness.record_decision(
                    symbol="NVDA", phase=phase, decision=action,
                    reasoning=f"Price {bar['close']:.2f} vs SMA5 {sma5:.2f} — no signal",
                    input_state={"price": bar["close"], "sma5": round(sma5, 2)},
                    tools_called=tools,
                    rules_evaluated=[],
                )

        # Verify: every bar has a decision logged
        decisions = self.repo.get_backtest_decisions(run_id)
        assert len(decisions) == 30  # one per bar

        # Verify: at least one trade happened
        assert trades_completed >= 1

        # Verify: all decisions have workflow_valid = 1 (we passed correct tools)
        violations = [d for d in decisions if d["workflow_valid"] == 0]
        assert len(violations) == 0

        # Verify: JSONL export works
        from backtest.logger import BacktestLogger
        logger = BacktestLogger(self.repo)
        lines = logger.export_jsonl(run_id)
        assert len(lines) == 30
```

- [ ] **Step 2: Run the integration test**

Run: `cd tools && uv run --extra dev pytest tests/test_harness.py::TestBacktestIntegration -v`
Expected: PASS

- [ ] **Step 3: Run the full test suite to confirm nothing broke**

Run: `cd tools && uv run --extra dev pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add tools/tests/test_harness.py
git commit -m "test: add full integration test for backtest harness with simple strategy"
```

---

## Execution Order

Tasks 1-4 are independent modules and can be implemented in parallel. Task 5 depends on Tasks 1-4. Task 6 depends on Task 5. Task 7 depends on all others.

```
Task 1 (schema) ─────┐
Task 2 (validator) ───┤
Task 3 (logger) ──────┼──► Task 5 (harness) ──► Task 6 (MCP tools) ──► Task 7 (integration)
Task 4 (labeler) ─────┘
```
