# Backtest Engine v3 — Revised Design

**Date:** 2026-05-27  
**Status:** Active  
**Supersedes:** 2026-05-24-backtest-engine-v2-design.md (v2 was partial implementation)

---

## Core Principle

The backtest IS the live trading agent running on historical data. Same skills, same tools, same decision flow. The only differences:

1. Data comes from historical bars instead of real-time
2. Orders are logged (not sent to broker)
3. Time advances discretely (bar-by-bar) instead of continuously

**If the backtest uses different code paths than live trading, the backtest proves nothing.**

---

## Architecture

```
User invokes backtest skill
    │
    ▼
skills/backtest/SKILL.md (orchestrator)
    │
    ├── Phase: SCAN (once per day)
    │   └── calls scan_for_candidates() — same MCP tool as live
    │       └── reads config.yaml universe (67+ stocks)
    │       └── uses production scanner/filters.py (4-layer filter)
    │       └── runs on DAILY bars with sim clock set to that date
    │
    ├── Phase: RESEARCH/DD (per candidate)
    │   └── LLM applies skills/research/SKILL.md
    │       └── calc_technical_indicators, get_news, get_market_data
    │       └── 5-layer DD → decide ENTER or SKIP
    │
    ├── Phase: ENTRY
    │   └── LLM applies skills/trader/SKILL.md
    │       └── risk gates, position sizing, order logging
    │
    ├── Phase: MONITOR (bar-by-bar, mostly mechanical)
    │   └── Mechanical Python checks EVERY bar:
    │       - Stop hit? (bar low <= stop)
    │       - Target hit? (bar high >= target)
    │       - Trailing stop update?
    │       - Time stop expired?
    │   └── LLM invoked ONLY on events:
    │       - Price drop > 3% in one bar
    │       - Approaching stop (within 0.5%)
    │       - Unusual volume spike (> 3x average)
    │       - Held > 5 days without reaching +0.5R (dead money check)
    │
    └── Phase: EXIT
        └── Mechanical exit on stop/target/time
        └── LLM exit on judgment calls (dead money, thesis broken)
```

---

## Two Modes

### Mode A: Fixed List (user gives tickers)
> "Backtest NVDA, AMD for Feb 2026, 1 hour bars"

- Skip scanner
- LLM does DD on given tickers each day
- Still applies full research skill (indicators, news, catalyst check)
- Won't force entry if DD fails

### Mode B: Scanner Mode (no fixed universe)
> "Backtest Feb 2026, 1 hour bars, scanner mode"

- Each trading day: run `scan_for_candidates()` with sim clock
- Scanner reads `config.yaml` universe (full list: 67 stocks)
- Scanner uses DAILY bars always (regardless of monitor timeframe)
- Only candidates that pass 4-layer filter go to LLM for DD
- If scanner returns 0 → skip day, no forced trades

---

## Daily Cycle (repeated each trading day)

```
┌─────────────────────────────────────────────────┐
│ START OF DAY                                     │
│                                                  │
│ 1. advance_to_next_day()                         │
│    → Sets sim clock to first bar of new day      │
│    → Returns: date, open positions summary       │
│                                                  │
│ 2. SCAN (Mode B) or EVALUATE (Mode A)           │
│    → scan_for_candidates() with daily bars       │
│    → Returns candidates list                     │
│                                                  │
│ 3. DD on each candidate                          │
│    → LLM applies research skill                  │
│    → Decides: enter / skip / watch               │
│                                                  │
│ 4. ENTRIES                                       │
│    → LLM applies trader skill                    │
│    → Logs simulated orders                       │
│                                                  │
├─────────────────────────────────────────────────┤
│ INTRADAY MONITORING (bar by bar)                 │
│                                                  │
│ 5. step_bar()                                    │
│    → Advances one intraday bar                   │
│    → Mechanical checks: stop/target/trail/time   │
│    → Returns:                                    │
│      - "nothing" → no LLM call needed            │
│      - "exit_triggered" → log the exit           │
│      - "event" → LLM must evaluate               │
│                                                  │
│ 6. Repeat step 5 until end of day               │
│                                                  │
├─────────────────────────────────────────────────┤
│ END OF DAY                                       │
│                                                  │
│ 7. Log daily summary                             │
│    → Open positions, P&L, decisions made         │
│                                                  │
│ 8. Roll to next day → back to step 1            │
└─────────────────────────────────────────────────┘
```

---

## MCP Tools (revised)

### Existing (keep, modify)

| Tool | Change |
|------|--------|
| `start_backtest_v2` | Support Mode B: symbols="" means scanner mode. Load daily data for full config universe. |
| `scan_for_candidates` | Already works — uses sim clock + config.yaml. No change needed. |
| `next_backtest_bar` | Rename to `step_bar`. Add mechanical checks. Return events. |
| `log_backtest_decision` | Keep but make OPTIONAL for routine "hold" bars. Only required for entries, exits, and events. |
| `end_backtest` | Keep as-is. |
| `get_backtest_results` | Keep as-is. |

### New Tools

| Tool | Purpose |
|------|---------|
| `advance_to_next_day()` | Move sim clock to next trading day. Returns date + portfolio state. Triggers daily scan. |
| `load_day_bars(symbols, timeframe)` | Load intraday bars for specific symbols for current sim day. Called after scanner finds candidates. |
| `step_bar()` | Advance one intraday bar. Run mechanical checks. Return: events (if any) or "nothing". Does NOT require decision logging for "nothing" bars. |
| `get_day_summary()` | End-of-day summary: positions, unrealized P&L, decisions count. |

### Mechanical Checks (inside step_bar)

Python handles these EVERY bar without LLM:

```python
def _mechanical_check(position, bar):
    events = []
    
    # Stop loss (close-based: previous bar closed below stop)
    if position.prev_close < position.stop_loss:
        events.append({"type": "stop_hit", "exit_price": bar.open})
    
    # Take profit (intrabar: high touches target)
    if bar.high >= position.take_profit:
        events.append({"type": "target_hit", "exit_price": position.take_profit})
    
    # Trailing stop update
    if bar.close > position.highest_close:
        position.highest_close = bar.close
        new_trail = bar.close - (1.5 * position.atr)
        if new_trail > position.trailing_stop:
            position.trailing_stop = new_trail
    
    # Time stop (15 trading days)
    if position.bars_held >= position.time_stop_bars:
        events.append({"type": "time_stop", "exit_price": bar.open})
    
    # Event triggers for LLM (not auto-exit, just flag)
    pct_change = (bar.close - bar.open) / bar.open * 100
    if pct_change < -3:
        events.append({"type": "large_drop", "pct": pct_change})
    
    if (bar.close - position.stop_loss) / position.stop_loss < 0.005:
        events.append({"type": "approaching_stop", "distance_pct": ...})
    
    return events
```

---

## Data Loading Strategy

### Scanner (daily — always)
- Pre-load: full config universe daily bars, lookback 4 months before start
- When: at `start_backtest_v2` time
- Why: scanner needs 50+ daily bars for SMAs, RSI, etc.

### Intraday (on-demand — per day, per candidates)
- Load: only candidates found by scanner + open positions
- Timeframe: user-specified (1Hour, 15Min, 5Min)
- When: after scan completes each day, via `load_day_bars()`
- Why: no point loading 1-min bars for 67 stocks × 20 days upfront

---

## Logging Strategy

### Always logged (every entry/exit):
- Symbol, time, price, side, quantity, stop, target, reasoning
- Phase, decision, input state

### NOT logged (routine monitoring):
- "Nothing happened this bar, still holding" — skip
- Only log when an EVENT occurs or a DECISION is made

### Event log (when LLM is called):
- What triggered the call (large drop, approaching stop, etc.)
- LLM's assessment and action taken

---

## What run_feb_backtest.py Should Be

DELETE the current `run_feb_backtest.py`. It violates this design by:
1. Hardcoding strategy logic in Python
2. Using a fixed 14-stock list
3. Not using the MCP tools or skills
4. Making decisions mechanically instead of through the LLM

Replace with: the user simply invokes the backtest skill and says:
> "Backtest Feb 2026, 1 hour bars, scanner mode"

The LLM follows `skills/backtest/SKILL.md` which orchestrates everything.

For automated/scripted runs, a thin wrapper can call the MCP server programmatically,
but the DECISION LOGIC must always flow through the skills, not Python.

---

## Implementation Order

1. ✅ `skills/backtest/SKILL.md` — already written (current version is good)
2. Revise `backtest/harness.py` — add daily cycle, mechanical monitoring, event detection
3. Add new MCP tools: `advance_to_next_day`, `load_day_bars`, `step_bar`, `get_day_summary`
4. Modify `start_backtest_v2` — support scanner mode (symbols="" loads config universe daily data)
5. Modify `scan_for_candidates` — ensure it respects sim clock correctly
6. Delete `run_feb_backtest.py` — replaced by skill invocation
7. Test: run "Backtest Feb 2026, 1H, scanner mode" through the actual agent

---

## Success Criteria

1. Agent discovers COP, ON, MRK etc. via scanner (not hardcoded list)
2. Agent applies research DD and makes enter/skip decisions with reasoning
3. Mechanical monitoring catches stops/targets at the correct bar
4. LLM is only called when events warrant judgment
5. Results are logged with full audit trail
6. Same config.yaml universe used in backtest and live trading
