Run the forward validation of swing SOP v1.3.0 on the unseen Jan-Feb 2026 window.

Read PROJECT_STATUS.md and sops/equity/swing/v1.3.0.md FIRST. Then:

## Step 1 — Data (you have network access; the loader needs .env Alpaca keys)
```
cd tools && uv run python scripts/load_universe.py --daily-end 2026-02-28
```
Verify: >=350 universe symbols with >=160 daily bars before 2026-01-26.

## Step 2 — Run the agent-driven backtest (Jan 26 – Feb 27, 2026)
Use `tools/scripts/week_runner.py` (read its docstring; bar-mode daily):
```
python3 scripts/week_runner.py init --capital 100000 --bar-mode daily
```
Daily loop, STRICT ordering per day D: `scan D` → YOU decide → `plan ...` → `run-day D`.
Never run a day before deciding it. Manage open positions through ~Mar 6 marks
if data allows, else mark at last close.

Decision procedure (FROZEN — this is a validation run, you may NOT tune anything):
- Eligibility per sops/_routing/v1.1.0 §1 from the scan's regime block.
  DEFENSIVE (tr_atr>1.5) → halve risk-pct; tr_atr>2 or stress row → no entries.
- Engine M (scanner `engine_m_pass` + agent gates): no new M if spy_vs_sma50_pct > +3
  (M-G1b). Rank by roc50, max 2 new/day. Entry: --entry-type market_open
  --gap-up-max-pct 5 --gap-down-max-pct 3 --stop-atr-mult 2.5 --trail 1
  --time-stop-sessions 20. Earnings within 5 sessions (check the calendar —
  you have web access) → skip; unknown → risk-pct 0.5.
- Engine R (scanner `engine_r_pass`, RSI3<10 enforced by scanner): rank by drop_3d,
  max 2 new/day. Skip structural-break drops (R-G7: read the news — fraud,
  guidance cut, regulatory = veto; index/sector sympathy = tradeable).
  Entry: --entry-type limit, limit = prev_close × (1 − 0.005×atr10_pct),
  --stop-atr-mult 2.5, --target-fill-pct max(4, atr10_pct), --time-stop-sessions 4.
- Sizing: risk-pct 1.0 full / 0.5 half per the DD rubric
  (skills/research/reference/swing-trade-dd.md); max 5 open; one engine per symbol;
  max 2 same-theme correlated positions.
- Log every skip/rank-out in --reason.

## Step 3 — Report
`python3 scripts/week_runner.py report`. Write
reports/backtests/2026-jan-feb-fwd-swing-v1.3.0.md in the style of the existing
reports (trade ledger, gate audit, WR/expectancy per engine, comparison vs the
in-sample projection of ~$570/wk @ 76% — state plainly whether forward results
support or refute v1.2.0/v1.3.0). Update PROJECT_STATUS.md. Commit.

## Hard rules
- NO threshold changes during this run (it stops being validation the moment you tune).
- Decisions only from data strictly before each scan date. You DO have live web
  access for historical news/earnings dates — use it for R-G7 and M-G8, but only
  with information published BEFORE the decision date.
- If results are bad, report them bad. Negative forward results are the most
  valuable output this run can produce.
