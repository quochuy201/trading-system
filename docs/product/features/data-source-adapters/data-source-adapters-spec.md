# Spec: Data Source Adapters

- **Slug:** `data-source-adapters`
- **Status:** `spec`
- **Priority:** `P1` — blocks `capital-aware-selection`; also closes a live deployment gap
- **Owner sign-off:** ☑ approved 2026-07-25 (BUILD-PLAN §2, **D3**)
- **Layer(s):** 1 Perception
- **Author:** Claude Code · **Date:** 2026-07-25

## Problem

### 1. Only one source is implemented, and it can't serve live trading

`tools/data/source.py` defines a clean `MarketDataSource` ABC — but with exactly **two methods** (`get_daily_bars`, `get_last_price`) and **one implementation**. The factory raises on anything else:

```python
name = (name or os.environ.get("TRADING_DATA_SOURCE", "yfinance")).lower()
if name == "yfinance": return YFinanceSource()
raise ValueError(f"unknown data source: {name!r}")     # source.py:100 — AlpacaSource does not exist
```

The module docstring states the intent ("swap to a paid source by adding a subclass and a factory branch") — the seam exists, the subclass was never written.

**yfinance is daily-only.** That is fine for premarket scanning and backtests, and **useless for monitoring**: during the session the monitor needs intraday bars and current quotes to evaluate stops, targets and exits. There is currently no source that can serve the live path.

### 2. 🔴 Deployment divergence — built capability never reached its consumer

**The options data source already exists and works.** `tools/data/options_source.py` provides `OptionsDataSource` + `AlpacaOptionsSource` (`get_chain`, `get_snapshot`, `capture_iv`, `iv_rank`), exposed as **five MCP tools** — `get_options_chain` (`server.py:1465`), `get_options_market_data` (:1514), `calc_iv_rank` (:1573), `get_put_skew` (:1697), `calc_expected_move` (:1766) — and `PROJECT_STATUS.md` records all of them smoke-tested live against Alpaca paper, plus one real multi-leg order filled.

**But the agent that needs them cannot see them.** The running `options-trader` skill lives **only in the Hermes deployment** (`Hermes/skills/options-trader/`) and **has no counterpart in this repo**. Verified: it references **zero** of the options MCP tools (`grep -c` = 0). Its gate requires an IV-rank read on every candidate, so with no tool it falls back to web search — producing the stale, contradictory IVR values that appear in `trades.jsonl` and the **34-session zero-trade drought**, alongside repeated escalations for an options data feed (6×) and XSP (33×).

**Consequence:** the escalations were solving the wrong problem. The feed is not missing — it is **built, tested, and unwired**. Two tracks drifted apart: the repo has tooling with no running options agent; Hermes has a running options agent with no tooling.

### 3. No capability model

Callers cannot ask a source what it can do. yfinance silently cannot serve intraday; there is no way to select correctly per phase, or to fail loudly when a needed capability is absent.

## Goal

One canonical `MarketDataSource` interface with **capability-flagged adapters**, selected by environment, so that: the live/monitoring path is served by the execution broker's own data, backtests stay on cached/daily data, a provider swap is one new adapter plus a config change — and **capability that exists in the repo demonstrably reaches the agents that need it**.

## User / System Value

- **Unblocks `capital-aware-selection`** — ranking options candidates by `credit/BPR` requires live chain data.
- **Makes monitoring possible** — intraday bars + quotes for stops and exits.
- **Ends the drought's data half** — by wiring existing tools rather than buying a feed.
- **Provider independence** — no vendor lock-in; swapping is a bounded, testable change.

## Scope

**In scope**
- Extend `MarketDataSource`: `get_intraday_bars`, `get_last_quote`, `get_universe`, and **`capabilities()`**.
- Canonical `Bar` / `Quote` types — downstream never sees a vendor payload.
- **Implement `AlpacaSource`** (equity: daily + intraday + quotes) behind the existing seam.
- **Capability flags** + a loud failure when a required capability is missing (never a silent wrong answer).
- **Env-bound selection**: `TRADING_ENV` drives data source alongside broker mode and risk config (D2/D3); dev/backtest → yfinance/cached, live → Alpaca. Fail-safe to dev.
- **Divergence audit + wiring:** verify the options MCP tools are exposed to the options consumer; close the gap so IVR/chain data comes from the API, not web search. Includes a **regression test that the repo's options tools are reachable by the options tool group.**

**Out of scope / non-goals**
- **Pre-computed-indicator APIs** (Alpha Vantage / FMP / TradingView screener) — **rejected 2026-07-25** (R1 §S1). Local bars stay the source of truth and we compute our own indicators: a screener returns only *today's* values, so **backtest replay (D7) becomes impossible**; vendor indicator math is unverifiable and silently divergent from ours; and it is **signal-layer lock-in, which the adapter pattern cannot rescue**. A screener may serve as a *discovery* layer (see below), never a computation layer.
- **Universe redesign** (point-in-time membership, dynamic movers discovery) — decided in R1 §S2/S3, built with the scanner (D4), not here. This feature supplies *bars and quotes*; `get_universe()` is the seam those will use.
- Paid feeds (SIP / Polygon / Databento) — deferred until profitability (D3).
- Rewriting the `options-trader` strategy itself (separate concern; this feature supplies data, not strategy).
- Reconciling the full Hermes-vs-repo skill divergence — flagged here, addressed by `deployment` (parked).
- **LLM anywhere in the runtime data path** — explicitly forbidden (D3). LLM authors adapters at build time only.

## Acceptance Criteria

1. `MarketDataSource` exposes daily bars, intraday bars, last quote, universe, and `capabilities()`.
2. `AlpacaSource` implemented and returns **the same canonical shapes** as `YFinanceSource` for overlapping methods.
3. `YFinanceSource.capabilities()` reports **no intraday**; requesting intraday from it raises a clear error — never returns daily data silently.
4. Downstream code (scanner, monitor, backtest) references **only canonical types**, never a vendor field name. Enforced by test.
5. `TRADING_ENV` selects the source; unknown/unset ⇒ dev; live env ⇒ Alpaca for the live path.
6. Monitoring reads live marks from the **execution broker's** feed (D3 principle).
7. **Options tools are reachable by the options consumer** — a test asserts the options MCP tools are exposed in the relevant tool group, so the "built but unwired" failure cannot recur silently.
8. Swapping providers requires **no change** to scanner/monitor/backtest code.
9. All existing tests stay green.

## Risks & Safety Impact

- **No direct trading-safety impact** — this is Perception, not Risk. It does not touch the kill switch, gate, or sizing.
- **Wrong data is the real risk.** A misaligned adapter (adjusted vs raw prices, tz drift, wrong volume basis) produces confidently wrong signals. Mitigation: canonical types + a **cross-source consistency test** (same symbol/date across yfinance and Alpaca must agree within tolerance) before Alpaca is trusted for live.
- **IEX partial volume:** Alpaca's free feed is ~2–3% of consolidated volume — acceptable for price/stop checks, **not** for volume-derived signals (RVOL). Must be flagged in `capabilities()` so a future RVOL consumer fails loudly rather than trusting thin volume.
- **Fail-safe:** unknown env ⇒ dev; missing capability ⇒ explicit error, never a silent substitution.

## Open Decisions

- **D-DS1: Cutover for equity bars** — keep yfinance as the daily default, or switch to Alpaca once validated? *(Recommend: **keep yfinance default until the cross-source consistency test passes**, then switch live to Alpaca; backtests stay on cached data for reproducibility.)*
- **D-DS2: Does the options wiring belong here or in `deployment`?** *(Recommend: **the audit + reachability test here** (it is a data-source concern); the broader Hermes/repo skill reconciliation in `deployment`.)*

## References

- Code: `tools/data/source.py` (ABC + factory :95-100), `tools/data/options_source.py`, `tools/data/cache.py`, `tools/data/validate.py`; options MCP tools `server.py:1465,1514,1573,1697,1766`
- `docs/product/BUILD-PLAN.md` — **D3** decision + D3 design notes; **D6** (cross-asset selection)
- `docs/product/research/R1-scanner-redesign.md` §S1 (data source), §S2 (dynamic candidates)
- Evidence of divergence: `Hermes/skills/options-trader/SKILL.md` (0 references to options MCP tools); `Hermes/trades.jsonl` (34 no-trade sessions citing unavailable chain data)
