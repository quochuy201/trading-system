# Spec: Capital-Aware Selection

- **Slug:** `capital-aware-selection`
- **Status:** `spec`
- **Priority:** `P1` — the actual fix for the trading drought
- **Owner sign-off:** ☑ approved 2026-07-25 (BUILD-PLAN §2, **D6**)
- **Layer(s):** 4 Action (Size stage), consumes 3 Reasoning
- **Author:** Claude Code · **Date:** 2026-07-25

## Problem

**Buying power is applied as a late veto instead of an input to selection**, so the system repeatedly picks candidates it can never afford.

Verified in `trades.jsonl` — the agent's own words on the final logged session:

> "AMD (~$550-560s, **IVR ~99 confirmed** … earnings Aug 4 outside window) — stock $550+ requires $10-wide long strike, max loss/contract ~$400-450 >> NEUTRAL-halved $100 A+ budget — **SKIP (sizing, 34th consecutive session on this constraint)**"
>
> "**Structural constraint persists: $10k account at 1-2% risk cannot size 1 contract of a liquid credit spread on any confirmed IVR>75 name priced >$50.**"

**33 logged no-trade records** (2026-05-31 → 2026-07-16), the top candidate skipped on affordability every time. The signal was confirmed; the position was unbuildable.

**Why it happens structurally.** The pipeline ranks on *signal quality first* and checks affordability last:

```
scan → score by signal → pick best → size it → ✗ can't afford → skip → repeat tomorrow
```

`calc_position_size` (`server.py:741`) computes quantity from `(account_value, risk_pct, entry, stop)` — correct math, but invoked **after** the candidate is chosen. Nothing filters the candidate list by what the account can actually hold.

**This is not an options problem.** The equity scanner has the same blind spot (a $700 stock at 1 share vs a per-trade risk budget). It surfaced first in options because contracts are chunky.

## Goal

Make buying power an **input to ranking, not a veto after it** — so the system always selects the best opportunity it can *actually take*, across equity and options in one pass.

## User / System Value

- **Ends the drought at its source.** The agent stops proposing positions it cannot build.
- **Better use of a small account** — a cheap equity swing that *can* be sized may legitimately beat an unaffordable options spread. Judged by one metric instead of two starving pipelines.
- **Removes the XSP escalation** — no new instrument needed (D6).

## Scope

**In scope**
- **Affordability pre-filter** — before ranking, drop any candidate whose minimum viable position cost exceeds the per-trade risk budget / available buying power.
- **Rank by return-on-capital**, not raw signal:
  - options: `credit ÷ BPR`, where `BPR = (strike width − credit) × 100 × contracts` (tastytrade standard)
  - equity: expectancy (or R) **per dollar of required risk capital**
- **Cross-asset ranking in one pass** (D6) — equity and options candidates compete on the same metric.
- **Greedy fill** to the position cap: take the best affordable, decrement buying power, repeat.
- Sizing stays **fixed-fractional (% of equity)**, quarter-Kelly cap retained (`OPERATING_MANUAL §3.4`).
- Deterministic Python — this is arithmetic, not judgment (`CLAUDE.md` RULE 3: no thresholds in code; they come from config/SOP).

**Out of scope / non-goals**
- ⛔ **No mean-variance / quadratic optimizer.** Research is explicit that MVO produces unstable, concentrated portfolios that fail out-of-sample. For a handful of positions this is a filter + sort, nothing more.
- NOT the scanner rebuild (D4, deferred) — this works on whatever candidates the current scanner produces.
- NOT new instruments (XSP dropped, D6).
- NOT changing `calc_position_size`'s math — only *when* it's applied.
- NOT the governance gate's affordability veto — that stays as a last-resort floor.

## Acceptance Criteria

1. Candidates whose **minimum 1-unit cost** exceeds the per-trade budget are excluded **before** ranking, and the exclusion is counted in `scan_funnel`.
2. Ranking key is **return-on-capital**; a lower-signal affordable candidate outranks a higher-signal unaffordable one.
3. Equity and options candidates are ranked **together** on the same metric (D6).
4. Greedy fill respects **available buying power** and `max_open_positions`; each selection decrements remaining capital.
5. Sizing remains fixed-fractional % of equity — **account-size-invariant** (works on $10k and $100k without re-tuning).
6. Options BPR uses live chain data; if unavailable, the candidate is **`UNAVAILABLE`, not silently ranked** (§3a rule).
7. On the historical AMD case, AMD is **filtered out pre-ranking** and a *sizeable* candidate is selected instead — a regression test using the real `trades.jsonl` numbers.
8. `why_zero` distinguishes **"nothing affordable"** from **"nothing qualified"** — today they're indistinguishable, which is why 33 sessions read the same.
9. All existing tests stay green; no change to what the gate enforces.

## Risks & Safety Impact

- **Does not weaken any risk control.** It selects *within* the existing budget; the gate still has final say.
- **Risk: cheap-and-bad bias.** Ranking by return-per-dollar could favour low-priced, low-quality names. Mitigation: affordability is a **filter**, signal quality still gates entry — a candidate must pass its SOP gates *first*, then compete on capital efficiency. **Affordability never promotes a candidate that failed its strategy gates.**
- **Risk: over-concentration in cheap names** on a small account. Mitigation: existing concentration cap (`max_concentration_pct`) is unchanged and applies after.
- **Risk: stale BPR.** Options prices move; a BPR computed at scan time may be wrong at execution. Mitigation: the gate re-checks affordability at order time; selection is a *planning* estimate, explicitly labelled as such.

## Open Decisions

- **D-CAS1: Tie-break when two candidates have similar return-on-capital.** *(Recommend: **higher signal score wins** — capital efficiency selects the feasible set; signal quality orders within it.)*
- **D-CAS2: Minimum viable position for equity — 1 share, or a minimum dollar size?** *(Recommend: **a configured minimum notional**. A 1-share position is technically affordable but commission/slippage make it noise, and it can't be scaled out.)*
- **D-CAS3: Does the affordability filter run before or after the LLM's DD?** *(Recommend: **before** — DD is the expensive step; filtering first stops us paying for analysis on positions we can't build. This is also the drought's direct cause: 33 sessions of DD on unaffordable names.)*

## References

- Evidence: `Hermes/trades.jsonl` (33 no-trade records; sizing cited as the constraint), `Hermes/strategy_improvements.md`
- Research: `[[2026-07-25-Capital-Aware-Selection-Research]]` — pro pipeline is *alpha → **portfolio construction** → risk → execution*; we have no portfolio-construction stage
- `docs/product/BUILD-PLAN.md` — **D6** (+ correction), §1.5 stage map
- Code: `calc_position_size` (`server.py:741`), `scanner/filters.py`, `analysis/options.py` (BPR inputs), `OPERATING_MANUAL.md §3.2/§3.4`
