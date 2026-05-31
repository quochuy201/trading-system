# Options Vol-Edge Strategy — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Author the complete, unambiguous decision protocol (SOP + agent-skill behavior, markdown only) for the two-engine defined-risk options book, ready for the Phase 2 tooling build.

**Architecture:** A versioned SOP (`sops/options-vol-edge/v1.0.0.md`) holds the strategy; the Research/Trader/Monitor skills get options paths; everything defers to `OPERATING_MANUAL.md`. No Python in this phase.

**Tech Stack:** Markdown only. Source of truth: `docs/specs/2026-05-31-options-vol-edge-strategy-design.md` (the design). Reference style: `sops/day-trade-momentum/v1.0.0.md` (existing SOP), `skills/research/reference/options-dd.md` (existing DD reference being superseded).

**Verification model:** Each task ends with a **Verification checklist** (not pytest). A task is done when every box is checkable by reading the produced markdown, and the cross-cutting invariant holds: *no rule is looser than `OPERATING_MANUAL.md`, and every agent decision has either a concrete rule or an explicit "skip if data missing."*

---

## File structure (locked before tasks)

| File | Responsibility |
|---|---|
| `sops/options-vol-edge/v1.0.0.md` | The strategy: header/deference, edge thesis, tiers, scan, structures/strikes, scoring, sizing, entry, exits, cost-tracking, journal schema, versioning. |
| `skills/research/reference/options-vol-edge-dd.md` | How Research scans + scores both engines; the per-market DD reference (replaces `options-dd.md`). |
| `skills/research/SKILL.md` | Add a pointer/branch to the options DD reference when the active SOP is `options-vol-edge`. |
| `skills/trader/SKILL.md` | Add options structure/strike/expiry selection, conviction-scaled tier sizing, multi-leg order placement. |
| `skills/monitor/SKILL.md` | Add the cross-day options exit loop. |
| `skills/research/reference/options-dd.md` | Add deprecation header pointing to the new reference (content left in place). |

The SOP is authored in section-coherent tasks (1–6); skills in tasks 7–9; deprecation in task 10; final consistency pass in task 11. All on branch `feature/options-vol-edge-strategy`.

---

### Task 1: SOP scaffold — header, deference, edge thesis, account tiers

**Files:**
- Create: `sops/options-vol-edge/v1.0.0.md`

- [ ] **Step 1: Author the header + constitution deference.** Title `# Options Vol-Edge Strategy — v1.0.0`. Then an Overview that states: (a) this is a **swing SOP** (multi-day holds, 30–120 DTE) that **explicitly overrides the day-trade 15:45 flatten** — cite `OPERATING_MANUAL.md` Rule 7 ("non-negotiable *for day-trade SOPs*"); (b) `OPERATING_MANUAL.md` is the constitution and wins on conflict; this SOP only ever makes itself stricter.

- [ ] **Step 2: Author the "Two Engines" thesis table** (verbatim values from design §"Core Principle"):

| | Engine A — Vol-Edge (income) | Engine B — Directional / Big-Fish |
|---|---|---|
| Edge | Vol mispricing: sell rich (IVR>75), buy cheap (IVR<25) | Trend continuation — catch the runner |
| Structures | Bull put / bear call credit spreads + debit verticals | Momentum debit spreads + leashed single-leg longs |
| Profit | Capped, high win-rate | Spread 3–8× · single-leg uncapped |
| Scored on | IVR / IV-HV / put-skew | RS63 + regime strength + setup quality |

State: both engines are **defined-risk only**; single-leg longs are the sole uncapped instrument, leashed (see Sizing).

- [ ] **Step 3: Author the Account Tiers table** (verbatim from design §"Account tiers"):

| Tier | Equity | Options? | Spread width | Notes |
|---|---|---|---|---|
| Bridge | < $3.5k | OFF → equity-swing fallback (future spec) | — | Compound up; options auto-enable on cross. |
| Small | $3.5k–$10k | ON | narrow only ($1–$2.50) | Single-leg ($35–$150) more granular than spreads here. |
| Standard | $10k–$25k | ON | $5 | Referenced $10k profile. |
| Pro | $25k+ | ON | $5+ | Above PDT; most diversification room. |

State tiers read **live equity** each session (compounding is structural). Note the Bridge equity-swing strategy is out of scope for this SOP.

- [ ] **Step 4: Commit**

```bash
git add sops/options-vol-edge/v1.0.0.md
git commit -m "feat(options-sop): scaffold v1.0.0 — header, two-engine thesis, account tiers"
```

**Verification checklist:**
- [ ] Header explicitly declares the swing override and cites the Manual rule by number.
- [ ] States Manual-wins-on-conflict and stricter-only.
- [ ] Both engine columns and all four tiers present with exact thresholds ($3.5k / $10k / $25k).
- [ ] "Defined-risk only" and the single-leg leash forward-reference are stated.

---

### Task 2: SOP — Scan section (Phase 1 of the strategy's own flow)

**Files:**
- Modify: `sops/options-vol-edge/v1.0.0.md`

- [ ] **Step 1: Author "Scan — Market Context".** SPY regime via EMA20/SMA50/SMA200 (UPTREND: `Close>EMA20>SMA50>SMA200` + SMA50 slope>0 over last 10 bars; DOWNTREND mirror; else NEUTRAL). VIX bands: `<15` compressed (favor single-name elevated IVR), `15–25` normal, `>25` reduce widths, `>35` no debit longs. Macro calendar: hold new entries the morning of FOMC/CPI/PPI/NFP until 30 min after; if a market-moving event lands inside the intended expiry window, widen the spread or wait.

- [ ] **Step 2: Author "Scan — IV & regime filter".** Define `IVR = (IV30 − 52wk_low)/(52wk_high − 52wk_low)×100` and `IV/HV = IV30/HV20`. Engine A routing: IVR>75 → sell (credit); IVR<25 → buy (debit); 25–75 → no vol edge (Engine A skips; Engine B may still qualify on momentum). Equity regime + `RS63 = stock_63d_return − SPY_63d_return`: UPTREND needs RS63>0, DOWNTREND needs RS63<0. Structure must agree with regime (bullish structures only in UPTREND, etc.). Put-skew `= IV_OTM_put − IV_equidistant_OTM_call`; note >5 favors selling puts.

- [ ] **Step 3: Author "Scan — Liquidity & earnings gates".** 20-day avg dollar volume ≥ $20M; option OI ≥ 100 (≥500 preferred); bid-ask on the spread ≤ 20% of mid. Earnings: confirmed date must be entirely outside the expiry window, or the window starts >7 calendar days after earnings. **If earnings date is unavailable/uncertain → skip the candidate** (explicit missing-data rule).

- [ ] **Step 4: Commit**

```bash
git add sops/options-vol-edge/v1.0.0.md
git commit -m "feat(options-sop): scan section — market context, IV/regime/RS63, liquidity/earnings gates"
```

**Verification checklist:**
- [ ] IVR, IV/HV, RS63, put-skew all have exact formulas.
- [ ] Engine A routing thresholds (75 / 25) and regime-agreement rule stated.
- [ ] Liquidity numbers ($20M ADV, OI 100/500, spread ≤20%) present.
- [ ] Earnings-missing → skip is explicit.

---

### Task 3: SOP — Structure, strike & expiry selection

**Files:**
- Modify: `sops/options-vol-edge/v1.0.0.md`

- [ ] **Step 1: Author Engine A structures.** Rich vol + UPTREND → **bull put spread** (sell OTM put, buy lower put). Rich vol + DOWNTREND → **bear call spread**. Cheap vol + trend → **debit vertical** (buy ATM/0.45–0.55 delta, sell ~1 expected-move OTM, where `expected_move = price × IV × √(DTE/365)`). Credit short strike at **0.20–0.25 delta** (go to 0.15 delta when IVR>90). Long-leg width per tier: Small $1–$2.50, Standard $5, Pro $5+.

- [ ] **Step 2: Author Engine B structures.** Momentum debit spread: buy ATM, sell a **wider** OTM short leg (target ~1.5–2 expected-moves) to keep more upside; 60–90 DTE. Single-leg long: 60–120 DTE; **IV-aware routing** — if `IVR ≥ 50` (vol hot) prefer the debit spread instead; single-leg reserved for `IVR < 50`. Engine B entry requires a **continuation setup** (one of: pullback-to-EMA20 with bullish reversal + volume ≥1.2×avg; consolidation breakout with BB-squeeze + volume ≥1.5×avg; MACD resumption cross) — no chasing extended moves (Manual Rule 5).

- [ ] **Step 3: Author expiry rules.** Credit spreads 30–45 DTE (never <21 at entry). Engine A/B debit 60–90 DTE. Single-leg 60–120 DTE. Restate the earnings-vs-expiry rule from Task 2.

- [ ] **Step 4: Commit**

```bash
git add sops/options-vol-edge/v1.0.0.md
git commit -m "feat(options-sop): structure/strike/expiry selection for both engines"
```

**Verification checklist:**
- [ ] Each structure maps to an exact (vol regime × trend) condition.
- [ ] Delta targets (0.20–0.25, 0.15 @IVR>90, ATM 0.45–0.55) and per-tier widths present.
- [ ] Single-leg IV-aware routing (IVR<50) and the 3 continuation setups are concrete.
- [ ] All DTE windows specified; earnings rule restated.

---

### Task 4: SOP — Scoring rubrics (0–100, two engines → one scale)

**Files:**
- Modify: `sops/options-vol-edge/v1.0.0.md`

- [ ] **Step 1: Author the Vol-Edge score (Engine A), 0–100.** A candidate is scored only if it passed the scan gates; any "reject" component fails the candidate outright.

| Component | Points |
|---|---|
| IVR magnitude | credit: IVR≥90→30, 80–90→22, 75–80→15, <75→reject · debit: IVR≤15→30, 15–25→20, >25→reject |
| IV/HV confirm | credit: >1.3→15, 1.1–1.3→8, else 0 · debit: <0.7→15, 0.7–0.85→8, else 0 |
| Regime strength | full alignment + slope→20, partial→10, misaligned→reject |
| RS63 rank | top5→15, top10→10, top20→5, positive→2 |
| Liquidity/spread | OI>1000 & spread<5%→10, OI>500 & spread<10%→6, OI>100→3, else reject |
| Earnings buffer | >14d outside→10, 7–14d→5, inside→reject |
| Put-skew bonus | put-spread with skew>5→5, else 0 |

Sum = 0–100. **A+ = score ≥ 80** (maps to `OPERATING_MANUAL.md` DEFENSIVE gate).

- [ ] **Step 2: Author the Momentum score (Engine B), 0–100.**

| Component | Points |
|---|---|
| RS63 rank | top3→30, top5→24, top10→15, top20→8, else reject |
| Regime strength | full alignment + slope→25, partial→12, misaligned→reject |
| Continuation setup quality | textbook→25, decent→15, none→reject |
| Liquidity | OI>1000 & spread<10%→10, OI>500→6, OI>100→3, else reject |
| IV sanity (single-leg) | IVR<50→10, 50–70→5, >70→0 (route to spread) |

Sum = 0–100. **A+ = score ≥ 80.**

- [ ] **Step 3: State the score's role.** Score drives (a) the Manual's A+/DEFENSIVE gate, (b) conviction-scaled sizing (Task 5), and (c) Research's candidate ranking. Reject < 70 (below B+).

- [ ] **Step 4: Commit**

```bash
git add sops/options-vol-edge/v1.0.0.md
git commit -m "feat(options-sop): 0-100 scoring rubrics for vol-edge and momentum engines"
```

**Verification checklist:**
- [ ] Both rubrics sum to a 0–100 max and define A+ ≥ 80 identically.
- [ ] Every component has explicit point bands; "reject" conditions named.
- [ ] Score explicitly tied to the Manual's gate, to sizing, and to ranking; <70 reject stated.

---

### Task 5: SOP — Sizing (defers to `OPERATING_MANUAL.md §3`)

**Files:**
- Modify: `sops/options-vol-edge/v1.0.0.md`

- [ ] **Step 1: Author the sizing formula** (maps options onto Manual §3):

```
risk_dollars      = E * risk_pct                       # E = live equity (get_account)
max_loss_per_unit = (spread_width - credit) * 100      # credit spreads
                  = debit_paid * 100                   # debit spreads / single-leg
contracts         = floor(risk_dollars / max_loss_per_unit)   # ≥1 or skip
```

- [ ] **Step 2: Author the conviction-scaled `risk_pct` table** (verbatim from design §"Sizing"):

| Score | Grade | Per-trade risk (defined max-loss) |
|---|---|---|
| 70–79 | B+ | ~1.5% |
| 80–89 | A | ~3% |
| 90–100 | A+ | up to full heat headroom (no fixed cap) |

- [ ] **Step 3: Author the account-level backstops (HELD — non-negotiable).** Portfolio heat cap **6%** (sum of all open max-loss). Single-leg sub-leash: total single-leg open max-loss ≤ **3%** of equity. Manual circuit breakers stand: −3% day / −6% week / −10% month → HALT. Kelly cap (§3.4) applies. State the natural governor: any single trade with max-loss >3% trips the daily halt if it loses, so oversized A+ bets are self-limiting.

- [ ] **Step 4: Commit**

```bash
git add sops/options-vol-edge/v1.0.0.md
git commit -m "feat(options-sop): conviction-scaled sizing with held account-level backstops"
```

**Verification checklist:**
- [ ] Sizing formula uses live equity and max-loss-per-unit (no equity-stop math).
- [ ] Conviction table present; A+ has no fixed cap; <70 not sized (skip).
- [ ] 6% heat, 3% single-leg leash, 3/6/10% breakers, Kelly cap all explicitly stated as held.
- [ ] No rule here is looser than the Manual (verify against `OPERATING_MANUAL.md §3–4`).

---

### Task 6: SOP — Entry gates, order placement, exits, cost-tracking, journal, versioning

**Files:**
- Modify: `sops/options-vol-edge/v1.0.0.md`

- [ ] **Step 1: Author entry gates.** Hard gates (any failure → skip today): SPY regime agrees; stock regime agrees with structure; IVR in correct zone (Engine A) or continuation setup present (Engine B); no earnings in window; time ≥ 9:45 ET; spread bid-ask ≤ 20% of mid; portfolio heat after trade ≤ 6%; single-leg heat after ≤ 3%. Soft gates (failure → reduce size, not skip): IV/HV confirm; put-skew confirm; option volume ≥ 100 on target strike; social neutral/confirming.

- [ ] **Step 2: Author order placement.** Multi-leg **limit at mid**; never market on spreads; on credit spreads start $0.05–0.10 better than mid, relax to mid after 5 min. Single-leg limit at/near mid. Log on fill.

- [ ] **Step 3: Author the exit framework** (daily 15:30 ET cross-day loop; most-urgent-first). Always-on: 50% max-profit close (credit), 21-DTE hard close (credit), 2× loss limit (credit & debit), no expiration holding. Trailing: credit value-stop (give back >20% of best gain → close); debit/single-leg (value < 75% of peak → close; scale at +100%). Thesis: regime/vol BROKEN → close; THREATENED+WEAKENING → reduce 50%. Single-leg: IV-crush rule (moved+crushed→take profit; no-move+crushed→cut) + time stop by mid-DTE. Emergency: gap-through-strike, SPY regime collapse, binary-event-in-window → immediate defensive exit. Roll: only untested/profitable with vol edge intact. Include the exit-reason enum verbatim from design §"Exit framework".

- [ ] **Step 4: Author cost-tracking + journal schema + versioning.** Cost-tracking: EOD review reports daily token + broker-fee burn vs realized P&L; **gate is OFF** (`income.target_per_day_usd: 0`). Journal schema: base Manual fields + `iv_rank, iv_hv, delta, theta, vega, structure, engine, max_profit, max_loss, breakeven, dte` + the exit-reason enum. Versioning section points to `sops/options-vol-edge/ROADMAP.md`.

- [ ] **Step 5: Commit**

```bash
git add sops/options-vol-edge/v1.0.0.md
git commit -m "feat(options-sop): entry gates, order placement, exit framework, journal + versioning"
```

**Verification checklist:**
- [ ] Hard vs soft gates clearly separated; heat (6%) and single-leg (3%) checks in hard gates.
- [ ] Exit framework covers all five families (always-on, trailing, thesis, single-leg, emergency) + roll; enum complete.
- [ ] Cost-tracking states gate OFF; journal lists all options fields; versioning points to ROADMAP.
- [ ] The exit loop's 15:30 cross-day cadence (overnight holds) is explicit.

---

### Task 7: Research skill — options DD reference + branch

**Files:**
- Create: `skills/research/reference/options-vol-edge-dd.md`
- Modify: `skills/research/SKILL.md`

- [ ] **Step 1: Author `options-vol-edge-dd.md`.** A Research-facing reference (mirror the style of the existing `options-dd.md`) covering: how to run the scan (market context → IV scan → regime/RS63 → liquidity/earnings), how to classify a candidate to Engine A vs B, and how to compute the two scores from Task 4. Output: a ranked, scored candidate list with `engine`, `structure`, `score`, and a one-line thesis each.

- [ ] **Step 2: Modify `skills/research/SKILL.md`.** Add a line to the market/DD-reference routing: when the active SOP is `options-vol-edge`, load `reference/options-vol-edge-dd.md` (not `options-dd.md`). Match the existing reference-routing pattern in that file.

- [ ] **Step 3: Commit**

```bash
git add skills/research/reference/options-vol-edge-dd.md skills/research/SKILL.md
git commit -m "feat(research): options vol-edge DD reference + SOP-based routing"
```

**Verification checklist:**
- [ ] DD reference reproduces scan + both scoring rubrics consistently with the SOP (same thresholds).
- [ ] SKILL.md routes `options-vol-edge` → the new reference, following the existing pattern.
- [ ] Output format names `engine`, `structure`, `score`.

---

### Task 8: Trader skill — options structure/sizing/placement

**Files:**
- Modify: `skills/trader/SKILL.md`

- [ ] **Step 1: Add an options section** to the trader skill: structure/strike/expiry selection (Task 3 rules), conviction-scaled tier sizing (Task 5 formula + table + backstops), and multi-leg limit-order placement (Task 6). Reference the SOP as the source of parameters; don't restate values that would drift — instead cite `sops/options-vol-edge/v1.0.0.md` sections, but DO state the sizing formula and the order-placement rule inline (these are Trader's core actions).

- [ ] **Step 2: Commit**

```bash
git add skills/trader/SKILL.md
git commit -m "feat(trader): options structure selection, conviction sizing, multi-leg placement"
```

**Verification checklist:**
- [ ] Trader knows how to turn a scored candidate into a sized, placed multi-leg order.
- [ ] Sizing formula + backstops present; cites the SOP for parameter tables.
- [ ] "Never market on spreads; limit at mid" stated.

---

### Task 9: Monitor skill — cross-day options exit loop

**Files:**
- Modify: `skills/monitor/SKILL.md`

- [ ] **Step 1: Add the options exit loop** to the monitor skill: the daily 15:30 ET cross-day sequence (emergency → mechanical profit/time → trailing → thesis integrity), the single-leg IV-crush/time-stop rules, and the exit-reason enum. Reference the SOP exit section for full rules; state the loop ordering inline (Monitor's core action). Note the two-tier design: tool-only checks daily, LLM escalation only when an exit condition triggers (token discipline).

- [ ] **Step 2: Commit**

```bash
git add skills/monitor/SKILL.md
git commit -m "feat(monitor): cross-day options exit loop with single-leg IV-crush handling"
```

**Verification checklist:**
- [ ] Loop ordering (emergency-first) present; all exit families reachable.
- [ ] Single-leg IV-crush + time-stop handled.
- [ ] Two-tier (tool-only vs LLM-escalation) cadence stated; holds overnight (not 15:45 flatten).

---

### Task 10: Deprecate the old single-leg DD stub

**Files:**
- Modify: `skills/research/reference/options-dd.md`

- [ ] **Step 1: Add a deprecation header** at the top: `> **DEPRECATED (2026-05-31).** Superseded by options-vol-edge-dd.md and sops/options-vol-edge/v1.0.0.md. The single-leg directional approach below is retained for reference and is re-homed (leashed) as Engine B's single-leg lane. Do not use this file for live decisions.` Leave the rest of the content unchanged (flag, don't delete).

- [ ] **Step 2: Commit**

```bash
git add skills/research/reference/options-dd.md
git commit -m "docs(research): mark options-dd.md superseded by vol-edge reference"
```

**Verification checklist:**
- [ ] Header present and points to both successor files; original content intact below it.

---

### Task 11: Final consistency pass against the design + Manual

**Files:**
- Read-only review of all Phase 1 files.

- [ ] **Step 1: Spec-coverage pass.** Open `docs/specs/2026-05-31-options-vol-edge-strategy-design.md` and tick each success criterion (its §"Success criteria"): SOP exists & consistent; every decision has a rule or skip; both engines + all v1.0.0 structures specified; conviction sizing wired to Manual with backstops intact; skills carry the options path; `options-dd.md` superseded; `ROADMAP.md` present. List any gap and fix inline.

- [ ] **Step 2: Manual-deference pass.** Re-read `OPERATING_MANUAL.md §1–4` and confirm no SOP rule is *looser*: modes unchanged, sizing maps to §3, heat/leash/breakers ≥ as strict. Fix any drift.

- [ ] **Step 3: Cross-file value-consistency pass.** Confirm the scoring bands, delta/DTE/width numbers, heat (6%) and single-leg leash (3%) are identical across `v1.0.0.md`, `options-vol-edge-dd.md`, the trader/monitor skills, and `ROADMAP.md`. Fix any mismatch (single source of truth = the SOP).

- [ ] **Step 4: Commit any fixes.**

```bash
git add -A
git commit -m "fix(options): consistency pass — align SOP, skills, and roadmap with design + Manual"
```

**Verification checklist:**
- [ ] All design success criteria ticked.
- [ ] No rule looser than the Manual.
- [ ] Numbers identical across all Phase 1 files.

---

## Self-Review (plan vs. design spec)

**Spec coverage:** design §"Where everything lives" → Tasks 1–10 (every file). §"SOP structure" 12 points → Tasks 1–6. §"Account tiers" → Task 1. §"Sizing" → Task 5. §"Exit framework" → Task 6. §"Agent behavior changes" → Tasks 7–9. §"Success criteria" → Task 11. §"4-phase program"/§"Config" → documented (Phases 2–4 out of scope here; cost gate OFF captured in Task 6). No uncovered requirement.

**Placeholders:** none — every task states concrete tables/values or cites the SOP section that holds them; scoring rubrics fully specified.

**Type/value consistency:** thresholds reused across tasks ($3.5k/$10k/$25k tiers; IVR 75/25; 6% heat; 3% single-leg leash; A+ ≥ 80; delta 0.20–0.25). Task 11 enforces them as a single source of truth (the SOP).
