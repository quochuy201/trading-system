# Routing Eligibility — Golden Cases (agent dry-run)

**Status:** test spec written; dry-run execution pending a paper environment
(needs the live Risk-Manager agent + Alpaca credentials, which the build
worktree does not have). Run these before enabling a second strategy in
`config.yaml strategies.enabled`.

Feed each snapshot to the Risk-Manager (temperature 0) with `sops/_routing/v1.0.0`
and `config.yaml`. Assert the eligible set. Run each case **k=3** times; the set
MUST be identical across runs (pass^k reliability per the Agent Evolution
Standard §3). Variance across runs = a defect to fix in the SOP wording
(ambiguity), not the model.

The snapshot mirrors `get_market_regime` output:
`{vix, spy_tr_atr, spy_vs_sma50_pct, spy_trend, iv_rank_spy}`.

| # | Snapshot | Expected eligible (options scope) | Expected (equity scope) |
|---|---|---|---|
| 1 | vix=35, spy_tr_atr=2.4, trend=down | none (stress row) | none |
| 2 | vix=18, spy_tr_atr=0.9, iv_rank_spy=80, spy_vs_sma50_pct=0.5 | options/vol-edge | none |
| 3 | vix=14, spy_tr_atr=0.8, iv_rank_spy=35, spy_vs_sma50_pct=3, trend=up | none | equity/intraday + swing (when enabled) |
| 4 | all null (data outage) | none (fail-safe) | none |
| 5 | vix=null, spy_tr_atr=1.1, iv_rank_spy=null, trend=up | none (vol-edge needs iv_rank → null → OFF) | none |

PASS = eligible set matches the column AND is stable across the 3 runs.

## Dry-run results (fill in when executed on paper)

| # | Run 1 | Run 2 | Run 3 | Stable? | Matches expected? |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |
| 4 | | | | | |
| 5 | | | | | |

Any mismatch or run-to-run variance → tighten the §1 wording in
`sops/_routing/v1.0.0.md` (propose via `reports/sop-changes/`), re-ratify, re-run.

## Note on case 2 / 5 and `iv_rank_spy`

These cases exercise `iv_rank_spy`, which `get_market_regime` currently returns
as `null` (SPY IV-rank not yet sourced — see the implementation plan "Deferred"
section). Until that signal is wired, the vol-edge eligibility rows fail-safe to
OFF in production, so case 2's "options/vol-edge" expectation only holds once
`iv_rank_spy` is supplied. The dry-run feeds the value explicitly to validate the
SOP logic independent of the data-sourcing gap.
