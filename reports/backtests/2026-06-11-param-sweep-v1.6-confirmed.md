# Hyperparameter sweep — v1.6.0 CONFIRMED; tuned variants fail holdout (cycle 6)

**Mandate (user, 2026-06-11):** tune on the loaded data (no 2024 load), cap
raised to 10 (ratified), quantitative-first, test quality-vs-quantity.
**Method:** mechanical sweep harness (`tools/scripts/param_sweep.py`) — gates
from the SHARED scanner metrics (`scanner.filters._swing_metrics`, same code
path as live), all strategy params as config data, portfolio sim mirrors
week_runner mechanics (next-open fills, close-based stops, intrabar R
targets, trail/scale-out, heat ceiling 6%, cap 10).
**Protocol:** 36 single-factor configs + 5 profiles ranked on TRAIN
(Aug 25 – Nov 28 2025); 5 combo survivors evaluated ONCE on HOLDOUT
(Dec 1 2025 – Feb 27 2026). NO DD layer — this is the mechanical baseline
the agent filters.

## Headline: the shipped SOP beat all 40 variants out-of-sample

| Config | Train $/wk | Holdout $/wk | Holdout WR | Holdout maxDD |
|---|---|---|---|---|
| **BASE = SOP v1.6.0 (cap 10, 1% risk)** | 894 | **1,323** | 68% | $3,374 |
| COMBO pb40+so1.5+w1.5 (train champion, $1,454/wk) | 1,454 | 278 | 52% | $5,656 |
| COMBO pb40+arm1.5 | 1,242 | 561 | 48% | $5,503 |
| COMBO pb40+scaleout1.5 | 1,320 | 453 | 54% | $5,656 |
| COMBO pb40 alone | 1,222 | 437 | 48% | $5,656 |

The M pullback gate tightened to RSI3<40 — the strongest single factor on
train (+$328/wk, +5pts WR, -$700 DD) — **reverses to -$886/wk on holdout**.
Regime-dependent overfit, caught by the split. Every stacked combo inherits
the damage. **No parameter change ships. v1.6.0 stands, now with a genuine
two-window mechanical validation: +29.6R train / +27.2R holdout, $894-1,323/wk
at cap 10.**

## Quality vs quantity (user question) — quality wins on P&L, decisively

| Profile | Train $/wk | Holdout $/wk | Holdout maxDD | n (holdout) |
|---|---|---|---|---|
| BASE (M long-hold + R short-hold blend) | 894 | **1,323** | $3,374 | 25 |
| QUALITY-strict-long (M-only, 25-sess, strict gates) | 562 | 1,320 | $4,683 | 21 |
| QUANTITY-both-short (5/3-sess holds, tight exits) | 537 | 718 | **$1,938** | 106 |
| QUANTITY-r-heavy (R-only, loose washouts) | 148 | 149 | $2,092 | 57 |

- Few-big-wins is the P&L engine: long-hold M earns ~2× any short-hold
  variant per week. Holding winners 20+ sessions is where the money is.
- Many-small-wins' only virtue is drawdown (~$1.9k vs $3.4k) — it buys
  smoothness at half the income. QUANTITY-r-heavy barely beats zero.
- The CURRENT two-engine blend (quality M + tactical R) outperformed both
  pure profiles on both windows — the design is already the right mix.
- Footnote: risk 0.5% with cap 10 → 41 holdout trades, $1,099/wk, similar
  DD — more, smaller positions is a viable lower-variance frontier point
  (untested middle: 0.75%). Logged, not shipped.

## Other single-factor reads (train, n≈30 — treat as direction only)

- Removing M scale-out: total R 29.6 → 16.4. v1.5.0's scale-out confirmed
  valuable mechanically.
- R RSI3 gate: loosening to <15 flips R expectancy negative (-0.18R avg);
  tightening to <5 starves it (n=2). RSI3<10 (v1.2.0) confirmed optimal.
- m_time_stop {10,15,20,25} → {$633, $168, $894, $426}/wk: nonmonotone =
  variance, not signal. Do not tune time stops from n≈30.
- Tighter M stop (2.0×ATR) inflates R multiples but LOWERS dollar P&L —
  the M stop is not the R-engine situation; 2.5× stands.

## Caveats

- Mechanical sim ≠ agent system: no DD vetoes, no half-sizing, takes every
  gate-passing signal. Prior agent runs realized far less than mechanical
  (~$45/wk) partly from cap 5, runner trail bugs (fixed), and conservative
  half-sizing. The agent layer must justify itself vs this baseline going
  forward — its job is vetoing structural breaks, not shrinking size.
- Holdout was consumed by this selection (once, 5+6 configs). The next
  fresh evidence must come from paper trading or newly arriving data.
- Survivorship: universe selected June 2025; both windows after.

## Shipped with this cycle

- Position cap 5→10 (OPERATING_MANUAL §3.1 + config.yaml, user-ratified).
- `param_sweep.py` harness + metric cache + 5 mechanics tests (suite 261).
- No SOP change — v1.6.0 confirmed. (A v1.7.0 would have been shipped had
  any variant survived the holdout; none did.)
