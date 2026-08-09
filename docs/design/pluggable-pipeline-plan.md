# Scalable Scanner & Research Pipeline — Implementation Plan

**Status:** DRAFT — review and approve before execution
**Date:** 2026-06-28
**Goal:** End-to-end daily scan pipeline that covers 400 symbols, costs < $0.10/day, and adapts when strategies decay

---

## 0. Cost & Scale Analysis

### Cost per daily cycle

| Stage | What | Estimated Cost |
|-------|------|---------------|
| Data refresh | yfinance batch download (400 symbols) | Free |
| Factor compute | 14 factors × 400 stocks × pandas vectorized | Free (CPU) |
| Universe storage | SQLite — 400 × 14 × 1 row per day | Free (local) |
| LLM research | 10-15 candidates × ~3K tokens each | ~$0.03-0.05 |
| LLM trading decisions | 3-5 candidates × ~2K tokens each | ~$0.005-0.01 |
| LLM EOD journal | One report per day | ~$0.005 |

**Total per day:** ~$0.05-0.07 at DeepSeek pricing. $1.50-2.10/month.

### Scale ceiling

With yfinance batch downloads and vectorized pandas, we can handle 2000+ symbols before hitting meaningful time constraints. The LLM research stage is the only cost bottleneck. The funnel keeps LLM calls proportional to top candidates, not universe size — scanning 2000 symbols costs the same in LLM as scanning 400.

### Where cost balloons (and how we prevent it)

| Danger | Prevention |
|--------|-----------|
| LLM researching 50 candidates | Funnel limits top N to 15 |
| Re-scanning stale symbols | Exclusion list from EOD feedback bridge |
| Getting news for every symbol | News only fetched for top candidates, not universe |
| Social sentiment for everything | Sentiment only for top 5 scoring candidates |

---

## 1. Architecture: The Pluggable Pipeline

### Core principle

The pipeline is generic. Strategies are config. Factors are registered by name. Adding a new strategy means writing a config file. Removing a dead factor means changing `status: dead` in config. Nothing is hardcoded.

### Pipeline stages

```
STAGE 1: LOAD    → Read cached bars from SQLite (all 400 symbols, 252-day lookback)
                   Cost: free. Time: ~2s. Runs: once per day.

STAGE 2: COMPUTE  → Compute factors for every symbol (14 raw → z-scores → composites)
                   Cost: free. Time: ~30s. Runs: once per day.

STAGE 3: FILTER   → SQL query: WHERE price $10-500 AND dollar_vol > $50M
                   ORDER BY composite_score DESC LIMIT 40
                   Cost: free. Time: <10ms. Runs: per scan.

STAGE 4: REGIME   → Classify market regime. Apply engine eligibility.
                   Drop candidates for ineligible engines.
                   Cost: free. Time: <1ms. Runs: per scan.
                   40 → ~25 candidates

STAGE 5: DE-DUP   → Remove: recently traded, excluded symbols, same sector > 3
                   Cost: free. Time: <1ms. Runs: per scan.
                   25 → ~20 candidates

STAGE 6: PREVIEW  → For top 15: fetch news headlines + last price
                   Cost: free (yfinance). Time: ~3s. Runs: per scan.

STAGE 7: RESEARCH → LLM due diligence on top 10-15 candidates
                   Cost: ~$0.03-0.05. Time: ~30s. Runs: per scan.
                   15 → 5-8 recommended trades

STAGE 8: TRADE    → LLM validates, sizes, enters 2-4 positions
                   Cost: ~$0.01. Time: ~15s. Runs: per scan.
```

**Total pipeline time:** ~1.5 minutes. Cost: ~$0.05/day.

### What goes where

```
tools/pipeline/
├── __init__.py
├── config.py          # Loads pipeline config from YAML/JSON
├── loader.py          # Stage 1: load cached bars
├── factors.py         # Stage 2: factor registry + compute
├── normalizer.py      # Z-score, percentile, rank normalization
├── composer.py        # Weighted composite scoring
├── regime.py          # Stage 4: regime classifier
├── filterer.py        # Stage 3 + 5: liquidity + exclusion filters
├── funnel.py          # Orchestrates stages 1-5 (everything before LLM)

tools/server.py        # Stage 6-8: existing scan_swing_candidates tool
                       # → calls funnel.py for stages 1-5,
                       # → returns structured candidates for LLM agents

tools/config/
├── strategies/
│   ├── equity-swing-v1.yaml    # Engine M + Engine R config
│   └── equity-intraday-v1.yaml # Future
├── factors.yaml                # Factor registry: name → computer + params
└── regimes.yaml                # Regime classification rules
```

---

## 2. Factor Registry

### Design

Each factor is a named entry. Factors can be active, weakened, or dead. Weights are adjustable.

```yaml
# tools/config/factors.yaml
factors:
  momentum_63d:
    computer: rate_of_change
    params: {window: 63}
    normalize: zscore
    status: active
    weight: 0.25
    engine: [M]           # which engines use this factor

  momentum_21d:
    computer: rate_of_change
    params: {window: 21}
    normalize: zscore
    status: active
    weight: 0.15
    engine: [M]

  relative_strength_10d:
    computer: relative_strength
    params: {window: 10, benchmark: SPY}
    normalize: zscore
    status: active
    weight: 0.15
    engine: [M]

  atr_pct:
    computer: atr_percent
    params: {window: 10}
    normalize: zscore
    status: active
    weight: 0.10
    engine: [M, R]

  realized_vol_60d:
    computer: realized_vol
    params: {window: 60}
    normalize: zscore
    status: active
    weight: 0.10
    engine: [M, R]

  trend_alignment:
    computer: sma_alignment
    params: {fast: 25, slow: 50}
    normalize: zscore
    status: active
    weight: 0.10
    engine: [M]

  trend_long:
    computer: dist_from_sma
    params: {window: 200}
    normalize: zscore
    status: active
    weight: 0.15
    engine: [R]

  short_reversal:
    computer: negative_rate_of_change
    params: {window: 21}
    normalize: zscore
    status: active
    weight: 0.20
    engine: [R]

  rsi_3:
    computer: rsi
    params: {window: 3}
    normalize: zscore
    invert: true       # lower RSI = higher score for Engine R
    status: active
    weight: 0.20
    engine: [R]

  dollar_vol_20d:
    computer: dollar_volume
    params: {window: 20}
    normalize: percentile    # liquidity is a floor, not a tilt
    status: active
    weight: 0.10
    engine: [M, R]

  rvol:
    computer: relative_volume
    params: {window: 20}
    normalize: zscore
    status: active
    weight: 0.05
    engine: [M]
```

### Adding a factor

```python
# tools/pipeline/computers.py
@register_computer("rate_of_change")
def compute_roc(df: pd.DataFrame, window: int) -> float:
    return (df["close"].iloc[-1] / df["close"].iloc[-window-1] - 1) * 100

# That's it. The config entry above wires it into the pipeline.
# No scanner code changes needed.
```

### Removing/dead factor

```yaml
rsi_14:
  status: dead
  reason: "IC < 0 for 8 weeks. Last effective: 2026-04."
  weight: 0.0
```

The pipeline reads `status` and skips dead factors. No code change.

---

## 3. Strategy Config

### Design

A strategy config defines everything that makes two strategies different: which factors, which weights, which engines, which entry rules, which exit rules.

```yaml
# tools/config/strategies/equity-swing-v1.yaml
strategy:
  id: equity/swing
  version: "1.0.0"
  
  engines:
    M:
      name: Momentum Continuation
      factors:
        momentum_63d: 0.30
        momentum_21d: 0.20
        relative_strength_10d: 0.15
        trend_alignment: 0.15
        atr_pct: 0.10
        dollar_vol_20d: 0.05
        rvol: 0.05
      regime_rules:
        trending_calm: ON
        trending_volatile: ON
        choppy: OFF
        crash: OFF
      entry:
        type: market_on_open
        gap_rules:
          gap_up_max_pct: 5.0    # skip if gap > 5%
          gap_down_max_pct: 3.0  # skip if gap < -3%
      stop:
        type: atr_multiple
        multiplier: 2.5
        atr_window: 10
      profit_protection:
        breakeven_at_r: 1.0
        trail_at_r: 1.5
        trail_atr_mult: 2.0
      exit:
        time_stop_sessions: 20
      
    R:
      name: Mean-Reversion Dip
      factors:
        short_reversal: 0.25
        rsi_3: 0.25
        trend_long: 0.20
        realized_vol_60d: 0.10
        dollar_vol_20d: 0.10
        atr_pct: 0.10
      regime_rules:
        trending_calm: ON
        trending_volatile: ON
        choppy: ON
        crash: OFF
      entry:
        type: limit_order
        limit_offset_atr_pct: -3.0   # limit 3% below prev close
        day_only: true
      stop:
        type: atr_multiple
        multiplier: 2.5
        atr_window: 10
      profit_protection:
        breakeven_at_r: null        # no breakeven for R
        trail_at_r: null
      exit:
        target_r: 1.5               # exit at 1.5R
        time_stop_sessions: 4

  selection:
    max_candidates_per_engine: 15
    max_total_positions: 10
    max_daily_trades: 4
    max_same_sector: 3
    min_composite_score: 0.0        # must be above universe median
```

### What this enables

- **Swap strategies**: change the config file. Pipeline doesn't change.
- **A/B test**: run engine M from swing-v1 but engine R from swing-v2 by loading two configs.
- **Backtest reproducibility**: pin the config version in the backtest run record.
- **Parameter sweeps**: vary `stop.multiplier` from 2.0 to 3.5 across backtest runs, find optimum.

---

## 4. Implementation Phases

### Phase 0: Operational (get it working)

| Step | What | Why |
|------|------|-----|
| 0.1 | Verify data pipeline | Can we refresh 400 symbols and store bars? |
| 0.2 | Check cron jobs | Are morning scans actually firing? |
| 0.3 | Verify MCP server | Can agents reach tools? |
| 0.4 | Run end-to-end dry run | Does Risk→Research→Trade→Monitor→EOD complete? |
| 0.5 | Fix whatever breaks | Operational gaps before architecture work |

This phase is **diagnose only** — no new code, just verify what exists works.

### Phase 1: Pipeline Foundation

| Step | What | Code |
|------|------|------|
| 1.1 | `tools/pipeline/computers.py` | Factor computation functions with registry decorator |
| 1.2 | `tools/pipeline/normalizer.py` | Z-score, percentile, rank normalization |
| 1.3 | `tools/pipeline/composer.py` | Weighted composite scoring (reads config) |
| 1.4 | `tools/pipeline/config.py` | Load YAML config, validate |
| 1.5 | `tools/config/factors.yaml` | Default factor registry (existing gates → factors) |
| 1.6 | `tools/pipeline/funnel.py` | Stages 1-5 orchestration |
| 1.7 | Wire into `scan_swing_candidates` | Funnel runs before LLM research |
| 1.8 | Tests for each module | Unit tests for normalize, compose, config load |

### Phase 2: DB Tables + Pre-Compute

| Step | What | Code |
|------|------|------|
| 2.1 | `market_snapshot` + `factor_scores` tables | Schema in `db.py` |
| 2.2 | `tools/scripts/compute_factors.py` | Batch job: compute → store |
| 2.3 | `repo.query_factor_scores()` | Query method in repository |
| 2.4 | Cron: compute_factors after data refresh | Schedule in cron config |
| 2.5 | Scanner SQL path | `scan_by_factor_scores()` reads pre-computed |

### Phase 3: Research Enhancement

| Step | What | Code |
|------|------|------|
| 3.1 | Funnel passes factor z-scores to Research agent | MCP tool return shape update |
| 3.2 | Research skill updated for factor profiles | SKILL.md §Layer 2 rewrite |
| 3.3 | Sector concentration filter | Group top candidates by sector, cap at 3 |
| 3.4 | News batch fetch | Fetch news for top 15, not all 400 |

### Phase 4: Strategy Lifecycle (after 4+ weeks of paper trading)

| Step | What | Depends on |
|------|------|-----------|
| 4.1 | `signal_performance` table | Phase 2 |
| 4.2 | IC computation | Trade outcome data |
| 4.3 | EOD auto-tunes factor weights | Phase 2 + 4.2 |
| 4.4 | Dead factor auto-removal | Phase 4.3 |
| 4.5 | Strategy A/B testing in backtest | Phase 2 + backtest harness |

---

## 5. What We NEVER Change

These are inviolate. The pipeline architecture must preserve every one:

1. **OPERATING_MANUAL.md is constitution.** Modes, limits, circuit breakers.
2. **Agents never call Alpaca directly.** All through MCP tools.
3. **SOPs are human-controlled.** Config files are proposed by agents, ratified by human.
4. **Kill switch blocks `place_order`.** Checked in server.py, not configurable.
5. **Backtest uses same code path as live.** Same pipeline, different broker reference.
6. **No hardcoded strategy logic.** All thresholds in config, not code.
7. **EOD journal runs every day.** Even zero-trade days. Even HALTED.

---

## 6. Adaptability: How Strategies Evolve

### Adding a new strategy

1. Write `tools/config/strategies/equity-pairs-v1.yaml`
2. Add factor functions if needed
3. Pipeline picks it up — zero code changes

### Tuning hyperparameters

1. Run backtest sweep varying `stop.multiplier` from 1.5 to 4.0
2. Find optimum
3. Edit `equity-swing-v1.yaml` → `stop.multiplier: 2.8`
4. Commit new config version
5. Next morning: scanner reads new multiplier

### Discovering new factors

1. Write a new `@register_computer` function
2. Add to `factors.yaml` with `status: unproven, weight: 0.05`
3. Run for 4 weeks
4. Check IC > 0.03 → promote to `weight: 0.15, status: active`
5. Check IC < 0 → set `status: dead`

### Responding to regime change

If the market shifts from trending to choppy long-term:
1. EOD agent detects: `regime == 'choppy'` for 10+ consecutive days
2. Auto-adjusts factor weights per `equity-swing-v1.yaml` choppy row
3. Momentum drops from 0.35 → 0.15, reversal rises from 0.10 → 0.30
4. Config file drives it — no code change, no deploy

---

## 7. Data Pipeline (Daily Cron)

```
06:00 ET   refresh_market_data   → yfinance pull 400 symbols + SPY, store bars
06:02     compute_market_snapshot → VIX, bread in, correlations, regime label
06:03     compute_factors        → 14 factors × 400 symbols, z-scores, composites
06:04     store in DB            → factor_scores table + market_snapshot table
06:35     launch-equity cron     → kanban workflow begins
          ├─ scan_swing_candidates → SQL query (instant)
          ├─ Research agent        → DD on top 10-15
          ├─ Risk agent            → preflight + mode
          ├─ Trader agent          → size + execute
          ├─ Monitor agent         → check open positions
          └─ EOD agent             → journal + tuning config
```

---

## 8. Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Scanned universe | 400 symbols (binary gates) | 400 symbols (factor composite) |
| Scan time | ~5-10s (per-stock loop) | <0.1s (SQL query) |
| Daily LLM cost | Unknown | <$0.10 |
| Factor compute time | N/A | <45s |
| Adapt to new strategy | Edit Python code | Edit YAML config |
| Add factor | 15 lines in filters.py | 1 function + 1 config entry |
| Dead factor removal | Comment out code | Set `status: dead` in YAML |
| Signal IC visibility | None | Rolling IC per factor, weekly report |

---

## 9. Open Decisions (for you)

1. **Config format**: YAML or JSON? YAML is more readable for config files. JSON is easier to validate programmatically. Preference?

2. **Old code removal**: When do we delete the binary-gate code in `filters.py`? After Phase 2 is validated? Never (keep as fallback)?

3. **Intraday data**: Do we want intraday bars eventually? If yes, the factor compute would need to handle 5-min bars differently than daily. Design for it now or YAGNI?

4. **Strategy backtest config**: Should backtests read the SAME `equity-swing-v1.yaml` that live trading uses? Or should backtests have their own config copies?

5. **Start with Phase 0**: Do you want me to diagnose the current operational state first (cron health, MCP connectivity, data freshness, end-to-end dry run), then we proceed to build Phase 1?
