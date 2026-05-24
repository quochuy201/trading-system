# Backtest Engine v2 — Design Spec

**Date:** 2026-05-24  
**Status:** Draft  
**Goal:** A backtest engine that forces the agent to follow the full skill workflow bar-by-bar against historical data, with no look-ahead bias, producing structured logs suitable for prompt engineering and fine-tuning.

---

## Problem

The current backtest tooling allows the agent to claim decisions without verifiable proof it followed the workflow. The agent can hallucinate results, skip due diligence steps, or unconsciously use future knowledge. There's no structured log format for extracting lessons or improving prompts.

---

## Requirements

1. **No look-ahead bias** — at bar N, the agent can only access data ≤ bar N's timestamp.
2. **Full workflow enforcement** — the agent must call required tools (indicators, price, risk checks) before any decision is accepted.
3. **Structured audit log** — every bar produces a JSONL-compatible record with: input state, tools called, rules evaluated, decision, reasoning, and (retroactively) outcome.
4. **Multi-symbol support** — preselected list of symbols for v1; full universe scan deferred.
5. **Two modes** — batch (autonomous full run) and interactive (step-by-step with human observation).
6. **Paper trade simulation** — orders fill at bar close price, logged to ledger, no real API calls.
7. **Outcome labeling** — after a trade closes, retroactively label the entry decision with P&L, R-multiple, and quality label (GOOD_ENTRY / BAD_ENTRY / NEUTRAL).
8. **Storage** — backtest results stored in the existing `trading.db` SQLite database in dedicated tables.

---

## Architecture

```
BacktestHarness (orchestrates the run)
│
├── DataGate
│   Enforces temporal isolation. Wraps the Repository so all
│   price/indicator queries are filtered to <= current_time.
│   The SimulationBroker already does this via set_time().
│
├── WorkflowValidator
│   Tracks tool calls per bar. Before a decision is accepted,
│   validates that required tools were invoked. Rejects and
│   logs WORKFLOW_VIOLATION if steps were skipped.
│
├── SimulationBroker (existing: broker/simulation.py)
│   Fills orders at current bar's close + slippage.
│   Tracks simulated positions, cash, equity.
│
├── BacktestLogger
│   Writes structured records to SQLite (backtest_decisions table).
│   Each record is one decision point at one bar for one symbol.
│
└── OutcomeLabeler
    After the run completes (or after each trade closes), updates
    the entry decision record with exit data and quality label.
```

---

## Database Schema (new tables in trading.db)

### backtest_runs

Metadata for each backtest session.

```sql
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    symbols TEXT NOT NULL,          -- JSON array: ["NVDA", "AAPL"]
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    timeframe TEXT NOT NULL,        -- "1Day", "5Min", etc.
    initial_capital REAL NOT NULL,
    final_equity REAL,
    total_pnl REAL,
    total_pnl_pct REAL,
    total_trades INTEGER,
    win_rate REAL,
    expectancy REAL,
    max_drawdown REAL,
    sop_version TEXT,
    skill_versions TEXT,            -- JSON: {"research": "v1.0", "trader": "v1.0"}
    config_snapshot TEXT,           -- JSON: risk params used
    status TEXT DEFAULT 'running'   -- running, completed, failed
);
```

### backtest_decisions

One row per decision point (per bar × per symbol). The core audit log.

```sql
CREATE TABLE IF NOT EXISTS backtest_decisions (
    decision_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    bar_index INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    phase TEXT NOT NULL,            -- "research", "trader", "monitor", "skip"
    input_state TEXT NOT NULL,      -- JSON: {price, rsi, macd, sma20, atr, volume_ratio, ...}
    tools_called TEXT NOT NULL,     -- JSON array: ["calc_technical_indicators", ...]
    rules_evaluated TEXT,           -- JSON array: [{rule, passed, value}, ...]
    score REAL,
    decision TEXT NOT NULL,         -- "enter", "exit", "hold", "skip"
    reasoning TEXT NOT NULL,
    trade_plan TEXT,                -- JSON: {entry, stop, target, rr} or null
    workflow_valid INTEGER NOT NULL, -- 1 = all required tools called, 0 = violation
    violation_details TEXT,         -- what was missing if workflow_valid = 0
    -- Outcome fields (filled retroactively after trade closes)
    outcome_pnl REAL,
    outcome_pnl_pct REAL,
    outcome_r_multiple REAL,
    outcome_exit_bar INTEGER,
    outcome_exit_price REAL,
    outcome_exit_reason TEXT,
    outcome_label TEXT,             -- "GOOD_ENTRY", "BAD_ENTRY", "NEUTRAL", "GOOD_EXIT", etc.
    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id)
);
```

### backtest_trades

Summary of each completed trade (entry + exit pair).

```sql
CREATE TABLE IF NOT EXISTS backtest_trades (
    trade_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,             -- "long", "short"
    entry_bar INTEGER NOT NULL,
    entry_timestamp TEXT NOT NULL,
    entry_price REAL NOT NULL,
    entry_quantity INTEGER NOT NULL,
    entry_decision_id TEXT NOT NULL,
    exit_bar INTEGER,
    exit_timestamp TEXT,
    exit_price REAL,
    exit_reason TEXT,               -- "stop_loss", "take_profit", "trailing", "time_stop"
    exit_decision_id TEXT,
    pnl REAL,
    pnl_pct REAL,
    r_multiple REAL,
    hold_bars INTEGER,
    max_favorable_excursion REAL,   -- best unrealized P&L during hold
    max_adverse_excursion REAL,     -- worst unrealized P&L during hold
    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id)
);
```

---

## Workflow: Batch Mode

```
1. User provides: symbols[], start_date, end_date, timeframe, capital, sop_version
2. Harness creates a backtest_runs record (status=running)
3. Harness loads all historical data into price cache for the symbol list
4. Harness swaps global _broker to SimulationBroker
5. For each bar (chronologically):
   a. Set current_time = bar.timestamp
   b. Reset per-bar tool call tracker
   c. Invoke agent with current state:
      - If no open positions → Research phase (scan, score, decide enter/skip)
      - If open positions → Monitor phase (check exits, decide hold/exit)
      - If Research says enter → Trader phase (validate, size, place paper order)
   d. WorkflowValidator checks required tools were called
   e. BacktestLogger writes decision record
   f. If order placed → SimulationBroker fills at close price
   g. If trade closed → OutcomeLabeler updates the entry decision
6. After all bars:
   a. Force-close any remaining positions at final bar's close
   b. Compute summary metrics (win rate, expectancy, drawdown, etc.)
   c. Update backtest_runs record (status=completed, metrics)
   d. Generate JSONL export of all decisions (for training pipeline)
```

---

## Workflow: Interactive Mode

Same as batch, but after step 5e (decision logged), the harness pauses and shows:
- Bar data (OHLCV)
- Indicator values the agent received
- The agent's decision and reasoning
- Current portfolio state

User can:
- "next" → advance to next bar
- "why?" → see full decision record with all rules evaluated
- "override: skip" → force a different decision (for testing "what if")
- "stop" → end the backtest early

---

## WorkflowValidator Rules

| Phase | Required Tool Calls Before Decision |
|-------|-------------------------------------|
| Research (score a candidate) | `calc_technical_indicators`, `get_market_data` |
| Research (enter recommendation) | above + score >= SOP threshold |
| Trader (place order) | `check_kill_switch`, `check_daily_limits`, `check_portfolio_risk`, `calc_position_size` |
| Monitor (hold) | `get_positions`, `get_market_data` |
| Monitor (exit) | `get_positions`, `get_market_data`, `place_order` |

If the agent produces a decision without the required calls → decision is logged with `workflow_valid=0` and the decision is **still recorded** (we don't block it — we log the violation for analysis). This way you can see how often the agent skips steps.

---

## Outcome Labeling Logic

After a trade closes, the entry decision is retroactively labeled:

| R-Multiple | Label |
|-----------|-------|
| >= +1.5R | GOOD_ENTRY |
| +0.5R to +1.5R | NEUTRAL |
| -0.5R to +0.5R | NEUTRAL |
| <= -0.5R | BAD_ENTRY |

Exit decisions are labeled separately:

| Condition | Label |
|-----------|-------|
| Exited at profit AND price continued another +1R after exit | EARLY_EXIT |
| Exited at profit AND price reversed after exit | GOOD_EXIT |
| Exited at loss at planned stop | EXPECTED_LOSS (SOP_FAULT) |
| Exited at loss below planned stop (moved stop / missed) | BAD_EXIT (AGENT_FAULT) |

---

## Anti-Hallucination Enforcement

1. **DataGate**: `SimulationBroker.current_time` + `Repository.query_price_data` already filter by timestamp. No code change needed — just verify this contract holds.

2. **Indicator computation**: `analysis/indicators.py` computes from cached bars. The agent receives numbers, it cannot fabricate them. The audit log records what was returned.

3. **WorkflowValidator**: New component. Intercepts tool calls during the bar, builds a checklist, validates before accepting the decision.

4. **Decision-vs-data cross-check**: Post-hoc analysis can compare the agent's stated reasoning ("RSI was 65") against the actual logged `input_state.rsi` value. Any mismatch = the agent hallucinated.

5. **No skip optimization**: The harness calls the agent at EVERY bar, even if "nothing is happening." The agent must explicitly say "skip" with a reason. No silent bars.

---

## JSONL Export Format (for training pipelines)

After a run completes, export all decisions as JSONL:

```jsonl
{"run_id": "bt-001", "bar": 48, "timestamp": "2026-03-18", "symbol": "NVDA", "phase": "research", "input_state": {"price": 220.50, "rsi": 65.2, "macd": 2.1, "macd_signal": 1.8, "sma20": 215.3, "sma50": 208.7, "atr": 4.5, "volume_ratio": 2.18, "daily_pnl_pct": 0.0, "positions_open": 0, "mode": "NORMAL"}, "tools_called": ["calc_technical_indicators", "get_market_data", "get_news"], "rules_evaluated": [{"rule": "TREND_ABOVE_SMA20", "passed": true, "value": "220.50 > 215.30"}, {"rule": "RVOL_HIGH", "passed": true, "value": "2.18 > 1.5"}, {"rule": "RSI_RANGE", "passed": true, "value": "65.2 in [50,75]"}, {"rule": "CATALYST_FRESH", "passed": true, "value": "earnings beat, age=0d"}], "score": 82, "decision": "enter", "reasoning": "Breakout on 2.2x volume above all SMAs with fresh earnings catalyst", "trade_plan": {"entry": 220.50, "stop": 215.00, "target": 232.00, "rr_ratio": 2.09, "quantity": 44, "risk_pct": 1.0}, "workflow_valid": true, "outcome": {"exit_bar": 52, "exit_price": 233.50, "pnl": 574.00, "pnl_pct": 2.6, "r_multiple": 2.36, "exit_reason": "take_profit", "label": "GOOD_ENTRY"}}
```

---

## MCP Tool Additions

New tools exposed in `server.py`:

| Tool | Purpose |
|------|---------|
| `start_backtest` | Initialize a run: symbols, dates, capital. Returns run_id. |
| `next_bar` | Advance one bar (interactive mode). Returns bar data + state. |
| `run_full_backtest` | Batch mode: runs all bars, returns summary. |
| `get_backtest_results` | Query results for a run_id: trades, metrics, decisions. |
| `export_backtest_jsonl` | Export a run's decisions as JSONL file for training. |
| `label_backtest_outcomes` | Retroactively label all decisions in a run with outcomes. |

---

## What's NOT in Scope (v1)

- Full universe scanning (50+ symbols per bar) — deferred to v2
- Intraday multi-timeframe backtesting (e.g., daily for trend + 5min for entry) — deferred
- Automated skill improvement (auto-rewriting rules) — human-in-the-loop only
- Live paper-trade comparison (running backtest alongside live for validation) — future
- Slippage/spread modeling beyond flat percentage — future
- Short selling mechanics — future (longs only for v1)

---

## Success Criteria

1. Run a backtest on NVDA 2026-01-01 to 2026-05-01 and get a complete decision audit for every bar
2. Verify no look-ahead: agent's indicator values at bar N match independently calculated values using only bars 1-N
3. WorkflowValidator catches at least one shortcut if the agent tries to skip steps
4. Export JSONL and successfully use entries as few-shot examples in a prompt
5. Outcome labels correctly identify winning/losing entries after the run
