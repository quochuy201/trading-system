# Strategy-Agnostic Backtest Engine — Design

**Date:** 2026-06-05
**Status:** Spec (peer-reviewed)
**Depends on:** Phase 2 options MCP tooling (complete), v3 equity harness (`tools/backtest/harness.py`)
**Goal:** Test ANY strategy (equity day-trade, options vol-edge, future option strategies) without modifying the engine core. A strategy that passes backtest must behave identically when deployed live on Hermes.

---

## Problem

The v3 harness has equity assumptions hardcoded in its core: a single-symbol `Position` with stop/target/trail, close-vs-stop mechanical checks, and `(exit − entry) × qty` P&L. Options need multi-leg positions, greeks, theta decay, net-credit P&L, and spread-based exits. Adding each new strategy by editing the engine is the wrong path — and worse, the backtest uses special-case tools (`backtest_enter`/`backtest_exit`) that differ from the live order path, so "passed backtest" does not currently imply "behaves the same live."

## Core principle

**The swap point is the broker adapter, not the engine.** The agent calls the same MCP tools live (Hermes/Alpaca) and in backtest. Only the `BrokerAdapter` subclass differs. Deploying to Hermes = swapping `SimulationBrokerAdapter` → `AlpacaBrokerAdapter`; the agent, skills, tools, and exit logic are byte-identical to what was backtested.

```
       SAME MCP TOOLS  (identical on Hermes-live and in backtest)
   get_options_chain · get_options_positions · place_multileg_order ·
   place_order · calc_iv_rank · get_market_data · log_decision ...
                          │
                          ▼
                   BrokerAdapter (abstract)
                   /                       \
        AlpacaBrokerAdapter         SimulationBrokerAdapter
        (Hermes/paper: real API)    (backtest: historical-data
                                     server + paper trade-logger)
```

---

## Architecture: three layers

### Layer 1 — Engine core (fixed, instrument-agnostic, never changes per strategy)

Three responsibilities, all reused from the validated v3 harness:

1. **Clock + no-look-ahead guarantee.** Sim time moves only via `set_time(t)`, called by the harness clock — never by the broker or agent. Every data query is bounded by the clock (`timestamp <= current_time`). The broker physically cannot read a bar past the clock. This is the existing mechanism in `simulation.py` (`_get_current_bar`, `get_historical_data` with `effective_end = min(end, current_time)`); options add a parallel `query_option_data(..., end=current_time)` with the identical bound.

2. **Entry-timing guard.** The agent decides on bar N's close (the last price visible without look-ahead); the fill is logged at bar N+1's open/quote — the first price transactable after the decision. This is the existing `_fill_price_bar` mechanism. Options honor it: log entries at the **ask that exists at the first bar after the decision bar**, not the quote the agent saw when deciding.

3. **Data feed + event dispatch.** Load the day's historical bars/chains into the clock-bounded broker view; each bar, run silent mechanical checks (via ExitChecker) or wake the LLM on strategy-declared event triggers.

The engine core has no equity or options assumptions. It does not change when a strategy is added.

### Layer 2 — SimulationBrokerAdapter (instrument-specific, mirrors the live API)

Answers the same calls the agent makes live, returning the same dict shapes `AlpacaBrokerAdapter` returns, sourced from clock-bounded history. **No order-fill simulation** — it is a historical-data server plus a paper trade-logger.

**Pricing convention (locked):** all option prices logged at the **ask** at the next bar after the decision. Bid/ask-spread modeling is deliberately omitted — the backtest measures strategy edge, not fill quality. A single consistent quote source removes a confounding variable.

Methods to implement (currently `NotImplementedError` stubs):

- **`get_option_chain(underlying, ...)`** — Build the chain at the sim clock:
  - Underlying price at `current_time` (clock-bounded).
  - Cached IV for that day from `iv_history`.
  - For each strike/expiry in the window, synthesize bid/ask/mid/greeks via `black_scholes_price` + greek formulas in `analysis/options.py` (underlying, strike, DTE-at-sim-date, IV, rate).
  - Return the live shape: `{symbol, underlying, strike, type, expiration, dte, bid, ask, mid, iv, greeks, open_interest, volume}`.
  - **OI:** backtest universe is restricted to deeply liquid names (see "Universe" below); the OI gate stays active/unchanged but always passes. `open_interest` is returned as a sentinel high value (e.g. 100000) so the gate logic runs without modification.

- **`get_options_positions()`** — Re-price open legs at the sim clock: synthesize current value via BSM at today's underlying + IV + remaining DTE; return greeks + unrealized P&L. Same shape as live.

- **`get_option_snapshot(symbols)`** — Same BSM synthesis for specific contracts (used by Monitor).

- **`place_multileg_order(legs, ...)`** — Paper-logger: record each leg at the **ask at the next bar** after the decision. No fill matching. Returns a `TradeTransaction` like live. P&L computed at close from logged entry/exit prices.

- **`get_option_historical_iv` / chain-derived IV** — reuse the existing BSM-inversion + `iv_history` cache; backtest pre-loads this cache as part of data setup.

The agent cannot tell it is a simulation: identical tool names, identical return shapes. The only difference is BSM-from-history instead of live OPRA.

### Layer 3 — Shared ExitChecker (makes backtest exits == live exits)

Mechanical exits must run identically live and in backtest. Exit thresholds are **strategy** (CLAUDE.md forbids strategy logic in Python), so they are declared in the SOP; the ExitChecker is a dumb evaluator.

**Rule format — structured block in the SOP:**

```yaml
# in sops/options-vol-edge/v1.0.0.md
exits:
  profit_target: { type: pct_of_credit, value: 50 }
  stop_loss:     { type: multiple_of_credit, value: 2 }
  dte_floor:     { type: dte, value: 21 }
  trailing:      { type: giveback_pct, value: 20 }
```

**ExitChecker = open registry of named rule-evaluators, NOT a hardcoded if/else.** Each rule type is a small function `(position, params) → bool`, registered by name. Adding a strategy with a novel exit condition = register a new evaluator + reference it in that strategy's SOP exit block. The checker core, the engine, and the live path stay untouched. **Rule-type names are the stable contract between SOPs and the checker.**

This is required because more option strategies are coming, each with different exit semantics:
- **Credit/debit verticals (v1.0.0):** `pct_of_credit`, `multiple_of_credit`, `dte`, `giveback_pct`.
- **Iron condors (v1.2.0):** two-sided exits; "credit" is the combined credit of both spreads; close-tested-side vs close-whole-structure.
- **Single-leg longs (Engine B):** debit not credit → `pct_of_debit`, `delta_stop`, `underlying_stop` (`pct_of_credit` is meaningless).
- **Calendars/diagonals (future):** exit on IV change or front-leg expiry, not just price.

**Used by both paths:**
- **Live (Hermes):** Monitor agent's 15:30 ET loop → `get_options_positions()` → `ExitChecker.check()` → if signal, `place_multileg_order(close)`.
- **Backtest:** engine each bar → `get_options_positions()` (sim broker) → same `ExitChecker.check()` → if signal, `place_multileg_order(close)` (sim logs it).

Same checker, same rules, same tool calls. The only difference is which broker answers.

**Equity strategies** declare their own exit block (stop/target/trail in price terms); the same ExitChecker evaluates a different registered rule set. One checker serves all strategies.

---

## Universe (backtest scope)

Backtest universe is restricted to deeply liquid optionable names (SPY, QQQ, AAPL, MSFT, NVDA, and similar). Rationale: every reasonable strike has OI in the thousands, so the OI liquidity gate always passes — no need for historical OI (which Alpaca's contracts endpoint does not serve as a time series), and the live code path stays unmodified. This also matches reality: these spreads would only be traded on liquid underlyings.

---

## Migration from the v3 harness

Refactor-in-place, not a rewrite. The existing equity backtest is the regression test.

1. **Extract the fixed core** from `harness.py`: clock, `advance_to_next_day`, `load_day_bars`, `step_bar`'s bar-advance + event-dispatch loop, decision logging, results aggregation. These become Layer 1.
2. **Move equity-specific logic out of the core:** the `Position` stop/target/trail checks become equity ExitChecker rule-evaluators; `(exit − entry) × qty` P&L moves behind the equity broker path.
3. **Route entries/exits through MCP tools + broker:** retire the special-case `backtest_enter`/`backtest_exit` tools (a known gap). Both equity and options go through `place_order` / `place_multileg_order` → SimulationBroker. This is what finally makes the backtest fully share the live code path.
4. **Regression gate:** re-run the existing Feb/May equity backtests (baseline: Feb +$542, etc.). Same trades, same P&L, or the refactor broke something.
5. **Then** add the options broker methods + options ExitChecker rules alongside.

---

## Output metrics

The output validates the strategy, not just reports P&L:

1. **Core performance:** total P&L, win rate, avg win, avg loss, payoff ratio, **expectancy per trade**, max drawdown, trade count.
2. **Discipline check:** compliance score (`audit/compliance.py` + options gate checks) — did the agent follow the SOP across the run?
3. **Premise test (most important):** **IVR-filtered vs. control.** Run the strategy as-specified (IVR > 75 entries) and a control (same structure, ignore IVR). If the filter does not beat the control, the vol-edge thesis is wrong. This is what makes it validation, not just a P&L number.
4. **Per-trade ledger** exported as JSONL (like the equity backtest) for inspection.

---

## Honest costs / risks

- **BSM-synthesized prices are approximate.** They ignore real skew during the holding period, real bid/ask, and microstructure. Accepted: the backtest answers "does the vol-edge thesis have positive expectancy?", not "what exact fills would I get." Real edge is likely better or worse at the margin; the premise test (IVR vs control) is robust to this because both arms use the same synthesis.
- **`iv_history` coverage limits the testable date range** to where IV data exists (cached or BSM-derivable). Backtests outside that range are not possible.
- **The ExitChecker rule registry must be built as a registry from the start.** Building four hardcoded checks now and refactoring at v1.2.0 (iron condors) is the trap this design explicitly avoids.

---

## Out of scope (future)

- Real OPRA historical data fidelity (vs. BSM synthesis).
- Fill-quality / slippage modeling.
- Multi-strategy concurrent backtests (one strategy per run for now).
- Iron condors / earnings-vol strategies themselves (this engine must *support* them, but they are separate strategy specs).

---

## Implementation order (for the plan)

1. ExitChecker registry + equity rule-evaluators (pure, testable in isolation).
2. Refactor v3 harness into Layer-1 core + equity path; route through `place_order`; **regression-test against Feb/May equity baseline.**
3. SimulationBroker options methods (chain/positions/snapshot/multileg via BSM from history).
4. Options ExitChecker rule-evaluators + SOP exit block.
5. Wire options path end-to-end; run vol-edge over a liquid-universe historical window.
6. Output metrics + IVR-vs-control premise test.
