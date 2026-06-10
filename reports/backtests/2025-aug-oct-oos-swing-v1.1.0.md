# Backtest report — equity/swing v1.1.0 OUT-OF-SAMPLE, Aug 25 – Oct 24, 2025

**Setup:** $100k, agent-driven, daily-bar mode (`week_runner.py` upgraded:
daily monitoring, fill-relative stops, intrabar targets). v1.1.0 thresholds
FROZEN before these windows were touched (calibrated only on Oct 27 – Nov 26).
Same fixed decision procedure as prior runs.

## Windows & results

| Window | Tape | Trades | Wins | WR | P&L | Avg R |
|---|---|---|---|---|---|---|
| A: Aug 25 – Sep 19 (+mgmt to Sep 24) | uptrend, extended | 1 | 1 | 100% | +$965 | +1.80 |
| B: Sep 22 – Oct 17 (+mgmt to Oct 24) | uptrend → tariff shock → chop | 4 | 3 | 75% | +$332 | +0.17 |
| **OOS combined** | | **5** | **4** | **80%** | **+$1,296** | **+0.49** |

Trade ledger:

| Window | Symbol | Eng | Entry | Exit | Reason | P&L | R |
|---|---|---|---|---|---|---|---|
| A | CAT | M | Aug 26 @ 431.22 | Sep 24 (time stop, 20 sess) | rode pullback entry to +9.4% | +$965 | +1.80 |
| B | GOOGL | M | Sep 26 @ 247.34 | Oct 23 (time stop) | +1.8% grind | +$215 | +0.40 |
| B | TSLA | M | Sep 26 @ 428.50 | Oct 23 (time stop) | chop, never trended | -$178 | -0.18 |
| B | PLTR | M | Sep 29 @ 179.79 | Oct 24 (time stop) | flat hold | +$168 | +0.18 |
| B | COIN | R | Oct 17 @ 318.62 (ATR-scaled limit) | Oct 20 (**intrabar +4% target**) | 1-session bounce capture | +$127 | +0.26 |

## What v1.1.0's new gates did out-of-sample

- **M-G1b extension throttle** blocked UNH (Sep 22, ext 3.58), LRCX/ORCL
  (Oct 10, ext 3.13), and every Sep 12–19 setup (ext 3.2–3.7). None of the
  blocked names produced a missed >1R win in-window — throttle cost ≈ 0,
  avoided initiating into the mid-Sep extension.
- **M-G7b pullback gate** produced CAT/GOOGL/PLTR-style entries (buy leaders
  on RSI3 dips) — the engine's 3 best M results.
- **Stress gate** (tr_atr > 2) correctly sat out Oct 13–15 (tariff-shock
  whipsaw, tr_atr 2.0–4.6) — the exact tape that mauled run 2.
- **Gap rule** refused AVGO's +16.3% earnings gap (Sep 5) — no chase.
- **ATR-scaled R limit + intrabar target**: COIN filled 2.93% below close and
  banked +4% in one session — both v1.1.0 mechanics changes paid as designed.

## Cumulative evidence, all runs

| Run | Window | SOP | Sample | Trades | WR | P&L/wk |
|---|---|---|---|---|---|---|
| 1 | Nov 17–21 | v1.0.0 | in-sample (diagnostic) | 3 | 33% | -$389 |
| 2 | Oct 27 – Nov 26 | v1.0.0 | calibration | 6 | 0% | ≈ -$700 |
| 3A | Aug 25 – Sep 24 | v1.1.0 | **out-of-sample** | 1 | 100% | ≈ +$214 |
| 3B | Sep 22 – Oct 24 | v1.1.0 | **out-of-sample** | 4 | 75% | ≈ +$74 |

## Verdict vs targets

- **Win rate: 80% OOS (4/5)** — above the 70% target, but n=5; the honest
  claim is "v1.1.0 stopped doing the thing that lost money and is now
  positive-expectancy on unseen data," not "80% is the true rate."
- **P&L: ≈ +$144/wk OOS vs $500/wk target.** The constraint is now FREQUENCY,
  not accuracy: the strict gates produce ~0.6 trades/week on a 67-name
  universe. Discipline is not the lever to pull — opportunity count is.

## Next lever (no SOP changes warranted by this data)

**Universe expansion** (criteria-based, per user directive): the gates are
selective by design; more qualifying names/day is the safe path to frequency.
Loader change: scan a larger liquid universe (e.g., S&P 500 ∩ dollar-volume
≥ $50M, ~300-400 names). Risk-per-trade stays 1% until a larger sample
justifies Kelly-based increases. Short engine remains deferred (user
decision 2026-06-10); regime gates continue to sit out hostile tape.
