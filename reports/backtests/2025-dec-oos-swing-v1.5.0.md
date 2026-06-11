# Backtest report — equity/swing v1.5.0 OUT-OF-SAMPLE, Dec 1-31 2025 (run 6)

**Setup:** $100k, agent-driven, daily-bar mode, 400-name universe, SOP v1.5.0
FROZEN before the window was touched (Dec 2025 never used in any calibration).
Entries Dec 1-31 only; open positions managed into January to natural exits.
First run with the plan-parameterized trail (v1.2.0 profile actually executed)
and the v1.5.0 scale-out. State: `tools/backtest_week_state.json`
(run-5 state preserved at `tools/backtest_state_run5_windowBext.json`).

## Trade ledger (all Engine M — see "R starvation" below)

| Sym | Size | Fill | Exit | Reason | R | P&L | DD note |
|---|---|---|---|---|---|---|---|
| CEG | half | Dec 1 @ 359.51 | Dec 30 | time stop | -0.04 | -$19 | score 65, rsi3 78 chasey |
| IQV | full | Dec 2 @ 228.27 | Dec 31 | time stop | -0.09 | -$52 | score 75, textbook pullback |
| PWR | full | Dec 2 @ 458.25 | Dec 31 | time stop | -0.66 | -$626 | score 70; AI-power selloff |
| TWLO | half | Dec 2 @ 129.35 | Dec 31 | time stop | **+1.20** | +$593 | score 63 (chasey — best trade) |
| AVGO | half | Dec 3 @ 380.19 | Dec 18 | **stop** | -0.91 | -$444 | score 62; earnings Dec 11 flagged at entry, risk materialized |
| ROST | full | Dec 22 @ 183.60 | Jan 22 | time stop | **+1.26** | +$489 | score 70, clean pullback |

**Totals: 6 trades, 2W/4L (33% WR), +0.76R total, +0.127R/trade, -$58 net**
(~1.4 trades/wk). Expectancy positive at 33% WR — W/L size ratio carried it
(winners avg +1.23R, losers avg -0.43R). Dollar P&L flat because the largest
loss (PWR) was full-size and TWLO (best R) was half-size.

## Findings

1. **R starvation = the window's story.** Zero R trades. The mid-Dec AI-infra
   washout (Dec 10-19) produced 10+ R-qualified candidates (FERG rsi3 3.0,
   CRDO 3.4-7.3, AMD 8.3-8.6, ALNY, INSM, VRT, CLS, PSX, FUTU, HOOD…) and
   every one was unavailable: slots full (5-cap) Dec 4-17, then a scan/run
   sequencing miss Dec 15-19 burned the only open slot days. Strongest
   evidence yet for the pending **position-cap 5→8 human decision** — the
   washout cluster arrived exactly when M slots were stuffed.
2. **Sector concentration bit.** 3 of 5 early entries (CEG, PWR, AVGO) were
   the same AI-power/semi factor; the Dec 12-17 complex selloff hit all
   three simultaneously (book drawdown ~-1.9% peak). No correlation gate
   exists in the SOP or risk-manager skill. Candidate hypothesis for a
   future cycle — n=1 window, do NOT ship from this alone.
3. **Conviction scoring inverted on this sample (n=6, noise-level):** the two
   half-size "chasey" entries went +1.20R/-0.91R; the score-70+ "clean"
   entries went -0.09/-0.66/+1.26. No action — log and watch.
4. **Event protocol executed properly this run** (vs run 5's failure): 7
   large_drop events evaluated, all HOLD (sector-wide moves, no thesis
   break, stops intact) — AVGO's eventual stop was the close-based rule
   doing its job, not a panic exit.
5. **v1.5.0 scale-out: never fired** (no close reached +2R). Confirmed
   zero-cost OOS; upside evidence remains n=1 (STX replay). Trail armed on
   TWLO and ROST, never breached — time stops captured 89-96% of peak gain
   on both winners (ROST peaked +5.6%, exited +5.0%).
6. **Process slip (logged, not re-decided):** Dec 15-19 scans were batched
   with run-days; with a slot open Dec 18-19, AMD/CRDO/VRT R washouts were
   never planned. Same class of miss as run 4. Mitigation now mechanical:
   runner rejects duplicate run-days, but cannot force scan-before-run —
   that remains agent discipline.

## Verdict vs targets

- WR 33% vs >70% target: missed. Expectancy +0.13R/trade: positive, OOS,
  with honest event handling. P&L ≈ flat in a window where SPY chopped
  through a -2% mid-month AI-complex drawdown.
- v1.5.0 neither helped nor hurt (scale-out unexercised) — it remains
  validated-as-harmless, pending a +2R runner forward.
- The binding constraints are unchanged and now doubly evidenced:
  **frequency (position cap + R starvation), not exit quality.**

## Next-cycle candidates (in evidence order)

1. Position cap 5→8 — HUMAN DECISION, propose with this window + run 4 data.
2. R-engine slot reservation (e.g., cap M at 4 of 5 slots) — SOP-expressible,
   testable by replay of this window's skipped washouts.
3. Sector/factor concentration gate — needs more than one window of evidence.
