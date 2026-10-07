# Trading System — Product Roadmap

**The master backlog. Every feature, its status, priority, and where its docs live.**
Maintained by Claude Code (roles: BUILD-PLAN §1). Last updated: 2026-10-07.

Read [`README.md`](README.md) for the workflow and [`ARCHITECTURE-MAP.md`](ARCHITECTURE-MAP.md)
for the mental model (the 6-layer lens over your role-agents).

Status vocabulary: `backlog → spec → design → plan → building → shipped` (also `parked`, `paused`).

---

## The Organizing Frame

Two lenses describe the same system:

1. **Role-agents** (how the code is organized): Orchestrator → Research, Trader,
   Monitor, Risk Manager, EOD Review — over two strata (markdown skills + Python MCP tools).
2. **The 6-layer decision pipeline** (the research lens, cuts across the agents):
   `PERCEPTION → MEMORY → REASONING → ACTION → RISK → AUDIT`.

Every feature below is tagged with the layer(s) it touches. The pipeline is the
*evaluation* frame; the agents are the *implementation* frame. See ARCHITECTURE-MAP.md.

---

## Now / Next / Later (priority tiers)

Priorities inherited from the Jul-6 research (Implementation-Guide.md) and validated
against the current code. **The single highest-impact change is the governance gate:
today the only hard code gate on `place_order` is the kill switch; all other risk
rules are advisory (markdown + optional tool calls the LLM is trusted to make).**

> **See [`BUILD-PLAN.md`](BUILD-PLAN.md)** for the ratified decisions (D1–D7), build waves, verification strategy (§4.5), and the design queue (§4.7). Ratified 2026-07-25; statuses refreshed 2026-10-07.

`#` is a backlog ID, not build order (BUILD-PLAN cites #3/#9/#12). P0's 0–2 match the BUILD-PLAN §4.7 queue; that queue is the build order.

### P0 — NOW (safety-critical foundation)

| # | Feature | Slug | Layer | Status | Docs |
|---|---------|------|-------|--------|------|
| 0 | **Deployment (repo → Hermes runtime)** — one installer plus `verify.sh` reachability checks; prerequisite for every other feature | `deployment` | operational | **paused** (08-09) — 10 of 12 tasks, 6 of 9 done-criteria; only blocker is an owner-approved real install | [spec](features/deployment/deployment-spec.md) · [design](features/deployment/deployment-design.md) · [plan](features/deployment/deployment-implementation-plan.md) |
| 1 | **Go-Live Metrics (trade-outcome capture)** — record broker fills, pair them into round trips, compute R per trade, report D5 progress; blocks D5 + D7 | `go-live-metrics` | 6 Audit | **building** — Tasks 1–10 done, 11 partial (live paper fill pending creds + an open market). 250 fills → 61 round trips, 0 R-computable (all predate intent capture); D5 clock 0/100. New tools: `get_go_live_scorecard`, `run_eod_reconcile` | [spec](features/go-live-metrics/go-live-metrics-spec.md) · [design](features/go-live-metrics/go-live-metrics-design.md) · [plan](features/go-live-metrics/go-live-metrics-implementation-plan.md) |
| 2 | **Deterministic Governance Gate** — move risk enforcement from advisory markdown into an unbypassable code gate inside `place_order` | `governance-gate` | 5 Risk | **plan** (approved 07-09, ready to build) | [spec](features/governance-gate/governance-gate-spec.md) · [design](features/governance-gate/governance-gate-design.md) · [plan](features/governance-gate/governance-gate-implementation-plan.md) |
| 2a | **Typed Action Contract** — first slice of the pipeline-contracts system; the `TradeProposal`/`ActionOutcome` types the gate consumes | `action-contract` | 4 Action | backlog | (folds into #2's design; graduates when full contracts start) |

### P1 — NEXT (data + selection, learning + reproducibility)

| # | Feature | Slug | Layer | Status | Docs |
|---|---------|------|-------|--------|------|
| 13 | **Data Source Adapters** — canonical `MarketDataSource` + capability-flagged adapters (yfinance daily; Alpaca daily, intraday, quotes); D3 | `data-source-adapters` | 1 Perception | **plan** (not started; BUILD-PLAN queue #3) | [spec](features/data-source-adapters/data-source-adapters-spec.md) · [design](features/data-source-adapters/data-source-adapters-design.md) · [plan](features/data-source-adapters/data-source-adapters-implementation-plan.md) |
| 14 | **Capital-Aware Selection** — affordability pre-filter + rank by return-on-capital across equity and options; D6, the drought fix | `capital-aware-selection` | 4 Action (Size) | **plan** (not started; queue #4; options half needs #13) | [spec](features/capital-aware-selection/capital-aware-selection-spec.md) · [design](features/capital-aware-selection/capital-aware-selection-design.md) · [plan](features/capital-aware-selection/capital-aware-selection-implementation-plan.md) |
| 3 | **Working + Episodic Memory Recall** — hand past-trade summaries to Research before it scans; structured working-memory snapshot that survives context compression | `memory-recall` | 2 Memory | backlog | — |
| 4 | **Full Pipeline Contracts** — typed dataclasses for all 6 layers + instrumentation | `pipeline-contracts` | all | backlog | — |
| 5 | **MR-1..MR-7 Compliance Report** — daily protocol-comparable reporting (no paper has this) | `mr-compliance-report` | 6 Audit | backlog | — |
| 6 | **Source Binding / Anti-Hallucination** — require verifiable citation for every catalyst | `source-binding` | 1 Perception / 3 Reasoning | backlog | — |
| 7 | **Reasoning Time-Scale Split** — enforce reactive=code, reflective/strategic=LLM; reasoning budgets per agent | `reasoning-timescales` | 3 Reasoning | backlog | — |
| 8 | **Role Attribution in Trade Ledger** — `attributed_to` column; P&L by agent | `role-attribution` | 6 Audit | backlog | — |
| 9 | **Tuning-Change Governance** — limits only tighten, auto-rollback, change log | `tuning-governance` | 2 Memory / 5 Risk | backlog | — |

### P2 — LATER (advanced)

| # | Feature | Slug | Layer | Status | Docs |
|---|---------|------|-------|--------|------|
| 10 | **Hash-Chain Audit Trail** — replayable, tamper-evident decision rounds | `audit-hashchain` | 6 Audit | backlog | — |
| 11 | **Deliberation Loop** — Research↔Risk negotiation before Trader executes | `deliberation-loop` | 3 Reasoning | backlog | — |
| 12 | **Semantic Memory → YAML** — machine-readable strategy config the gate reads | `semantic-yaml` | 2 Memory | backlog | — |

---

## Research Queue (owner-defined discovery track)

These are OPEN QUESTIONS the owner wants researched → spec'd, not yet designed.
Each becomes one or more features above once researched. Tracked here so nothing is lost.

| # | Topic | What to answer | Status |
|---|-------|----------------|--------|
| R1 | **Scanner redesign** | Replace the 400-daily-bars scan with the data patterns pro algo traders actually use. (Related: the Jun-28 Factor-Scanner design in `docs/design/factor-scanner-tdd.md` — 14 factors, engines M+R — never implemented; unratified research input.) | research — in progress · [findings](research/R1-scanner-redesign.md) |
| R2 | **Position monitoring — stop panic selling** | Monitor logic exits on noise. Define what a real exit trigger is vs. intraday noise. | research |
| R3 | **Overnight gap handling** | System panic-sells on next-day open gaps. Define gap-aware hold/exit rules. | research |
| R4 | **New strategies beyond M/R** | Expand past momentum + mean-reversion. Candidate strategy families. | research |
| R5 | **Options trading** | Deepen the options/vol-edge track (credit spreads, IV-rank routing). | research |

---

## Shipped (recent — full history in PROJECT_STATUS.md)

| Date | What | Commit |
|------|------|--------|
| 2026-08-16 | Preflight rewrite: check 1 measures auth, not a key name; calls `hermes` directly; right profile path under cron | `33b51cc`, `277a013`, `ce77a56` |
| 2026-08-08 → 08-10 | `deployment` Tasks 1–8, 11, 12 (code; feature paused, see P0 #0): single installer `./install.sh`, `verify.sh` + `mcp_probe.py` reachability checks, provenance stamp, skills copied into the profile | `0aced42` … `86268dc` |
| 2026-08-08 | Telegram notifier committed (`telegram.py` was imported but never tracked) | `141b48a` |
| 2026-06-27 → 06-29 | EOD Pattern & Insight capture; EOD→morning feedback bridge (`tuning_config.json`) | `4cef139`, `0ec0d34` |
| 2026-06-27 | Single-profile Hermes redesign; preflight health gate | — |
| 2026-06-23 | Scan-funnel observability; **data-staleness root-caused + fixed** | `041d5c0`, `c6e9b06` |
| 2026-06-21 | Market-data foundation (yfinance single writer); options IV capture; **paper trading enabled** | — |

---

## Legacy Artifact Homes (superseded by this directory going forward)

Historical design docs — removed from git in `570f314` (2026-08-08); `docs/_archive/` is gitignored.
Recover any with `git show 570f314^:<path>`, using these original paths:
- `docs/specs/` + `docs/plans/` — backtest engine v2/v3, options vol-edge, strategy routing
- `docs/superpowers/specs/` + `plans/` — engine-B, market-data foundation, options adapter, scan-funnel, single-profile redesign
- Still tracked in `docs/design/`, none of them current: `consolidated-architecture.md`, `pluggable-pipeline-plan.md` and `detailed-design.md` are superseded (BUILD-PLAN §1.5 and D4); `factor-scanner-tdd.md` is unratified research input (R1 §S4)

New product work is specced under `docs/product/features/`. Changes to existing behaviour get a note under `docs/product/changes/<slug>/`.
