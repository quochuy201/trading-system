# Trading System Architecture — Consolidated Design

**Status:** DESIGN COMPLETE — awaiting implementation approval
**Date:** 2026-06-28
**Capital:** $5,000 starting · $200/month break-even · $50-100/day at $25K+
**Target:** Steady income → capital growth → learning platform

---

## Design Decisions (Locked)

### System Philosophy

| Decision | Answer |
|----------|--------|
| Goal | Three horizons: steady income first, then growth, then learning platform |
| Initial capital | $5,000 |
| Monthly target | >$200/month (break-even + profit) |
| Max drawdown | 10% ($500) |
| Focus | Win rate + asymmetric R:R (let winners run, cut losers fast) |
| Approach | Momentum continuation — 45-55% WR with 2-3x R:R winners |
| Positions | 3-4 concurrent, sector-diversified |
| Exit authority | Agent discretion with mechanical stop as safety floor |

### Scan Architecture

| Decision | Answer |
|----------|--------|
| Scan data | Daily bars for factor computation (252-day history) |
| Universe | 400 liquid US equities (existing `universe_backtest.json`) |
| Scan pass 1 | Factor ranking at 6:00 AM (statistical) |
| Scan pass 2 | Pre-market filter at 9:25 AM (gap-adjusted) |
| Scan cadence | Once per day pre-market |

### Monitoring Architecture

| Decision | Answer |
|----------|--------|
| Price check | Latest price every 60 seconds for open positions |
| Context data | 5-minute bars, pulled at alert time |
| Exit flow | Evaluate-first: agent classifies flush vs breakdown BEFORE exiting |
| Hard floor | 1.5x original stop = unconditional exit, no further evaluation |
| Evaluation window | 60 seconds max. Timeout = exit. Uncertain = exit |
| Pattern library labels | Mechanical: same-day markout + T+3 markout. Agent never labels |

### Pattern Library

| Decision | Answer |
|----------|--------|
| Matching fields | Price action (close-location), news present, sector correlation, volume (capitulation/distribution/drift/absorption classification), regime |
| Volume classification | 5-bucket: capitulation, distribution, drift, absorption, overnight event |
| Bootstrap | Empty. Learns from live paper trading only. No backtest pre-loading |
| Labeling | EOD agent computes labels mechanically. Monitor agent queries — never labels |

### System Adaptability

| Decision | Answer |
|----------|--------|
| Strategy changes | YAML config, not Python code |
| Factor changes | Registry decorator + config entry |
| Dead factors | Set `status: dead` in config |
| Pattern learning | Accumulates from paper trading exits |
| Human role | Ratifies strategy config changes, reviews weekly patterns |

---

## Consolidated Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     PRE-MARKET (6:00-9:25 AM)              │
│                                                           │
│  6:00  refresh_market_data    yfinance → 400 symbols       │
│  6:03  compute_factors        14 factors × 400 = 5,600     │
│  6:04  store in DB            factor_scores table           │
│  6:04  classify_regime        trending/choppy/crash         │
│                                                           │
│  9:25  pre_market_filter      gap check top 15 candidates  │
│  9:25  load_factor_scores     SQL query → ranked list      │
│  9:25  Research agent DD      5-layer stack, top 10-15     │
│  9:28  Risk agent preflight   mode, limits, portfolio      │
│  9:29  Trader agent            size + plan entries          │
│  9:30  Enter positions         market on open               │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                    TRADING SESSION (9:30-16:00)           │
│                                                           │
│  Every 60s: check_latest_price(positions)                 │
│    ↓ price > stop? → nothing                               │
│    ↓ price ≤ stop? → ALERT                                 │
│       ├─ pull 5-min bar context                            │
│       ├─ classify volume (capitulation/distribution/…)     │
│       ├─ check sector correlation                          │
│       ├─ check news (if extreme vol + low sector corr)     │
│       ├─ query pattern library (top 20 similar past exits) │
│       └─ agent verdict (60s max):                          │
│          FLUSH      → hold. Tighten floor to 1.5x stop.    │
│          BREAKDOWN  → exit now.                            │
│          UNCERTAIN  → exit. "I don't know" = get out.      │
│          TIMEOUT    → exit. No verdict in 60s.             │
│                                                           │
│  Every 15min: pull 5-min bars for all positions            │
│    → update thesis evaluation (trend intact? momentum?)    │
│    → no price alert, just context refresh                   │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                    POST-MARKET (16:00+)                    │
│                                                           │
│  EOD agent:                                                │
│    ├─ compute performance metrics                          │
│    ├─ label today's exits (same-day markout)               │
│    ├─ store in pattern library                             │
│    ├─ label past exits (T+3 markout for exits from 3 days ago) │
│    ├─ compute factor ICs (rolling correlation)             │
│    ├─ generate tuning config (exclusions, thresholds)      │
│    └─ write journal + notify                               │
│                                                           │
│  Weekly (Friday EOD):                                     │
│    ├─ review pattern library: does exit classification    │
│    │  prediction match outcomes? Adjust rules if not.     │
│    ├─ review factor weights: any factors decaying?        │
│    └─ propose strategy config changes for human approval   │
└─────────────────────────────────────────────────────────┘
```

---

## Data Requirements

| Data | Source | Resolution | Frequency | Cost |
|------|--------|-----------|-----------|------|
| Daily bars (400 symbols) | yfinance | 1Day | Once per day | Free |
| Pre-market price (15 symbols) | Alpaca REST | Quote | 9:25 AM | Free |
| Current price (5 symbols) | Alpaca REST | Quote | Every 60s | Free |
| 5-minute bars (5 symbols) | Alpaca REST | 5Min × 10 bars | On alert + every 15min | Free |
| News (5 symbols) | Alpaca News API | Headlines | On alert (extreme vol + low sector corr) | Free |
| VIX | yfinance or Alpaca | Daily close | Once per day | Free |
| Sector ETFs | yfinance | 1Day | Once per day | Free |
| SPY | yfinance | 1Day + 5Min | Daily + monitoring | Free |

**Everything is available on free tier.** No paid data feeds needed.

---

## Pattern Library Schema

```sql
CREATE TABLE exit_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    engine TEXT NOT NULL,           -- 'M' or 'R'
    exit_trigger TEXT NOT NULL,     -- 'stop_hit', 'time_stop', 'agent_discretion'
    exit_price REAL NOT NULL,
    exit_timestamp TEXT NOT NULL,
    
    -- Context at exit (pattern matching fields)
    close_location REAL,            -- (close-low)/(high-low) of the 5-min alert bar
    volume_class TEXT,              -- 'capitulation', 'distribution', 'drift', 'absorption', 'overnight_event'
    volume_ratio REAL,              -- volume / avg_vol_20
    sector_correlation REAL,        -- correlation with peer stocks in same bar
    news_present INTEGER,           -- boolean: was news in past 24h?
    regime TEXT,                    -- 'trending_calm', 'trending_volatile', 'choppy', 'crash'
    hold_days INTEGER,              -- how long was the position open?
    entry_rr REAL,                  -- R:R at entry
    
    -- Agent verdict at exit time
    agent_verdict TEXT,             -- 'hold', 'exit'
    agent_reasoning TEXT,           -- why the agent decided
    
    -- Mechanical labels (computed by EOD, never by agent)
    markout_same_day_pct REAL,      -- (same-day close - exit_price) / exit_price
    markout_t3_pct REAL,            -- (day+3 close - exit_price) / exit_price, NULL until T+3
    premature INTEGER,              -- 1 if same-day close > exit_price (exit was too early)
    reentry_viable INTEGER,         -- 1 if T+3 close > exit_price (re-entry profitable)
    
    created_at TEXT NOT NULL,
    labeled_at TEXT                 -- when EOD computed labels
);
```

---

## Phase 0: Diagnostic (immediate)

Verify the current system actually works end-to-end before building anything new.

| Check | How |
|-------|-----|
| Data refresh pipeline | `refresh_market_data` → bars in SQLite, no staleness |
| Factor scores pipeline | `compute_factors.py` runs, scores in DB |
| Cron jobs | Morning scan + workflow actually fire |
| MCP server connectivity | Agents can reach 61 tools |
| Gateway | Trading profile Discord/gateway status |
| Dry run | Risk→Research→Trade→Monitor→EOD completes |

**Phase 0 is diagnostic only.** No code changes. Just verification.

---

## Implementation Phases

### Phase 1: Pipeline Foundation
- `tools/pipeline/` — factor registry, normalizer, composer, config loader
- `tools/config/` — YAML strategy configs, factor registry
- Wired into existing `scan_swing_candidates` (additive, fallback preserved)

### Phase 2: DB Tables + Pre-Compute
- `factor_scores`, `market_snapshot` tables
- `compute_factors.py` cron job
- Scanner SQL query path

### Phase 3: Monitoring + Pattern Library
- `exit_patterns` table
- 60-second price checking loop
- Volume classification (5-bucket)
- Pattern library matching query
- EOD mechanical labeling (same-day + T+3 markout)

### Phase 4: Strategy Evolution
- Factor IC tracking + `signal_performance` table
- Auto-tune factor weights
- Weekly pattern review
- Strategy config proposal → human ratification

---

## What We NEVER Change

1. OPERATING_MANUAL.md is constitution
2. Agents never call broker directly
3. Strategy = YAML config, not Python code
4. Kill switch blocks `place_order`
5. Backtest uses same pipeline as live
6. EOD journal runs every day
7. Agent never labels its own exits — data does

---

## References

- `design/factor-scanner-tdd.md` — Factor ranking deep design (31KB)
- `design/pluggable-pipeline-plan.md` — Plugable pipeline plan (16KB)
- `OPERATING_MANUAL.md` — Constitution
- `sops/equity/swing/v1.0.0.md` — Current swing SOP
- `sops/_routing/v1.1.0.md` — Strategy routing
