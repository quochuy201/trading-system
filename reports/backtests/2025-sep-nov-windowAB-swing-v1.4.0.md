# Backtest report — swing v1.4.0, windows A + B-extended (run 5, DEGRADED)

**Written 2026-06-11, post-hoc.** The 2026-06-10 overnight `/iterate` session ran
these windows but degraded mid-run (provider rate limit) and never wrote this
report. Reconstructed from `tools/backtest_state_windowA.json`,
`tools/backtest_state_windowB67.json`, `tools/backtest_week_state.json`, and
the decisions DB. **This run is NOT a valid OOS data point for v1.4.0** — see
Process integrity below.

## Windows

| Window | Span | Role | Trades | P&L |
|---|---|---|---|---|
| A | 2025-08-26 → 2025-09-24 | OOS (overlaps run-3 window 1) | 1 | **+$965** |
| B | 2025-09-22 → 2025-10-24 | OOS-ish (overlaps run-4 span) | 4 | +$332 |
| B-ext | 2025-10-24 → 2025-11-25 | continuation of B state | 2 | **-$432** |
| Jan-2026 | 2026-01-04 → 2026-01-05 | abandoned after 2 days | 0 | — |

Combined B+B-ext final equity: $99,899.84 (**-$100 over ~9 weeks**).

## Trades (window B + extension)

| Symbol | Engine | Fill date | Exit reason | R | P&L | DD logged? |
|---|---|---|---|---|---|---|
| COIN | R | 2025-10-17 | take_profit | +0.26 | +$127 | yes (score 75, DEFENSIVE half) |
| GOOGL | M | 2025-09-26 | time_stop_next_open | +0.40 | +$215 | yes |
| TSLA | M | 2025-09-26 | time_stop_next_open | -0.18 | -$178 | yes |
| PLTR | M | 2025-09-29 | time_stop_next_open | +0.18 | +$168 | yes |
| SOFI | M | 2025-10-29 | stop_loss | **-1.15** | **-$1,150** | **NO — empty entry_reason** |
| STX | M | 2025-10-28 | time_stop_next_open | +0.73 | +$718 | **NO — empty entry_reason** |

Window A: CAT M +1.8R +$965 (full DD logged, pullback-gate entry).

Blended: 5W/2L (71% WR) but **expectancy ≈ 0** — avg winner +0.39R (ex-CAT)
vs one -1.15R loser. In-sample projection was ~$570/wk; realized ≈ -$11/wk on B.

## Findings

1. **Process breakdown decided the P&L.** The last two entries (STX, SOFI)
   carry no entry reasoning; `backtest_decisions` has 0 rows for all 5
   registered runs. SOFI was entered 2025-10-29 (day after its Oct-28
   earnings report) and fired two `large_drop` events (-4.6%, -9.8%) that
   never received the required LLM hold-vs-exit evaluation. The un-vetted
   pair nets -$432 and includes the run's only full-R loss.
2. **M-engine sub-1R capture leak, now visible OOS.** 5 of 6 exits were
   20-session time stops at sub-1R. TSLA peaked +7.2% (+0.62R) on session 4
   and exited -0.18R. The trail arms at +1R = 2.5×ATR10 (≈11-13% of price) —
   rarely reached inside the time-stop window, so M has no profit capture
   below it.
3. **High-ATR winners leak even with the trail.** STX peaked +28.2% (+2.17R)
   and captured +0.73R. Verified against price data: STX ATR10 ≈ $18 (~7.5%
   of price), so a correctly-armed 2×ATR10 trail sits ~15% below peak —
   exit ≈ $238-255 vs the time stop's $251. The trail rule does not protect
   winners in high-ATR names; trail width needs to be conditioned on ATR%
   or regime, not a flat ATR multiple.
4. **Risk caps held.** Worst loss -1.15R (stop honored at next open);
   exposure and sizing within limits throughout.

## Process integrity (why this is not a valid v1.4.0 OOS point)

- Agent DD absent for 2 of 6 entries → "LLM decides, Python executes" contract
  violated (CLAUDE.md backtest rule 5).
- `large_drop` events not evaluated (rule 6).
- No decisions persisted, no report written, PROJECT_STATUS not updated.
- Session hit a provider rate limit mid-run and continued mechanically.

**Action shipped with this report:** `week_runner.py plan` now refuses plans
with an empty reason, so a degraded session can no longer enter un-vetted
positions silently.

## Verdict

- v1.4.0's regime-adjusted R target remains `FORWARD-VALIDATION-PENDING` —
  this run exercised it on exactly one R trade (COIN, +0.26R take-profit).
- Negative result recorded plainly: B+B-ext ≈ flat-to-negative under degraded
  process. Findings 2-3 motivate the next exit-round hypothesis (M sub-1R
  capture / ATR%-conditioned trail).
- Jan-Feb 2026 forward validation still outstanding.
