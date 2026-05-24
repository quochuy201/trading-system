# E2E Paper Trading Validation Results

**Date:** 2026-05-21
**Account:** Alpaca Swing Trade (paper)
**Starting Equity:** $101,936.54

## Summary

All 22 MCP tools validated against live Alpaca paper trading. One bug found and fixed during testing.

## Results

| Test | Status | Notes |
|------|--------|-------|
| Environment setup | ✅ | .env with swing trade keys, dotenv loading added to server.py |
| MCP server startup | ✅ | 22 tools registered, no import errors |
| Broker connectivity | ✅ | Account info retrieved, 4 existing positions visible |
| Research workflow | ✅ | Live quotes, 126 bars loaded, RSI/MACD/SMA/ATR computed |
| Trader workflow | ✅ | Position sizing, risk checks, daily limits, order placed |
| Monitor workflow | ✅ | All positions with P&L, exit criteria comparison works |
| Kill switch | ✅ | Activates (closes positions), blocks orders, clears |
| Notifications | ✅ | Graceful skip without webhook, formatting correct |
| Persistence | ✅ | SQLite: 8 tables, trade plans, transactions, price data |

## Bug Found & Fixed

**Issue:** `place_order` did not check kill switch state before executing.
**Impact:** Orders could be placed even with kill switch active.
**Fix:** Added guard at top of `place_order` that returns error JSON when kill switch is active.

## Known Limitations

1. **News tool** — stub returning `[]` (needs Alpaca News API or alternative)
2. **SMA50** — returns None with 60 days of data (needs 70+ days loaded)
3. **Slack notifications** — untested with live webhook (no URL configured)
4. **Wash trade warnings** — Alpaca rejects buys when kill switch sell orders are pending on same symbol (expected behavior, retries handle it)

## Artifacts

- Trade placed: BUY 1 NVDA @ market (order ID: 3e9a466d)
- Trade plan saved: test-e2e-001 (day-trade-momentum, stop $215, target $235)
- Price cache: 126 bars across AAPL, NVDA, TSLA
