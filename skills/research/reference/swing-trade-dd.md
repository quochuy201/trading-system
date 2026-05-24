# Swing Trade Due Diligence

Reference guide for swing trade candidate evaluation. Covers both short swings (2-5 days, momentum/breakout) and longer trend plays (1-4 weeks, pullback/continuation).

---

## Holding Period Decision

| Setup Type | Hold Period | Exit Logic |
|-----------|-------------|------------|
| Breakout momentum | 2-5 days | Trail stop after 1R profit; exit if momentum fades (volume drops 50%) |
| Gap-and-go continuation | 2-3 days | Take 50% at 2R, trail rest; hard exit if gap fills |
| Pullback to support | 5-15 days | Hold as long as support holds; exit on close below SMA20 |
| Sector rotation play | 1-4 weeks | Hold while sector outperforms; exit on relative strength breakdown |
| Earnings gap hold | 3-10 days | Hold while gap doesn't fill; exit on first close below gap low |

---

## Catalyst Decay Model

Catalysts lose power over time. This affects entry timing and position conviction:

| Days Since Catalyst | Catalyst Strength | Action |
|--------------------|-------------------|--------|
| Day 0 (today) | FULL | Enter on confirmation (15-min candle direction) |
| Day 1 | HIGH | Enter on pullback to support only |
| Day 2 | MEDIUM | Reduced conviction — half size only |
| Day 3+ | STALE | Do NOT enter — catalyst is priced in |

**Exception:** Multi-day sector rotations (e.g., rate cuts benefiting banks over 1-2 weeks) — these are not single-event catalysts and can persist.

---

## Trend Confirmation Checklist

Before entering any swing trade, ALL of these must be true:

### For Long Swings

- [ ] Price > SMA20 (short-term trend bullish)
- [ ] SMA20 > SMA50 (intermediate trend aligned)
- [ ] Price making higher lows on the daily chart
- [ ] Volume on up-days > volume on down-days (last 10 bars)
- [ ] RSI > 40 and < 75 (momentum present but not exhausted)
- [ ] Relative strength vs SPY positive (trailing 10 or 20 days)

### For Short Swings

- [ ] Price < SMA20 (short-term trend bearish)
- [ ] SMA20 < SMA50 (intermediate trend aligned)
- [ ] Price making lower highs on the daily chart
- [ ] Volume expanding on down-days
- [ ] RSI < 60 and > 25 (weakness present but not oversold bounce risk)
- [ ] Relative weakness vs SPY (underperforming)

---

## Entry Timing

### Breakout Entry (momentum swings)

1. Wait for breakout candle to close above resistance on > 2x volume
2. Enter on next candle's pullback to breakout level (buy the retest)
3. If no pullback within 2 bars, enter at market only if still < 1 ATR above breakout
4. If price extends > 1.5 ATR above breakout without you — MISSED IT. Move on.

### Pullback Entry (trend swings)

1. Identify the trend (higher highs/lows, above rising SMAs)
2. Wait for pullback to SMA20 or prior breakout level
3. Confirm pullback is on declining volume (not a reversal)
4. Enter when price prints a higher low or bullish engulfing at support
5. Stop goes below the pullback low (structural invalidation)

---

## Position Sizing for Swings

Swings use the same sizing math as day trades (OPERATING_MANUAL §3) but with adjustments:

| Factor | Day Trade | Swing Trade |
|--------|-----------|-------------|
| Risk per trade | 1% of equity | 0.5-1% of equity (wider stops) |
| Stop distance | 0.5-1.5 ATR | 1-2 ATR (needs room to breathe) |
| Position concentration | Max 20% in one name | Max 15% (overnight risk) |
| Max open positions | 5 | 3-5 (diversified exposure) |

---

## Swing-Specific Exit Rules

### Profit Taking

| Profit Level | Action |
|-------------|--------|
| +1R | Move stop to breakeven |
| +1.5R | Take 25-33% off, trail remainder |
| +2R | Take another 25-33% off |
| +3R | Close remaining or trail very tight (0.5 ATR) |

### Stop-Loss Rules

- Initial stop: below structural support or 1.5x ATR below entry
- **Never widen a stop** — if the trade needs a wider stop, the entry was wrong
- If price gaps below stop overnight: exit at open, do not hold hoping for recovery

### Time-Based Exits

| Setup | Max Hold | Exit if... |
|-------|----------|-----------|
| Breakout momentum | 5 days | No new high in 3 days (momentum dead) |
| Pullback trend | 15 days | Closes below SMA50 |
| Earnings gap | 10 days | Gap fills (thesis invalidated) |

---

## Overnight Risk Management

Swings hold overnight — unique risks vs day trades:

1. **Gap risk**: Earnings, news, macro can gap against you. Accept this or don't swing trade.
2. **Mitigation**: Size smaller (0.5-0.75% risk vs 1% for day trades). Use wider stops.
3. **Avoid holding through**: Known binary events (earnings, FDA, FOMC) unless that's the thesis.
4. **Position limit**: Max 3-5 concurrent swing positions to limit correlated gap risk.
5. **Sector diversification**: Never have > 2 swings in the same sector.

---

## Scoring Rubric (Swing-Specific)

| Factor | Points | Criteria |
|--------|--------|----------|
| Trend alignment | 0-25 | 25 = above rising SMAs, sector strong. 0 = fighting trend. |
| Catalyst quality | 0-25 | 25 = fresh Day-0 institutional catalyst. 0 = no catalyst / stale. |
| Volume confirmation | 0-20 | 20 = breakout on 3x volume. 0 = no volume interest. |
| Risk/Reward | 0-20 | 20 = R:R > 3:1 with clear structure. 0 = R:R < 2:1. |
| Relative strength | 0-10 | 10 = top decile vs SPY. 0 = underperforming. |

**Total: /100**

| Score | Recommendation | Action |
|-------|---------------|--------|
| 80-100 | Strong buy | Full size, enter aggressively |
| 70-79 | Buy | Standard size |
| 60-69 | Weak buy | Half size only, need additional confirmation |
| < 60 | Skip | Does not meet minimum quality bar |
