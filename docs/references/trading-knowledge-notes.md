# Trading knowledge notes (ported from Cowork session memory, 2026-06-10)

Cross-platform knowledge that previously lived only in the Cowork assistant's
memory. Kept terse — these inform skill/SOP design judgment, not rules.

## Mental models that govern this system's design (Tharp, *Trade Your Way…*)

- **The entry signal is the LEAST important part of a system.** Position
  sizing and exits dominate outcomes. (Borne out here: v1.2.0/v1.3.0 exit
  changes moved P&L far more than any entry tweak.)
- **Expectancy per R is the metric, not win rate.** A 45% WR system with
  2.5:1 W/L beats a 70% WR system with 0.4:1. Engine M is judged this way
  on purpose; chasing the blended-WR target alone invites bad design.
- **Position sizing is the master variable** for both growth and ruin-risk.
  Hence quarter-Kelly caps and the 6% heat ceiling in OPERATING_MANUAL.
- **Drawdown asymmetry:** -50% needs +100% to recover. Protect the downside
  first; the stress gate and mode ladder exist for this.
- Cognitive traps to watch in agent decision logs: lotto bias (overweighting
  entries), gambler's fallacy (doubling after losses), taking conservative
  profits while letting losses run (the exact inverse of correct behavior).

## Source-quality map (from r/stocks curated guide + own reading)

- **Load-bearing for this system:** Bensdorp *Automated Stock Trading Systems*
  (the swing SOP's parent — 12 ingredients, Sys-1/3/5 adaptations, the
  non-correlation argument that motivates Engine S someday); Tharp (above).
- **Recommended, not yet mined:** Market Wizards series (Schwager), Adam
  Grimes *Art & Science of Technical Analysis*, Steenbarger (psychology),
  Kahneman. Chan *Algorithmic Trading* and López de Prado *Advances in
  Financial ML* are in `references/` for a future quant pass (backtest
  overfitting chapters are directly relevant to our calibration discipline).
- **Treat as baseline-only / marketing-adjacent:** Aziz *How to Day Trade for
  a Living* (the intraday SOP's vocabulary echoes it — fine as a checklist,
  not authoritative; r/stocks flags it as a funnel book).

## Hard-won process rules (backtest runs 1-4, this repo)

1. Scan BEFORE run-day, always — batched scan+run silently skips entries.
2. Never re-decide a window after seeing its outcomes (hindsight
   contamination); log execution misses instead and move on.
3. Every threshold change needs: named hypothesis → mechanical replay →
   ship only with multi-sample support → forward-validate before live.
4. Record REJECTED ideas in the SOP with evidence (stagnation exit, trail
   ratchet) so they aren't re-invented.
5. In-sample replay arithmetic is diagnosis, never forecast.
