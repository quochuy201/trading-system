# Trading Plan - STX - 2025-10-28 - Engine M

**Stock:** STX
**Date:** 2025-10-28
**Engine:** M
**Entry Type:** market_open
**Stop ATR Multiplier:** 2.5
**Time Stop Sessions:** 20
**Trail:** true
**Trail Arm R:** 1.0
**Trail Width ATR:** 2.0
**Risk Percent:** 1.0%
**Gap Up Max PCT:** 5.0%
**Gap Down Max PCT:** 3.0%
**Reason:** M engine candidate from 2025-10-27 scan: strong momentum setup

## Notes

- This plan is generated based on the Engine M scan from 2025-10-27.
- All parameters are to be used by the Trader Agent for order execution and position management.
- The plan adheres to the system's BACKTEST DEVELOPMENT RULES: strategy logic resides in skill files/SOPs, not in this plan.
- Entry will be at the next available price (market open of 2025-10-28).
- Gap checks will be applied: if stock gaps up >5% or down >3% from prior close, the trade will be skipped.
- Stop loss is set at 2.5 * ATR from entry.
- Time stop: 20 sessions (approximately 1 month of trading sessions).
- Trailing stop is enabled, armed when profit reaches 1.0R, with trail width of 2.0 * ATR.
- Risk per trade is 1% of portfolio.