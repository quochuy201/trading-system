# Scanner Tuning Config — 2026-07-15 (Wed)

## Regime Context
| Signal | Value | Implication |
|--------|-------|-------------|
| SPY trend | UP (+1.14% vs SMA50) | Favorable for M engine |
| SPY TR-ATR | 0.70% | Low volatility |
| SPY IV Rank | 13.4 | Low implied vol environment |
| VIX | N/A | Data source unavailable |

Low-ATR regime favors M (momentum) continuation engines. R engine naturally produced 0 passes — mean-reversion works best in higher-ATR environments.

## 6a. Exclusion List
- No symbols rejected 2+ consecutive days yet (need longer tracking).
- Candidates today: IBM, MS, EBAY, OSCR, GD, IBKR, NTAP — all M-pass only.

## 6b. Threshold Overrides (Regime-Adaptive)
- None proposed. Low-ATR bull trend is standard operating conditions for M engine defaults.
- R engine's 0 passes is expected behavior in low-ATR (0.70%) environment; no threshold change.

## 6c. Risk Limit Overrides
- None. Daily PnL -0.12% well within 3% limit.
- Account equity $105,545 — no capital constraints.

## 6d. Notes
- **Auto-revert**: All overrides expire 2026-07-22 unless renewed.
- OKTA approaching +1R (currently +0.77R, entry $135.43, 1R = $155.53). If it crosses +1R on tomorrow's close, trailing stop will activate. Monitor closely.
- IBKR is a repeat candidate (passed today and was position opened yesterday). M engine continuation thesis intact.
- No new entries today — agent did not run DD on any candidates. Recommendation: investigate whether the research agent executed its scanning/DD workflow or skipped processing.

## 6e. Friday Review (N/A — Wednesday)
