# Exit-variant replay — Engine M capture hypothesis → SOP v1.5.0

**Date:** 2026-06-11 · **Method:** mechanical replay (`tools/scripts/replay_exits.py`,
variants in `replay_exit_variants.json`, trades in `replay_m_trades.json`).
**This is in-sample replay arithmetic — diagnosis, never a forecast.**

## Hypothesis (M-CAPTURE-1)

M winners are clipped by the 20-session time stop before the +1R trail arms
(run 5: GOOGL +0.40R, PLTR +0.18R, TSLA -0.18R after a +0.62R peak; STX
captured +0.73R of a +2.17R peak). An ATR-relative capture mechanism below
or at the trail should raise M expectancy without dumping slow starters.

## Sample

All 11 unique closed M trades across runs 3-5 (runs 3B and 5 window B are
the SAME trades — not double-counted):
- **CAL** (calibration, runs 3+4): CAT, XYZ, BURL, RDDT, SHOP, TLN, GOOGL,
  TSLA, PLTR.
- **CHECK** (run-5-only): STX, SOFI.

Fills: exact where recorded; otherwise next-open + slippage (runner rule).
ATR10 computed from the 10 sessions strictly before fill (no look-ahead).

## Results (R totals)

| Variant | CAL n=9 | CHECK n=2 | Verdict |
|---|---|---|---|
| B0 v1.2.0 baseline (trail arm +1R, 2×ATR10) | **+3.24** | -0.32 | reference |
| C1 early arm at +1×ATR10 gain | +2.19 | -0.32 | **REJECT** |
| C2 giveback-50 after +1×ATR10 peak | +2.44 | -0.32 | **REJECT** |
| C3 swing-low structure stop after arm | +2.19 | -0.32 | **REJECT** |
| C4 scale-out 50% at +2R | +3.24 | **+0.26** | **SHIP** (v1.5.0) |

- C1-C3 all fail the same way: they clip slow grinders (PLTR +0.52R → -0.04R,
  TSLA +0.38R → -0.11R) — the stagnation-exit failure mode again. The
  hypothesis's "earlier capture" half is **rejected**.
- C4 is Pareto-dominant on this sample: 10 of 11 trades never reach +2R
  (identical outcome); STX +0.81R → +1.39R. Upside evidence is **n=1** —
  shipped because sample downside is zero and it targets the documented
  high-ATR giveback leak. `FORWARD-VALIDATION-PENDING`.
- SOFI -1.13R under every variant: exit rules cannot save a bad entry
  (fixed separately by the plan-reason guard).

## Runner-fidelity findings (mechanics, fixed this cycle)

1. **The runner still executed the v1.1.0 trail** (BE @+1R, arm @+1.5R,
   hardcoded) — v1.2.0+'s "trail armed at +1R, no BE" never ran in runs 3-5.
   Recorded M exits in those runs reflect v1.1.0 trailing. Fixed: trail
   arm/width/BE + scale-out are now plan parameters (SOP-owned numbers);
   plans with `--trail` but no thresholds are rejected.
2. **run-day was not idempotent**: run 5 executed 2025-10-17 twice,
   double-counting `sessions_held` and firing time stops a session early
   (GOOGL/TSLA exits 10-23 vs correct 10-24). Fixed: duplicate dates rejected.
3. Replay B0 vs run-5 actuals reconciles once both bugs are accounted for.

## Calibration/validation separation

CAL window = Aug-Nov 2025 (already used to tune v1.2.0-v1.4.0; this cycle
re-uses it only to REJECT candidates). The shipped C4 must be validated
agent-driven on an untouched window — **Dec 2025** is reserved for that
(Jan-Feb 2026 stays frozen for the full forward validation).

Suite: 256 tests green.
