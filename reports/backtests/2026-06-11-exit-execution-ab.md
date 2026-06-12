# Exit-execution A/B — touch vs close-confirm, swing stops, R trail (cycle 7)

**Motivation (user, 2026-06-11):** next-open exits suffer overnight gaps;
proposal = touch-based intraday exits (both engines), hybrid swing-low/ATR
stops, R trail backstop. **Method:** sweep harness extended with
`exec_mode` / `exec_mode_m|r` (touch = resting orders, intrabar fills,
pessimistic stop-before-target ordering), `stop_basis: hybrid_swing`
(stop = max(last 2-bar-fractal low, fill − k×ATR)), and an R trail
(arm at +1×ATR intraday high, width 1.0-1.5×ATR). A/B on TRAIN
(Aug-Nov 2025) and HOLDOUT (Dec 2025-Feb 2026), daily bars (intrabar
approximated by H/L; same-bar ambiguity resolved against the strategy).

## Results ($ per week / holdout M avg R)

| Config | Train | Holdout | Holdout M avg R |
|---|---|---|---|
| **A: current v1.6.0 (close-confirm + ATR)** | **894** | **1,323** | **+0.746** |
| B: touch, both engines | 914 | 804 | +0.283 |
| C: B + hybrid swing stops | 804 | 499 | +0.006 |
| D: C + R trail 1.5×ATR | 725 | 499 | +0.006 |
| E: C + R trail 1.0×ATR | 723 | 449 | +0.006 |
| F: touch for R only | 879 | 1,323 | +0.746 |
| G: F + hybrid swing stops | 655 | 1,235 | +0.609 |
| H: F + R trail 1.5×ATR | 800 (R avg -0.07) | 1,323 | +0.746 |

## Findings

1. **Touch execution destroys Engine M** — holdout M expectancy +0.746 →
   +0.283 (touch) → +0.006 (with swing stops). Mechanism: M's 20-session
   winners routinely spike through ATR/structure levels intraday and recover
   by the close; close-confirmation was load-bearing, not lag. This
   re-confirms (third independent time) that M must not be exited on
   intraday noise — same failure family as the rejected stagnation exit,
   early trail arming, and swing-low trail.
2. **The gap cost is real but small and already priced in.** The validated
   $894/1,323 per week INCLUDES every next-open gap (e.g. SOFI's extra
   -0.15R). Eliminating gaps via touch costs 2-6× more in wick-outs than
   it saves in gaps, in both windows.
3. **Touch for R alone is a wash** (F ≈ A): with the v1.6.0 1.5×ATR stop,
   R stops rarely trigger before target/time-stop, so execution style
   barely matters. No gain, no harm — not worth the live complexity.
4. **Hybrid swing-low stops hurt both engines** (tighter stops → more
   stop-outs; the structure level is exactly where washouts wick).
   **R trail backstop hurts R** (clips bounces before target;
   train R avg +0.22 → -0.07).
5. Caveat: daily-bar touch simulation is an approximation (no intraday
   sequencing; we resolved ambiguity pessimistically). The M wick-out
   effect is large enough (-62% holdout P&L) that ordering nuances cannot
   reverse it. Hourly bars exist only for the 67-name universe
   (Oct 2025-Feb 2026) if a higher-fidelity check is ever wanted.

## Decision

**RECOMMEND: keep v1.6.0 exits (close-confirm, ATR stops, no R trail).**
Recorded as tested-and-rejected: touch execution for M, hybrid swing-low
initial stops, R trail backstop. Per the user-control rule, the final call
on shipping any variant despite this data belongs to the human — presented,
not shipped.

Suite: 261 tests green (harness extension covered by existing mechanics tests).

## Addendum — progressive-width trail ("dynamic stop that scales with profit")

User-requested follow-up: trail arms EARLY but starts wide and tightens as
peak gain grows (tier set by best gain achieved; protection never loosens).
`m_trail_tiers` added to the harness. Four tier schedules tested:

| Config (arm/width tiers) | Train $/wk | Holdout $/wk | Holdout M avg R |
|---|---|---|---|
| **A: control v1.6.0** (arm +1R, 2×ATR flat) | 894 | **1,323** | +0.746 |
| P2 gentle (.5R/2.5 → 1R/2 → 2R/1.5) | 953 | 1,078 | +0.561 |
| P1 standard (.5R/3 → 1R/2 → 2R/1) | 584 | 867 | +0.353 |
| P3 early-arm (.3R/3 → …) | 584 | 867 | +0.353 |
| P4 wide-long (.5R/3 → 1.5R/2) | 638 | 625 | +0.385 |

- No schedule beats control on both windows (pre-agreed ship criterion).
  The gentlest (P2) edges train (+$59/wk, DD -$1,100) but gives up
  -$245/wk on holdout. Aggressive schedules lose 30-50% everywhere.
- Mechanism unchanged from every prior protect-early test: early/tight
  protection trades small saved givebacks for amputated runners
  (holdout M expectancy -25% to -53%).
- One honest observation FOR the idea: profit protection consistently buys
  a smoother equity curve (P2 train DD $3.9k vs $5.0k) at the cost of
  income — same trade-off as quantity-vs-quality. If smoothness ever
  matters more than P&L (e.g., living off withdrawals), P2 is the
  best-tested smoothness candidate.
- **REJECTED for P&L purposes; recorded here so it isn't re-invented.**
