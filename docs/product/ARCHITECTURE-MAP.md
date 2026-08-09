# Architecture Map — Understanding This Repo

**Purpose:** one page to orient anyone (you, Hermes, Claude Code) on how the system is
built and where each concern lives in the code. This is the "help me understand the
repo" reference. Verified against the actual codebase 2026-07-07.

---

## Two Lenses on the Same System

### Lens A — Role-Agents (how the code is organized)

```
Orchestrator (deploy/SOUL.md) — workflow coordinator, never trades directly
  ├── Research Agent   (skills/research/SKILL.md)     → scan + score candidates
  ├── Trader Agent     (skills/trader/SKILL.md)       → plan + place orders
  ├── Monitor Agent    (skills/monitor/SKILL.md)      → track + exit positions
  ├── Risk Manager     (skills/risk-manager/SKILL.md) → mode + sizing + circuit breakers
  └── EOD Review       (skills/eod-review/SKILL.md)   → journal + reflect
```

Two strata:
- **Agent behavior** = markdown (`SOUL.md`, `skills/*/SKILL.md`, `sops/`, `OPERATING_MANUAL.md`)
- **Tool implementation** = Python MCP tools (`tools/server.py` + submodules)

The constitution is `OPERATING_MANUAL.md` — 3 modes (NORMAL/DEFENSIVE/HALTED), trader
math, the risk staircase, circuit breakers. **It wins on any conflict.**

### Lens B — The 6-Layer Decision Pipeline (the research evaluation lens)

This is NOT another set of agents. It's a lens that cuts *across* the agents, asking:
inside any single trade decision, what six things happen? Every layer should emit a
typed contract (the baton handed to the next layer).

```
  PERCEPTION → MEMORY → REASONING → ACTION → RISK → AUDIT
   (get data)  (recall)  (decide)  (propose) (gate) (record)
```

> Don't confuse Lens B with the scanner's internal "4-layer binary gate"
> (liquidity → relative-strength → trend → momentum) in `tools/scanner/filters.py`.
> That's a filter funnel inside the Research agent, a different thing entirely.

---

## The Map + Current State (verified in code)

| Layer | Owned by (agent) | Where it lives in code | State today | Gap | Priority |
|-------|------------------|------------------------|-------------|-----|----------|
| **1 Perception** | data cron + Research | `tools/data/source.py` (`YFinanceSource.get_daily_bars`, yfinance `auto_adjust=True`), `refresh_market_data()` (server.py:2722), `is_stale()` + `freshness_report()` (`data/validate.py`, 5-day tol) | **Strong.** Daily refresh + staleness guard already fixed the real bug (06-23). | Only P1 audit-stamping of per-trade data provenance (MR-1). yfinance is unofficial/unstable (reliability risk if going live). | none for P0 |
| **2 Memory** | all agents | 16 SQLite tables (`tools/persistence/db.py`): `trade_plans`, `trade_transactions`, `decisions`, `transaction_ledger`, `journal_entries`, `scan_funnel`, `performance_metrics`, `iv_history`, …; `tuning_config.json`; skills markdown | **Rich data, real feedback bridge** (EOD→scan). Ahead of most research. | **Recall, not storage:** episodic data isn't handed to Research before a scan. Working memory lives in fragile LLM context. | P1 |
| **3 Reasoning** | Research, EOD (LLM) | `skills/research/SKILL.md` DD + scoring, `skills/eod-review/SKILL.md` reflection; scanner `filters.py` | LLM does the thinking. | No time-scale taxonomy (reactive vs reflective vs strategic); no reasoning budgets; risk of LLM used where code should be. | P1 |
| **4 Action** | Trader | `TradePlan` dataclass (`tools/models.py:54`, carries stop_loss/take_profit/side/qty), `save_trade_plan`/`get_trade_plan` (server.py:861), `place_order` (server.py:145) | Trade plans are typed + persisted. | `place_order` signature is thin (7 args) — can't judge R:R itself; relies on the plan lookup. This is the gate's input. | P0 (with #5) |
| **5 Risk** | Risk Manager (mostly LLM) | **Hard gate:** kill switch inside `place_order` (server.py:166-167). **Advisory:** `check_portfolio_risk`/`check_daily_limits` (server.py:769/806 → `risk/checks.py`) — separate tools the LLM is *told* to call. Constitution in `OPERATING_MANUAL.md`. | **The weak link.** Only the kill switch is enforced in code. Everything else = LLM compliance with markdown. | Make the whole constitution a hard, unbypassable code gate. | **P0 — THE change** |
| **6 Audit** | all agents | `transaction_ledger`, `decisions`, `scan_funnel`, `journal_entries` tables; `reports/` | Append-only logs exist; good coverage. | Not hash-chained/replayable; no role attribution; no MR-1..7 report. | P1 (report) / P2 (hash chain) |

---

## The Safety Thesis (one sentence)

**The LLM reasons; deterministic code gates; deterministic code executes.** The LLM
should be boxed in the middle (Layers 3–4). Perception (1), Risk (5), and Audit (6)
should be code. Today only Layer 5's kill switch enforces this — P0 closes the gap.

```
TODAY:   LLM ──(trusted to self-check)──► place_order ──[kill switch only]──► broker
TARGET:  LLM ──► place_order ──[GOVERNANCE GATE: whole constitution]──► broker
                                       ↑ same choke slot as kill switch; unbypassable
```

---

## Fast Repo Navigation (where do I go to change X?)

| I want to change… | Go to |
|-------------------|-------|
| A risk rule / limit / mode | `OPERATING_MANUAL.md` (rule) + `tools/risk/checks.py` (today) → `tools/governance/gate.py` (after P0) |
| What data we pull | `tools/data/source.py` |
| How candidates are scanned/scored | `tools/scanner/filters.py` + `skills/research/SKILL.md` |
| How a trade is planned/sized | `skills/trader/SKILL.md` + `TradePlan` in `tools/models.py` |
| How orders are placed | `place_order` in `tools/server.py:145` |
| How positions are monitored/exited | `skills/monitor/SKILL.md` + `tools/monitor_sentinel.py` |
| EOD journal / feedback tuning | `skills/eod-review/SKILL.md` + `tools/scanner/tuning.py` |
| DB schema | `tools/persistence/db.py` + `repository.py` |
| The MCP tool surface | `tools/server.py` (`@mcp.tool()` functions) |
| Agent wiring / cron schedule | `deploy/SOUL.md`, `deploy/runs/`, `cron/` |
