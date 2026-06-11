Autonomous improvement loop: tools + skills → backtest → analyze → iterate.
Read first: PROJECT_STATUS.md, CLAUDE.md, sops/equity/swing/v1.3.0.md,
docs/references/trading-knowledge-notes.md. Then loop until win rate and P&L
stop improving out-of-sample.

## Mission targets (judged out-of-sample, never in-sample)
Win rate > 70% blended, P&L ≥ $500/week on $100k — but the decision metric is
expectancy per R per engine. Never sacrifice expectancy to chase the WR number.

## Focus 1 — Exit strategy (highest-leverage area, see v1.2.0/v1.3.0 history)
- NO fixed magic numbers. Every exit parameter must be expressed relative to:
  (a) price action — structure breaks, close-based confirmation, swing
  highs/lows; (b) volatility — ATR-scaled trails/targets; (c) current market
  regime — tighten exits in DEFENSIVE/stress regimes, loosen in trending ones
  (regime comes from get_market_regime + routing SOP rows).
- Candidate ideas to test (not conclusions): regime-conditional trail width;
  structure-based stops (below last swing low instead of pure ATR); partial
  scale-out at +2R for Engine M (listed untested in v1.3.0); R target scaling
  with regime breadth.
- Already tested and REJECTED with evidence (do NOT re-add): stagnation exit,
  trail ratchet (sops/equity/swing/v1.3.0.md).

## Focus 2 — Stock picking
You have live web access: make the layers that were blind in prior backtests
real — R-G7 drop diagnosis from actual dated news, M-G8 earnings calendar,
catalyst scoring. Only use information published BEFORE each decision date.
Improve the DD rubric where evidence shows misgrading (e.g. RSI3<10 cohort
sizing — PROJECT_STATUS open item).

## Division of labor (CLAUDE.md is NON-NEGOTIABLE)
- Strategy rules → SOP version files (never edit in place) + skills.
- Deterministic mechanics → Python in tools/scripts/ or shared modules, with
  pytest tests (suite currently 243 passing; keep it green).
- The LLM decides entries/exits per skills; Python executes mechanics.
- Scanner thresholds must mirror the SOP version they implement.

## Skill & token discipline
- When writing or editing any SKILL.md: use the skill-creator skill.
- Keep skills LEAN: triggering conditions + behavior, no duplicated SOP
  content, no narrative bloat. Push detail into reference/ files loaded on
  demand. If a skill grows past ~300 lines, split or prune it.

## Loop protocol (each cycle, no exceptions)
1. Named hypothesis with the evidence that motivated it.
2. Implement (SOP version + scanner mirror + tests, or script + tests).
3. Backtest: agent-driven via tools/scripts/week_runner.py — scan day D →
   decide → plan → run-day D, strictly in that order; data strictly before
   the scan date; calibration windows and validation windows must be
   DIFFERENT and labeled in the report.
4. Analyze: per-engine WR, expectancy/R, capture efficiency, gate audit,
   counterfactuals on skips/no-fills. Write reports/backtests/<date>-<name>.md.
5. Ship or reject. Record rejections in the SOP. Update PROJECT_STATUS.md.
   Commit with a descriptive message.
6. Repeat. Stop and summarize when two consecutive cycles fail to improve
   OOS expectancy (you are overfitting — say so).

## Hard limits
- OPERATING_MANUAL.md and risk caps: human-ratified only. Position cap 5→8
  and Engine S (short) are PENDING USER DECISIONS — propose, don't ship.
- Negative results are deliverables, not failures. Report them plainly.
