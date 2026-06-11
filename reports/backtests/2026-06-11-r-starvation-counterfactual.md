# R-starvation counterfactual — Dec 10-19 2025 skipped washouts (cycle 4)

**Hypothesis R-STARVE-1:** the 5-slot cap suppressed the R engine in run 6;
freeing slots would have added meaningful positive expectancy.
**Method:** mechanical replay (`tools/scripts/replay_r_counterfactual.py`,
signals in `replay_r_signals_dec2025.json`) of all 29 R-eligible scan
signals from run 6 that were never planned (slots full or sequencing slip),
under frozen v1.4.0 R rules. Diagnosis only; upper bound (no R-G7 news veto
applied — some entries would have been DD-vetoed).

## Result: hypothesis largely REFUTED in P&L terms

| | |
|---|---|
| Signals | 29 |
| Filled | **5 (17%)** — 24 no-fills: the 0.5×ATR10 limit never reached |
| Outcomes | ALNY -0.34R (time stop), CORZ +0.20R, NBIS +0.20R, CRDO +0.20R, NBIS(re) +0.20R — all targets |
| Total | **+0.46R** (+0.26R if NBIS same-day reentry disallowed) |

Even with unlimited slots, the Dec washout cluster was worth ~+0.3-0.5R
(~$150-450 at 0.5-1% risk). The entry-limit discipline made 83% of the
"missed" signals free skips — prices bounced before reaching the limit.
**The slot cap's cost in this window was real but small.** Run 4's
slots-exceeded evidence (uptrend, M-engine setups) remains the stronger
argument for a cap increase; this window adds little.

## New structural finding → next cycle's hypothesis (R-RR-1)

Every counterfactual win capped at exactly **+0.20R**: the v1.4.0 low-vol
tier targets max(2.5%, 0.5×ATR10) while the stop risks 2.5×ATR10. When the
ATR term dominates (high-ATR% names), reward/risk is FIXED at 0.2 (low),
0.4 (med), 0.6 (high tier). The R engine risks 1R to make 0.2-0.6R by
construction — it needs 63-83% WR just to break even, leaving no margin.
Candidate fixes to test on the 19 historical R trades (14 prior + 5 here):
- Tighten R stop (e.g., 1.5×ATR10) — washout bounces either work fast or
  fail fast; the 4-session time stop already bounds duration.
- Or scale target with the SAME ATR multiple family as the stop.
NOT shipped — replay first (cycle 5).

## Scenario quantification for the cap decision

- **Cap 8 (3 extra slots):** all 5 fills fit chronologically → +0.46R upper
  bound, ≈ +$230 at half-size (0.5%) in this window.
- **R-slot reservation (cap M at 4 of 5):** would have dropped TWLO (M rank
  3, half-size) — run 6's BEST trade (+1.20R, +$593) — to free one R slot
  worth ≤ +0.26R. **Net NEGATIVE in this window; reservation rejected.**

Suite: 256 tests green (replay script is read-only diagnosis).
