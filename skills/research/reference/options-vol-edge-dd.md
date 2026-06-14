# Options Vol-Edge — Research Reference

> **SOP:** `options-vol-edge/v1.0.0`
> **Engines:** A (vol-edge income) · B (directional / big-fish)
> All thresholds are sourced verbatim from the SOP. Do not invent or relax values.

---

## Step 1: Market Context (run before the first scan pass)

**SPY Regime** — compute from morning data:

| Classification | Condition |
|---|---|
| UPTREND | `Close > EMA20 > SMA50 > SMA200` AND SMA50 slope > 0 over last 10 bars |
| DOWNTREND | `Close < EMA20 < SMA50 < SMA200` AND SMA50 slope < 0 over last 10 bars |
| NEUTRAL | All other cases |

**VIX Bands:**

| VIX | Implication |
|---|---|
| < 15 | Compressed vol — favor single-name elevated IVR opportunities |
| 15–25 | Normal — no adjustment |
| > 25 | Elevated — reduce spread widths |
| > 35 | No new debit long positions |

**Macro calendar:** Hold new entries the morning of FOMC / CPI / PPI / NFP until 30 minutes after release. If such an event lands inside the intended expiry window, widen the spread to absorb expected vol expansion, or wait for the event to pass.

---

## Step 2: IV Scan — Compute for Every Candidate

```
IVR      = (IV30 − IV30_52wk_low) / (IV30_52wk_high − IV30_52wk_low) × 100
IV/HV    = IV30 / HV20
RS63     = stock_63d_return − SPY_63d_return
put_skew = IV_OTM_put − IV_equidistant_OTM_call
```

**Engine A vol routing (IVR threshold):**

| IVR | Signal | Engine A action |
|---|---|---|
| > 75 | Rich vol | Engine A: sell premium → credit spread |
| < 25 | Cheap vol | Engine A: buy premium → debit spread |
| 25–75 | No vol edge | Engine A **skips**; Engine B may still qualify on momentum |

---

## Step 3: Equity Regime + RS63 Gate

The option structure must agree with the SPY regime:

- **UPTREND** → RS63 must be > 0; bullish structures only (bull put spread, long call debit spread, long call).
- **DOWNTREND** → RS63 must be < 0; bearish structures only (bear call spread, long put debit spread, long put).
- **NEUTRAL** → Engine A skips. Engine B waits for a confirmed directional regime.

`put_skew > 5` specifically favors selling puts (bull put spread) over the symmetric bearish equivalent, independent of the regime-direction gate.

---

## Step 4: Liquidity & Earnings Gates (Hard — fail any → skip)

**Liquidity:**

| Check | Minimum | Preferred |
|---|---|---|
| 20-day average dollar volume | ≥ $20M | — |
| Option open interest (target strike) | ≥ 100 | ≥ 500 |
| Bid-ask spread on the spread | ≤ 20% of mid | tighter |

**Earnings:**

- Confirmed earnings date must fall **entirely outside** the expiry window, OR the expiry window must **start > 7 calendar days after** earnings.
- **If the earnings date is unavailable or uncertain → skip. Do not guess.**

---

## Step 5: Engine Classification

A candidate routes to Engine A **or** Engine B — not both.

| Route to… | When |
|---|---|
| **Engine A** (vol-edge) | IVR > 75 (rich) OR IVR < 25 (cheap) — a clear vol mispricing exists |
| **Engine B** (momentum) | IVR 25–75 (no vol edge) AND RS63 qualifies AND a confirmed continuation setup is present (see Phase 2) |
| **Skip** | NEUTRAL SPY regime; or Engine A IVR misses and no Engine B continuation setup confirmed |

**Engine B continuation setups** (one must be confirmed before scoring):
1. Pullback-to-EMA20 with bullish reversal candle (hammer / engulfing / pin bar) AND volume ≥ 1.2× 20-day avg.
2. Consolidation breakout with Bollinger Band squeeze AND volume ≥ 1.5× 20-day avg.
3. MACD resumption cross (line crosses signal after a pullback, histogram turning in trend direction).

---

## Step 6: Scoring

Only candidates that have passed **all** Phase 1 gates above are scored. A reject component voids the entire score — do not average around it.

### Scale

| Grade | Score | Usage |
|---|---|---|
| A+ | 90–100 | Highest conviction; full conviction sizing |
| A | 80–89 | Strong; standard conviction sizing |
| B+ | 70–79 | Permitted in NORMAL mode; reduced conviction sizing |
| Reject | < 70 | Do not trade |

The Manual's DEFENSIVE-mode gate ("A+ setups only, score ≥ 80") maps to **score ≥ 80 (grade A or A+)**.

---

### Rubric 1 — Vol-Edge Score (Engine A), 0–100

Nominal max is 105 pts; **reported score capped at 100**.

| Component | Points |
|---|---|
| **IVR magnitude** | Credit (IVR ≥ 75): IVR ≥ 90 → 30 · IVR 80–90 → 22 · IVR 75–80 → 15 · IVR < 75 → **reject** |
| | Debit (IVR < 25): IVR ≤ 15 → 30 · IVR 15–25 → 20 · IVR > 25 → **reject** |
| **IV/HV confirm** | Credit: IV/HV > 1.3 → 15 · IV/HV 1.1–1.3 → 8 · else → 0 |
| | Debit: IV/HV < 0.7 → 15 · IV/HV 0.7–0.85 → 8 · else → 0 |
| **Regime strength** | Full alignment + positive SMA50 slope → 20 · Partial alignment → 10 · Misaligned → **reject** |
| **RS63 rank** | Top 5% of universe → 15 · Top 10% → 10 · Top 20% → 5 · Positive (above zero) → 2 |
| **Liquidity/spread** | OI > 1000 AND bid-ask < 5% of mid → 10 · OI > 500 AND spread < 10% → 6 · OI > 100 → 3 · else → **reject** |
| **Earnings buffer** | Earnings > 14 days outside expiry window → 10 · Earnings 7–14 days outside → 5 · Earnings inside window → **reject** |
| **Put-skew bonus** | Bull put spread with put_skew > 5 → 5 · else → 0 |

> RS63 rank bands are **percentiles of the universe** scanned today (e.g., "top 5%" means the candidate's RS63 is above the 95th percentile of all candidates evaluated in this session).

---

### Rubric 2 — Momentum Score (Engine B), 0–100

Maximum is exactly 100 pts; no cap needed.

| Component | Points |
|---|---|
| **RS63 rank** | Top 3% of universe → 30 · Top 5% → 24 · Top 10% → 15 · Top 20% → 8 · Outside top 20% → **reject** |
| **Regime strength** | Full alignment + positive SMA50 slope → 25 · Partial alignment → 12 · Misaligned → **reject** |
| **Continuation setup quality** | Textbook (all criteria cleanly met) → 25 · Decent (setup present but marginal) → 15 · No qualifying setup → **reject** |
| **Liquidity** | OI > 1000 AND bid-ask < 10% of mid → 10 · OI > 500 → 6 · OI > 100 → 3 · else → **reject** |
| **IV sanity (single-leg)** | IVR < 50 → 10 · IVR 50–70 → 5 · IVR > 70 → 0 (route to debit spread instead; does **not** reject) |

> RS63 rank bands are **percentiles of the universe** scanned today, matching the Engine A convention above.

> IVR > 70 on the IV sanity row does not reject the candidate — it scores 0 and routes the structure to a momentum debit spread (per Phase 2 Engine B IV-aware routing). The candidate can still reach A+ if other components are strong.

---

## Output Format

Produce a ranked candidate list. Each row must carry all five fields below:

```
## Options Vol-Edge Candidates — [DATE]

| Rank | Symbol | Engine | Structure | Score | Thesis |
|------|--------|--------|-----------|-------|--------|
| 1    | XYZ    | A      | bull_put_spread | 87 | Selling rich vol (IVR 91) into uptrend with positive RS63; put skew confirms. |
| 2    | ABC    | B      | momentum_debit_spread_call | 76 | Top-10% RS63 runner with clean EMA20 pullback reversal; IVR 38 (cheap, debit preferred). |
| ...  |        |        |           |       |        |

## Rejected Candidates
[Symbol — gate that failed — brief reason]

## Summary
- Universe scanned: [N]
- Passed scan gates: [N]
- Engine A candidates: [N]  Engine B candidates: [N]
- A+ (90–100): [N]  A (80–89): [N]  B+ (70–79): [N]  Rejected (< 70): [N]
- SPY regime: [UPTREND / DOWNTREND / NEUTRAL]
- VIX: [X] ([band])
- SOP version: options-vol-edge/v1.0.0
```

Valid `structure` values: `bull_put_spread`, `bear_call_spread`, `debit_vertical_call`, `debit_vertical_put`, `momentum_debit_spread_call`, `momentum_debit_spread_put`, `single_leg_call`, `single_leg_put`.

---

## Engine B — Directional Swing (v1.1.0)

> **SOP:** `options-vol-edge/v1.1.0`
> This section describes the research process specific to Engine B in v1.1.0.
> It supplements (does not replace) the shared scan gates in Steps 1–5 above.
> Direction scope: **long-only** for v1.1.0 (SPY regime = UPTREND, bullish structures only).
> The short path (DOWNTREND → bearish structures) is a reserved seam, not active.

---

### Three-Leg Research Model

Every Engine B candidate is evaluated on three independent evidence streams. The
research agent must **reconcile** all three and show its work in the logged rationale
before producing an armed plan.

#### Leg 1 — Technical Analysis (GATE with veto power)

**Tools:** `calc_technical_indicators`, price/volume bars, continuation-setup gates
(Steps 4–5 above), `calc_iv_rank`, `calc_hv`, `get_put_skew`, `calc_expected_move`.

**What it answers:** Is the price-action setup real, and is the option priced right?

**Veto rule:** If the setup or pricing does not qualify under the shared scan gates
(Steps 1–5), no amount of social or LLM signal can override. The leg 1 gate is binary
pass/fail — a fail ends DD immediately.

Passing leg 1 requires:

- One confirmed continuation setup (pullback-to-EMA20 + bullish reversal candle +
  RVOL ≥ 1.2×; OR consolidation/BB-squeeze breakout + RVOL ≥ 1.5×; OR MACD resumption
  cross after pullback).
- Stock is not extended (anti-chase: not at or above upper Bollinger Band).
- IVR, HV, skew, and expected-move computed — these feed the IVR committee below.

#### Leg 2 — Web / Social Research

**Tools:** `WebSearch` + firecrawl over r/options, r/wallstreetbets, X, and
high-signal accounts.

**What it answers:** What is the catalyst? How known, crowded, or priced-in is it?
Is there an event the tape has not yet shown?

**Reddit access note:** Reddit's direct crawler is blocked — the agent NEVER hits
reddit.com directly. Reach r/options and r/wallstreetbets content via `WebSearch`
(Google surfaces threads) and firecrawl to fetch the resulting URLs.

**Signal weighting rules:**

| Signal type | Weight |
|---|---|
| Thesis with explicit reasoning + fresh timestamp (≤ 48 h) | High — include verbatim excerpt in rationale |
| Thesis with old timestamp or no date | Medium — note staleness; require corroboration |
| Rocket-emoji / gain-screenshot posts | Discount heavily — do not treat as thesis |
| Consensus across independent sources + verifiable claims | High — note the convergence |
| Single high-follower-count account without corroboration | Low — authority ≠ accuracy |

**Crowding read is contrarian:** if the overwhelming public posture is
"everyone is long into the event," treat it as a **caution signal**, not
confirmation. Crowded trades have compressed upside and amplified reversal risk.

#### Leg 3 — LLM Reasoning (the referee)

The model synthesizes legs 1 and 2 and acts as referee.

**Required outputs in the logged rationale:**

1. Explicit statement of how legs 1 and 2 align or conflict.
2. If they conflict: which leg wins and why. Default resolution rules:
   - Social NEVER overrides the quant gate (leg 1 always retains veto).
   - On any other conflict → default to the **safer structure** (spread over
     single-leg) and/or smaller size; state the reason explicitly.
3. The chosen structure (see IVR committee below) and conviction tier.
4. Earnings/event handling judgment: if a confirmed event lands inside the option's
   life, the LLM decides skip / force-spread-and-downsize / hold-through with
   written justification; quant IV-crush risk retains veto.

---

### IVR Committee — Instrument Selection

IVR is the **lead vote** for instrument selection, never the lone trigger. Apply
after leg 1 passes; use `calc_iv_rank`, `calc_hv`, `get_put_skew`, and
`calc_expected_move` output.

| IVR band | Default structure | DTE target |
|---|---|---|
| IVR < 35 (cheap vol) | Long call, delta 0.55–0.65 | 35–45 DTE |
| IVR > 55 (rich vol) | Call debit vertical: buy ~ATM (0.45–0.55 delta), sell OTM ~1.5–2 expected-moves out | 35–45 DTE |
| IVR 35–55 (neutral band) | LLM tiebreak on IV/HV + skew + setup quality; **default to spread** when ambiguous | 35–45 DTE |

**Neutral-band tiebreak heuristics (IVR 35–55):**

- `IV/HV > 1.2` (vol rich relative to realized) → lean spread.
- `IV/HV < 0.85` (vol cheap relative to realized) → lean single-leg call.
- `put_skew > 5` in a bullish setup → no special adjustment; note skew confirms
  downside hedging demand and bullish positioning may be cleaner.
- Setup quality A+ with very clean momentum → LLM may lean single-leg; document why.

---

### Armed Plan Output Format

The research agent produces an **ARMED PLAN, never an order.** An armed plan is a
pre-market trade blueprint that the monitor sentinel executes only after intraday
confirmation triggers. Producing a plan is not a trade — it is a conditional
intention.

Per qualified candidate, emit all of the following fields:

```
symbol:             [ticker]
direction:          long
structure:          [long_call | call_debit]
trigger_price:      [underlying price level that must confirm intraday — e.g. "break and hold above $143.50"]
invalidation_price: [underlying level that, if hit, cancels the plan — e.g. "close below $140.00"]
cutoff_et:          [time after which the plan expires unexecuted — default "11:00"]
dte_target:         [~40]
delta_target:       [~0.60 for long_call; ~0.50 for call_debit long leg]
rationale:          [three-leg reconciliation: leg 1 findings → leg 2 findings →
                     how they align or conflict → chosen structure and why →
                     size tier (base, reduced, or skip)]
```

After emitting the plan, call `notify_analysis` with the armed plan as the payload.

**Long-only constraint:** `direction` is always `long` in v1.1.0. `structure` values
are limited to `long_call` and `call_debit`. The short path (`long_put`,
`put_debit`) is reserved and not active.

**Size discipline:** conviction from legs 2–3 may only shrink size from the
quarter-Kelly base (per `OPERATING_MANUAL.md`). Social or LLM confidence never
enlarges the base size.
