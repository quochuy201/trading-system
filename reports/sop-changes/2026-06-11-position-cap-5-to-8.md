# PROPOSAL — position cap 5 → 8 (OPERATING_MANUAL change, human ratification required)

**Status: PROPOSED 2026-06-11. Not shipped — agents may not modify
OPERATING_MANUAL or risk caps.**

## Ask

Raise max concurrent positions from 5 to 8. Per-trade risk (1% full /
0.5% half) and the 6% portfolio heat ceiling UNCHANGED — the heat ceiling
remains the binding risk control (8 × 1% > 6% is intentionally possible on
paper; heat check still rejects the 7th/8th full-size entry when needed).

## Evidence FOR (two independent windows)

1. **Run 4 (Aug-Oct 2025, 400-name universe, uptrend):** multiple days had
   more SOP-qualified setups than slots; report ranked cap increase as the
   #1 lever toward the $500/wk target (15 trades ≈ $120/wk at cap 5).
2. **Run 6 (Dec 2025):** slots were 5/5 from Dec 3-18; the Dec 10-19 R
   washout cluster (29 signals) was entirely locked out.

## Evidence AGAINST (honest accounting — same windows)

1. **The Dec lockout was cheap.** Counterfactual replay
   (`reports/backtests/2026-06-11-r-starvation-counterfactual.md`): only
   5 of 29 skipped signals would have filled (limit discipline = free
   skips); value ≈ **+0.3-0.5R (~$150-450)** for the whole cluster.
2. **Concentration risk scales with slots.** Run 6's 5-slot book already
   held 3 same-factor names (CEG/PWR/AVGO) through a -2% sector drawdown;
   8 slots makes factor stacking easier. No correlation gate exists yet.
3. Sample for "slots binding" is 2 windows; expectancy/trade at cap 5 is
   +0.07 to +0.13R — more slots multiply a thin edge, and also multiply
   its variance.

## Recommendation

**Approve 5 → 8, gated:** (a) heat ceiling 6% unchanged; (b) max 2 positions
per sector/factor bucket until a proper correlation gate ships (interim rule,
SOP-expressible); (c) revisit after 30 more closed trades. Alternative
considered and REJECTED: R-slot reservation (cap M at 4 of 5) — in run 6 it
would have dropped the window's best trade (TWLO +1.20R) to free a slot
worth ≤ +0.26R.

## Decision

- [ ] APPROVED (date/initials): ______
- [ ] REJECTED — reason: ______
- [ ] DEFERRED until: ______
