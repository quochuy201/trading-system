# Prediction Markets Due Diligence — Reference

## Prediction Market-Specific Layers

Prediction markets are fundamentally different from price-based trading:
1. **Binary outcomes** — contracts resolve YES ($1) or NO ($0)
2. **Edge = probability estimation** — you profit when market price ≠ true probability
3. **Resolution criteria matter** — HOW the contract resolves is as important as WHAT happens
4. **Time value** — contracts approaching resolution converge to true value

## Platforms

| Platform | Markets | Settlement |
|----------|---------|------------|
| Kalshi | US regulated, politics, economics, weather, events | USD, CFTC regulated |
| Polymarket | Crypto-native, broader markets, international | USDC, unregulated |

## Scanning Criteria

| Criterion | Requirement |
|-----------|-------------|
| Volume | > $50K total volume on the contract |
| Liquidity | Spread < 5¢ between YES and NO |
| Resolution date | 7–90 days out (avoid too short or too long) |
| Resolution clarity | Unambiguous resolution source defined |
| Edge estimate | Your probability estimate differs from market by > 10% |

## The Probability Estimation Framework

### Step 1: Base Rate

What's the historical frequency of this type of event?
- "Will X happen by date Y?" → find base rate from similar past events
- "Will metric exceed threshold?" → look at distribution of past values

### Step 2: Update with Evidence

Bayesian update from base rate:
- What NEW information exists that the market may not have priced?
- Is there insider knowledge asymmetry? (e.g., you follow a niche source)
- What's the consensus view and why might it be wrong?

### Step 3: Compare to Market Price

- Market says 60¢ (60% probability)
- Your estimate is 80% probability
- Edge = 20% → BUY YES at 60¢ (expected value: 0.80 × $1 - 0.60 = +$0.20)

**Minimum edge to trade: 10% (your estimate vs market price)**

## Scoring for Prediction Markets

| Factor | Weight | High Score | Low Score |
|--------|--------|-----------|-----------|
| Edge size (your prob vs market) | 30% | > 20% edge | < 10% edge |
| Resolution clarity | 20% | Crystal clear source | Ambiguous |
| Time to resolution | 15% | 14-45 days (sweet spot) | > 90 days or < 3 days |
| Liquidity | 15% | Tight spread, high volume | Wide spread, thin |
| Information advantage | 20% | You have unique insight | Consensus view |

**Threshold: Only trade with estimated edge > 10% AND score > 65.**

## Entry Rules

- **Size by Kelly fraction** (simplified): `bet_size = edge / odds`
  - Example: 20% edge, contract at 60¢ → Kelly = 0.20 / 0.40 = 50% of bankroll (use quarter-Kelly: 12.5%)
- **Never bet > 10% of prediction market bankroll on one contract**
- **Limit orders only** — place at your target price, let it fill
- **Scale in** — buy 1/3 position, add if price improves

## Exit Rules

| Condition | Action |
|-----------|--------|
| Market moves to your estimated probability | Take profit (edge gone) |
| New information invalidates thesis | Exit immediately |
| Resolution approaching + you're right | Hold to resolution ($1 payout) |
| Resolution approaching + unclear | Sell at market (lock in partial gain) |
| Better opportunity elsewhere | Sell to redeploy capital |

## Cross-Platform Arbitrage

Check if the same event trades on multiple platforms:
- Kalshi YES + Polymarket NO < $1.00 → risk-free profit
- Same event, different prices → buy cheap side
- **Always check resolution criteria match** — slight wording differences can mean different outcomes

## Red Flags (Auto-Reject)

- Resolution criteria ambiguous or subjective
- Market maker is the only liquidity (no real price discovery)
- Contract resolves in > 90 days (too much uncertainty, capital locked)
- Your edge estimate < 10% (not enough margin of safety)
- Low volume (< $10K) — can't exit if wrong
- Political markets close to election (too efficient, no edge)
- "Will X tweet about Y" type markets (unresearchable, pure noise)

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Confusing "I think X will happen" with "market is mispriced" | Always compare YOUR probability to MARKET price |
| Ignoring time value | A 70% contract at 65¢ with 60 days left may not be worth it (capital locked) |
| Not reading resolution criteria | The contract might resolve differently than you expect |
| Overconfidence in political predictions | Markets are efficient for high-profile events |
| Betting on "obvious" outcomes | If it's obvious, it's already priced in |
