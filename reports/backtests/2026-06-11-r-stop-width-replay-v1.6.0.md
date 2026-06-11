# R stop-width replay — hypothesis R-RR-1 → SOP v1.6.0 (cycle 5)

**Method:** mechanical replay (`tools/scripts/replay_r_counterfactual.py`,
signals in `replay_r_signals_all.json`, inputs derived from price_data with
no look-ahead). v1.4.0 target tiers held fixed; stop width swept. At
constant 1% risk, avg R is the dollar comparison. **Replay = diagnosis.**

## Hypothesis (R-RR-1, from cycle 4)

The R engine risks 2.5×ATR10 to earn regime-tier targets of 0.5-1.5×ATR10 —
reward/risk structurally 0.2-0.6. A tighter stop should raise expectancy
unless washout winners routinely close below it before bouncing.

## Sample

All 15 fillable R signals ever: Aug-Oct cohort n=10 (run-4 ledger: ETSY,
CSX, APLD, HUM, FERG, BLDR, ALAB, WBD, BABA + COIN from run 3B) and Dec
cohort n=5 (cycle-4 counterfactual fills). Cohorts kept separate; run-1
(v1.0.0 flat-3% limit era) excluded — different entry mechanics.

## Results

| Stop | ALL (n=15) total R / avg | Aug-Oct avg | Dec avg | WR | Stop-outs |
|---|---|---|---|---|---|
| 2.5× | +2.06 / +0.137 | +0.160 | +0.092 | 73% | 0 |
| 2.0× | +2.60 / +0.173 | +0.202 | +0.116 | 73% | 0 |
| **1.5×** | **+3.58 / +0.239** | **+0.282** | **+0.152** | 73% | 1 (BABA -0.24 vs -0.23) |
| 1.25× | +4.30 / +0.287 | +0.338 | +0.184 | 73% | 1 |
| 1.0× | +5.37 / +0.358 | +0.422 | +0.230 | 73% | 2 (BLDR **-1.36**) |

Mechanism: winners never close 1.5×ATR below the washout fill before
bouncing (entry is already 0.5×ATR below the signal close); losers die by
time stop regardless. Tightening shrinks the R denominator → ~1.67× shares
per 1% risk → target exits earn 0.33-1.00R instead of 0.20-0.60R.

## Decision

**SHIP 1.5×ATR10 (SOP v1.6.0)** — improvement holds in both cohorts
independently (+76%/+65%), WR untouched, one grazed trade is a wash.
**REJECT 1.0×/1.25×** — monotone gains only reflect zero adverse paths
between -1.0 and -2.5 ATR in n=15; BLDR at 1.0× (-1.36R) shows the failure
mode. Tightest-tested = curve fit. Recorded in the SOP.

`FORWARD-VALIDATION-PENDING` — Jan-Feb 2026 frozen window now validates
v1.4.0 + v1.5.0 + v1.6.0 together.

## Stop-rule check (loop protocol)

Cycle 4: refutation, no ship. Cycle 5: shipped with two-cohort replay
support. Not two consecutive non-improvements — loop continues, but the
next step must be FORWARD VALIDATION, not more replay tuning: three
consecutive exit-parameter changes (v1.4-v1.6) are now stacked on the same
historical windows. Further calibration on Aug-Dec 2025 data is overfitting
risk by construction.

Suite: 256 tests green.
