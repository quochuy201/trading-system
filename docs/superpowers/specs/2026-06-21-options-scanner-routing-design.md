# Design: Options Scanner + Strategy Routing

**Date:** 2026-06-21
**Status:** Draft — pending operator review (then implementation plans)
**Author:** brainstorming session (zelyuh + Claude)
**Scope:** Add a mechanical stock scanner + strategy-routing front-end to the existing options vol-edge program, so the system finds option-suitable stocks, maps each to a defined-risk structure, and feeds the existing Engine A/B DD + execution + minute-monitor exits. Builds on the Plan-1 market-data foundation.

---

## 1. Problem & current-state eval

The options/vol-edge program (Engine A vol-edge + Engine B directional, SOP v1.1.0) is enabled in live config but realistically cannot produce trustworthy candidates today:

1. **No mechanical options scanner exists** — selection is 100% agent-driven (the LLM picks names, calls IV/chain tools, applies the DD rubric). Only `scan_for_candidates` and `scan_swing_candidates` (both equity) exist. This is the missing piece this design adds.
2. **IV-rank is effectively blind** — IVR (the credit-vs-debit signal) needs 52 weeks of IV30 per underlying; `iv_history` holds **SPY only, ~92 days**. Engine A cannot route any individual name.
3. **Options data feed is `INDICATIVE` (paper)** — modeled greeks + synthetic quotes; the known `HARD_SPREAD_WIDTH` noise. True accuracy needs a real OPRA feed (paid).
4. **No options backtest** — `simulation.py` options methods are `NotImplementedError`; the edge is unvalidated (the Phase-4 `option_surface` engine is design-only).
5. **The exit side is already strong** — defined-risk-only, 50%-profit close, 21-DTE hard close, 2× loss limit, credit/debit value-trailing stops, +100% scale, short-strike delta safety, gap-through-strike + regime-collapse defenses, per-minute sentinel. **Reuse, do not rebuild.**

The Plan-1 data foundation already fixed the *equity* data (adjusted, consolidated, single-writer) — so the **stock-level half of this design is buildable now on correct data**; the options-specific half is gated on options-data quality, handled by graceful degradation + accrual.

## 2. Thesis validation (literature-grounded)

The strategy selection rests on volatility theory. Validation below is grounded in the established literature (live r/options + web retrieval was unavailable at authoring time — WebSearch rate-limited, fetch classifier down — and is a **follow-up to verify/extend**, not a blocker).

**Sources (real, checkable):** Natenberg *Option Volatility & Pricing*; Sinclair *Volatility Trading* / *Option Trading*; McMillan *Options as a Strategic Investment*; tastytrade (Sosnoff/Battista) mechanical research; academic variance-risk-premium work (Carr & Wu 2009; Bakshi & Kapadia 2003; Bollerslev–Tauchen–Zhou).

| Claim | Verdict | Nuance |
|---|---|---|
| IV mean-reverts / clusters | ✅ Supported (GARCH literature) | Foundation of the regime concept |
| **Sell rich IV (credit)** | ✅ **Structural edge — the variance risk premium** | Negative skew: small wins, occasional large losses → defined-risk + small size + regime defenses (already in SOP) |
| **Buy cheap IV (debit/long)** | ⚠️ **Not a vol edge** — buyers pay the VRP on average | Edge is **direction**; cheap IV only cuts cost. Don't size expecting a vol tailwind |
| Earnings → IV crush | ✅ Supported | IV inflates pre-, collapses post- → avoid for debit; binary for credit |

**The key refinement:** the two engines earn from *different* sources. **Engine A (credit) = structural vol edge (VRP), tail-bounded.** **Engine B (debit/long) = directional edge, options as the leverage vehicle.** This split governs sizing and validation throughout.

*Caveat on tastytrade:* influential but methodologically criticized (limited samples, often ignores costs/tail) — directionally right, not gospel. r/options is retail/mixed-quality — useful for popularity/common mistakes, not proof.

## 3. Decisions locked (this session)

1. **Framing:** the mechanical scanner is a **Phase-1 front-end feeding the existing Engine A/B** (DD, defined-risk execution, monitor exits). It computes signals + a *suggested* structure; the **agent confirms/overrides**. Scanner gates, agent decides.
2. **Shared module, distinct profile:** reuse `scanner/filters.py`, the corrected daily-bar data path, the TA primitives, and the pipeline. Add `scan_universe_options` (an `OPTIONS_V1` profile) as a sibling to `scan_universe_swing` — **not** the identical swing gates.
3. **Data architecture:** *fetch-live for perishable data* (chains, greeks, quotes, current IV) at research + order time, never stored; *store-and-accrue only IV history* (the one thing no API serves on demand), behind a **swappable `OptionsDataSource` adapter** (default Alpaca INDICATIVE, swap to paid OPRA later). Sanity-gate every live fetch; validate every captured IV point.
4. **Routing:** a **direction × IV matrix** that **degrades gracefully** — when IV-rank is unavailable, **default to buying defined-risk premium (debit), never selling blind**. Credit unlocks per-name as `iv_history` accrues.
5. **Sequencing:** start now (path A) on Alpaca live + IV accrual, with accuracy guardrails so moving to a paid feed (path B) is a one-adapter swap.
6. **Scope:** bullish family first (matches the filter set); bearish mirror + earnings-vol play + iron condors/calendars deferred.

## 4. Design

### 4.1 Options data adapter (`tools/data/options_source.py`)
Mirrors the Plan-1 `MarketDataSource`. Interface (sketch):
- `get_chain(symbol, dte_range) -> list[contract]` — **live**, sanity-gated (reject zero/crossed/missing bid-ask, absurd width, stale ts).
- `get_greeks_iv(option_symbols) -> {...}` — **live**.
- `capture_iv30(symbols) -> n` — daily job: compute ATM 30-day IV from the live chain, append a scalar to `iv_history`; anomaly-validate each point.
- `iv_rank(symbol) -> float | None` — from local `iv_history`; `None` when history is insufficient.
Default impl = Alpaca INDICATIVE; swappable. **Only `iv_history` is persisted.**

### 4.2 Mechanical scanner (`scan_universe_options`, `OPTIONS_V1` profile)
A sibling in `scanner/filters.py`. Reads **local corrected daily bars** for the whole universe; reads **local `iv_history`** for the shortlist's IV-rank. SOP-owned starting thresholds (mirrored), reconciled from the operator's list:

- Liquidity: **optionable** (required), market cap **> $10B**, avg volume **> 1M**, RVOL **> 1.5**, price **floor ≥ $20** (drop the $50 cap — it conflicts with the >$10B mega-cap requirement; a `$20–$50` "cheaper-premium" sub-bucket may be added for small account tiers later).
- Trend/momentum: price **> SMA50 and > SMA200**, **RSI(14) 40–70**, **ATR 2–5%** of price, **perf-quarter +10–20%**, **perf-week** for pullback detection, RS-vs-SPY, **beta > 1**.
- Hard gate: **no confirmed earnings inside the hold window** (§4.6).
- Output: per-symbol metrics + IV regime + a suggested structure + honest gate-fail lists (§4.7).

### 4.3 Strategy routing matrix (SOP-owned, mirrored in the router)
Direction (TA) × IV regime → suggested structure → existing engine. Bullish family (v1):

| Direction | IV regime | Suggested structure | Engine |
|---|---|---|---|
| Bullish | RICH (IVR ≥ 75) | Bull put credit spread | A |
| Bullish | NEUTRAL (25–75) | Debit call spread | B |
| Bullish | CHEAP (IVR ≤ 25) | Long call (top conviction) or debit call spread | B |
| Bullish | **UNKNOWN** (no IV history) | **Debit call spread (safe default)** | B |

Never sell premium when IV-rank is unknown. Bearish cells (long put / bear-call, gated to SPY DOWNTREND) are reserved, deferred.

### 4.4 Strike & DTE selection (delta-based; strikes resolved from the LIVE chain)
Targets emitted by the router; actual strikes chosen at research/order time from the live chain:
- DTE: **35–45** entry (21-DTE hard close already handles the back end).
- Long call: **~0.60–0.70 Δ**, with a **hard anti-lottery gate: reject Δ < 0.55** (cheap far-OTM longs are where buyers lose to theta + IV-crush).
- Debit call spread: buy **~0.60 Δ**, sell **~0.30 Δ**; width by account tier ($1–2.50 small / $5 standard).
- Bull put credit spread: short **~0.30 Δ**, long one width below; matches the SOP's short-strike safety (Δ<0.25, >8% away).

### 4.5 Conviction & sizing (asymmetric by engine)
- **Engine A (credit):** conviction = IVR magnitude + regime alignment + short-strike safety. Binding constraint is **portfolio heat / correlation** (the VRP tail is correlated) — keep each small, defined, never stack correlated credit risk; lean on existing regime-collapse + heat defenses.
- **Engine B (debit/long):** conviction = **TA directional strength** + DD; cheap IV is a cost discount, not a size-up reason. Lower hit-rate, larger winners.
- Both: defined-risk only; risk-per-trade ≤ `OPERATING_MANUAL` cap and tier width; conviction scales full-vs-half **within** the cap. **Single-leg longs stay leashed** (smallest sleeve, top-conviction + cheap-IV only).
- Rule of thumb: **credit sized against tail/heat; debit sized against directional conviction.**

### 4.6 Earnings / IV-crush gate
Hard mechanical gate via the data adapter's earnings dates (yfinance, free; conservative when unknown): **reject** any candidate whose hold window (entry → expected exit / 21-DTE close, + buffer) contains a confirmed earnings date — for **both** engines in v1. The deliberate earnings-IV-crush sell is deferred (roadmap v1.3.0).

### 4.7 Scanner output schema (per candidate)
```
symbol, price, dollar_vol20, atr_pct
trend(>SMA50&200), perf_qtr, perf_wk, rs_vs_spy, rsi14
optionable, beta, market_cap, earnings_in_window(+date)
iv30, iv_rank | null, iv_regime ∈ {RICH,NEUTRAL,CHEAP,UNKNOWN}
suggested_structure ∈ {long_call, debit_call_spread, bull_put_credit_spread}
routed_engine ∈ {A,B}, target_dte, target_deltas, suggested_width
conviction_score, gate_fails:[...], needs_live_chain: true
```
The agent fetches the live chain, runs DD (news/social/LLM), confirms/overrides, sizes, executes.

### 4.8 Reuse map (what this plugs into — not rebuilt)
- Execution: existing `place_multileg_order` / `place_order` (defined-risk).
- DD: existing `skills/research/reference/options-vol-edge-dd.md` rubric, extended to read the scanner's suggestion.
- Exits/monitoring: existing SOP v1.1.0 + monitor sentinel (50% profit, 21-DTE, 2× loss, value/trailing stops, short-strike safety, gap/regime defenses) — unchanged.
- Risk/sizing: `OPERATING_MANUAL` caps, account tiers — unchanged.

## 5. Validation approach (options can't be sim-backtested yet)
1. **Directional edge → equity-backtest proxy.** Run the `OPTIONS_V1` stock-selection gates through the existing equity backtest harness, trading the underlying as **stock**, to confirm positive directional expectancy. Validates selection (the hard part) with no options pricing. *Proxies direction, not the option's leverage/theta/IV P&L.*
2. **Vol edge (credit) → trust structure, validate forward.** VRP is established; the specific implementation (IVR>75, 0.30Δ, 50%/21-DTE) is paper-validated now, or via the Phase-4 `option_surface` engine later. Paper-only, small, defined-risk until then.
3. **Options frictions → paper trading.** Fills, spread noise, IV-crush avoidance, greeks exits — forward-only. IV-capture accrues in parallel so credit becomes properly validatable over time.

**Go-live gate (real money):** (a) directional selection shows positive expectancy on the equity backtest **and** (b) a paper period confirms the options round-trip + exits + acceptable data quality.

## 6. Decomposition into plans (too big for one)
1. **Options-data adapter + IV-capture** — `OptionsDataSource`, live sanity-gated chain/greeks fetch, daily `capture_iv30` job + cron, `iv_rank` from `iv_history`, validation. (Foundation; starts IV accruing immediately.)
2. **Mechanical `scan_universe_options` + routing** — `OPTIONS_V1` profile, the matrix + graceful degradation, the output schema, earnings gate. Tests mirror `test_scanner_swing.py`.
3. **DD + execution wiring** — research skill reads the suggestion + fetches live chain + resolves strikes; route to existing place/exits.
4. **Equity-proxy validation harness** — run `OPTIONS_V1` selection through the equity backtest; report expectancy.

## 7. Out of scope (YAGNI)
Bearish engine (long put / bear-call); deliberate earnings-IV-crush play; iron condors / calendars; the Phase-4 options backtest engine (separate, large); paid OPRA feed (adapter-swap when justified); live (real-money) mode.

## 8. Success criteria
1. `scan_universe_options` returns option-suitable candidates with IV regime + a suggested structure + honest fail-lists, on the corrected local data, emitted even on zero days.
2. Perishable options data (chains/greeks/quotes) is fetched **live** at research/order time and sanity-gated; nothing perishable is read from a store; `iv_history` is the only persisted options data and grows daily.
3. When IV-rank is unavailable, routing yields a **debit/defined-risk** suggestion (never a blind credit).
4. Earnings inside the hold window hard-blocks a candidate.
5. The directional selection is run through the equity backtest and reports expectancy (the proxy gate).
6. Everything routes into the existing Engine A/B execution + monitor exits unchanged; full test suite green.

## 9. Risks & mitigations
- **INDICATIVE feed inaccuracy** → live sanity gates + BSM cross-check; adapter-swap to OPRA later; paper-only until validated.
- **IVR blind for months** → graceful degradation to debit-default; system trades the directional side meanwhile; credit unlocks per-name as history accrues.
- **Over-trusting tastytrade/retail claims** → treat as directional, not proof; the go-live gate requires the equity-proxy expectancy + a paper period.
- **VRP tail risk on the credit side** → defined-risk only, small size, heat/concentration cap, regime-collapse exits (existing).
- **Hardcoding strategy logic** → matrix + thresholds live in the SOP, mirrored in the scanner (same pattern as `SWING_V1`); agent confirms.

## 10. Open questions
- Earnings-date source reliability via yfinance (spot-check a few names during Plan 1 of this program).
- Exact `OPTIONS_V1` thresholds are starting values — to be tuned via the equity-proxy backtest, not pre-optimized.
- Whether to add the `$20–$50` cheaper-premium sub-bucket for small account tiers now or defer (lean defer).
