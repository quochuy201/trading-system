# Backtest report — equity/swing v1.0.0, week of Nov 17–21, 2025

**Setup:** $100k, agent-driven (research/monitor skills + SOP applied by LLM day
by day; Python mechanics only — `tools/scripts/week_runner.py`). Universe: 67
liquid names. Week chosen as most volatile in cached range (SPY -1.6%, chop,
NVDA earnings Wed, violent reversal Thu). Social layer: neutral (no history).
News access: none — R-G7 diagnosis done from cross-sectional price data only.

## Results vs targets

| Metric | Result | Target | Book reference |
|---|---|---|---|
| Trades closed | 3 (all Engine R) | — | Sys-3 trades constantly |
| Win rate | 33% (1/3) | >70% | Sys-3 long-run: ~63% |
| P&L | **-$389** | +$500/wk | — |
| Avg R | -0.18R | — | — |
| Worst loss | -0.42R (PLTR) | -1R cap | time stop cut it |

Trades: PLTR -$208 (-0.42R, time stop), SHOP +$77 (+0.16R, time stop),
AMD -$258 (-0.27R, time stop at mark — filled into the Nov 20 NVDA reversal).

**n=3 is statistically meaningless for WR/expectancy. The value of the week is
the GATE AUDIT and counterfactuals below.** Engine M was never eligible (no
uptrend all week) — half the system was dark by design; this week cannot
validate M at all.

## Gate audit — what the gatekeeper did

| Day | Regime → eligibility | Notes |
|---|---|---|
| Mon 11/17 | tr_atr 1.72 → DEFENSIVE, half-risk; R-ONLY | 5 R candidates; entered top-2 by drop_3d (PLTR, SHOP); TSLA RANKED_OUT (3rd correlated high-beta) |
| Tue 11/18 | DEFENSIVE; R-ONLY | semis skipped (NVDA binary Wed); SNOW limit no-fill |
| Wed 11/19 | NORMAL (tr_atr 1.29); R-ONLY | AMZN scored 65 → half-size per rubric; limit no-fill |
| Thu 11/20 | NORMAL; R-ONLY | NVDA binary resolved → AMD entered rank-1, filled INTO the reversal; MU RANKED_OUT |
| Fri 11/21 | **tr_atr 2.97 → STRESS ROW: ALL OFF** | no entries despite deepest washouts of week |

Limit-entry discipline: 3 of 6 submitted orders never filled (SNOW, AMZN, and
TSLA wouldn't have either) — exactly the book's expectation ("place ten orders,
execute three or four"). No-fill ≠ failure; it's the entry edge.

## Counterfactuals (mechanically computed, no hindsight in entries)

| Skipped setup | Why skipped | Would have... | Lesson strength |
|---|---|---|---|
| INTC 11/18 (rsi3 7.5) | my NVDA-sector-binary discipline | filled 33.68, **hit +4% next day** | weak-moderate (n=1) |
| MRVL 11/21 (drop 8.2) | STRESS gate (tr_atr 2.97) | filled 74.40, **hit +4% same day**, ran +18% | weak — stress gate is tail insurance, one obs can't price it |
| TSLA 11/17 | RANKED_OUT (correlation) | limit never filled — skip was FREE | validation |
| MU 11/24 | (out of week) | limit never filled | — |
| SHOP intrabar | close-based +4% target | Wed close +3.11% (high 147.01 vs 147.33 target — 32¢ short); Thu high 154.40 **touched intrabar target** → +4% instead of +2.36% exit | moderate (also mechanics-realism: a resting limit IS how live works) |
| PLTR intrabar | same | Thu high 174.39 vs 175.59 — never touched; no rescue | — |

## Iteration hypotheses (NOT shipped — n=3 calibration would be curve-fitting)

- **H1 (low risk, mechanics):** R profit-taking = resting intrabar limit at +4%
  instead of close-then-next-open. Matches live execution reality. Evidence:
  SHOP +$53 better; PLTR/AMD unchanged. Candidate for SOP v1.1.0.
- **H2 (signal, needs multi-week):** require deeper washout — rsi3 < 15 at
  signal (keep drop_3d ≥ 6). Evidence: worst trade PLTR entered at rsi3 29.6;
  the week's flat/winning entries+counterfactuals were all rsi3 ≤ 15.
- **H3 (judgment rule):** narrow the sector-binary skip to names with direct
  revenue linkage to the reporter (kept us out of INTC's win, but also out of
  pre-print AMD/LRCX exposure — mixed evidence, defer).
- **H4:** stress gate (tr_atr > 2) cost MRVL's +18% run but is the tail-risk
  insurance the book demands. Keep; re-examine only with months of data.

## Verdict & next step

The gatekeeper, ranking, sizing ladder (DEFENSIVE→NORMAL→HALTED), time stops,
and limit discipline all executed exactly per SOP — **the machinery is
validated**. The edge is NOT yet validated: one choppy week, R-only, 3 trades,
-$389. Targets (70% WR, $500/wk) unmeasurable at this sample size.

**Next:** extend to 4 weeks (Oct 27 – Nov 28, 2025: uptrend → correction →
recovery) so Engine M gets eligible days and R reaches ~12–20 trades; test H1/H2
across that sample before any SOP version bump.
