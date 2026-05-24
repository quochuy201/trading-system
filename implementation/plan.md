# Implementation Plan: Multi-Agent Trading System

## Architecture Summary

This system is built as a **Hermes Profile Distribution** — a git repo that packages agents, skills, MCP tools, and config for one-command install on Hermes, Kermes, or MeshClaw.

**4 Agents:** Orchestrator (SOUL.md), Research, Trader, Monitor
**Communication:** Hub-and-spoke, request→response through Orchestrator
**Core:** Python MCP tools server + markdown SKILL.md files (platform-agnostic)

## Checklist

- [ ] Step 1: Repo scaffolding and profile distribution structure
- [ ] Step 2: Data models and database
- [ ] Step 3: MCP tools server — broker adapter (Alpaca)
- [ ] Step 4: MCP tools — market data and analysis
- [ ] Step 5: MCP tools — risk and portfolio management
- [ ] Step 6: Research Agent skill (scan + analyze)
- [ ] Step 7: Trader Agent skill (plan + execute)
- [ ] Step 8: Monitor Agent skill (track + exit)
- [ ] Step 9: Orchestrator SOUL and workflow
- [ ] Step 10: Install scripts and platform testing
- [ ] Step 11: Notifications and cron scheduling
- [ ] Step 12: Backtesting (simulation broker adapter)
- [ ] Step 13: Kill switch and error hardening
- [ ] Step 14: End-to-end paper trading validation

---

## Step 1: Repo scaffolding and profile distribution structure

**Objective:** Set up the repo in Hermes Profile Distribution format with the correct directory structure for cross-platform install.

**Implementation guidance:**
- Create the repo structure:
  ```
  trading-system/
  ├── distribution.yaml        # Hermes manifest
  ├── SOUL.md                  # Orchestrator agent identity
  ├── config.yaml              # Model, provider settings
  ├── mcp.json                 # MCP tools server declaration
  ├── .env.EXAMPLE             # Required API keys template
  ├── skills/
  │   ├── research/SKILL.md
  │   ├── trader/SKILL.md
  │   └── monitor/SKILL.md
  ├── cron/
  │   ├── market-scan.json
  │   └── eod-review.json
  ├── tools/                   # Python MCP server
  │   ├── pyproject.toml
  │   ├── server.py            # MCP server entry point
  │   ├── broker/
  │   ├── data/
  │   ├── analysis/
  │   ├── risk/
  │   ├── persistence/
  │   └── notifications/
  ├── sops/                    # Strategy SOPs (versioned)
  │   └── day-trade-momentum/
  │       └── v1.0.0.md
  ├── install.sh               # Platform install script
  └── README.md
  ```
- Create `distribution.yaml`:
  ```yaml
  name: trading-system
  version: 0.1.0
  description: "Multi-agent autonomous trading system"
  hermes_requires: ">=0.12.0"
  env_requires:
    - name: ALPACA_API_KEY
      description: "Alpaca API key (paper trading)"
      required: true
    - name: ALPACA_SECRET_KEY
      description: "Alpaca secret key"
      required: true
    - name: SLACK_WEBHOOK_URL
      description: "Slack webhook for notifications"
      required: false
  ```
- Create `mcp.json` declaring the tools server:
  ```json
  {
    "mcpServers": {
      "trading-tools": {
        "command": "uv",
        "args": ["run", "--directory", "./tools", "server.py"]
      }
    }
  }
  ```
- Create stub `SOUL.md`, stub `SKILL.md` files, and `.env.EXAMPLE`
- Initialize `tools/` as a Python project with `pyproject.toml` (use `uv`)
- Create `install.sh` with platform detection (hermes/kermes/meshclaw)

**Test requirements:**
- Verify `distribution.yaml` is valid YAML with required fields
- Verify `mcp.json` is valid JSON
- Verify `install.sh` runs without error on both platforms (dry-run mode)
- Verify `uv run server.py` starts without import errors (empty server)

**Integration with previous work:** Foundation for everything else.

**Demo:** Run `./install.sh kermes --dry-run` showing what would be deployed. Run `uv run server.py` showing the MCP server starts and exposes zero tools.

---

## Step 2: Data models and database

**Objective:** Define all data models and implement the SQLite persistence layer inside the MCP tools server.

**Implementation guidance:**
- In `tools/models.py`, define dataclasses:
  - `ScanCandidate`, `ScanReport`
  - `AnalysisReport`
  - `TradePlan`, `TradeTransaction`, `ExecutionReport`
  - `PositionStatus`, `MonitorReport`
  - `JournalEntry`, `ReviewReport`
  - `WorkflowCheckpoint`, `KillSwitchState`
- In `tools/persistence/db.py`, create SQLite schema:
  - `trade_plans`, `trade_transactions`, `portfolio_snapshots`
  - `performance_metrics`, `sop_versions`, `workflow_runs`
  - `price_data`, `journal_entries`
- Implement repository layer with CRUD operations
- Add JSON serialization for all dataclasses

**Test requirements:**
- Unit tests for dataclass serialization round-trips
- Unit tests for all repository CRUD operations (in-memory SQLite)
- Schema creation is idempotent

**Integration with previous work:** Uses project structure from Step 1. All tools in subsequent steps use these models.

**Demo:** Run tests showing models serialize/deserialize, DB tables create, CRUD works.

---

## Step 3: MCP tools server — broker adapter (Alpaca)

**Objective:** Implement the broker abstraction and Alpaca adapter, exposed as MCP tools.

**Implementation guidance:**
- In `tools/broker/adapter.py`, implement `BrokerAdapter` ABC:
  - `place_order`, `cancel_order`, `get_positions`, `get_account`
  - `get_market_data`, `get_historical_data`
- In `tools/broker/alpaca.py`, implement `AlpacaBrokerAdapter` wrapping `alpaca-py` SDK
- Implement retry wrapper with exponential backoff (max 10 retries)
- In `tools/server.py`, expose as MCP tools:
  - `place_order(symbol, side, order_type, quantity, ...)`
  - `cancel_order(order_id)`
  - `get_positions()`
  - `get_account()`
- Paper vs live: same adapter, different base URL via env var

**Test requirements:**
- Unit tests with mocked Alpaca SDK — verify adapter methods return correct dataclasses
- Unit test retry wrapper: backoff timing, max retries, exception propagation
- Integration test against Alpaca paper trading: place order, verify fill, cancel order

**Integration with previous work:** Uses models from Step 2. All trading operations go through this adapter.

**Demo:** Start MCP server, call `place_order` tool to place a paper trade on Alpaca, see `TradeTransaction` returned with real broker order ID.

---

## Step 4: MCP tools — market data and analysis

**Objective:** Implement data-gathering and technical analysis tools exposed via MCP.

**Implementation guidance:**
- Data tools (in `tools/data/`):
  - `get_market_data(symbol)` — current quote via Alpaca
  - `get_historical_data(symbol, start, end, timeframe)` — OHLCV bars
  - `load_price_cache(symbols, start, end, timeframe)` — bulk load into SQLite
  - `query_price_cache(symbol, start, end, timeframe)` — read from cache
  - `get_news(query)` — news headlines (Alpaca news API or web search)
- Analysis tools (in `tools/analysis/`):
  - `calc_technical_indicators(symbol, timeframe)` — RSI, MACD, SMA(20/50/200), ATR, volume profile
  - Uses `pandas` + `ta` library, reads from price cache
- Expose all as MCP tools in `server.py`

**Test requirements:**
- Unit test cache query with pre-populated SQLite
- Unit test technical indicators against known values
- Integration test: load 1 month of data, run indicators, verify reasonable outputs

**Integration with previous work:** Uses broker adapter from Step 3, price_data table from Step 2.

**Demo:** Load AAPL historical data, call `calc_technical_indicators`, show RSI/MACD/SMA values.

---

## Step 5: MCP tools — risk and portfolio management

**Objective:** Implement risk calculation and portfolio management tools.

**Implementation guidance:**
- Risk tools (in `tools/risk/`):
  - `calc_position_size(account_value, risk_pct, entry_price, stop_loss)` → quantity
  - `check_portfolio_risk(proposed_trade)` → concentration %, exposure, pass/fail
  - `check_daily_limits(daily_pnl, limit)` → bool
  - `get_portfolio_state()` → account + positions summary
- Persistence tools (in `tools/persistence/`):
  - `save_trade_plan(plan)`, `get_trade_plan(plan_id)`
  - `save_transaction(tx)`, `get_transactions(plan_id)`
  - `save_journal_entry(entry)`, `get_journal_entries(period)`
  - `save_workflow_checkpoint(checkpoint)`, `get_latest_checkpoint()`
- Expose all as MCP tools

**Test requirements:**
- Unit test position sizing: $100K account, 1% risk, entry $50, stop $48 → quantity = 1000
- Unit test portfolio risk: concentration limits trigger correctly
- Unit test persistence: save and retrieve all model types

**Integration with previous work:** Uses broker adapter (Step 3) for portfolio state, models/DB from Step 2.

**Demo:** Call `calc_position_size` and `check_portfolio_risk` with sample inputs, show results.

---

## Step 6: Research Agent skill (scan + analyze)

**Objective:** Write the Research Agent SKILL.md that combines scanning and analysis into one agent.

**Implementation guidance:**
- Write `skills/research/SKILL.md`:
  - Description: scans market for candidates, performs technical analysis, ranks opportunities
  - Tools required: `get_market_data`, `get_historical_data`, `get_news`, `calc_technical_indicators`, `query_price_cache`
  - Input: strategy SOP reference, market conditions
  - Output: structured report with ranked candidates + analysis scores
  - Instructions: step-by-step process (scan → filter → analyze each → rank → report)
- Write the strategy SOP: `sops/day-trade-momentum/v1.0.0.md`
  - Scanning criteria: volume > 1M, price $5-$500, gap up > 2%
  - Analysis criteria: RSI thresholds, MACD signals, volume confirmation
  - Scoring rubric for ranking candidates
- The SKILL.md references the SOP and instructs the agent to follow it

**Test requirements:**
- Manual test: invoke Research agent on Kermes/Hermes with the skill loaded, verify it calls the right tools and produces a structured candidate report
- Verify it only uses its declared tools (no broker tools)
- Test with cached historical data (no live API dependency for testing)

**Integration with previous work:** Uses data and analysis MCP tools from Steps 4-5. Called by Orchestrator in Step 9.

**Demo:** Run the Research agent (via Kermes or Hermes), show it scanning the market and producing a ranked list of candidates with scores and signals.

---

## Step 7: Trader Agent skill (plan + execute)

**Objective:** Write the Trader Agent SKILL.md that plans and executes trades.

**Implementation guidance:**
- Write `skills/trader/SKILL.md`:
  - Description: creates trade plans with risk validation, then executes via broker
  - Tools required: `calc_position_size`, `check_portfolio_risk`, `check_daily_limits`, `get_portfolio_state`, `place_order`, `cancel_order`, `save_trade_plan`, `save_transaction`
  - Input: candidate analysis (from Research), portfolio state
  - Output: execution report with trade plan + transactions
  - Instructions: determine entry/exit/stop → size position → validate risk → execute → record
- Handles partial fills: accept partial for entries, retry for stop-losses
- Risk validation is a hard gate — no execution if risk checks fail

**Test requirements:**
- Manual test: invoke Trader agent with a mock analysis report, verify it plans and executes correctly on Alpaca paper trading
- Verify risk rejection: provide inputs that breach limits, confirm no trade is placed
- Verify transactions are persisted to database

**Integration with previous work:** Uses risk tools (Step 5), broker tools (Step 3), persistence (Step 5). Called by Orchestrator in Step 9.

**Demo:** Feed a "strong buy" candidate to the Trader agent, show it planning the trade, validating risk, executing on Alpaca paper, and recording the transaction.

---

## Step 8: Monitor Agent skill (track + exit)

**Objective:** Write the Monitor Agent SKILL.md for position tracking and exit execution.

**Implementation guidance:**
- Write `skills/monitor/SKILL.md`:
  - Description: monitors open positions, evaluates exit conditions, executes exits
  - Tools required: `get_positions`, `get_market_data`, `place_order`, `save_transaction`, `get_trade_plan`
  - Input: open positions with their trade plans (entry price, take-profit, stop-loss, trailing stop, time stop)
  - Output: monitor report with position statuses and any exits triggered
  - Instructions: check each position → compare to exit criteria → execute exit if triggered → report
- Two-tier design encoded in the skill:
  - First: tool-only check (get positions, compare prices to levels)
  - Then: LLM reasoning only if exit condition is approaching (within 1% of stop/target)
- Trailing stop logic: update stop-loss as price moves favorably

**Test requirements:**
- Manual test: with an open paper position, invoke Monitor agent, verify it reports correct P&L and position status
- Test exit trigger: set stop-loss close to current price, verify Monitor executes the exit
- Verify exit transaction is recorded with correct plan_id

**Integration with previous work:** Uses broker tools (Step 3), persistence (Step 5). Called by Orchestrator in Step 9.

**Demo:** With a paper trade open, run the Monitor agent. Show it checking positions, reporting status. Manually adjust stop-loss close to price, run again, show it triggering an exit.

---

## Step 9: Orchestrator SOUL and workflow

**Objective:** Write the Orchestrator SOUL.md that drives the full trading workflow by delegating to the 3 specialist agents.

**Implementation guidance:**
- Write `SOUL.md` — the orchestrator's identity and workflow instructions:
  - Identity: autonomous trading orchestrator
  - Workflow: scan → trade → monitor → review (at EOD)
  - Delegation pattern: spawn Research agent → collect report → spawn Trader agent → collect report → spawn Monitor agent
  - Decision gates: skip trading if no candidates, skip if risk budget exhausted
  - EOD review: orchestrator runs review itself (no separate agent) — journals trades, calculates metrics
  - Crash recovery: on startup, check for open positions and resume monitoring
- Write `config.yaml` with model settings, scheduling preferences
- Implement workflow checkpoint logic as an MCP tool:
  - `save_checkpoint(status, data)`, `get_checkpoint()`
  - Orchestrator calls this between each phase
- Wire the review SOP into the orchestrator's EOD behavior:
  - Query completed trades, calculate P&L, write journal entries, send summary

**Test requirements:**
- Manual test: run the full orchestrator on Kermes/Hermes, verify it delegates to Research → Trader → Monitor in sequence
- Test decision gates: provide a Research report with no candidates, verify Trader is not invoked
- Test checkpoint persistence: kill mid-workflow, restart, verify recovery
- Test EOD review: after trades close, verify journal entries are created

**Integration with previous work:** Delegates to Research (Step 6), Trader (Step 7), Monitor (Step 8). Uses all MCP tools.

**Demo:** Run the full orchestrator workflow: watch it scan, analyze, plan, execute a paper trade, monitor it, and produce a review. Show checkpoints in the database.

---

## Step 10: Install scripts and platform testing

**Objective:** Implement and test the install scripts for Hermes and Kermes.

**Implementation guidance:**
- Write `install.sh` with subcommands:
  ```bash
  ./install.sh hermes    # hermes profile install from local dir
  ./install.sh kermes    # symlink skills + configure MCP
  ./install.sh meshclaw  # generate agent specs (future)
  ```
- Hermes install:
  - Copies/links into `~/.hermes/profiles/trading-system/`
  - Sets up SOUL.md, skills/, config.yaml, mcp.json, cron/
- Kermes install:
  - Symlinks skills into `~/.kermes/skills/` or adds to `skills_external_dirs`
  - Copies SOUL.md reference
  - Prints instructions for MCP server setup
- Test on both platforms:
  - Verify skills are discoverable (`/skills` command)
  - Verify MCP tools server connects and tools are available
  - Verify orchestrator can delegate to subagents

**Test requirements:**
- Run install on Kermes (this machine), verify skills appear in `kermes /skills`
- Run install on Hermes (other laptop), verify `hermes profile info trading-system` shows correct manifest
- Verify MCP tools are callable from both platforms
- Verify subagent delegation works on both platforms

**Integration with previous work:** Packages everything from Steps 1-9 for deployment.

**Demo:** Run `./install.sh kermes`, start kermes, show skills loaded, invoke the orchestrator, see it delegate to Research agent successfully.

---

## Step 11: Notifications and cron scheduling

**Objective:** Implement Slack notifications and scheduled cron jobs.

**Implementation guidance:**
- Notification MCP tool (in `tools/notifications/`):
  - `send_slack_message(text, channel)` — via webhook or Slack SDK
  - Message templates: trade executed, position exited, daily summary, alert, kill switch
- Cron jobs (in `cron/`):
  - `market-scan.json` — triggers orchestrator at market open (9:45 AM ET)
  - `eod-review.json` — triggers EOD review at 4:15 PM ET
  - Format follows Hermes/Kermes cron spec
- Wire notifications into skills:
  - Trader skill: notify on execution
  - Monitor skill: notify on exit and alerts
  - Orchestrator: notify on daily summary

**Test requirements:**
- Unit test message formatting for each template
- Integration test: send test message to Slack, verify delivery
- Verify cron jobs are recognized by the platform (`hermes cron list` / kermes equivalent)
- Verify notification failures don't block trading

**Integration with previous work:** Adds notification tool to MCP server. Cron triggers the orchestrator workflow from Step 9.

**Demo:** Trigger a cron job manually, show the orchestrator running and Slack messages arriving for trade events.

---

## Step 12: Backtesting (simulation broker adapter)

**Objective:** Implement a simulation broker adapter that replays historical data through the same agent code paths.

**Implementation guidance:**
- In `tools/broker/simulation.py`, implement `SimulationBrokerAdapter`:
  - Maintains simulated account (cash, positions) in memory
  - `place_order()`: fills against historical data + slippage + fees
  - `get_positions()`, `get_account()`: return simulated state
  - `get_market_data()`: return current bar from replay (no look-ahead)
  - `get_historical_data()`: only data up to current replay time
- Backtest runner MCP tool:
  - `run_backtest(sop_name, symbols, start_date, end_date, initial_capital)` → results
  - Replays data bar-by-bar, runs orchestrator workflow at each step
  - Temperature=0 for all LLM calls
- Statistical backtesting:
  - `run_backtest_suite(n_runs, ...)` → metric distributions (mean, std, min, max)
- Switch between live and simulation via env var (`BROKER_MODE=paper|simulation`)

**Test requirements:**
- Unit test simulation adapter: market order fills at next bar open + slippage
- Unit test no look-ahead: data request at time T returns nothing after T
- Integration test: run backtest with simple strategy over 1 month, verify valid results

**Integration with previous work:** Implements same `BrokerAdapter` interface from Step 3. Same agent skills, same tools — only the broker is swapped.

**Demo:** Run a backtest of day-trade-momentum over 3 months. Show total return, Sharpe, max drawdown, trade count. Run 5 times, show metric distributions.

---

## Step 13: Kill switch and error hardening

**Objective:** Implement emergency halt mechanism and harden error handling.

**Implementation guidance:**
- Kill switch MCP tools:
  - `activate_kill_switch(reason)` — cancels orders, closes positions, alerts, halts
  - `check_kill_switch()` — returns current state
  - `clear_kill_switch()` — manual restart
- Trigger mechanisms:
  - Manual: Slack command or `KILL_SWITCH` file presence
  - Automated: daily loss limit breached, circuit breaker (10 consecutive broker failures)
- Kill switch execution: cancel pending → close positions at market → Slack alert → halt
- Error hardening:
  - All MCP tools wrapped with try/except + structured error responses
  - Stop-loss orders: unlimited retries with alerts
  - Database writes use transactions
  - Orchestrator checks kill switch before every delegation

**Test requirements:**
- Unit test kill switch activation sequence
- Unit test daily loss limit trigger
- Unit test circuit breaker (10 failures → kill switch)
- Unit test all operations blocked when kill switch active
- Test manual restart flow

**Integration with previous work:** Integrates with broker (Step 3), Monitor skill (Step 8), notifications (Step 11).

**Demo:** With a paper trade open, trigger kill switch. Show it cancelling orders, closing positions, sending Slack alert, halting. Clear and resume.

---

## Step 14: End-to-end paper trading validation

**Objective:** Validate the complete system running autonomously on Alpaca paper trading.

**Implementation guidance:**
- Configure for full trading day:
  - SOP: day-trade-momentum v1.0.0
  - Broker: Alpaca paper trading
  - Cron: scan at 9:45 AM ET, EOD review at 4:15 PM ET
  - Notifications: Slack configured
- Run for a full market day
- Validate MVP criteria:
  1. ✅ Orchestrator running one strategy on Alpaca paper trading
  2. ✅ SOP-driven behavior with versioned markdown
  3. ✅ Trade journaling with rationale and outcome
  4. ✅ Slack notifications for trades and summaries
  5. ✅ Backtesting with same code paths as live
  6. ✅ Installable on both Hermes and Kermes
- Test crash recovery: kill mid-monitoring, restart, verify recovery
- Test kill switch: trigger, verify clean shutdown
- Compare backtest results against paper trading results

**Test requirements:**
- Full integration: start system, run one complete workflow cycle, verify all DB tables populated
- Crash recovery works
- Kill switch works
- Backtest metrics are in same ballpark as paper trading

**Integration with previous work:** Exercises everything from Steps 1-13.

**Demo:** Full trading day on paper. System starts, scans market, analyzes, trades, monitors, exits, reviews, sends Slack summaries. Show it working on both Kermes and Hermes.
