# Options Vol-Edge Strategy — Design (Phase 1 of 4)

**Date:** 2026-05-31
**Status:** Active — design approved, implementation pending
**Scope of this doc:** The full options-trading program (4 phases). **Phase 1** (the Strategy SOP + agent behavior, markdown only) is specified in full here and implemented next. Phases 2–4 are scoped at the program level so the work cannot be dropped; each gets its own design + plan when reached.
**Supersedes:** `skills/research/reference/options-dd.md` (old single-leg directional stub — to be marked deprecated, not deleted).

---

## Origin

Ported and adapted from the prior "Multi Agent Trading System with OpenClaw / Hermes" work:
`options-trader.skill`, `options-exit-manager.skill`, `swing_trading_strategy.md`, and the
`options_dry_run_june2_2026.md` worked example (QCOM bull put spread). Theoretical basis:
Sheldon Natenberg, *Option Volatility and Pricing*. This design re-homes that strategy into
this repo's architecture (versioned SOP + 4-agent model + MCP tools + backtest-shares-live-code-path).

---

## Core Principle

The options book runs **two complementary engines** under one SOP, both gated by the same
equity-regime filter and both governed by `OPERATING_MANUAL.md`:

| | **Engine A — Vol-Edge (income)** | **Engine B — Directional / Big-Fish** |
|---|---|---|
| Edge | Volatility mispricing (Natenberg): sell rich vol (IVR > 75), buy cheap vol (IVR < 25) | Trend continuation — catch the runner (MU/AMD/INTC-style moves) |
| Structures | Credit spreads (bull put / bear call) + debit verticals | Momentum debit spreads **+ leashed single-leg longs** |
| Profit shape | Capped, high win-rate, repeatable | Spread: capped 3–8× · single-leg: **uncapped** |
| Scored on | IVR / IV-HV / put-skew | RS63 + regime strength + continuation-setup quality |
| Risk | Defined (spread width or premium) | Defined (spread width or premium) |

**Direction is always a filter, never the edge for Engine A.** Both engines are **defined-risk
only** — no naked options. Single-leg longs are the one uncapped instrument, deliberately leashed
(see Sizing).

`OPERATING_MANUAL.md` is the constitution and wins on every conflict. This SOP defers all
mode/limit/sizing-framework decisions to it and only ever makes itself **stricter**, never looser.

---

## Breadth: v1.0.0 = "Standard + Directional lane"

In scope for v1.0.0:

- **Engine A:** bull put spread (rich vol + uptrend), bear call spread (rich vol + downtrend),
  debit vertical (cheap vol + trend).
- **Engine B:** momentum-tuned debit spread, and single-leg long call/put (≤ leash).

Out of scope for v1.0.0 (roadmap — see `sops/options-vol-edge/ROADMAP.md`):

- Iron condors (neutral-regime path) → **v1.2.0**
- Earnings-vol single-leg variant (implied-vs-actual move) → **v1.3.0** (= "Comprehensive" complete)

---

## Where everything lives (this repo's pattern)

| File | Action | Contents |
|---|---|---|
| `sops/options-vol-edge/v1.0.0.md` | **new** | The strategy: tiers, scan, structures, strikes, expiry, scoring, sizing, exits, journal schema. The "what." |
| `sops/options-vol-edge/ROADMAP.md` | **new** | Version ladder + phase program (cross-machine pickup point). |
| `skills/research/reference/options-vol-edge-dd.md` | **new** | How Research scans (IV scan + regime + RS63) and scores both engines. Replaces `options-dd.md`. |
| `skills/research/reference/options-dd.md` | **deprecate** | Add header pointing to the new file; leave content in place (flag dead code, don't silently delete). |
| `skills/trader/SKILL.md` | **edit** | Options section: structure/strike/expiry selection, tier-based conviction-scaled sizing, multi-leg limit-order placement. |
| `skills/monitor/SKILL.md` | **edit** | Cross-day options exit loop (the exit-manager logic). |
| `config.yaml` | **edit (Phase 1 documents; Phase 2 wires)** | Options tier thresholds, heat cap; `income.target_per_day_usd` stays `0` (cost gate off, costs tracked). |

The standalone Hermes `.skill` bundles are **not** copied in verbatim — their logic is decomposed
into the SOP (strategy) + the three agent skills (behavior), per repo convention.

---

## SOP structure (`sops/options-vol-edge/v1.0.0.md`)

1. **Header + constitution deference** — declares this a *swing* SOP (multi-day holds) that
   overrides the day-trade 15:45 flatten (sanctioned by Manual Rule 7: "non-negotiable *for
   day-trade SOPs*").
2. **Edge thesis** — the two engines (above).
3. **Account tiers** (see next section).
4. **Phase 1 — Scan:** market context (SPY regime via EMA20/SMA50/SMA200, VIX bands, macro
   calendar) → IV scan (`IVR`, `IV/HV`, put-skew) → equity regime + `RS63` → liquidity
   (≥ $20M ADV, OI, bid-ask) → earnings-clear.
5. **Phase 2 — Structure & strike selection:**
   - Engine A credit: short strike 0.20–0.25 delta, long leg per tier width; 30–45 DTE (never < 21).
   - Engine A debit (cheap vol): ATM/0.45–0.55 delta long, short ~1 expected-move OTM; 60–90 DTE.
   - Engine B momentum debit: wider short-leg target (capture more of the move); 60–90 DTE.
   - Engine B single-leg: 60–120 DTE (blunt theta); IV-aware routing — if the runner's IV is hot,
     prefer the debit spread (short leg sells back inflated vol); single-leg reserved for non-extreme IV.
   - Expiry vs earnings: window must be entirely before earnings, or > 7 calendar days after.
6. **Scoring (0–100), two rubrics → one scale** so the Manual's A+ gate (≥ 80) and DEFENSIVE
   mode work unchanged:
   - Vol-Edge score: IVR magnitude, IV/HV confirm, regime strength, RS63 rank, liquidity/spread,
     earnings buffer, put-skew. (Social signal is a Phase-5 soft gate, not a scoring component.)
   - Momentum score: RS63 rank, regime strength, continuation-setup quality (pullback-to-EMA20 /
     consolidation breakout / MACD resumption), liquidity, IV sanity (penalize extreme IV for single-leg).
7. **Entry gates** (hard = skip on failure; soft = reduce size) + **order placement**
   (multi-leg limit at mid; never market on spreads; single-leg limit at/near mid).
8. **Sizing** — defers to Manual §3, mapped to options (see Sizing section).
9. **Exit framework** (see Exit section) — runs as a **daily 15:30 ET cross-day loop**.
10. **Cost tracking** — EOD review reports daily token + broker-fee burn vs. realized P&L
    (gate off; reporting only).
11. **Journal schema** — base Manual fields + `iv_rank, iv_hv, delta, theta, vega, structure,
    max_profit, max_loss, breakeven, dte, engine` and the exit-reason enum.
12. **Versioning** — points at `ROADMAP.md`.

---

## Account tiers (small-cap reconciliation)

Defined-risk spreads are chunky and indivisible. One standard $5-wide credit spread risks ~$350
max loss — which blows through any sane per-trade % on a small account. Tiers + a minimum-equity
gate resolve this. **The system started this build around a $3.5k–$10k account (Small tier).**

| Tier | Equity | Options? | Spread width | Notes |
|---|---|---|---|---|
| **Bridge** | < $3.5k | **OFF** → equity-swing fallback* | — | Compound up to the gate, options auto-enable on cross. |
| **Small** | $3.5k–$10k | **ON** | narrow only ($1–$2.50) | Single-leg longs ($35–$150 premium) are *more* granular here than spreads. |
| **Standard** | $10k–$25k | ON | $5 standard | The referenced $10k profile. |
| **Pro** | $25k+ | ON | $5+ | Above PDT line; most diversification room. |

\* The **equity-swing bridge** (below the gate) is **out of scope for Phase 1** — the account
starts at $3.5k+, so options are on at launch. The gate + fallback hook is specified; the bridge
SOP itself is a separate future spec (noted in the roadmap). Tiers read **live equity** every
session, so position size scales with the account — **compounding is structural, not manual.**

---

## Sizing (defers to `OPERATING_MANUAL.md §3`)

Options math maps onto the Manual: `max-loss-per-unit` plays the role of `(entry − stop)`.

```
risk_dollars        = E * risk_pct                  # E = live equity from get_account
max_loss_per_unit   = (spread_width - credit) * 100 # credit spreads
                    = debit_paid * 100              # debit spreads / single-leg
units (contracts)   = floor(risk_dollars / max_loss_per_unit)
```

**Per-trade `risk_pct` is conviction-scaled — no fixed ceiling** (so a genuine A+ "big fish" is
not rejected for being chunky on a small account; justified because the loss is hard-capped, unlike
an equity stop that can gap):

| Score | Grade | Per-trade risk (defined max-loss) |
|---|---|---|
| 70–79 | B+ | ~1.5% |
| 80–89 | A | ~3% |
| 90–100 | A+ | up to the full heat headroom (no fixed cap) |

**Account-level backstops — HELD, not loosened (this is the capital-preservation floor):**

- **Portfolio heat cap: 6%** — sum of all open positions' max-loss ≤ 6% of equity.
- **Single-leg sub-leash:** total single-leg open max-loss ≤ ~3% of equity (lower-win-rate,
  theta-bleed bets must not crowd out the steady engine).
- **Manual circuit breakers stand:** −3% day / −6% week / −10% month → HALT (`OPERATING_MANUAL.md §4`).
- **Kelly cap (§3.4)** still applies.

Natural governor: any single trade sized past 3% max-loss will, *if it loses*, trip the daily
halt — so an oversized A+ bet is self-limiting at the account level. Conviction can swing big;
the account cannot be bled to death.

---

## Exit framework (daily 15:30 ET cross-day loop)

Most-urgent-first; an emergency stops further evaluation and acts before end of day.

**Always-on (mechanical, no judgment):**
- **50% max-profit close** (credit spreads) — buy back at half the credit.
- **21-DTE hard close** (credit spreads) — gamma-acceleration zone.
- **2× loss limit** — close at 2× credit collected / debit paid.
- **No expiration holding** — close everything with ≥ 1 day left.

**Profit protection (trailing):**
- Credit spreads: value-stop — close if spread value gives back > 20% of best gain.
- Debit spreads / single-leg: close if value falls below 75% of peak; scale at +100%.

**Thesis integrity:** regime check (EMA20/SMA50), vol-thesis check, short-strike safety
(delta + distance). Regime/vol BROKEN → close. THREATENED + WEAKENING → reduce 50%.

**Single-leg specific:** **IV-crush rule** — moved + IV crushed → take profit (won't reverse);
no-move + IV crushed → cut (thesis failed). **Time stop** if not working by mid-DTE.

**Emergency:** gap-through-strike, SPY regime collapse (Manual catastrophic stop), binary-event-
inside-window, all → immediate defensive exit.

**Roll logic:** only on untested/profitable positions with vol edge intact; never to avoid
recognizing a loss on a breached position.

Exit-reason enum (for the post-mortem agent): `50pct_profit`, `21dte_hard_close`, `trailing_stop`,
`2x_loss_limit`, `gap_through_strike`, `market_regime_collapse`, `binary_event_in_window`,
`strike_threatened_size_reduce`, `thesis_broken_regime`, `thesis_broken_vol`, `iv_crush_no_move`,
`roll_replaced`, `manual_early_close`.

---

## Agent behavior changes

- **Research** (`skills/research/SKILL.md` + new `reference/options-vol-edge-dd.md`): adds the
  options scan path (both engines) and produces scored, ranked candidates.
- **Trader** (`skills/trader/SKILL.md`): adds structure/strike/expiry selection, conviction-scaled
  tier sizing, and multi-leg limit-order placement.
- **Monitor** (`skills/monitor/SKILL.md`): adds the cross-day options exit loop above.
- **Orchestrator** (`SOUL.md`): strategy-router note — runs `options-vol-edge` when equity ≥ gate;
  Bridge tier defers to the (future) equity-swing SOP. (Router is a one-line note in Phase 1; full
  multi-strategy routing is future work.)

---

## The 4-phase program

| Phase | Deliverable | Status |
|---|---|---|
| **1** | Strategy SOP + agent behavior (markdown). **This doc + implementation.** | Designing → implement next |
| **2** | Options MCP tooling: chain fetch, IVR, Greeks, HV20, put-skew, expected-move; multi-leg spread orders; Alpaca adapter methods; cost-capture. IVR/Greeks behind **one interface usable live and in backtest**. | Future (own design + plan) |
| **3** | Paper-trade validation on Alpaca; options journal fields; end-to-end on real market data. | Future |
| **4** | **Options backtest engine** — extend `tools/backtest/` (`start_backtest_v2`/`next_backtest_bar`) with an options simulation adapter (agent-driven bar replay, no look-ahead, multi-leg fills). | Future (own design + plan) |

**Phase 4 open decision (data fidelity — the one genuine risk to a vol-edge backtest):**
real Alpaca historical options data (~1.5 yrs from ~Feb 2024, paid, *real* IV) **vs.** a synthetic
Black-Scholes pricer (free, long history, *modeled* IV — cannot validate the vol edge itself)
**vs.** hybrid (real for recent primary validation, synthetic for longer robustness). Decided in
Phase 4; the Phase 2 IVR/Greeks interface is built to feed either source through one code path
(per CLAUDE.md's "backtest = live code path" rule). **This phase is confirmed in-program and must
not be dropped.**

---

## Configuration notes

- `income.target_per_day_usd: 0` — **cost-coverage gate OFF**. Costs (token + broker fees) are
  **tracked and reported** in EOD review vs. realized P&L, but do not block trading.
- Alpaca options are commission-free with small per-contract regulatory fees, so the dominant
  recurring cost is LLM tokens; the two-tier monitor (tool-only daily checks, LLM only on a
  triggered exit condition) keeps that burn low.

---

## Success criteria (Phase 1)

1. `sops/options-vol-edge/v1.0.0.md` exists, is internally consistent, and defers correctly to
   `OPERATING_MANUAL.md` (no rule looser than the Manual).
2. Every decision the agent must make for a Standard + Directional trade on a $3.5k–$10k account
   has an unambiguous rule — or an explicit "skip if data missing."
3. Both engines (Vol-Edge, Directional) and all v1.0.0 structures are fully specified: scan →
   score → structure/strike → size → enter → manage → exit.
4. Conviction-scaled sizing is wired to the Manual's score/mode/Kelly framework; account-level
   backstops (6% heat, single-leg leash, 3/6/10% breakers) are explicit and intact.
5. `skills/research|trader|monitor` carry the options path; `options-dd.md` marked superseded.
6. `ROADMAP.md` committed with the version ladder and the 4-phase program (incl. the options
   backtest engine).
