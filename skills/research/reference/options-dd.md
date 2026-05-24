# Options Due Diligence — Reference

## The Options-Specific Layers (on top of base 5-layer stack)

Options add TWO extra dimensions beyond stock direction:
1. **Time** — theta decay means being right slowly still loses money
2. **Volatility** — IV expansion/collapse can override direction

## Contract Quality Checklist

Before recommending any options trade, verify ALL of:

| Check | Requirement | Why |
|-------|-------------|-----|
| Delta | ≥ 0.35 | Below this, too far OTM — needs huge move |
| DTE | 30–45 days (swing) / 7–14 (event) | Enough time for thesis without overpaying |
| Bid-ask spread | < 10% of mid | Wide spreads destroy edge before trade starts |
| Open interest | > 100 | Liquidity — can exit without slippage |
| IV Rank | < 50 preferred for buying | High IV = expensive options = sell premium instead |
| Strike | ATM to 5% OTM | Never ITM (paying for intrinsic that already happened) |

## IV and Volatility Assessment

| IV Rank | Implication | Strategy |
|---------|-------------|----------|
| < 30 | Options are cheap | Buy calls/puts (debit) |
| 30–50 | Normal | Buy with strong thesis only |
| 50–70 | Getting expensive | Spreads preferred over naked buys |
| > 70 | Options are expensive | Sell premium (credit spreads) or skip |

### Expected Move Check

Calculate: `Expected Move = Stock Price × IV × √(DTE/365)`

**Your target must exceed the expected move.** If the market already prices in a $10 move and your target is $8, there's no edge — the option is fairly priced for that outcome.

## Scoring Adjustments for Options

Add these to the base equity score:

| Factor | Bonus/Penalty |
|--------|---------------|
| IV Rank < 30 | +10 |
| IV Rank > 60 | -15 |
| DTE sweet spot (30-45d) | +5 |
| DTE too short (< 14d) | -10 |
| Spread < 5% | +5 |
| Spread > 10% | -10 (or reject) |
| OI > 1000 | +5 |
| OI < 100 | Reject |
| Earnings within DTE | -10 (IV crush risk) |

## Entry Rules (Options-Specific)

- **Limit order at ask × 1.03** (slightly above ask for fills)
- **Never market order** on options (spread kills you)
- **Max 3 entries per day** (avoid overtrading)
- **No entries within 3 days of earnings** (IV crush)
- **Day-1 catalyst only** — if the news is > 1 day old, it's priced in

## Exit Framework (Options-Specific)

| Rule | Condition | Action |
|------|-----------|--------|
| Day 1-5 | Hold unless structural break | No panic sells |
| -60% floor | DTE < 14 | Auto-exit |
| -60% floor | DTE ≥ 14, no break | Suspended (thesis has time) |
| +20% profit | Day 6+ | Activate 15% trailing stop |
| +100% profit | Any day | Scale 1/3, tighten trail to 10% |
| DTE ≤ 5 | Underwater | Time stop — exit |
| Day 10 | < +20% | Stale — consider exit |

## Structural Break Definition (Exit Allowed)

A structural break means the STOCK (not the option) shows:
- Closed below SMA20 for 2 consecutive days
- Below 5-day entry-zone low on closing basis
- Stock dropped > 10% from entry price

**NOT a structural break:** Option down 30% (that's theta/IV), one red day, market down.

## The 7-Question Sell Diligence

Before recommending any exit (except auto-triggers):

1. What was the original thesis? (one sentence)
2. Has the catalyst been INVALIDATED by NEW information?
3. Stock vs SMA20? (above = hold, below 2d+ = exit allowed)
4. Below 5-day entry-zone low? (yes = exit allowed)
5. Stock down > 10% from entry? (yes = exit allowed)
6. Would you enter this trade RIGHT NOW? (yes = hold)
7. Reacting to one bar or structural change? (one bar = hold)

**Count YES to exit conditions (Q2-Q7):**
- 0 = HOLD
- 1 = HOLD unless DTE < 14
- 2-3 = Exit allowed
- 4+ = Strong sell

## Red Flags (Auto-Reject for Options)

- IV Rank > 70 for debit trades (options too expensive)
- DTE < 7 for new entries (pure theta bet)
- Spread > 15% (illiquid, will lose on entry)
- Earnings within 3 days (IV crush)
- Stock below SMA200 for calls
- No clear catalyst (momentum-only options trades lose to theta)
