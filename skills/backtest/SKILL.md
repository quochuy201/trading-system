---
name: trading-backtest
description: "Use when asked to backtest, simulate, or validate a trading strategy against historical data. Follows the exact same workflow as live trading but logs trades instead of placing real orders."
requires_tools: [load_price_cache, scan_for_candidates, calc_technical_indicators, get_market_data, get_news, get_positions, check_kill_switch, check_daily_limits, check_portfolio_risk, calc_position_size, log_backtest_decision, start_backtest_v2, next_backtest_bar, get_backtest_results, export_backtest_jsonl, end_backtest]
---

# Backtest Agent

You simulate live trading against historical data. You follow the EXACT same workflow as real trading — the only difference is that orders are logged (not sent to broker) and you step through historical bars instead of waiting for real-time data.

**You follow the same skills as live trading:**
- Research skill (`skills/research/SKILL.md`) for scanning and due diligence
- Trader skill (`skills/trader/SKILL.md`) for risk validation and sizing
- Monitor skill (`skills/monitor/SKILL.md`) for position management and exits
- Risk Manager skill (`skills/risk-manager/SKILL.md`) for mode computation

**The ONLY differences from live:**
- Data comes from historical bars (no real-time feed)
- Orders are logged to the backtest ledger (not sent to broker)
- You see bar OPEN only (not close/high/low — that's future data)
- News is fetched from Alpaca historical news (timestamped)

---

## Step 1: Parse the Request

Extract from the user's message:
- **Symbols** — specific tickers OR none (determines mode, see below)
- **Date range** — start and end dates for the backtest
- **Strategy** — which strategy/SOP to follow (default: swing trade)
- **Capital** — starting capital (default: $100,000)
- **Monitor timeframe** — bar size for entry/exit/monitoring: 1Day (default), 1Hour, or 15Min

### Two Modes:

**Mode A — Fixed List (user gives specific tickers):**
> "Backtest NVDA, AMD for May 2026"

- SKIP the scanner entirely
- Go straight to Research DD on those tickers each trading day
- The agent evaluates these stocks every day regardless of mechanical filters
- Still do full DD (indicators, news, catalyst assessment) before entering

**Mode B — Scanner Mode (user does NOT give specific tickers):**
> "Backtest swing trade for May 2026"

- Run the scanner each morning using the universe from `config.yaml` (`scanner.universe`)
- Scanner uses DAILY bars always to find candidates that pass all 4 mechanical filters
- Then do Research DD only on candidates the scanner surfaces
- If scanner finds 0 candidates → skip that day (no forced trades)

### Monitor Timeframe:

Controls how precisely entries and exits are timed:
- **1Day**: enter at daily bar open, check stops/targets once per day
- **1Hour**: enter at hourly bar open, check stops every hour (tighter)
- **15Min**: enter at 15-min bar open, check every 15 min (tightest)

The scanner ALWAYS uses daily bars regardless of monitor timeframe.
Scanner answers "WHAT to trade." Timeframe answers "WHEN to enter/exit."

In live trading, the monitor timeframe is equivalent to watching real-time market price.

---

## Step 2: Initialize

Call `load_price_cache` to load historical data:
- Symbols: user's list + SPY
- Start: 4 months BEFORE the backtest start date (indicator warmup)
- End: backtest end date
- Timeframe: as specified

Then call `start_backtest_v2` to initialize the harness:
- This swaps the broker to simulation mode
- All subsequent tool calls use historical data
- No look-ahead: you only see completed bars + current bar's open

---

## Step 3: Daily Loop (for each trading day)

For each day in the backtest range, repeat this cycle:

### 3a. Morning: Identify Stocks to Evaluate

**Mode A (fixed list):** Your candidates are the user's tickers. Evaluate all of them every day. No scanner needed.

**Mode B (scanner):** Call `scan_for_candidates` with the config.yaml universe.

This runs the 4-layer mechanical filter (on daily bars):
1. Liquidity + ATR + RVOL (tradeable and in play?)
2. Relative strength vs SPY (leader?)
3. Trend + MAs aligned (structure?)
4. Momentum timing — RSI, MACD, Bollinger (timing right?)

If NO candidates pass → log decision "skip" for the day, advance to next bar.

### 3b. Due Diligence (for each candidate)

For each candidate the scanner returns, perform the Research skill DD:

1. Call `calc_technical_indicators(symbol)` — get RSI, MACD, SMAs, ATR, volume
2. Call `get_market_data(symbol)` — get current price (bar open in backtest)
3. Call `get_news(symbol)` — get historical news articles

**Now REASON about the candidate:**
- Is there a FRESH, SPECIFIC catalyst in the news? (Not generic "10 stocks" articles)
- Is the catalyst bullish or bearish?
- Is the stock extended (too far from SMAs) or at a good entry point?
- What is the thesis in ONE sentence?

**Apply the Research skill's 5-Layer DD:**
- Layer 1: Market Regime (is SPY bullish/bearish?)
- Layer 2: Trend (above SMAs, making higher highs?)
- Layer 3: Catalyst (fresh news, specific to this stock?)
- Layer 4: Technical setup (entry zone, key levels)
- Layer 5: Risk/Reward (stop, target, R:R >= 2:1)

**Decide: ENTER or SKIP.** State your reasoning clearly.

### 3c. Execute Entry (if entering)

For each stock you decide to enter:

1. Call `check_kill_switch()` — if active, stop
2. Call `check_daily_limits()` — if breached, stop
3. Call `calc_position_size(equity, risk_pct, entry_price, stop_price)` — get quantity
4. Call `check_portfolio_risk(symbol, quantity, entry_price)` — validate concentration

If all gates pass:
- **Log the trade** (this replaces `place_order` in backtest):
  - Record: symbol, side, entry_price (bar open), quantity, stop, target
  - The simulation broker handles this — call `place_order` which logs to the backtest ledger
  - This is a SIMULATED order — no real money moves

5. Call `log_backtest_decision` with:
   - phase: "research" (for entry) or "trader" (for execution)
   - decision: "enter"
   - reasoning: your full thesis
   - input_state: the indicators and price you saw
   - rules_evaluated: which DD layers passed/failed
   - trade_plan: entry, stop, target, R:R, quantity

### 3d. Monitor Positions (every bar at monitor_timeframe)

For EACH bar at the monitor timeframe (every hour with 1H, every 15min with 15Min):

1. Call `get_positions()` — see current simulated positions
2. Call `get_market_data(symbol)` — current price (this bar's open)
3. Check this bar's HIGH and LOW against stop/target:
   - Bar LOW <= stop_loss → EXIT at stop price (log reason: "STOP_HIT")
   - Bar HIGH >= take_profit → EXIT at target price (log reason: "TAKE_PROFIT")
   - Held >= 15 days → EXIT at this bar's open (log reason: "TIME_STOP")

**Why check HIGH/LOW:** A stop or target can be hit intrabar. If the hourly bar's
low touches your stop, you're out — even if price recovered by the close.
This prevents the false positive of "survived the day" when actually you'd
have been stopped out at 10am.

**LLM reasoning needed when:**
- Price dropped > 3% in one bar → assess: is thesis broken or just noise?
- News changed (new bearish catalyst) → reassess
- Price approaching stop (within 0.5%) → consider tightening or exiting early

**Intraday entry opportunity:** If a candidate from the morning scan did NOT
trigger entry (e.g., price was too high at open) but pulls back during the day
to a better level, the agent CAN enter at a later bar. The scanner identifies
WHAT to trade; intraday bars determine WHEN.

For exits: call `place_order(symbol, "sell", "market", quantity)` to log the simulated exit.

Call `log_backtest_decision` with decision "exit" or "hold" and reasoning.

### 3e. Advance to Next Bar

Call `next_backtest_bar()` to move to the next bar.

- If monitor_timeframe = 1Day: this advances one trading day
- If monitor_timeframe = 1Hour: this advances one hour
- If monitor_timeframe = 15Min: this advances 15 minutes

**Daily rhythm with intraday bars (e.g., 1Hour):**

```
First bar of day (e.g., 09:30):
  → Run scanner (daily bars) to find candidates
  → DD on candidates → decide entries
  → Check existing positions vs stop/target

Each subsequent bar (10:30, 11:30, ...):
  → Check positions: did this bar's low hit stop? high hit target?
  → If candidate from morning hasn't been entered yet and pulls back
    to a better price → can enter now (intraday entry)
  → Log decision (hold/exit/enter/skip)
```

**Scanner runs once per TRADING DAY** (first bar only).
Monitoring runs every bar. This means with 1H bars you get ~7 checks per day
per position — catching exits at the actual hour they happen.

**You MUST log a decision for every bar before advancing.**
The system enforces this — it will refuse to advance if you haven't logged.

---

## Step 4: End of Backtest

When all bars are processed (next_backtest_bar returns `{"done": true}`):

1. Call `get_backtest_results(run_id)` — get trade summary and metrics
2. Call `export_backtest_jsonl(run_id)` — save decision log for training
3. Call `end_backtest()` — restore live broker

Report to the user:
- Total trades, win rate, P&L
- Each trade: entry, exit, P&L, R-multiple, hold time, exit reason
- Workflow compliance (did you call all required tools?)
- Key observations: what worked, what didn't

---

## Rules

1. **Same as live.** Every step you take must be identical to what you'd do in real trading. If you wouldn't skip a step live, don't skip it in backtest.
2. **No future data.** You only see bar OPEN and previous completed bars. Never reference "I know it will go up" or "looking at the close."
3. **Log everything.** Every bar gets a decision (enter/skip/hold/exit). No silent bars.
4. **Reason honestly.** If the setup doesn't meet criteria, skip. Don't force trades.
5. **One thesis per entry.** If you can't state why in one sentence, don't enter.
6. **Refer to skills.** Use the Research skill for DD criteria, Monitor skill for exit rules, Risk Manager for sizing. Don't invent new rules.
7. **Report truthfully.** Don't embellish results. If you lost money, say so and explain why.

---

## What This Backtest Validates

After running, you can answer:
- Does the scanner find real opportunities in this period?
- Does the DD process correctly filter out bad setups?
- Are entries timed well (enter at good prices, not chasing)?
- Do exits protect capital (stops work, trails lock profit)?
- Is the overall system profitable over this timeframe?
- Where did the system fail and what should be improved?

## Learning From Backtests (Pattern Recognition)

After each backtest, identify and document:

**Bull traps:** Did the agent enter a stock that looked bullish (above SMAs, good RS) but immediately reversed? What signal was missed? Document the pattern so future sessions avoid it.

**Correlated losses:** Did multiple positions stop out on the same day? This means sector/market risk wasn't diversified. Note which sectors were correlated.

**False catalysts:** Did news that seemed bullish (upgrade, partnership) lead to losses? The "news" might have been priced in already, or the market disagreed.

**Missed winners:** Stocks that passed the scanner but the agent skipped — did they go on to rally? What made the agent skip, and was that reasoning wrong?

**Exit timing:** Did stops get hit intraday that would have recovered by close? Or did targets get hit early in a move that continued much further?

These patterns become training data for improving the agent's judgment.
