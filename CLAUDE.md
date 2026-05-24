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
  └── Monitor Agent (skills/monitor/SKILL.md)   → track + exit positions
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
- **Simulation broker** swaps the global `_broker` reference during backtests. `setup_backtest` → `advance_bar` loop enables bar-by-bar agent-driven replay without future data leakage.

### Data Flow

```
Agent decision → MCP tool call → broker/adapter.py (abstract)
                                     ├── alpaca.py (live/paper)
                                     └── simulation.py (backtest)
                                  → persistence/repository.py → SQLite (tools/trading.db)
                                  → notifications/slack.py (fire-and-forget)
```

## Development Best Practices

### When Modifying MCP Tools (`tools/server.py`)

- Every `@mcp.tool()` function must include a docstring with: purpose, when to use, sample input, and expected output. This is how agents discover tool capabilities.
- Tools that mutate state (place_order, activate_kill_switch) must log to the transaction ledger via `_log_to_ledger()`.
- Tools must never raise exceptions to the agent — return JSON errors: `{"error": "description"}`.
- Use `with_retry(fn, _retry_config)()` for any broker call that could transiently fail.

### When Adding a New Broker Adapter

- Implement `broker/adapter.py` abstract class (`BrokerAdapter`).
- All methods must return the same dict/list shapes as `alpaca.py`.
- Simulation adapter must respect `current_time` for historical replay.

### When Writing Agent Skills (`skills/*/SKILL.md`)

- Follow the [agentskills.io/specification](https://agentskills.io/specification) format: YAML frontmatter with `name` and `description`, then markdown body.
- `description` field: start with a verb phrase describing what the agent does. Keep under 500 chars.
- `requires_tools` in frontmatter: list only MCP tools this agent actually calls.
- Skills define BEHAVIOR (what to do, when to stop, what to reject). Tools define CAPABILITY (how to do it).
- Never embed API keys, broker details, or config values in skill files — those come from the tools layer.

### When Writing Strategy SOPs (`sops/`)

- SOPs are versioned (semver): `sops/<strategy-name>/v<major>.<minor>.<patch>.md`.
- SOPs define entry criteria, exit rules, sizing parameters, and scoring thresholds.
- Changes to SOP logic require a new version file — never edit an existing version in place.
- The agent's compliance score (`audit/compliance.py`) measures adherence to SOP rules, so every rule must be taggable with a rule ID (e.g., `RVOL_HIGH`, `RR_VALID`).

### When Modifying Risk Logic (`tools/risk/`)

- The risk staircase is defined in OPERATING_MANUAL.md §4. Code in `risk/checks.py` must match those thresholds exactly.
- Risk checks return `{"passed": bool, ...}` — never silently pass. The Trader agent uses this to gate execution.
- Daily limits, concentration limits, and max positions are read from `config.yaml` at runtime.

### When Adding Cron Jobs (`cron/`)

- JSON format with schedule, command, and description fields.
- All times are ET (Eastern Time) — the system operates on US market hours.
- Cron jobs invoke agent workflows, not tools directly.

## Trading Domain Context

### Why This Matters for Development

Trading systems have unique constraints that inform code design:

- **Idempotency**: Orders can fill partially. A crash + restart must not double-enter a position. The preflight checklist (OPERATING_MANUAL §2) and crash recovery logic handle this.
- **Time sensitivity**: Stale data (>5 min) is dangerous. The Research agent rejects stale quotes. Time stops (3:45 PM ET for day trades) are hard constraints, not suggestions.
- **Asymmetric risk**: A missed trade costs $0. A bad trade costs real money. The system is designed to be conservative — when in doubt, skip.
- **Mode transitions are state-driven, not choice-driven**: The agent computes its mode (NORMAL/DEFENSIVE/HALTED) from account state. It cannot choose to override this.

### Key Concepts in the Code

| Concept | Where | What it means |
|---------|-------|---------------|
| Kill switch | `server.py`, `OPERATING_MANUAL.md` | Emergency halt — closes all positions, blocks new orders |
| R:R (risk/reward) | `sops/`, `skills/trader/` | Ratio of potential profit to potential loss. Minimum 2:1. |
| ATR | `analysis/indicators.py` | Average True Range — volatility measure for stop placement |
| RVOL | `sops/`, `skills/research/` | Relative Volume — today's volume vs average. >2x = institutional interest |
| PDT | `OPERATING_MANUAL.md` | Pattern Day Trader rule — 3 day-trades in 5 days on sub-$25K accounts |
| Kelly criterion | `OPERATING_MANUAL.md §3.4` | Position sizing formula capped at quarter-Kelly |
| Expectancy | `OPERATING_MANUAL.md §3.3` | (win_rate × avg_win) - (loss_rate × avg_loss). Must be positive to trade. |
| Compliance score | `audit/compliance.py` | Fraction of decisions that followed SOP rules. <0.9 forces DEFENSIVE. |

### Market Hours (US Equities, ET)

| Phase | Window | System behavior |
|-------|--------|-----------------|
| Pre-market scan | 08:00–09:25 | Data loading only |
| Research | 09:25–09:45 | Wait for first 15-min candle |
| Trade execution | 09:45–11:30 | No new entries after 11:30 |
| Monitoring | continuous | Until all positions flat or 15:45 |
| Time stop | 15:45 | Close all day-trade positions |
| EOD review | 16:05–16:30 | Journal, metrics, compliance |

## Configuration

- **`config.yaml`** — Risk parameters, broker mode (`paper | live | simulation`), scheduling, income target gating.
- **`.env` at project root** — Loaded by `server.py` on startup. Required: `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`. Optional: `SLACK_WEBHOOK_URL`.
- **`distribution.yaml`** — Hermes profile manifest (package metadata, env requirements).
- **`mcp.json`** — MCP server declaration for agent harnesses.
