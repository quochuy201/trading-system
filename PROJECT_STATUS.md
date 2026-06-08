# Project Status

**Living index of what exists, what's in progress, and known gaps.**
Any AI/engineer (this machine, another machine, Hermes) reads this first.
Update it as part of finishing each unit of work — like committing code.

Last updated: 2026-06-05 · Branch: `main` · Tests: 208 passing

---

## Built & validated

### Core trading system (Phase 0 — pre-options)
- **OPERATING_MANUAL.md** — the constitution: modes (NORMAL/DEFENSIVE/HALTED), sizing math (Kelly + expectancy), staircase risk limits, circuit breakers, EOD reflection.
- **Agents** (`SOUL.md` + `skills/*/SKILL.md`): Orchestrator, Research, Trader, Monitor, Risk Manager, EOD Review, Backtest.
- **Equity day-trade strategy**: `sops/equity/intraday-momentum/` — catalyst-driven momentum, score-based sizing.
- **MCP tools** (`tools/server.py`): broker (place_order, positions, account), data (market data, historical, indicators), risk (kill switch, daily limits, portfolio risk, position size), persistence (trade plans, transactions, decisions ledger), scanner, social sentiment.
- **Broker adapters** (`tools/broker/`): `adapter.py` (abstract) → `alpaca.py` (live/paper) + `simulation.py` (backtest). Global `_broker` swapped during backtest.
- **Backtest v3 harness** (`tools/backtest/harness.py`): equity-only, daily-cycle bar replay, mechanical exits + LLM-on-events. **No-look-ahead guard** = clock-bounded data queries (`query_price_data(end=current_time)`); **entry-timing guard** = `_fill_price_bar` fills at next bar's open, not decision-bar close.

### Options Vol-Edge — Phases 1 & 2 COMPLETE
- **Phase 1 (SOP + agent behavior, markdown)** — merged `9a44cc5`:
  - `sops/options/vol-edge/v1.0.0.md` — Engine A (vol-edge credit/debit spreads) + Engine B (big-fish momentum debit spreads + leashed single-leg longs). Defined-risk only.
  - DD reference, trader/monitor skill updates, `ROADMAP.md`, `HANDOFF.md`.
- **Phase 2 (MCP tooling)** — commits `8d5882a`..`3cd74e4`:
  - `tools/analysis/options.py` — pure fns: parse_occ_symbol, calc_iv_rank, calc_hv, calc_put_skew (IV **points**), calc_expected_move, black_scholes_price, implied_vol_from_price (BSM inversion).
  - 8 MCP tools: `get_options_chain`, `get_options_market_data`, `get_options_positions`, `calc_iv_rank`, `calc_hv`, `get_put_skew`, `calc_expected_move`, `place_multileg_order`.
  - `iv_history` table + repo methods (save/query/count/batch); BSM cold-start bootstrap.
  - Broker adapter options methods (alpaca.py) + simulation stubs (NotImplementedError, await Phase 4).
- **Phase 3 (validation)** — partial, ongoing:
  - Smoke test (`tools/scripts/smoke_test_options.py`): all 8 tools verified live on Alpaca paper.
  - Two real agent dry-runs of the SOP, decision logs audited — agent follows strategy correctly (IVR routing, gate checks, conviction sizing, honest soft-gate downgrades).
  - **One real paper multi-leg order placed & filled** (QQQ 650/640 bull put spread, net credit $1.03) — `place_multileg_order` works end-to-end against Alpaca.

---

## In progress

### Strategy-agnostic backtest engine — DESIGN being written
Goal: test ANY strategy (equity, options, future) without modifying the engine core.
Spec target: `docs/specs/2026-06-05-strategy-agnostic-backtest-design.md` (not yet written).

**Decisions locked so far:**
- **Swap point = broker adapter**, NOT the engine. Same MCP tools serve live (Hermes/Alpaca) and backtest (SimulationBroker). Deploy to Hermes = swap broker back to Alpaca; agent/skills/tools/exits byte-identical.
- **Engine core = thin clock + data feed + event dispatch.** Instrument-agnostic, never changes per strategy.
- **No order-fill simulation.** SimulationBroker = historical-data server + paper trade-logger. Log entry/exit at the **ask price** that existed at the **next bar after the decision** (reuse v3's `_fill_price_bar` next-bar guard). P&L computed at close from logged prices. Bid/ask spread modeling deliberately omitted — measuring strategy edge, not fill quality.
- **Reuse v3 guards verbatim**: clock-bounded queries (add `query_option_data` with same `timestamp <= end` bound), next-bar fill.
- **Exit checks**: deterministic mechanical rules (50% profit / 2× stop / DTE floor) declared in the SOP, run by one shared `ExitChecker` used by BOTH live Monitor and backtest — so backtest exits == live exits.
- **ExitChecker = open registry of named rule-evaluators**, NOT hardcoded if/else. Each rule type is `(position, params) → bool`. Future option strategies (iron condors v1.2.0 = two-sided exits; single-leg longs = pct_of_debit/delta_stop not pct_of_credit; calendars = IV/front-leg-expiry exits) add a new evaluator + reference it in their SOP exit block. Checker core / engine / live path stay untouched. Rule-type names are the stable contract between SOPs and the checker.
- **Backtest universe restricted to deeply liquid names** (SPY/QQQ/AAPL/MSFT/NVDA…) so the OI liquidity gate stays active/unchanged but always passes — avoids needing historical OI (which Alpaca doesn't serve), keeps live code path intact.

**Still to design:** SimulationBroker options methods (chain/positions/greeks from history), ExitChecker rule format, migration path from v3 harness, output metrics (win rate, expectancy, IVR-vs-control comparison to validate the strategy's central premise).

**Spec `docs/specs/2026-06-05-strategy-agnostic-backtest-design.md` — REVISED after peer review; all findings resolved. Ready for a 2nd review pass / implementation plan.**

Resolutions (chose **Option A: historical IV surface**, verified feasible — Alpaca serves per-strike historical option bars; BSM-inverting each strike's close reconstructs real skew, e.g. QQQ showed IV 0.327@m0.78 vs 0.282@m0.85):
1. Greeks: spec now lists `black_scholes_greeks()` as NEW prerequisite work (step 1), not existing.
2. IV surface: new `option_surface` table (per strike/expiry/day) + builder job replaces scalar `iv_history` for backtest pricing. Real skew, not flat.
3. Pricing: BSM **mid** (bid=ask=mid); "ask" removed. Net-spread-width gate explicitly not validated in backtest (needs live OPRA) — noted, not silent.
4. Next-bar fill guard: spec now flags `_fill_price_bar` as dead code → must be implemented + gap-skip added (step 4).
5. IVR-vs-control: demoted to "directional signal"; control arm = separate `v1.0.0-control.md` SOP (no Python strategy logic); LLM-judgment confound + small-sample caveats stated.
6. Regression baseline: freeze a fresh re-run (step 0) instead of trusting the wrong remembered +$542.
7. ExitChecker: evaluator signature carries mutable exit_state (stateful trailing); unknown rule type hard-fails.

---

## Known bugs & gaps

- **`place_multileg_order` qty hardcoded to 1** (`tools/broker/alpaca.py:689`) — ignores agent-computed contract count; always trades 1 spread. Safe for testing, must fix before production sizing.
- **`HARD_SPREAD_WIDTH` gate unreliable on Alpaca INDICATIVE paper feed** — synthetic quotes produce noisy/too-wide net spreads. Needs real OPRA data to validate spread-width gates accurately.
- **Backtest does not yet share full live code path** — `backtest_enter`/`backtest_exit` are separate MCP tools from `place_order`/`place_multileg_order`. The new engine design fixes this (route through the same tools via SimulationBroker).
- **Options simulation methods are stubs** — `simulation.py` options methods raise NotImplementedError pending the backtest engine.
- **No edge validation yet** — agent discipline is proven, but the strategy's profitability (positive expectancy, win rate matching deltas, IVR-filter beating control) is UNVALIDATED. This is the backtest engine's purpose.

---

## Roadmap (options program)

| Phase | Scope | Status |
|---|---|---|
| 1 | Strategy SOP + agent behavior (markdown) | ✅ Complete |
| 2 | Options MCP tooling | ✅ Complete |
| 3 | Paper-trade validation | 🔄 In progress (plumbing + discipline validated; edge not yet) |
| 4 | Strategy-agnostic backtest engine | 🔄 Design in progress |

Future strategy versions: v1.1.x (paper-tuned params), v1.2.0 (iron condors), v1.3.0 (earnings-vol single-leg).

---

## Key references
- `CLAUDE.md` — build/test commands, architecture, backtest rules (NON-NEGOTIABLE).
- `OPERATING_MANUAL.md` — risk constitution.
- `docs/AGENT_EVOLUTION_STANDARD.md` — how the agent learns/remembers safely (frozen-model = externalized learning; four-store separation; Tier 1/2/3 trust; runtime-trust memory). **Includes a "Deployment on Hermes" section**: Hermes (Nous Research) auto-generates SKILL.md + has a Curator; its autonomous skill-promotion MUST be gated through human ratification for risk-bearing behavior. Read before wiring any memory/learning loop or deploying to Hermes.
- `docs/specs/` — design + implementation-plan docs per feature.
- `sops/options/vol-edge/HANDOFF.md` + `ROADMAP.md` — options program detail.
