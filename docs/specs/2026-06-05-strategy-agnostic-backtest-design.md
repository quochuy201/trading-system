# Strategy-Agnostic Backtest Engine — Design

**Date:** 2026-06-05
**Status:** Spec — revised after adversarial peer review (resolved 3 BLOCKERs: greeks are new work, real IV surface replaces scalar IV, BSM-mid replaces incoherent "ask"). Data approach = Option A (historical IV surface), verified feasible.
**Depends on:** Phase 2 options MCP tooling (complete), v3 equity harness (`tools/backtest/harness.py`)
**New code prerequisites (NOT existing — do not assume):** `black_scholes_greeks()`, `option_surface` table + builder, working next-bar fill guard.
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

Three responsibilities:

1. **Clock + no-look-ahead guarantee (reused, sound).** Sim time moves only via `set_time(t)`, called by the harness clock — never by the broker or agent. Bulk queries are bounded by the clock: `get_historical_data` applies `effective_end = min(end, current_time)` (simulation.py:211) — verified airtight. The bound is inclusive (`timestamp <= current_time`), so the bar *at* the clock is visible; that is intentional for mechanical checks but means decision-time look-ahead is prevented by the next-bar fill guard below, NOT by the query bound alone. Options add a parallel `query_option_surface(..., date <= current_time)` with the identical inclusive bound.

2. **Entry-timing guard (NEW WORK — currently dead code, must be implemented).** The agent decides on bar N's close (last price visible without look-ahead); the fill must be logged at bar N+1's open/mid — the first price transactable after the decision. `_fill_price_bar` exists in `simulation.py` (declared line 36, read lines 70/184) but **is never set by anything** — the equity backtest currently routes through `backtest_enter` → `enter_position`, which accepts an arbitrary LLM-supplied `entry_price` (harness.py:451), so there is NO next-bar enforcement today. The migration (step 2) must: (a) set `_fill_price_bar` to the N+1 bar before fills, (b) make the entry path stop accepting a caller-supplied price, (c) add **gap-skip** (CLAUDE.md §4: skip if gaps >5% above / >3% below planned entry). This applies to both equity and options entries.

3. **Data feed + event dispatch (reused).** Load the day's historical bars/surface into the clock-bounded broker view; each bar, run silent mechanical checks (via ExitChecker) or wake the LLM on strategy-declared event triggers.

The engine core has no equity or options assumptions. It does not change when a strategy is added.

### Data layer — historical IV surface (Option A, prerequisite for Layer 2)

The existing `iv_history` table stores a single scalar ATM IV per `(symbol, date)`. That is insufficient: a multi-strike chain priced off one ATM IV has a flat vol surface, which forces `put_skew ≡ 0` and structurally breaks the vol-edge strategy's own skew gate. **We build a real historical IV surface instead** (verified feasible 2026-06-05: per-strike historical option bars are available from Alpaca, and inverting each strike's daily close via `implied_vol_from_price` reconstructs genuine skew — e.g. QQQ 2026-01-02 showed IV 0.327 at moneyness 0.78 vs 0.282 at 0.85).

**New table `option_surface`:**
```sql
CREATE TABLE IF NOT EXISTS option_surface (
    underlying   TEXT NOT NULL,
    date         TEXT NOT NULL,   -- YYYY-MM-DD (the historical trading day)
    expiration   TEXT NOT NULL,   -- YYYY-MM-DD
    strike       REAL NOT NULL,
    type         TEXT NOT NULL,   -- 'call' | 'put'
    iv           REAL NOT NULL,   -- BSM-inverted from that day's option close
    close        REAL NOT NULL,   -- option close price (source of the inversion)
    underlying_close REAL NOT NULL,
    PRIMARY KEY (underlying, date, expiration, strike, type)
);
```

**Surface builder (one-time per backtest, data-prep step):** for each underlying in the (liquid) backtest universe and each historical day in range: enumerate the strikes/expiries that existed, fetch their daily option bars (multi-symbol batch), fetch the underlying daily close, BSM-invert each strike's close → IV, store the row. This is a data-prep job run before the backtest, not on the hot path. Coverage is bounded by Alpaca's historical options data (~Feb 2024 onward) — backtests outside that range are not possible.

`query_option_surface(underlying, date, expiration_window, strike_window)` serves rows with the no-look-ahead bound `date <= current_time` (same pattern as `query_price_data`).

### Layer 2 — SimulationBrokerAdapter (instrument-specific, mirrors the live API)

Answers the same calls the agent makes live, returning the same dict shapes `AlpacaBrokerAdapter` returns, sourced from the clock-bounded `option_surface`. **No order-fill simulation** — it is a historical-data server plus a paper trade-logger.

**Pricing convention (locked):** all option prices are the **BSM mid (fair value)** computed from the surface IV. There is NO separate bid/ask — with no spread model, "bid" and "ask" are not meaningful, and (per the user's call) bid/ask differences do not affect strategy-edge evaluation. One consistent price source (BSM mid from the historical surface IV) removes the confounding variable. A symmetric slippage haircut MAY be added later via the existing `slippage_pct` if desired; it is out of scope for v1.

**Prerequisite — greek functions (new code, do not assume existing):** `analysis/options.py` currently has `black_scholes_price` and `implied_vol_from_price` but **no greeks**. Add `black_scholes_greeks(stock, strike, dte, rate, vol, type) -> {delta, gamma, theta, vega, rho}` with unit tests. The live adapter returns a full greeks dict per contract (sourced from OPRA); the sim must match that shape, and `calc_put_skew` requires per-contract `delta`, so greeks must land before chain synthesis.

Methods to implement (currently `NotImplementedError` stubs):

- **`get_option_chain(underlying, ...)`** — Build the chain at the sim clock:
  - Underlying close at `current_time` (clock-bounded).
  - Per-strike IV from `option_surface` for that day/expiration window (real skew, not a single ATM value).
  - For each strike/expiry, compute mid price via `black_scholes_price` and greeks via the new `black_scholes_greeks`, using that strike's own surface IV.
  - Return the live shape: `{symbol, underlying, strike, type, expiration, dte, bid, ask, mid, iv, greeks, open_interest, volume}`. With no spread model, `bid = ask = mid` (documented; downstream net-spread-width gate therefore reads ~0% in backtest — acceptable since the live OPRA feed is the real test of that gate).
  - **OI:** backtest universe is restricted to deeply liquid names (see "Universe"); the OI gate stays active/unchanged but always passes. `open_interest` returns a sentinel high value (e.g. 100000). `volume` returns the historical option volume from the bar if available, else the same sentinel. No selection logic may depend on relative OI/volume (verify against SOP + skills during implementation).

- **`get_options_positions()`** — Re-price open legs at the sim clock: value each leg via BSM at the current underlying close + that strike's current surface IV + remaining DTE; return greeks + unrealized P&L. Same shape as live.

- **`get_option_snapshot(symbols)`** — Same BSM synthesis for specific contracts (used by Monitor).

- **`place_multileg_order(legs, ...)`** — Paper-logger: record each leg at its **BSM mid at the next bar after the decision** (next-bar guard — see Layer 1 / Finding below). No fill matching. Returns a `TradeTransaction` like live. P&L computed at close from logged prices.

The agent cannot tell it is a simulation: identical tool names, identical return shapes. The only difference is BSM-from-surface instead of live OPRA.

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

**ExitChecker = open registry of named rule-evaluators, NOT a hardcoded if/else.** Each rule type is a small evaluator registered by name. Adding a strategy with a novel exit condition = register a new evaluator + reference it in that strategy's SOP exit block. The checker core, the engine, and the live path stay untouched. **Rule-type names are the stable contract between SOPs and the checker.**

Two non-obvious requirements (from review):
- **Evaluator signature is NOT a pure predicate.** Trailing/giveback rules need mutable per-position exit state (current trailing logic mutates `trailing_stop`/`highest_close`, harness.py:315+). Signature: `(position, params, exit_state) → (triggered: bool, exit_state')` — it reads and updates per-position state.
- **Unknown rule type → HARD FAIL.** If a SOP references an unregistered rule type, the checker raises at load time. Never silently skip an exit — a skipped exit is unbounded loss. The SOP `exits:` block also gets a schema + validation step.

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
3. **Route entries/exits through the broker adapter + tool wrappers:** retire the special-case `backtest_enter`/`backtest_exit` tools. Both equity and options go through `place_order` / `place_multileg_order` → SimulationBroker. This makes the backtest **share the broker-adapter and MCP-tool interface** — note this is a real parity *improvement*, not "full" parity: enumerate explicitly which server-layer concerns the backtest now exercises (kill switch, `_log_to_ledger`, `with_retry`) vs. deliberately bypasses, so the parity claim is honest. The sim `place_multileg_order` is NEW code (currently a `NotImplementedError` stub), not a retirement.
4. **Regression gate:** capture a **frozen baseline first** — re-run the current equity backtest on today's code (step 0), record the exact run_id, P&L, and monitoring timeframe. The earlier remembered figures are inconsistent (Feb has been recorded as both +$2,415 and as a per-trade ~+$483; the +$542 figure is unreliable) and were produced under daily-bar monitoring that has since changed. Do NOT regress against a remembered number — regress against the frozen re-run. After refactor: same trades, same P&L vs. that frozen baseline, or the refactor broke something.
5. **Then** add the options broker methods + options ExitChecker rules alongside.

---

## Output metrics

The output validates the strategy, not just reports P&L:

1. **Core performance:** total P&L, win rate, avg win, avg loss, payoff ratio, **expectancy per trade**, max drawdown, trade count.
2. **Discipline check:** compliance score (`audit/compliance.py` + options gate checks) — did the agent follow the SOP across the run?
3. **Premise test (directional signal, not proof):** **IVR-filtered vs. control.** The control arm must NOT be implemented by hardcoding strategy logic in Python (CLAUDE.md §1 forbids it). Instead, run a **separate SOP version** (`sops/options-vol-edge/v1.0.0-control.md`) identical to v1.0.0 except the IVR gate is removed, as its own backtest. Compare expectancy. Caveats stated up front: (a) the LLM's qualitative judgment (news, conviction, structure choice) is a confound a single run can't hold constant; (b) the strategy produces few trades per month (single digits per the equity history), so significance requires multiple windows or a long range. This is therefore a **directional signal**, demoted from "most important" — the primary deliverable is the core performance + discipline metrics; the control comparison is supporting evidence, not a clean A/B proof.
4. **Per-trade ledger** exported as JSONL (like the equity backtest) for inspection.

---

## Honest costs / risks

- **BSM-from-surface prices are approximate.** The surface IV is real (inverted from actual historical option closes, so it captures skew and term structure as they actually were), but BSM repricing ignores microstructure, real bid/ask, and intraday moves between daily bars. Accepted: the backtest answers "does the vol-edge thesis have positive expectancy?", not "what exact fills would I get."
- **Surface coverage limits the testable date range** to Alpaca's historical options data (~Feb 2024 onward) and to the universe for which the surface was pre-built. Backtests outside that range/universe are not possible.
- **Net-spread-width gate is not validated in backtest** — with `bid = ask = mid`, the spread-width hard gate reads ~0% and always passes. That gate can only be validated on the live OPRA feed. Noted as a known non-coverage, not a silent gap.
- **The ExitChecker rule registry must be built as a registry from the start**, including a mutable per-position state model for stateful rules (trailing/giveback mutate `trailing_stop`/`highest_close` — they are not pure predicates) and a **hard-fail on unknown rule type** (never silently skip an exit — a skipped exit is unbounded loss). Building hardcoded checks now and refactoring at v1.2.0 (iron condors) is the trap this design avoids.
- **Stateful exits need explicit state.** Today's trailing/giveback logic mutates position fields (harness.py:315+). The registry's evaluator signature must allow reading+updating per-position exit state, not just `(position, params) -> bool`.

---

## Out of scope (future)

- Real OPRA historical data fidelity (vs. BSM synthesis).
- Fill-quality / slippage modeling.
- Multi-strategy concurrent backtests (one strategy per run for now).
- Iron condors / earnings-vol strategies themselves (this engine must *support* them, but they are separate strategy specs).

---

## Implementation order (for the plan)

0. **Freeze the equity regression baseline** — re-run current equity backtest, record run_id + P&L + timeframe.
1. **`black_scholes_greeks()`** in `analysis/options.py` + unit tests (prerequisite — does not exist today).
2. **`option_surface` table + surface-builder** data-prep job (fetch per-strike historical bars → BSM-invert → store) + `query_option_surface` with no-look-ahead bound. Validate it reconstructs real skew on a known date.
3. **ExitChecker registry** + equity rule-evaluators (with state model + hard-fail on unknown rule).
4. **Refactor v3 harness** into Layer-1 core + equity path; implement the next-bar fill guard (`_fill_price_bar`) + gap-skip; route through `place_order`; **regression-test against the frozen baseline from step 0.**
5. **SimulationBroker options methods** (chain/positions/snapshot/multileg via BSM from the surface).
6. **Options ExitChecker rule-evaluators** + SOP exit block + YAML schema/validation.
7. Wire options path end-to-end; run vol-edge over a liquid-universe historical window.
8. Output metrics + IVR-vs-control (separate control SOP) directional comparison.
