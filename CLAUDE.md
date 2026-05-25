# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# MCP tools server (must be running for agents to work)
cd tools && uv run server.py

# Tests (all, single file, single test)
cd tools && uv run --extra dev pytest tests/ -v
cd tools && uv run --extra dev pytest tests/test_broker.py -v
cd tools && uv run --extra dev pytest tests/test_broker.py::test_place_order -v

# Platform install (hermes | kermes | meshclaw)
./install.sh hermes
./install.sh hermes --dry-run
```

## Package Purpose

This is a **platform-agnostic agent package** — a set of markdown skill definitions + Python MCP tools that can be installed on any agent harness (Claude Cowork, MeshClaw, OpenClaw, Hermes, Kermes). The packaging format is a Hermes Profile Distribution (`distribution.yaml`), but the content is harness-neutral.

The system trades real money (or paper) autonomously. **Safety is not optional.** Every code change must preserve the kill switch, risk gates, circuit breakers, and mode state machine. A bug here means financial loss.

## Architecture

```
Orchestrator (SOUL.md) — workflow coordinator, never trades directly
  ├── Research Agent (skills/research/SKILL.md) → scan + score candidates
  ├── Trader Agent  (skills/trader/SKILL.md)    → plan + execute orders
  ├── Monitor Agent (skills/monitor/SKILL.md)   → track + exit positions
  ├── Risk Manager  (skills/risk-manager/SKILL.md) → mode + sizing + circuit breakers
  └── EOD Review    (skills/eod-review/SKILL.md)   → journal + reflect
```

### Two Layers

| Layer | Files | Language | Changes require |
|-------|-------|----------|-----------------|
| Agent behavior | `SOUL.md`, `skills/*/SKILL.md`, `sops/` | Markdown | Understanding the trading domain |
| Tool implementation | `tools/server.py` + submodules | Python 3.11+ | Tests passing, risk invariants preserved |

### Key Invariants

- **OPERATING_MANUAL.md is the constitution.** It defines modes (NORMAL/DEFENSIVE/HALTED), sizing math, circuit breakers, risk limits. It overrides all other files on conflict. Read it before modifying any risk-related code.
- **Agents never call Alpaca directly.** All market data and orders flow through MCP tools, which handle retry, ledger logging, and kill switch enforcement.
- **SOPs are human-controlled.** Agents propose changes to `reports/sop-changes/` but never modify files in `sops/` directly.
- **Kill switch blocks `place_order`** when active — checked via `_kill_switch_state` in `server.py`.
- **Simulation broker** swaps the global `_broker` reference during backtests. `start_backtest_v2` → `next_backtest_bar` loop enables bar-by-bar agent-driven replay without future data leakage.

### Data Flow

```
Agent decision → MCP tool call → broker/adapter.py (abstract)
                                     ├── alpaca.py (live/paper)
                                     └── simulation.py (backtest)
                                  → persistence/repository.py → SQLite (tools/trading.db)
                                  → notifications/slack.py (fire-and-forget)
```

## BACKTEST DEVELOPMENT RULES (CRITICAL)

These rules are NON-NEGOTIABLE. Violating them produces misleading results.

### 1. Never Hardcode Strategy Logic in Backtest Scripts

```
❌ WRONG: Writing `if rsi > 50: score += 20` in a backtest .py file
❌ WRONG: Writing exit rules like `if hold_bars >= 10: exit` in Python
❌ WRONG: Defining thresholds, scoring weights, or entry criteria in code

✅ RIGHT: Strategy rules live in skill files (skills/*/SKILL.md) or SOPs (sops/)
✅ RIGHT: The AI agent reads the skills and makes decisions via MCP tool calls
✅ RIGHT: Python only handles MECHANICAL operations (check if price hit stop level)
```

### 2. Backtest Must Use Same Code Path as Live Trading

The scanner, the DD process, the entry logic, the monitoring — ALL must be the same module whether running in backtest or live. If you build a scanner for backtesting that isn't used live, the backtest proves nothing about the real system.

### 3. Entry at Next-Available Price (Never Signal Price)

```
❌ WRONG: Scanner finds candidate at today's close ($143), enter at $143
✅ RIGHT: Scanner finds candidate at today's close, enter at NEXT DAY'S OPEN

The market is closed when the scanner runs. You cannot buy at the close price.
This prevents fake profits from overnight gaps.
```

### 4. Gap Detection

- If stock gaps UP > 5% above planned entry → SKIP (missed the move, don't chase)
- If stock gaps DOWN > 3% below planned entry → SKIP (thesis may be broken)

### 5. The AI Agent Makes Decisions, Not Python

Python's role in the backtest:
- Advance the clock (next_backtest_bar)
- Provide data when asked (calc_technical_indicators, get_market_data, get_news)
- Execute mechanical checks (did price hit stop? did time expire?)
- Log decisions

The AI agent's role:
- Read skill files and apply the DD framework
- Evaluate news/catalysts qualitatively
- Score candidates and decide enter/skip
- Determine position sizing based on conviction

### 6. When to Invoke the LLM (Not Every Bar)

- **Start of day:** LLM decides what to trade (research + DD)
- **Unusual event:** Price drops >3% in one bar → LLM evaluates hold vs exit
- **Everything else:** Python handles mechanically (stop hits, trailing updates, time stops)

## Development Best Practices

### When Modifying MCP Tools (`tools/server.py`)

- Every `@mcp.tool()` function must include a docstring with: purpose, when to use, sample input, and expected output.
- Tools that mutate state (place_order, activate_kill_switch) must log to the transaction ledger via `_log_to_ledger()`.
- Tools must never raise exceptions to the agent — return JSON errors: `{"error": "description"}`.
- Use `with_retry(fn, _retry_config)()` for any broker call that could transiently fail.

### When Adding a New Broker Adapter

- Implement `broker/adapter.py` abstract class (`BrokerAdapter`).
- All methods must return the same dict/list shapes as `alpaca.py`.
- Simulation adapter must respect `current_time` for historical replay.

### When Writing Agent Skills (`skills/*/SKILL.md`)

- Follow the [agentskills.io/specification](https://agentskills.io/specification) format: YAML frontmatter with `name` and `description`, then markdown body.
- `description` field: start with "Use when..." — triggering conditions only, never workflow summary.
- `requires_tools` in frontmatter: list only MCP tools this agent actually calls.
- Skills define BEHAVIOR (what to do, when to stop, what to reject). Tools define CAPABILITY (how to do it).

### When Writing Strategy SOPs (`sops/`)

- SOPs are versioned (semver): `sops/<strategy-name>/v<major>.<minor>.<patch>.md`.
- SOPs define entry criteria, exit rules, sizing parameters, and scoring thresholds.
- Changes to SOP logic require a new version file — never edit an existing version in place.

### When Working on the Scanner

- Scanner code must be a SHARED MODULE used by both backtest and live trading (task #15 pending).
- Scanner filters are: liquidity + ATR → relative strength → trend/structure → momentum/timing.
- The scanner outputs CANDIDATES. The AI agent does the final DD and decides.

## Trading Domain Context

### Key Concepts

| Concept | Where | What it means |
|---------|-------|---------------|
| Kill switch | `server.py`, `OPERATING_MANUAL.md` | Emergency halt — closes all positions, blocks new orders |
| R:R (risk/reward) | `sops/`, `skills/trader/` | Ratio of potential profit to potential loss. Minimum 2:1. |
| ATR | `analysis/indicators.py` | Average True Range — volatility measure for stop placement |
| RVOL | Scanner | Relative Volume — today's volume vs 20-day average. 1.1x+ for swing trades |
| Kelly criterion | `OPERATING_MANUAL.md §3.4` | Position sizing formula capped at quarter-Kelly |
| Compliance score | `audit/compliance.py` | Fraction of decisions that followed SOP rules. <0.9 forces DEFENSIVE. |

### Hybrid Architecture (Scanner + AI Agent)

```
Strategy Engine (Python, mechanical) → scans universe, applies quantitative filters
         ↓ candidates
AI Agent (LLM) → does qualitative DD (reads news, assesses catalyst, makes judgment)
         ↓ decisions
Execution (Python, mechanical) → places orders, monitors stops, logs trades
```

The AI's value over code: interpreting news/sentiment, recognizing novel market conditions, adapting strategy selection, 24/7 monitoring across information sources.

## Configuration

- **`config.yaml`** — Risk parameters, broker mode (`paper | live | simulation`), scheduling, income target gating.
- **`.env` at project root** — Loaded by `server.py` on startup. Required: `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`. Optional: `SLACK_WEBHOOK_URL`.
- **`distribution.yaml`** — Hermes profile manifest (package metadata, env requirements).
- **`mcp.json`** — MCP server declaration for agent harnesses.
