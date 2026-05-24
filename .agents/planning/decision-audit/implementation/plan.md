# Implementation Plan: Decision Audit & Performance Logging

## Checklist

- [ ] Step 1: Database schema and data models
- [ ] Step 2: Transaction ledger auto-logging
- [ ] Step 3: Decision log tool
- [ ] Step 4: Query tools (decisions + transaction ledger)
- [ ] Step 5: Compliance scorer
- [ ] Step 6: Performance calculator
- [ ] Step 7: Report generator
- [ ] Step 8: Export tool and cron integration
- [ ] Step 9: Update agent skills to call log_decision
- [ ] Step 10: End-to-end validation

---

## Step 1: Database schema and data models

**Objective:** Add the `decisions`, `transaction_ledger`, and `performance_reports` tables to the existing SQLite database, and define corresponding dataclasses.

**Implementation guidance:**
- Add new table DDL to `tools/persistence/db.py` SCHEMA string
- Add dataclasses to `tools/models.py`:
  - `DecisionLogEntry` (decision_id, timestamp, agent, action, symbol, rules_triggered, rules_considered, reasoning, sop_version, plan_id, market_context, violations)
  - `LedgerEntry` (ledger_id, timestamp, action, symbol, quantity, order_type, price, total_cost, fees, status, broker_order_id, account_equity, account_cash, buying_power, pnl, pnl_pct, entry_price, plan_id, decision_id, sop_version, platform, trigger, notes)
  - `PerformanceReport` (report_id, report_type, start_date, end_date, sop_version, metrics dict, generated_at)
- Add repository methods: `save_decision`, `save_ledger_entry`, `query_decisions`, `query_ledger`, `save_report`, `get_reports`

**Test requirements:**
- Unit test: create tables idempotently (existing DB not broken)
- Unit test: save and retrieve DecisionLogEntry round-trip
- Unit test: save and retrieve LedgerEntry round-trip
- Unit test: query filtering (by symbol, date range, action, sop_version)

**Integration with previous work:** Extends existing `persistence/db.py` and `models.py`. Existing tables unchanged.

**Demo:** Run tests showing new tables created alongside existing ones, CRUD works for all new models.

---

## Step 2: Transaction ledger auto-logging

**Objective:** Modify `place_order` and `cancel_order` to automatically write to the transaction ledger on every call. Deprecate `save_transaction`.

**Implementation guidance:**
- In `server.py`, after `place_order` executes the broker call:
  - Fetch account state (`broker.get_account()`)
  - For sells: look up entry_price from existing positions or trade_plans to calculate P&L
  - Write a `LedgerEntry` to the DB
  - Include `platform` from env (ALPACA_BASE_URL → "alpaca_paper" or "alpaca_live")
  - Include `trigger="agent"` (default), or accept as parameter
- In `cancel_order`: write a ledger entry with action="cancel"
- In `activate_kill_switch`: pass `trigger="kill_switch"` when closing positions
- Mark `save_transaction` tool as deprecated (keep it working but add deprecation note)

**Test requirements:**
- Unit test: `place_order` with mocked broker → verify ledger entry written with correct fields
- Unit test: sell order → verify pnl and entry_price populated
- Unit test: `cancel_order` → verify ledger entry with action="cancel"
- Unit test: kill switch → verify all close orders have trigger="kill_switch"
- Unit test: no duplicate writes (one place_order = exactly one ledger entry)

**Integration with previous work:** Modifies existing `place_order`, `cancel_order`, `activate_kill_switch` in server.py.

**Demo:** Place a paper trade, show the ledger entry with full account state and platform. Cancel it, show the cancel entry.

---

## Step 3: Decision log tool

**Objective:** Implement the `log_decision` MCP tool that agents call at every decision point.

**Implementation guidance:**
- New MCP tool in `server.py`:
  ```python
  log_decision(agent, action, symbol, rules_triggered, rules_considered,
               reasoning, sop_version, plan_id="", market_context="") -> str
  ```
- Writes to `decisions` table via repository
- Returns immediately: `{"logged": true, "decision_id": "..."}`
- Never throws — wraps errors and returns `{"logged": false, "error": "..."}`
- `rules_triggered` and `rules_considered` are comma-separated strings (simpler for MCP tool interface), stored as JSON arrays internally

**Test requirements:**
- Unit test: log a decision, retrieve it, verify all fields
- Unit test: error handling (malformed input → returns logged=false, doesn't crash)
- Performance test: verify <10ms execution time (no heavy computation)

**Integration with previous work:** Uses repository from Step 1. Called by agents in Step 9.

**Demo:** Call `log_decision` with sample data, then query it back.

---

## Step 4: Query tools (decisions + transaction ledger)

**Objective:** Implement `query_decisions` and `query_transaction_ledger` MCP tools.

**Implementation guidance:**
- `query_decisions(symbol, agent, action, sop_version, start_date, end_date, has_violation, limit)` → JSON array
- `query_transaction_ledger(symbol, action, start_date, end_date, sop_version, platform, trigger, limit)` → JSON array
- Both support flexible filtering (all params optional)
- Default limit: 50 entries
- Results ordered by timestamp descending (most recent first)

**Test requirements:**
- Unit test: insert 10 decisions with varying fields, verify each filter works correctly
- Unit test: insert ledger entries for buy/sell/cancel, verify filtering by action
- Unit test: date range filtering
- Unit test: empty result returns `[]` not error

**Integration with previous work:** Reads from tables created in Step 1, populated by Steps 2-3.

**Demo:** Query "show all exits for NVDA this week" and "show all transactions with trigger=kill_switch".

---

## Step 5: Compliance scorer

**Objective:** Implement the internal compliance scoring module that detects violations.

**Implementation guidance:**
- New module: `tools/audit/compliance.py`
- Function: `score_decisions(repo, start_date, end_date, sop_version) -> list[Violation]`
- For each decision in the range, cross-reference with:
  - Trade plans (stop_loss, take_profit, time_stop)
  - Transaction ledger (actual prices at execution)
  - Market context logged in the decision
- Violation detection logic:
  - `PANIC_SELL`: action="exit" AND market_context.price > plan.stop_loss
  - `EARLY_EXIT`: action="exit" AND no valid exit rule in rules_triggered AND price between stop and target
  - `OVERSIZED`: ledger.quantity > expected from calc_position_size
  - `RULE_CONFLICT`: rules_triggered contains known conflicting pair
  - `UNTAGGED_DECISION`: action in (enter, exit) AND rules_triggered is empty
  - `SOP_DEVIATION`: action taken but no matching rule exists
- Write detected violations back to the decision's `violations` field

**Test requirements:**
- Unit test: PANIC_SELL detection (exit at $220 when stop was $215)
- Unit test: EARLY_EXIT detection (exit at $225 when target was $235, no rule triggered)
- Unit test: UNTAGGED_DECISION detection (exit with empty rules_triggered)
- Unit test: clean decision (no violations) → empty violations list
- Unit test: RULE_CONFLICT detection

**Integration with previous work:** Reads from decisions table (Step 3), trade_plans table (existing), transaction_ledger (Step 2).

**Demo:** Insert a decision where AI exited above stop-loss without a valid rule → scorer flags PANIC_SELL.

---

## Step 6: Performance calculator

**Objective:** Implement trading performance metrics calculation from the transaction ledger.

**Implementation guidance:**
- New module: `tools/audit/performance.py`
- Function: `calc_performance(repo, start_date, end_date, sop_version) -> dict`
- Metrics calculated from closed trades (pairs of buy + sell in ledger):
  - `win_rate`: % of sells with pnl > 0
  - `profit_factor`: sum(winning pnl) / abs(sum(losing pnl))
  - `expectancy`: avg pnl per closed trade
  - `total_pnl`: sum of all realized pnl
  - `total_trades`: count of closed trades
  - `avg_winner`: avg pnl of winning trades
  - `avg_loser`: avg pnl of losing trades
  - `max_drawdown`: largest peak-to-trough equity decline
  - `by_symbol`: metrics grouped by symbol
  - `by_sop_version`: metrics grouped by SOP version

**Test requirements:**
- Unit test: 5 trades (3 wins, 2 losses) → verify win_rate=60%, correct profit_factor, expectancy
- Unit test: max drawdown calculation with known equity curve
- Unit test: empty period → returns zeroes, not errors
- Unit test: grouping by symbol and sop_version

**Integration with previous work:** Reads from transaction_ledger (Step 2).

**Demo:** Insert 10 sample trades, run calculator, show metrics report.

---

## Step 7: Report generator

**Objective:** Implement `generate_performance_report` MCP tool that combines compliance scoring and performance metrics into a unified report.

**Implementation guidance:**
- MCP tool: `generate_performance_report(start_date, end_date, sop_version, export_format)` → str
- Calls compliance scorer (Step 5) + performance calculator (Step 6)
- Produces combined report with:
  - Trading metrics (win rate, PF, expectancy, etc.)
  - Compliance metrics (compliance rate, violations by type)
  - SOP version comparison (if multiple versions in range)
- `export_format`:
  - `"summary"` → returns JSON summary in tool response
  - `"markdown"` → writes full report to `reports/` dir, returns file path
  - `"json"` / `"csv"` → writes export file, returns path
- Also implement `get_compliance_score(start_date, end_date, sop_version)` → quick % lookup
- Save report to `performance_reports` table

**Test requirements:**
- Unit test: generate report with known data → verify metrics match expected
- Unit test: markdown output contains all sections
- Unit test: JSON export is valid and parseable
- Unit test: report saved to DB

**Integration with previous work:** Uses compliance scorer (Step 5), performance calculator (Step 6), repository (Step 1).

**Demo:** Generate a report for the past week, show markdown output with both scorecards.

---

## Step 8: Export tool and cron integration

**Objective:** Implement `export_decisions` tool and wire reports into existing cron jobs.

**Implementation guidance:**
- MCP tool: `export_decisions(start_date, end_date, format, symbol, sop_version)` → file path
  - Exports both decisions AND transaction ledger entries for the period
  - `format`: "json" or "csv"
  - Writes to `exports/` directory with timestamped filename
- Cron integration:
  - Update `eod-review.json` to include daily report generation
  - Add `cron/weekly-review.json` for weekly report (Sunday 6 PM ET)
  - Reports auto-saved as markdown in `reports/daily/` and `reports/weekly/`

**Test requirements:**
- Unit test: CSV export has correct headers and data
- Unit test: JSON export is valid
- Unit test: export with filters produces subset of data
- Verify cron JSON is valid

**Integration with previous work:** Uses query tools (Step 4), report generator (Step 7). Extends existing cron/ directory.

**Demo:** Export a week of decisions as CSV, open it, verify columns and data.

---

## Step 9: Update agent skills to call log_decision

**Objective:** Update Research, Trader, and Monitor SKILL.md files to instruct agents to call `log_decision` at every decision point.

**Implementation guidance:**
- Add to each SKILL.md a "Decision Logging" section:
  - **Research:** log "skip" (with reasoning) for rejected candidates, log "enter" recommendation for selected candidates
  - **Trader:** log "enter" before placing order (with rules + reasoning), log "adjust" when modifying stops
  - **Monitor:** log "hold" on each check cycle (brief), log "exit" when triggering an exit (with rules)
- Keep logging instructions minimal — one sentence per decision point
- Emphasize: reasoning should be 1-2 sentences max, rules_triggered must not be empty

**Test requirements:**
- Manual test: run each agent, verify log_decision is called at appropriate points
- Verify decisions appear in query_decisions output
- Verify no context bloat (log_decision response is tiny)

**Integration with previous work:** Modifies existing SKILL.md files. Uses log_decision tool from Step 3.

**Demo:** Run the Monitor agent on open positions, show decision log entries appearing with "hold" actions and reasoning.

---

## Step 10: End-to-end validation

**Objective:** Run a complete trading cycle and verify the full audit trail works.

**Implementation guidance:**
- Run the orchestrator through one full cycle (scan → trade → monitor)
- Verify:
  1. Transaction ledger has entries for all broker actions (with account state, P&L)
  2. Decision log has entries from all agents (with rules and reasoning)
  3. No orphan transactions (every ledger entry has a matching decision)
  4. Compliance scorer runs without errors
  5. Performance report generates correctly
  6. Export produces valid CSV/JSON
  7. No duplicate entries anywhere
- Test violation detection: manually create a "bad" decision (exit above stop) and verify it's flagged

**Test requirements:**
- Integration test: full cycle produces complete audit trail
- Verify ledger entry count matches expected (1 per broker action)
- Verify decision count matches expected (1 per decision point)
- Generate report, verify metrics are reasonable

**Integration with previous work:** Exercises everything from Steps 1-9 against live Alpaca paper trading.

**Demo:** Show the full audit trail for one trade: decision to enter → ledger entry (buy) → decision to hold (3x) → decision to exit → ledger entry (sell with P&L) → compliance score → performance report.
