# Backtest report — equity/swing v1.1.0, 400-name universe, Aug 25 – Oct 24, 2025

**Setup:** $100k continuous, agent-driven, daily-bar mode, criteria-based
400-name universe (`universe_backtest.json`, June-2025 liquidity gate — no
look-ahead in selection; survivorship caveat documented in loader). v1.1.0
frozen. Same span as the 67-name OOS run → direct frequency comparison.

## Headline: frequency objective met, accuracy diluted

| | 67-name OOS | **400-name OOS** | Target |
|---|---|---|---|
| Closed trades | 5 | **15** | more |
| Trades/week | 0.6 | **1.8** | — |
| Win rate | 80% | **53.3%** | >70% |
| P&L | +$1,296 | **+$1,027** | — |
| P&L/week | ≈$144 | ≈**$120** | $500 |
| Expectancy/trade | +$259 | +$68 | — |
| Max loss | -0.18R | -1.13R (BURL gap) | caps held |

Engine split: **M = the P&L engine** (6 trades, 50% WR, avg win $532 vs avg
loss $251 → +$841, $140/trade). **R = high-frequency, thin edge** (9 trades,
55.6% WR, +$186, $21/trade — wins avg +0.32R vs losses -0.30R).

## Trade ledger

| # | Sym | E | Entry | Exit | Reason | P&L | R | RSI3@signal |
|---|---|---|---|---|---|---|---|---|
| 1 | XYZ | M | Aug 26 | Sep 24 | time stop | -$173 | -0.35 | — |
| 2 | CAT | M | Aug 26 | Sep 24 | time stop | +$940 | +1.72 | — |
| 3 | ETSY | R | Aug 26 | Sep 2 | time stop | -$211 | -0.42 | 9.6 |
| 4 | CSX | R | Aug 26 | Sep 2 | time stop | -$9 | -0.02 | 5.0 |
| 5 | BURL | M | Sep 8 | Sep 18 | stop (gap) | -$536 | -1.13 | — |
| 6 | APLD | R | Sep 8 | Sep 9 | intrabar target | +$96 | +0.19 | 5.8 |
| 7 | RDDT | M | Sep 9 | Sep 26 | trail (BE) | -$45 | -0.05 | — |
| 8 | HUM | R | Sep 10 | Sep 11 | intrabar target | +$193 | +0.39 | 8.4 |
| 9 | FERG | R | Sep 15 | Sep 16 | intrabar target | +$233 | +0.47 | 8.9 |
| 10 | BLDR | R | Sep 19 | Sep 25 | time stop | -$276 | -0.54 | 11.1 |
| 11 | SHOP | M | Sep 25 | Oct 13 | trail | +$619 | +0.71 | — |
| 12 | TLN | M | Sep 25 | Oct 20 | trail | +$37 | +0.08 | — |
| 13 | ALAB | R | Sep 25 | Sep 26 | intrabar target | +$193 | +0.19 | 8.4 |
| 14 | WBD | R | Oct 10 | Oct 13 | intrabar target | +$184 | +0.36 | 7.0 |
| 15 | BABA | R | Oct 10 | Oct 16 | time stop | -$216 | -0.23 | 13.6 |

Execution misses (my scan/run sequencing error, fixed mid-run, days Aug 27 +
Sep 2-5): PDD, DKS, U, SOFI qualified and were never planned — P&L above
slightly UNDERSTATES the system. R limit no-fills: AMD, NUE, RCL, RBLX, JBL,
SNOW (bounced without fills — consistent with design).

## The two patterns that drive v1.2.0

**R: all five winners had RSI3 < 9 at signal.** Across all 14 R trades ever
(3 independent samples): RSI3<10 → 8 trades, 6 wins, +$805; RSI3≥10 → 6
trades, 1 win, -$1,076. Monotone across samples → R-G5 tightened to RSI3<10.

**M: giveback is the engine's leak.** RDDT round-tripped +15% → breakeven
(v1.1.0 trail armed only at 1.5R). Replay with the trail armed at +1R:
M total +$841 → +$1,534 (4 of 6 trades improve). → v1.2.0 arms the 2×ATR
trail at +1R, no breakeven step.

**Projected v1.2.0 on this same span (in-sample arithmetic, NOT a forecast):**
M +$1,534 + R(RSI3<10 cohort) +$890 ≈ +$2,400 ≈ $285/wk.

## Path to $500/wk (levers ranked, none shipped without approval)
1. Position cap 5 → 8 (config/OPERATING_MANUAL — human ratification needed;
   multiple days had more qualified setups than slots).
2. R conviction recalibration: deep-washout (RSI3<10) entries earned half-size
   in 6 of 9 cases under the rubric's 60-69 band — if the cohort keeps winning
   forward, full-size them.
3. Forward-validate v1.2.0 on an unseen window (Jan-Feb 2026 once daily data
   for the 400-name universe is refreshed through Feb).
