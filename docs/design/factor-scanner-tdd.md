# Technical Design Document: Factor-Based Scanner Replacement

**Version:** 1.0.0 — DRAFT FOR REVIEW
**Date:** 2026-06-28
**Status:** DESIGN PHASE — no implementation started
**Author:** Hermes Agent (Agent Orchestrator)
**Review required by:** Human operator before any code changes

---

## 1. Executive Summary

The current scanner (`tools/scanner/filters.py`) uses single-stock binary gates (RSI
40-70, RS > 2%, RVOL > 1.1) derived from 1990s-era technical analysis. Academic
research (q-fin.ST, 2020-2026) shows that professional quantitative funds have
moved to cross-sectional factor-based ranking, regime-adaptive weighting, and
signal-decay monitoring. The gap between our scanner and the state of the art is
substantial and represents the largest single leverage point in the system.

**This document proposes:**

1. Replace binary gates with cross-sectional factor ranking (Phase 1)
2. Add market-regime detection and regime-adaptive factor weighting (Phase 1)
3. Pre-compute factor scores into the existing SQLite database (infrastructure)
4. Add signal performance monitoring with automated decay detection (Phase 2)
5. Wire decay signals into the existing EOD-to-scanner feedback bridge (Phase 2)

**What does NOT change:**
- The SOP (`sops/equity/swing/v1.x.x.md`) remains the strategy authority
- The LLM Research agent still does final due diligence
- The EOD review agent still generates tuning config
- The MCP tool signatures agents call are preserved
- All risk invariants from `OPERATING_MANUAL.md` are preserved
- No hardcoded strategy logic — all thresholds live in data, not code

---

## 2. Problem Statement: What's Wrong With Binary Gates

### 2.1 Current Architecture

```
For each stock in universe:
    if price < $10 or price > $500:       → FAIL, next stock
    if avg_vol < 2M:                       → FAIL, next stock
    if atr_pct < 1.5 or atr_pct > 5:      → FAIL, next stock
    if rvol < 1.1:                         → FAIL, next stock
    if rs_10d <= 2:                        → FAIL, next stock
    if RSI < 40 or RSI > 70:              → FAIL, next stock
    if not macd_bullish:                   → FAIL, next stock
    if not price > SMA20 > SMA50:         → FAIL, next stock
    if chasing:                            → FAIL, next stock
    → CANDIDATE
```

Every gate is: absolute threshold applied to one stock in isolation. A stock with
RSI 39.8 fails. A stock with RSI 40.1 passes. The difference is 0.3 units of an
oscillator with no cross-sectional meaning.

### 2.2 Specific Failures

**Failure 1: Regime blindness.** `rs_10d > 2` means nothing in a bear market
(400/500 stocks pass because SPY is down 15%, everything has "relative strength")
and nothing in a bull market (everything passes for the opposite reason). The
threshold's semantics change daily but the value doesn't.

**Failure 2: Border kills.** A stock that fails RSI by 0.1 but dominates on
every other dimension gets killed. A stock that barely passes every gate gets
through. There's no compensation — one weak signal vetoes all strong ones.

**Failure 3: No universe context.** The scanner has no idea that AAPL with
RS_10d=3.2 is actually WEAK compared to the rest of the tech sector this week.
It only knows 3.2 > 2.0 → pass.

**Failure 4: Static thresholds.** The SWING_V1 dictionary has been tuned by hand
with no empirical basis for where the thresholds should be. They are
`BOOK-DERIVED` and `PLACEHOLDER-FAIL-SAFE` tags on every gate in the SOP.

**Failure 5: No marginal contribution measurement.** We don't know which of the
8 gates actually predict returns. Some may be neutral. Some may be negative.
Some may be redundant. We have no mechanism to discover this.

### 2.3 The Academic Consensus

From our literature review (arXiv: q-fin.ST, 2016-2026):

| Finding | Source | Implications |
|---------|--------|-------------|
| 191 trading signals → only 17 survive LASSO selection after controlling for fundamentals | 2601.06499 (2026) | 91% of indicator-style signals are noise |
| Factor momentum works at short lags (<3mo) but is mostly spanned by stock momentum | 2009.04824 (2020) | Factor-level timing matters; single-stock technicals don't |
| Cross-sectional z-scores outperform absolute thresholds in every tested regime | Multiple papers | Core design principle |
| Factor crowding causes alpha decay; uncrowded signals outperform | 2002.03319 (2020) | Need decay monitoring |
| Factor relationships evolve over time, especially during crises | 2111.05072 (2021) | Static weights are wrong by construction |
| Order-flow microstructural signals contain predictive power beyond OHLCV | 2604.20949 (2026) | Future direction when tick data available |
| LLM-driven alpha mining outperforms hand-designed factors when iterated | 2602.07085 (2026) | Our LLM Research agent is an advantage, not a substitute for quant |

---

## 3. Proposed Architecture

### 3.1 Core Principle: Rank, Don't Filter

```
CURRENT (binary filtering):
    Stock → Gate 1 pass/fail → Gate 2 pass/fail → ... → Gate N pass/fail → CANDIDATE or KILLED

PROPOSED (cross-sectional ranking):
    All stocks → Compute all factors → Z-score normalize across universe →
    Weighted composite score → Rank by composite → Top N = candidates
```

A stock that is weak on one factor but exceptional on others gets ranked
appropriately. A stock that is "average" on everything gets a middle rank —
not falsely passed because it cleared every gate, not falsely failed because
it missed one.

### 3.2 Factor Taxonomy

These factors are computable from our EXISTING daily OHLCV data. Nothing here
requires intraday or alternative data.

#### A. Momentum Factors (4 signals)

| Factor | Computation | Window | Source justification |
|--------|------------|--------|---------------------|
| `roc21` | % change close over 21 days | 1 month | Short-term momentum |
| `roc63` | % change close over 63 days | 3 months | Medium momentum (dominant in lit) |
| `roc126` | % change close over 126 days | 6 months | Classic momentum factor |
| `rs_10d` | `roc10_stock - roc10_spy` | 10 days | Relative strength (existing) |

#### B. Volatility Factors (3 signals)

| Factor | Computation | Source justification |
|--------|------------|---------------------|
| `atr_pct` | ATR10 / close | Existing gate M-G3, R-G3 |
| `realized_vol_60d` | Annualized std of daily returns over 60d | Low-vol anomaly (Fama-French) |
| `beta_spy` | Cov(stock_returns, spy_returns) / Var(spy_returns) over 252d | CAPM beta |

#### C. Trend Quality Factors (3 signals)

| Factor | Computation | Source justification |
|--------|------------|---------------------|
| `sma_alignment` | `(price / sma25 - 1) + (sma25 / sma50 - 1)` — continuous | Existing M-G4 |
| `dist_from_200ma` | `(price / sma200 - 1) * 100` | Trend strength |
| `dd_from_52wk_high` | `(price / high_252d - 1) * 100` | Drawdown from peak |

#### D. Liquidity Factors (2 signals)

| Factor | Computation | Source justification |
|--------|------------|---------------------|
| `dollar_vol20` | Avg(close * volume) over 20 days | Existing M-G2, R-G2 |
| `rvol` | volume_today / avg_vol_20d | Existing gate |

#### E. Valuation Factors (2 signals, for anti-momentum / mean-reversion)

| Factor | Computation | Source justification |
|--------|------------|---------------------|
| `return_1m_inverse` | `-1 * roc21` | Short-term reversal (Fama-French) |
| `rsi_3` | RSI(3) | Existing R-G5 — extreme readings for reversion |

**Total: 14 raw factors.** Each gets z-scored cross-sectionally → 14 z-scores.

### 3.3 Factor Combination: Composite Score

Raw z-scores → regime-weighted sum → composite score.

```python
# Each factor gets a z-score: (raw - universe_mean) / universe_std
# The composite is a weighted sum of z-scores:

composite = sum(
    weight[factor] * z_score[factor]
    for factor in active_factors
)
```

Weights come from two sources, applied multiplicatively:

1. **Strategy weights** (from SOP): which factors matter for Engine M vs Engine R
2. **Regime weights** (from §4): how much does each factor matter in the current regime?  
3. **Decay adjustment** (from §6): has this factor's predictive power decayed?

The Research agent gets both the composite score AND the individual factor
z-scores. The agent does the final DD and can override based on qualitative
factors (catalyst, thesis-break, etc.).

### 3.4 Two-Engine Scoring

The current scanner produces `engine_m_pass` and `engine_r_pass`. We preserve
this but make it continuous:

```python
# Engine M composite: momentum-heavy, trend-aligned
engine_m_composite = (
    0.35 * mom_z      +  # ROC63 z-score
    0.20 * mom_short_z +  # ROC21 z-score
    0.15 * rs_z       +  # Relative strength z-score
    0.15 * trend_z    +  # SMA alignment z-score
    0.10 * quality_z  +  # Trend quality
    0.05 * liq_z         # Liquidity
)

# Engine R composite: reversion-heavy, long-uptrend-filtered
engine_r_composite = (
    0.30 * reversal_z     +  # Short-term reversal (inverse momentum)
    0.25 * rsi3_z         +  # RSI(3) — lower is better for dips
    0.20 * trend_long_z   +  # Must be > SMA200
    0.15 * quality_z      +  # Quality filter
    0.10 * liq_z             # Liquidity
)
```

The Research agent sees both engine scores and uses routing SOP §2 to determine
which strategy applies.

---

## 4. Regime Detection

### 4.1 Design Principle

Pros don't detect regimes from the same signals they trade on — that's circular.
Regime classification uses **market-wide** inputs: index behavior, volatility
levels, market breadth, and correlations.

Our inputs are all computable from data we already have (SPY bars in SQLite +
VIX from Alpaca or Yahoo):

| Input | Source | What it measures |
|-------|--------|-----------------|
| `spy_trend` | SPY vs SMA50, SMA200 | Directional regime |
| `vix_level` | Alpaca or Yahoo | Fear/uncertainty |
| `spy_tr_atr` | SPY true range / ATR20 | Intraday stress |
| `breadth_pct` | % of tracked symbols above SMA50 | Market participation |
| `avg_pairwise_corr` | Mean of correlation matrix of top 50 by volume | Diversification / crowding |

### 4.2 Regime Classes

Four regimes, following the academic consensus plus our routing SOP categories:

| Regime | Conditions | Factor tilt | Max positions |
|--------|-----------|-------------|---------------|
| `trending_calm` | SPY > SMA50, VIX < 20, breadth > 50% | Momentum 0.40, Quality 0.15, Growth 0.15 | 10 |
| `trending_volatile` | SPY > SMA50, VIX 20-30 | Momentum 0.25, Quality 0.30, LowVol 0.25 | 5 |
| `choppy` | SPY near SMA50 (±3%), VIX < 25 | Momentum 0.15, Value 0.30, Quality 0.25, Reversal 0.20 | 3 |
| `crash` | SPY < SMA200, VIX > 30, or SPY tr/ATR > 2.0 | Quality 0.40, LowVol 0.40, Momentum 0.00 | 1 (if any) |

### 4.3 Implementation

Not a Hidden Markov Model — too complex, needs training data we don't have, and
overfits. Instead: **rule-based classifier with fuzzy edges**.

```python
def classify_regime(snapshot: dict) -> tuple[str, float]:
    """
    Returns (regime_label, confidence).
    
    Labels: trending_calm, trending_volatile, choppy, crash
    
    Rules, evaluated in priority order:
    1. crash:    (spy < sma200 and vix > 30) or spy_tr_atr > 2.0
    2. trending: above sma50, check VIX for calm vs volatile substate
    3. choppy:   near sma50, or mixed signals
    """
```

Confidence score enables soft regime boundaries. When confidence < 0.6, the
scanner uses blended weights from the two nearest regimes.

### 4.4 Integration with Routing SOP

The regime classifier output maps directly to the routing SOP §1 eligibility
table:

| Regime | `equity/swing` |
|--------|---------------|
| `trending_calm` | ON (both engines) |
| `trending_volatile` | M-ONLY |
| `choppy` | R-ONLY |
| `crash` | OFF |

This replaces the manual regime check the Research agent currently does as a
precondition. The scanner itself enforces it — crashed regime means zero scanning.

---

## 5. Database Architecture

### 5.1 Principle: Pre-Compute Once, Query Many Times

Factor computation is expensive (14 signals × 500 stocks × 160-bar DataFrames).
Scanning must be instant. So: factors are computed ONCE per day in a batch job,
stored in SQLite, and the scanner is a SQL query.

### 5.2 New Tables

All in the existing `tools/trading.db`. Same file, same `Repository` class,
same WAL mode.

#### Table: `market_snapshot`

```sql
CREATE TABLE market_snapshot (
    date TEXT PRIMARY KEY,
    spy_close REAL,
    spy_sma50 REAL,
    spy_sma200 REAL,
    spy_trend TEXT,              -- 'up', 'down', 'flat'
    spy_tr_atr REAL,             -- today's TR / 20-day ATR
    vix_close REAL,
    breadth_pct_above_50ma REAL, -- % of universe above SMA50
    avg_pairwise_corr REAL,      -- mean correlation of top 50
    regime TEXT,                 -- 'trending_calm', 'trending_volatile', 'choppy', 'crash'
    regime_confidence REAL,      -- 0.0-1.0
    computed_at TEXT
);
```

One row per trading day. Computed after market close or pre-market.

#### Table: `factor_scores`

```sql
CREATE TABLE factor_scores (
    date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    -- Raw factors
    roc21 REAL, roc63 REAL, roc126 REAL,
    rs_10d REAL,
    atr_pct REAL, realized_vol_60d REAL,
    sma_alignment REAL, dist_from_200ma REAL, dd_from_52wk_high REAL,
    dollar_vol20 REAL, rvol REAL,
    return_1m_inverse REAL, rsi_3 REAL,
    beta_spy REAL,
    -- Cross-sectional z-scores (normalized within 'date')
    mom_z REAL, mom_short_z REAL, rs_z REAL,
    vol_z REAL, trend_z REAL, trend_long_z REAL, quality_z REAL,
    liq_z REAL, reversal_z REAL, rsi3_z REAL,
    -- Engine composites (regime-weighted)
    engine_m_composite REAL,
    engine_r_composite REAL,
    -- Metadata
    computed_at TEXT,
    PRIMARY KEY (date, symbol)
);

CREATE INDEX idx_factor_scores_date_m ON factor_scores(date, engine_m_composite DESC);
CREATE INDEX idx_factor_scores_date_r ON factor_scores(date, engine_r_composite DESC);
CREATE INDEX idx_factor_scores_date_liq ON factor_scores(date, dollar_vol20 DESC);
```

#### Table: `signal_performance`

```sql
CREATE TABLE signal_performance (
    period TEXT NOT NULL,        -- '2026-Q2' or '2026-06'
    factor_name TEXT NOT NULL,
    information_coefficient REAL, -- Rank correlation(signal, forward_return)
    long_short_spread REAL,      -- Top quintile - bottom quintile return
    turnover REAL,               -- % of names that change quintile month/month
    status TEXT,                 -- 'healthy', 'weakening', 'dead', 'unproven'
    updated_at TEXT,
    PRIMARY KEY (period, factor_name)
);
```

### 5.3 Scanner as SQL Query

The `scan_swing_candidates` MCP tool becomes:

```python
def scan_swing_candidates(lookback_days: int = 120) -> str:
    # Step 1: Get today's date and regime
    today = get_today_date()
    regime = repo.get_market_snapshot(today).get("regime", "trending_calm")
    
    # Step 2: If regime allows scanning (not crashed):
    if regime == "crash":
        return json.dumps({"candidates": [], "regime": "crash", "reason": "market halted"})
    
    # Step 3: Query pre-computed scores
    candidates = repo.query_factor_scores(
        date=today,
        min_dollar_vol=50_000_000,
        min_price=10,
        max_price=500,
        engine=engine_for_regime(regime),  # 'M' or 'R' or 'both'
        min_composite=-99,  # No minimum — get all, let the agent decide
        order_by=composite_field_for_regime(regime),
        limit=40,
    )
    
    # Step 4: Return same shape as today (agent compatibility)
    return json.dumps({
        "candidates": candidates,
        "scanned": repo.count_factor_scores(today),
        "regime": regime,
        "sop_version": "equity/swing v1.0.0",
    })
```

The MCP tool signature is preserved. Agents see the same return shape.

### 5.4 Batch Computation Job

```python
# tools/scripts/compute_factors.py
# Runs at 6:00 AM ET via cron, after refresh_market_data

def main():
    repo = Repository()
    
    # 1. Load all cached daily bars (one query, returns dict)
    bars = load_all_daily_bars(repo, lookback=252)
    
    # 2. Compute market snapshot (SPY + breadth + correlations)
    snapshot = compute_market_snapshot(bars, vix= fetch_vix())
    repo.save_market_snapshot(snapshot)
    
    # 3. Compute raw factors for every stock (vectorized, ~30s for 500 stocks)
    raw_factors = compute_all_raw_factors(bars)
    
    # 4. Cross-sectional normalization (z-scores)
    z_scores = normalize_cross_section(raw_factors)
    
    # 5. Regime-weighted composite scores
    composites = compute_composites(z_scores, snapshot["regime"])
    
    # 6. Bulk insert (one SQL INSERT with 500 rows)
    repo.save_factor_scores(composites)
```

Duration: ~35 seconds for 500 stocks on a modern CPU. Runs once, pre-market.

### 5.5 Integration With Existing Cron

The existing morning pipeline (from `deploy/runs/equity.yaml`):

```
06:00  refresh_market_data     → loads fresh bars
06:05  compute_factors          → NEW: batch factor computation
06:35  launch-equity            → kanban workflow begins
       └─ scan_swing_candidates → now a SQL query, not per-stock computation
```

---

## 6. Signal Performance Monitoring (Phase 2)

### 6.1 Information Coefficient

The Information Coefficient (IC) is the rank correlation between a factor's
z-score and forward returns. It's the single most important metric for whether
a signal works.

```python
def compute_ic(factor_scores: list, forward_returns: list) -> float:
    """
    Spearman rank correlation between factor z-scores at time t
    and forward N-day returns.
    """
    from scipy.stats import spearmanr
    return spearmanr(factor_scores, forward_returns).correlation
```

### 6.2 Decay Rules

Updated weekly by EOD agent via the tuning bridge:

| IC range | Status | Action |
|----------|--------|--------|
| IC > 0.05 | healthy | Full weight in composite |
| 0.02 < IC ≤ 0.05 | weakening | Reduce weight by 50% |
| 0.00 < IC ≤ 0.02 | warning | Reduce weight by 75%, flag for review |
| IC ≤ 0.00 for 4+ weeks | dead | Zero weight, log for manual review |
| < 8 weeks of data | unproven | Default weight, don't tune yet |

### 6.3 Integration With Feedback Bridge

The existing `generate_tuning_config` MCP tool gains a new parameter:

```python
generate_tuning_config(
    # Existing params preserved:
    exclude_symbols=[...],
    threshold_overrides={...},
    risk_limit_overrides={...},
    
    # New: factor decay adjustments
    factor_weight_adjustments={
        "mom_z": 0.5,         # halved — IC dropping in choppy regime
        "vol_z": 1.0,         # full weight — still healthy
        "rs_z": 0.0,          # killed — IC negative for 6 weeks
    },
    factor_status={
        "mom_z": "weakening",
        "rs_z": "dead",
    },
    notes="RS_10d IC negative since May. Dropped from composite. Review in July."
)
```

The EOD agent's Step 6 (feedback bridge) already has the rules for threshold
adjustment. This extends it with factor-level decay monitoring. Same mechanism,
richer data.

---

## 7. Risk Invariants (Preserved From Current System)

This design MUST preserve every invariant from `OPERATING_MANUAL.md`. Here is
the explicit mapping:

| Invariant | Current mechanism | Preserved by |
|-----------|------------------|--------------|
| Kill switch blocks all orders | `_kill_switch_state` in server.py | Unchanged |
| Preflight runs before any trade | Orchestrator skill §2 | Unchanged |
| Mode computed from state, not chosen | `OPERATING_MANUAL.md` §1 | Unchanged |
| SOP is strategy authority | `sops/equity/swing/v1.x.x.md` | Unchanged — factor weights derived from SOP gates |
| Agents never call Alpaca directly | MCP tools as broker abstraction | Unchanged |
| SOPs versioned, never edited in place | Semver version files | Unchanged |
| Circuit breakers enforced mechanically | `risk/checks.py` | Unchanged |
| EOD compliance scoring | `skills/eod-review/SKILL.md` | Extended — gains factor IC metrics |
| Scanner → candidate → LLM DD flow | 5-Layer DD stack in Research skill | Enhanced — LLM gets factor z-scores alongside raw signals |
| Entry gap rules (M: gap>5%=skip, R: limit order discipline) | Research skill | Enhanced — gap detection uses pre-computed prev_close |
| 2% daily loss limit, 3 consecutive loss circuit breaker | `risk/checks.py` | Unchanged |

### 7.1 New Risk Consideration: Factor Crowding

When a factor's IC stays elevated (>0.08) for 6+ months, it may attract
crowding. The `signal_performance` table tracks turnover. If turnover is
dropping (same names stay in same quintiles) but IC is high → possible
overfitting. The weekly EOD report flags "elevated crowding risk" on factors
with IC > 0.08 AND turnover < 20%.

The Response: reduce factor weight by 25%, not eliminate. Crowded factors can
still contribute; they just shouldn't dominate.

---

## 8. Agent Impact

### 8.1 What Agents See (API Compatible)

The `scan_swing_candidates` MCP tool returns:

```json
{
  "candidates": [
    {
      "symbol": "NVDA",
      "price": 220.50,
      "engine_m_composite": 1.85,
      "engine_r_composite": -0.32,
      "engine_m_pass": true,
      "engine_r_pass": false,
      "factor_zs": {
        "mom_z": 2.10, "rs_z": 1.54, "trend_z": 1.21,
        "vol_z": -0.43, "quality_z": 0.87, "liq_z": 1.92
      },
      "raw": {
        "roc63": 34.2, "rs_10d": 5.1, "atr_pct": 2.8,
        "dollar_vol20": 32000000000, "rvol": 1.4
      }
    }
  ],
  "scanned": 395,
  "regime": "trending_calm",
  "regime_confidence": 0.85,
  "sop_version": "equity/swing v1.0.0"
}
```

Key additions to the existing return shape:
- `factor_zs`: the normalized factor scores driving the composite
- `regime_confidence`: how certain the regime classification is
- `engine_m_composite`: continuous score instead of just boolean pass/fail
- `engine_m_pass` preserved for backward compatibility (derived: `composite > 0`)

### 8.2 Research Agent Changes

The Research agent's 5-layer DD stack changes at Layer 2 and Layer 4:

**Layer 2 (Trend & Relative Strength):** Instead of reading raw RSI/MACD/RS
values, the agent reads factor z-scores. A `mom_z` of -0.5 means "this stock
ranks in the bottom 30% on momentum today." More actionable than "RSI is 47."

**Layer 4 (Technical Setup):** The agent sees the full per-factor breakdown and
can flag "this stock has exceptional momentum but terrible trend quality — it's
extended, going parabolic" — something the raw numbers alone wouldn't show.

**Output format** gains a new section:

```
### Factor Profile
| Factor | Z-Score | Percentile | Direction |
|--------|---------|------------|-----------|
| Momentum (63d) | +1.85 | 97th | Strong ⬆️ |
| Relative Strength | +0.92 | 82nd | Good ⬆️ |
| Trend Quality | -0.45 | 33rd | Weak ⬇️ |
| Volatility | +0.23 | 59th | Neutral |
```

### 8.3 EOD Agent Changes

EOD agent steps 6a-6d (tuning config generation) gain:

- **Step 6f: Factor performance review**: compute rolling IC for each factor,
  update `signal_performance` table, adjust weights in tuning config
- **Step 6g: Regime review**: verify that yesterday's regime classification
  matched actual market behavior. If misclassified, flag for review.

---

## 9. Implementation Phases

### Phase 1: Foundation (this cycle)

| # | Component | Effort | Risk |
|---|-----------|--------|------|
| 1.1 | Add `factor_scores` + `market_snapshot` tables to `db.py` | Small | None — additive schema change |
| 1.2 | `tools/analysis/factors.py` — raw factor computation functions | Medium | None — pure functions, unit-testable |
| 1.3 | `tools/analysis/regime.py` — extend with `classify_regime()` | Small | Low — extends existing module |
| 1.4 | `tools/scripts/compute_factors.py` — batch computation script | Medium | Low — reads from cache, writes to DB |
| 1.5 | `tools/scanner/filters.py` — new `scan_by_factor_scores()` path | Medium | Low — additive, old path preserved |
| 1.6 | `tools/server.py` — updated `scan_swing_candidates` with fallback | Small | Low — fallback to old path if no factor data |
| 1.7 | Tests for factor computation, normalization, regime classification | Medium | None |
| 1.8 | Cron: add `compute_factors` after `refresh_market_data` | Trivial | None |

**Total Phase 1:** ~500 lines new code, ~200 lines modified. All additive.

### Phase 2: Signal Monitoring (after Phase 1 validated)

| # | Component | Effort | Risk |
|---|-----------|--------|------|
| 2.1 | `signal_performance` table | Trivial | None |
| 2.2 | IC computation in `tools/analysis/factors.py` | Small | None |
| 2.3 | EOD skill §6f: factor performance review | Small | None |
| 2.4 | `generate_tuning_config` extended with `factor_weight_adjustments` | Small | Low |
| 2.5 | Scanner reads decay-adjusted weights from tuning config | Small | Low |
| 2.6 | Weekly decay report to operator | Small | None |

**Total Phase 2:** ~200 lines new code. All additive.

### Phase 3: Future (dependencies not met)

| Component | Dependency |
|-----------|-----------|
| Microstructure signals (order flow, VPIN) | Tick data — not available on Alpaca free tier |
| LASSO-based factor selection | Needs 6+ months of live paper-trading data with factor scores logged at entry |
| LLM-driven alpha mining (QuantaAlpha-style) | Major research project; separate design doc |

---

## 10. Migration & Rollback

### 10.1 Migration Strategy

The old scan path (`_swing_metrics` with binary gates) is **preserved, not
deleted**. The MCP tool `scan_swing_candidates` uses a flag:

```python
def scan_swing_candidates(..., use_factors: bool = True) -> str:
    if use_factors:
        try:
            return scan_by_factor_scores(...)
        except (NoFactorDataError, Exception):
            # Fall back to old binary gates
            return scan_by_binary_gates(...)
    else:
        return scan_by_binary_gates(...)
```

This means:
- If factor scores exist → use new path
- If factor scores don't exist (first run, migration in progress) → use old path
- Operator can pass `use_factors=false` to force old behavior

### 10.2 Rollback

1. Stop factor computation cron
2. Set `use_factors = False` in the MCP tool call (or remove the flag)
3. System continues with binary gates — zero data loss, zero downtime

### 10.3 Validation Criteria

Before removing the old path:

- [ ] Factor-based scan returns candidates with correlation > 0.7 to binary-gate
      scan under NORMAL regime conditions (it should be similar, not identical —
      the point IS that it's different)
- [ ] 5+ full trading cycles completed with factor-based scan under paper trading
- [ ] No regressions: all existing tests pass
- [ ] Regime classification correctly identifies crash conditions (VIX > 30 test)
- [ ] Factor scores table stays current (no days where `compute_factors` silently
      failed)
- [ ] Compositing doesn't surface obviously bad candidates (negative earnings,
      penny stocks, halted stocks)

---

## 11. Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|-----------|
| Factor computation fails silently, scan returns empty | Medium | Health check: assert `factor_scores` row count ≈ universe size. Alert if < 90%. |
| Regime misclassification → wrong engine active | Medium | Confidence threshold: if < 0.6, blend regimes. Log regime changes with reasoning. |
| Correlation breakdown in crisis → regimes shift faster than daily update | High | Intraday VIX threshold: if VIX jumps > 25% intraday, force DEFENSIVE (existing rule). |
| Over-optimization to backtest period | High | All factor weights are adjustable via tuning config, not hardcoded. No curve-fitting. |
| Composite score surface-minimum (flat region) → ranking unstable | Low | Rank by composite, not filtered by threshold. Ranking is stable even if scores are close. |
| Factor decay faster than weekly monitoring | Low | Phase 2 adds daily IC tracking. Until then, SOP thresholds provide a floor. |
| Liquidity filter too aggressive → universe shrinks in bear market | Low | Dollar volume filter is relative (z-score) within the liquidity factor, not an absolute gate. |

---

## 12. Open Questions (for human operator)

1. **Factor weight initial values**: Should we start with equal weights for all
   14 factors, then let decay monitoring tune them? Or start with the
   SOP-derived weights shown in §3.4?

2. **Regime classification**: The rule-based classifier (§4) is simpler than
   an HMM but less adaptive to structural market changes. Acceptable for now?

3. **Engine R composite**: The reversion engine currently uses RSI3 and drop_3d
   as hard gates. Should the factor-based version use the same weights as
   Engine M but with inverted momentum? Or a completely separate set?

4. **Scan frequency**: Currently factors are computed once/day. Should we add
   an intraday refresh if the market regime shifts mid-session (e.g., VIX
   spikes from 18 to 32 at 2 PM)?

5. **Phase 2 timing**: Signal decay monitoring requires trade outcomes. Should
   we wait for N weeks of paper-trading data before implementing Phase 2?

6. **Removal of old binary-gate code**: How many cycles with both paths
   running before we delete `_swing_metrics`?

---

## 13. References

### Academic

- Cross-Market Alpha via Double-Selection LASSO (Du, Walter, Ulrich 2026) — [arXiv:2601.06499](https://arxiv.org/abs/2601.06499)
- Is Factor Momentum More than Stock Momentum? (Falck, Rej, Thesmar 2020) — [arXiv:2009.04824](https://arxiv.org/abs/2009.04824)
- QuantaAlpha: Evolutionary LLM-Driven Alpha Mining (Han et al. 2026) — [arXiv:2602.07085](https://arxiv.org/abs/2602.07085)
- From Factor Models to Deep Learning (Ye et al. 2024) — [arXiv:2403.06779](https://arxiv.org/abs/2403.06779)
- Generating Synergistic Formulaic Alpha Collections via RL (Yu et al. 2023) — [arXiv:2306.12964](https://arxiv.org/abs/2306.12964)
- The Evolving Causal Structure of Equity Risk Factors (D'Acunto et al. 2021) — [arXiv:2111.05072](https://arxiv.org/abs/2111.05072)
- Crowded Trades, Market Clustering, and Price Instability (van Kralingen et al. 2020) — [arXiv:2002.03319](https://arxiv.org/abs/2002.03319)
- Early Detection of Latent Microstructure Regimes (Hiremath, Hiremath 2026) — [arXiv:2604.20949](https://arxiv.org/abs/2604.20949)

### Project

- `OPERATING_MANUAL.md` — Agent constitution, risk invariants (§1-4, §7)
- `sops/equity/swing/v1.0.0.md` — Current two-engine SOP (M-G1 through R-G8)
- `sops/_routing/v1.1.0.md` — Strategy routing and eligibility
- `skills/research/SKILL.md` — 5-layer DD stack
- `skills/eod-review/SKILL.md` — Feedback bridge (Step 6)
- `tools/scanner/filters.py` — Current binary-gate scanner
- `tools/analysis/regime.py` — Current regime signal computation
- `tools/scanner/tuning.py` — Existing feedback bridge (tuning_config.json)

---

## Change Log

| Version | Date | Author | Change |
|---------|------|--------|--------|
| 1.0.0 | 2026-06-28 | Hermes Agent | Initial draft for human review |
