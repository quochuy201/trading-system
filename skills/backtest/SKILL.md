---
name: trading-backtest
description: "Use when asked to backtest, simulate, or validate a trading strategy against historical data. Follows the exact same workflow as live trading but uses the v3 daily-cycle harness with mechanical monitoring."
requires_tools: [start_backtest_v2, advance_to_next_day, load_day_bars, step_bar, backtest_enter, backtest_exit, get_backtest_positions, get_backtest_results, end_backtest, load_market_data, scan_for_candidates, calc_technical_indicators, get_market_data, get_news, get_social_sentiment, score_catalyst, calc_position_size, check_portfolio_risk, check_daily_limits, check_kill_switch, log_backtest_decision, export_backtest_jsonl]
---

# Backtest Agent

You simulate live trading against historical data using the v3 daily-cycle harness. The harness handles mechanical monitoring (stops, targets, trailing) automatically. You make all ENTRY and JUDGMENT decisions using the same skills as live trading.

**You follow the same skills as live trading:**
- Research skill → scanning and due diligence (5-layer DD + catalyst scoring)
- Trader skill → risk validation, conviction-scaled sizing, entry timing
- Monitor skill logic → handled mechanically by `step_bar()` (you only act on events)

**The ONLY differences from live:**
- `advance_to_next_day()` replaces waiting for market open
- `step_bar()` replaces real-time price monitoring (mechanical checks run automatically)
- `backtest_enter()` replaces `place_order()` (logs simulated entry)
- `backtest_exit()` for LLM judgment exits (dead money, thesis broken)

---

## Step 1: Parse the Request

Extract from the user's message:
- **Symbols** — specific tickers OR empty string (determines mode)
- **Date range** — start and end dates
- **Capital** — starting capital (default: $100,000)
- **Monitor timeframe** — 1Hour (default), 15Min, or 1Day

### Two Modes:

**Mode A — Fixed List:** `start_backtest_v2("NVDA,AMD", ...)`
- Skip scanner, evaluate given tickers each day

**Mode B — Scanner Mode:** `start_backtest_v2("", ...)`
- Scan ALL symbols in DB each day through 4-layer filter
- Only candidates that pass go to DD

---

## Step 2: Initialize

```
start_backtest_v2(symbols, start_date, end_date, lookback_start, timeframe, initial_capital)
```

This:
- Loads daily data for the full universe (scanner warmup)
- Loads intraday data for the monitor timeframe
- Swaps broker to simulation mode
- Returns: run_id, trading_days count, mode

---

## Step 3: Daily Cycle (repeat until done)

### 3a. Advance to next day

```
advance_to_next_day()
```

Returns: date, day_number, open_positions summary, account state.
If returns `null` → backtest complete, go to Step 4.

### 3b. Scan for candidates

**Mode B:** Call `scan_for_candidates("")` — scans full universe.
**Mode A:** Your candidates are the fixed list.

Scanner filters (always on DAILY bars):
1. Liquidity: price $10-500, avg vol > 2M, ATR 1.5-5%, RVOL > 1.1x
2. Relative Strength: outperforming SPY by > 2% over 10 days
3. Trend: above SMA20, SMA20 > SMA50
4. Momentum: RSI 40-70, MACD bullish, not at upper Bollinger
5. Anti-chase: reject if near high AND ran >5% in 5 days

If 0 candidates → load bars for open positions only, go to 3e.

### 3c. Due Diligence (per candidate)

Load intraday bars: `load_day_bars(candidate_symbols + open_position_symbols)`

For each candidate:

1. `calc_technical_indicators(symbol)` — RSI, MACD, SMAs, ATR
2. `get_news(symbol)` — last 3 days of headlines
3. **Score the catalyst** (MANDATORY):

```
score_catalyst(symbol, freshness, magnitude, priced_in, convergence, relevance, headline, thesis)
```

| Score | Action |
|-------|--------|
| ≥ 7 | Proceed to entry |
| 5-6 | Skip (borderline, not worth the risk) |
| < 5 | Skip (no real catalyst) |

If score < 7 → skip this candidate. Log reason and move to next.

### 3d. Entry (if catalyst passes)

**First-hour confirmation:** Step 2 bars to see first-hour price action.

Check: is current price ABOVE the day's open after 2 hours?
- YES → first-hour confirmed, proceed
- NO → first-hour fade, skip today

**Conviction-scaled sizing:**

| Catalyst Score | Risk % | Target R:R |
|---------------|--------|------------|
| 9-10 | 2.0% | 3:1 |
| 8 | 1.5% | 2.5:1 |
| 7 | 1.0% | 2:1 |

**Position size:** `qty = min(risk_budget / risk_per_share, available_cash / entry_price)`

No separate concentration cap — the risk % and available cash are the limits.

**Enter:**
```
backtest_enter(symbol, "long", entry_price, quantity, stop_loss, take_profit, atr, reasoning, time_stop_bars)
```

- stop_loss = entry - 1.5×ATR
- take_profit = entry + (target_R × risk_per_share)
- time_stop_bars = 105 (15 days × 7 hourly bars)

### 3e. Monitor (step through remaining bars)

Call `step_bar()` in a loop until `"day_complete"`.

The harness handles mechanically:
- **Stop loss**: previous bar closed below stop → exits at next bar open
- **Take profit**: bar high reaches target → exits at target price
- **Trailing stop**: after +1R, trails at 1.5×ATR (or 2×ATR if ATR% > 3%)
- **Time stop**: exceeded 105 bars (15 days) → exits at bar open

**You only act when step_bar returns events:**
- `large_drop` (>3% one bar): assess — is thesis broken? Call `backtest_exit()` if yes.
- `approaching_stop` (<0.5% from stop): consider early exit if thesis weakened.
- `dead_money` (35+ bars, never reached +0.5R): exit via `backtest_exit()`.

**For routine "nothing" bars:** no action needed. Just keep calling `step_bar()`.

### 3f. End of day

When `step_bar()` returns `"day_complete"`, go back to 3a.

---

## Step 4: End of Backtest

When `advance_to_next_day()` returns null:

1. `get_backtest_results("")` — returns full metrics + trade list (force-closes open positions)
2. `export_backtest_jsonl(run_id)` — save decision log
3. `end_backtest()` — restore live broker

Report to user:
- P&L, return %, max drawdown
- Win rate, profit factor, expectancy
- Each trade: symbol, entry→exit, P&L, R-multiple, days held, exit reason
- Decisions: what was skipped and why (catalyst scores, first-hour fades)
- Key learning: what worked, what failed, suggested improvements

---

## Rules

1. **Same as live.** Every step must mirror real trading decisions.
2. **No future data.** Only see bar opens and previously completed bars.
3. **Catalyst scoring is mandatory.** Never enter without calling `score_catalyst`.
4. **Let the harness monitor.** Don't manually check stops — `step_bar()` does this.
5. **Only act on events.** Don't call `backtest_exit` unless an event triggers judgment.
6. **Reason honestly.** If setup doesn't meet criteria, skip. Don't force trades.
7. **One thesis per entry.** State it in the `reasoning` field.
