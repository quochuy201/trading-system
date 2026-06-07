# Strategy Routing — Design Spec

**Status:** Draft v1 — awaiting human review
**Date:** 2026-06-06
**Author:** huylez (with Claude)
**Topic:** How the agent decides *which* strategy to apply, automatically, when multiple strategies are enabled across multiple markets.
**Governed by:** [`OPERATING_MANUAL.md`](../../OPERATING_MANUAL.md) (constitution) and [`docs/AGENT_EVOLUTION_STANDARD.md`](../AGENT_EVOLUTION_STANDARD.md) (this routing layer is **risk-bearing skill-routing** — human-authored, ratified, versioned; the agent applies it, never invents it).

---

## 1. Problem & Goals

### Problem
Today the system runs **one strategy at a time**, chosen **manually**: `SOUL.md` Phase 1 says "Load the strategy SOP for today," and risk-manager preflight item #8 is "Load today's strategy SOP" — a human picks it. As we add strategies (`equity/intraday-momentum`, `equity/swing`, `options/vol-edge`, future crypto/prediction-markets), we need the agent to **decide which strategy(ies) to apply on its own**, based on conditions — without a human picking each morning, and without running a strategy in a regime that's hostile to it (e.g. selling premium into a volatility spike).

### Goals (success criteria)
1. Given the enabled strategy set and live market conditions, the agent **selects which strategies are active this cycle** by applying human-authored rules — deterministically and auditably.
2. A strategy is **never run in a regime its rules deem hostile** (the safety win).
3. Multiple strategies can be active in one cycle **without multiplying risk** — they share one portfolio risk budget.
4. The routing logic is **declarative, versioned, human-ratified**, and **backtestable** (replayable against history).
5. Adding a new strategy requires editing **only** the registry + routing table + that strategy's SOP — no engine/role code changes.

### Non-goals (YAGNI)
- No machine-learned routing. Rules are human-authored (the playbook may later *propose* changes via the review gate — out of scope here).
- No truly parallel/concurrent workflows. "Concurrent strategies" means *evaluated within one serialized orchestration cycle sharing one risk budget*, not multiple independent loops.
- No new markets implemented here. Crypto/prediction-markets remain placeholders.
- Not re-deciding the directory restructure (separate spec). This spec assumes the 2-level `sops/<market>/<strategy>/` layout but does not depend on it landing first.

---

## 2. Design Overview — Hybrid Routing

Two stages, each owned by the role that already does the closest job:

```
Stage 1 — ELIGIBILITY GATE  (hard rules, owned by Risk-Manager, runs in preflight)
   live regime signals  ──►  routing SOP §1 matrix  ──►  ELIGIBLE strategy set
   "what kind of day is it? which strategies are even allowed to run today?"

Stage 2 — SETUP ROUTING     (classification + judgment, owned by Research)
   scan candidates  ──►  routing SOP §2 table  ──►  each candidate routed to an ELIGIBLE strategy's DD
   "this ticker looks like X — run X's due diligence on it (only if X is eligible)"
```

- **Stage 1 is a risk governor.** It turns strategies OFF when the regime is wrong for them. Hard rules, no LLM discretion. Fail-safe: missing/ambiguous signal → the strategy that depends on it is treated as **ineligible** (restrictive default).
- **Stage 2 is where judgment lives.** The LLM classifies each candidate to the strategy whose entry profile it matches, but may only route to strategies that survived Stage 1.

This is the standard professional pattern: **regime filters, setup selects.** It composes with what exists — risk-manager already reads SPY range-expansion (Rule 2) and computes mode; research already has a Layer-1 regime read and per-market scan sections.

---

## 3. Components & Changes

Five artifacts. Two are new; three are edits to existing files.

### 3.1 Strategy registry — `config.yaml` (NEW section)
Declares which strategies exist and are enabled for this account. Single source of truth for "what *could* run." Stage 1 narrows this to "what *does* run."

```yaml
strategies:
  enabled:
    - id: equity/swing
      sop: v1.0.0
    - id: options/vol-edge
      sop: v1.0.0
  disabled:                      # known but turned off (not even eligible)
    - id: equity/intraday-momentum
      sop: v1.0.0
```

- `id` resolves to `sops/<id>/<sop>.md` (rules) and `sops/<id>/dd.md` (due diligence reference).
- Disabling a strategy here is the master kill — it can never become eligible.
- No resolver *logic* in code; the agent reads this list (consistent with how it already reads `scanner.universe`).

### 3.2 Routing SOP — `sops/_routing/v1.0.0.md` (NEW, human-ratified, versioned)
The teachable artifact. Two tables.

**§1 Eligibility matrix** — regime conditions → per-strategy ON/OFF. Evaluated by risk-manager.

| Regime condition (from `get_market_regime`) | equity/swing | equity/intraday | options/vol-edge |
|---|---|---|---|
| `vix > 30` OR `spy_tr_atr > 2.0` (stress/crash) | OFF | OFF | OFF |
| `spy_tr_atr` in (1.5, 2.0] (elevated) | OFF | DEFENSIVE | DEFENSIVE |
| `iv_rank_spy > 70` AND `|spy_vs_sma50_pct| < 2` (high-vol, range-bound) | OFF | OFF | ON |
| `spy_vs_sma50_pct > 0` AND `spy_trend = up` AND `iv_rank_spy < 50` (clean uptrend) | ON | ON | OFF |
| `catalyst_density = high` (many fresh gappers) | ON | ON | OFF |
| default (no row matches) | OFF | OFF | OFF |

Cell values: `ON` (full), `DEFENSIVE` (eligible but half-size / A+ only — inherits risk-manager DEFENSIVE semantics), `OFF` (ineligible). **Most-restrictive-wins** when multiple rows match (same conflict rule risk-manager already uses). *(The three-state vs. binary ON/OFF choice is open — see §10.2; if binary wins for v1, the `DEFENSIVE` cells collapse to `OFF` and global mode handles sizing.)*

**§2 Setup routing** — candidate signature → strategy. Evaluated by research, only against eligible strategies.

| Setup signature | → strategy |
|---|---|
| premarket gap >3% + RVOL >2x + fresh catalyst (≤48h) | equity/intraday-momentum |
| multi-day base/consolidation breakout, trend intact, RS>SPY | equity/swing |
| pullback to rising SMA20/50 within uptrend | equity/swing |
| IV-rank >70, range-bound, liquid options chain | options/vol-edge |
| (no clear match) | **drop candidate** (log "unroutable") |

Provenance tags required on any threshold (per evolution standard §"hard limit"): each numeric bound tagged `BACKTEST-CALIBRATED`, `MARKET-HISTORY-DERIVED`, or `PLACEHOLDER-FAIL-SAFE`. v1 ships mostly `PLACEHOLDER-FAIL-SAFE` (conservative), tightened as backtest evidence arrives.

### 3.3 `get_market_regime()` — NEW MCP tool (`tools/server.py`)
Returns **raw measured signals only** — *not* a classified regime, *not* eligibility. Classification + the ON/OFF decision live in the SOP/agent (keeps strategy logic out of Python, per `CLAUDE.md` backtest rule #1). Mechanical data in, decision stays with the agent.

Output shape (all values clock-bounded to `current_time` for backtest no-look-ahead):
```json
{
  "vix": 18.4,
  "spy_tr_atr": 0.9,            // today's true range / 20-day ATR (reuses risk-mgr Rule 2)
  "spy_vs_sma50_pct": 2.3,     // % above/below SMA50
  "spy_trend": "up",           // up | down | flat (HH/HL structure)
  "iv_rank_spy": 41.0,         // existing calc_iv_rank on SPY
  "catalyst_density": "low",   // low|med|high — count of universe names with fresh catalyst+gap
  "as_of": "2026-06-06T13:30:00Z"
}
```
Built by composing tools that already exist (`get_market_data`, `calc_technical_indicators`, `calc_iv_rank`). On any missing input → field returns `null`; the SOP treats `null` in a condition as **fail-safe restrictive** (the dependent strategy → OFF).

### 3.4 Risk-Manager edits — `skills/risk-manager/SKILL.md`
- Preflight item #8 changes from "Load today's strategy SOP" → **"Compute eligible strategy set"**:
  1. `get_market_regime()`
  2. Read `config.yaml strategies.enabled`
  3. Apply routing SOP §1 → produce `{strategy_id: ON|DEFENSIVE|OFF}`
  4. `log_decision(action="strategy_eligibility", rules_triggered=[matched rows], reasoning=...)`
- Output adds an **Eligible Strategies** block (set + the regime snapshot + which §1 row fired per strategy).
- The eligibility gate is **subordinate to mode**: if global mode is HALTED, eligible set is empty regardless of §1. DEFENSIVE mode caps every eligible strategy at DEFENSIVE.

### 3.5 Research edits — `skills/research/SKILL.md`
- Receives the **regime snapshot + eligible set** from the orchestrator (does *not* re-read regime — single source of truth; removes the current risk of research's Layer-1 and risk-manager's regime read diverging).
- Phase 1 scan: classify each candidate via routing SOP §2; **discard candidates whose matched strategy is not eligible** (log "ineligible: <regime reason>").
- Phase 2 DD: load the matched strategy's `dd.md` and score with **that** strategy's rubric.
- Output groups candidates **by strategy**.

### 3.6 Orchestrator edits — `SOUL.md`
- Phase 1 step 3 "Load the strategy SOP" → "Obtain eligible strategy set from Risk-Manager."
- Phase 2: run research **once**, producing candidates grouped by eligible strategy.
- Phase 3: trader executes across strategies **against one shared risk budget** (see §4). Execution is serialized (one trader pass), not parallel.
- Phase 4: monitor handles all resulting positions regardless of originating strategy, each under its own SOP's exit rules.
- Rule 3 reworded: "One **orchestration cycle** at a time" — multiple strategies may be active within a cycle; there is still never more than one concurrent scan/execute loop.

---

## 4. Critical Invariant — One Shared Risk Budget

**Concurrency must not multiply risk.** All portfolio-level governors apply *across* the union of active strategies, not per-strategy:

| Governor (source) | Applies across all active strategies |
|---|---|
| `max_open_positions` (config) | total positions, all strategies combined |
| `daily_loss_limit_pct` (config / OPERATING_MANUAL) | one daily budget for the whole account |
| Sector concentration — max 1/sector (risk-mgr Rule 1) | counts positions from *every* strategy |
| Quarter-Kelly sizing cap (risk-mgr) | computed on combined account equity |
| Mode (NORMAL/DEFENSIVE/HALTED) | one mode for the account; gates all strategies |

Consequence: enabling a second strategy does **not** add a second budget. It competes for the *same* budget. The trader allocates the shared budget across the candidates research surfaced (highest-conviction first, across strategies), stopping when any portfolio governor binds. This is what makes multi-strategy safe rather than 2× leverage.

---

## 5. Data Flow (one cycle)

```
SOUL cycle start
  │
  ├─ Risk-Manager preflight (items 1–7: kill switch, limits, account, positions, mode)
  │     └─ item 8: get_market_regime() → apply routing SOP §1 → ELIGIBLE set + snapshot
  │         (HALTED ⇒ empty; DEFENSIVE ⇒ all capped DEFENSIVE)
  │
  ├─ [gate] eligible set empty? → STOP "no eligible strategy today" (safe, common)
  │
  ├─ Research (given snapshot + eligible set)
  │     └─ scan → classify via §2 → drop ineligible → DD per matched SOP → candidates grouped by strategy
  │
  ├─ [gate] no candidate ≥ threshold? → STOP "no opportunities"
  │
  ├─ Trader (given grouped candidates + ONE shared risk budget)
  │     └─ rank across strategies → size (quarter-Kelly, shared) → place until a governor binds
  │
  ├─ Monitor (all positions; each exits under its own strategy SOP)
  │
  └─ EOD Review (P&L + process metrics, incl. "was the router consulted?", per-strategy attribution)
```

---

## 6. Safety & Governance (per AGENT_EVOLUTION_STANDARD)

1. **Routing rules are SOP-tier — human-ratified only.** `sops/_routing/v*.md` is versioned; the agent reads and applies it, never edits it. Changes go through `reports/sop-changes/` → human ratifies → new version. (Same store-separation as every other SOP.)
2. **Fail-safe defaults.** Missing regime signal, no matching §1 row, or unroutable candidate all resolve to the *restrictive* outcome (OFF / drop / no trade). The system's failure direction is "trade less," never "trade more."
3. **Most-restrictive-wins** on rule conflicts — identical to the existing risk-manager conflict rule. The eligibility gate can only *subtract* from what mode/limits already allow, never add.
4. **Provenance tags** on every numeric threshold in the routing SOP. No self-invented crash/regime numbers presented as fact (§"hard limit").
5. **Full audit trail.** Eligibility decision and per-candidate routing both `log_decision(...)` with the rows that fired → inspectable, not self-reported.
6. **Hermes note.** Routing rules must **not** be left to Hermes's Curator/auto-skill-promotion. This is risk-bearing behavior → human ratification gate applies (standard §"Deployment on Hermes").
7. **Future learning loop (out of scope, noted):** the playbook's Tier-2 statistical findings may *propose* §1/§2 refinements via `reports/sop-changes/`; never auto-applied.

---

## 7. Failure Modes

| Situation | Handling |
|---|---|
| `get_market_regime` partial/unavailable | Affected signals `null` → dependent strategies OFF; if SPY data entirely missing → empty eligible set → STOP |
| No §1 row matches | default row → all OFF → STOP "no eligible strategy" |
| Candidate matches no §2 signature | drop, log "unroutable" |
| Candidate matches an *ineligible* strategy | drop, log "ineligible: <reason>" |
| Two strategies both want the same capital | shared budget + rank-across-strategies; governor binds → later candidates skipped |
| Regime flips intraday (stress spike) | risk-mgr Rule 2/5 already act on it; in-flight positions exit under their own SOP; no *new* entries for now-ineligible strategies |
| Routing SOP and a strategy SOP conflict | OPERATING_MANUAL > routing SOP > strategy SOP; most-restrictive applied |

---

## 8. Validation Strategy

"Sophisticated + validated" means the router is tested as rigorously as the strategies it gates.

1. **Deterministic rule tests (unit).** Fixture regime snapshots → assert exact eligible set. Golden table of `(snapshot → expected ON/DEFENSIVE/OFF per strategy)` covering each §1 row + conflicts + all-null. These are the regression baseline; a diff here must be intentional + ratified.
2. **`pass^k` reliability (per standard §3).** Replay the same historical day *k* times at temperature 0. The eligible set and per-candidate routing must be **identical** across runs. Variance = a reliability defect to fix, not noise.
3. **Backtest: gate-vs-control.** Using the Phase-4 strategy-agnostic engine, replay a historical window two ways — (a) with §1 eligibility gate active, (b) control with all enabled strategies always eligible. Compare expectancy / drawdown / worst-day. The gate must demonstrably reduce tail damage (its whole justification). Demoted to "directional signal" given small samples, per standard.
4. **Process metrics (per standard §3).** EOD review asserts: was `get_market_regime` called before scanning? Did every entered candidate map to an eligible strategy? Did sizing reconcile to one shared budget? Logged jointly with P&L — never P&L alone.
5. **Negative tests.** Inject a stress snapshot (`vix=35`) → assert empty eligible set. Inject `iv_rank=80, range-bound` → assert only `vol-edge` eligible. Inject all-`null` → assert STOP.

**Acceptance:** #1, #2, #4, #5 green; #3 shows gate ≥ control on max-drawdown for the test window. Until #3 runs, routing ships **disabled by default** (registry `enabled: []` beyond the single current strategy) behind paper-only.

---

## 9. Rollout (phased)

- **P0 — scaffolding:** registry section + `sops/_routing/v1.0.0.md` with conservative `PLACEHOLDER-FAIL-SAFE` thresholds; `get_market_regime` tool + tests. No behavior change yet (one strategy enabled).
- **P1 — wire eligibility:** risk-manager computes + logs eligible set; orchestrator consumes it. Still single strategy enabled → eligible set is {that one} or empty. Validates the gate end-to-end with zero added risk.
- **P2 — enable setup routing:** research consults §2; enable a *second* strategy; shared-budget trader path. Paper-only.
- **P3 — backtest validation (§8.3):** run gate-vs-control; tighten thresholds from `PLACEHOLDER` → `BACKTEST-CALIBRATED`; ratify v1.1.0 of the routing SOP.

Each phase is independently revertible (disable in registry).

---

## 10. Open Questions (confirm before implementation plan)

1. **Regime ownership:** OK that risk-manager is the *single* regime reader and research consumes its snapshot (removing research's independent Layer-1 read)? (Recommended — prevents divergence.)
2. **`DEFENSIVE` as an eligibility cell value** — keep the three-state ON/DEFENSIVE/OFF, or simplify to binary ON/OFF for v1 and let global mode handle sizing? (Lean: binary for v1, YAGNI; global DEFENSIVE already exists.)
3. **`catalyst_density` signal** — worth computing for v1, or defer (it overlaps research's own catalyst scan)? (Lean: defer; start with VIX + spy_tr_atr + trend + iv_rank.)
4. **Routing SOP location** — `sops/_routing/v1.0.0.md` vs a section in `OPERATING_MANUAL.md`. (Lean: standalone versioned SOP — it'll evolve independently of the constitution.)
```
