# Project Status

**Living index of what exists, what's in progress, and known gaps.**
Any AI/engineer (this machine, another machine, Hermes) reads this first.
Update it as part of finishing each unit of work — like committing code.

Last updated: 2026-06-09 (session 2) · Branch: `main` (local, ahead of origin/main) · Tests: 230 passing, 0 failures

---

## ⏩ Session handoff — 2026-06-09 session 2 (swing gatekeeper program, Bensdorp-derived)

**Goal (user):** improve swing+intraday gatekeeping per Bensdorp *Automated Stock
Trading Systems*; add social hype detection; validate research+monitor skills on a
1-week backtest; iterate toward >70% WR and $500/week on $100k.
**Reality check (logged):** the book's BEST mean-reversion systems run ~57-63% WR
(Sys-3) and trend systems ~45%; a 1-week sample is ~5-15 trades → statistically
indicative at best. Judge by expectancy per R; treat 70%/$500 as a stretch target,
beware overfitting one week.

**Shipped this session:**
1. **`sops/equity/swing/v1.0.0.md`** — NEW two-engine swing SOP (12-ingredient frame):
   Engine M = momentum continuation (book Sys-1 adapted, gates M-G1..G9), Engine R =
   mean-reversion dip (Sys-3/5 hybrid, gates R-G1..G8, incl. AI thesis-break veto
   R-G7). All thresholds `BOOK-DERIVED` pending calibration.
2. **`sops/_routing/v1.1.0.md`** — engine-aware eligibility (R-ONLY/M-ONLY cells),
   new mild-correction row (Engine R runs in pullbacks), iv_rank removed from
   equity rows (price-only, backtest-computable).
3. **Scanner**: `scan_universe_swing()` in `tools/scanner/filters.py` (SWING_V1
   thresholds mirror the SOP; per-gate fail lists for honest rules_triggered
   logging) + `scan_swing_candidates` MCP tool. 9 new tests.
4. **Research skill**: two-engine swing scan section, ranking rules, reentry rule,
   and a 4-state **Hype Detection** framework (EARLY/CONFIRMED/LATE/NO-HYPE) with
   engine-specific use (R inverts: retail panic = contrarian-positive). Backtest
   fallback: social scores NEUTRAL, logged "social: unavailable" — APIs have no history.
5. **`swing-trade-dd.md`** rewritten: per-engine 0-100 rubrics (≥70 full / 60-69 half /
   <60 skip), R-engine drop-diagnosis block (35 pts), kill lists, catalyst decay model.
6. **`sops/equity/intraday-momentum/v1.1.0.md`** — Phase 0 gatekeeper (I-G1 market
   alignment, I-G2 $50M dollar-vol, I-G3 spread), RVOL ranking, reentry rule, hype veto.
7. **Monitor skill**: engine-aware exit profiles table (M: trail/20d; R: +4% target,
   4-session time stop, NEVER trail).
8. **Backtest prep**: week chosen = **Nov 17-21, 2025** (most volatile in cached SPY
   range: 3.7% range, chop — stresses gates AND fires R-engine dips).
   `tools/scripts/load_backtest_week.py` ready; found+handles corrupted SPY bar
   (2026-02-02 low=69.005, decimal-shifted tick).

**NEXT STEP (blocked on user's machine — sandbox can't reach Alpaca):**
```
cd tools && uv run python scripts/load_backtest_week.py
```
Then: agent-driven backtest per CLAUDE.md rules (v3 harness, agent applies
skills/SOPs day by day, Python only mechanics), analyze WR/expectancy/P&L per
engine, calibrate `BOOK-DERIVED` thresholds via a new SOP version.

---

## ⏩ Session handoff — 2026-06-09 (routing blockers 1+2 cleared, bug fixes)

**Shipped this session (commit `34cd106` on local `main` — push before switching machines):**
1. **Routing blocker 1 FIXED — `iv_rank_spy` sourced.** Extracted shared `_compute_iv_rank()` in `tools/server.py` (used by both the `calc_iv_rank` tool and `get_market_regime`). `get_market_regime` now injects SPY IV-rank; any failure → null (fail-safe). **Skipped entirely in backtest mode** — SimulationBroker options stubs raise NotImplementedError and `with_retry` (10 attempts, exp backoff) would have stalled replay ~10 min per call. Phase-4 engine will serve it from the historical IV surface. Tests: `tests/test_regime.py::TestGetMarketRegimeTool` (4 cases incl. backtest-skip).
2. **Routing blocker 2 FIXED — research DD pointer.** `skills/research/SKILL.md` routing step now has an explicit strategy-id → `reference/*-dd.md` mapping table (was a dangling `sops/<id>/dd.md` pointer). Chose pointer-fix over co-locating dd.md per strategy (no install-path churn).
3. **`place_multileg_order` qty unhardcoded.** New `qty` param (default 1) plumbed through MCP tool → adapter ABC → alpaca.py (`tools/broker/alpaca.py`); validates qty ≥ 1 at both layers; ledger quantity = qty × Σratio_qty. Trader skill Step O-5 now says to pass the Step O-4 `contracts` count as `qty`. 7 new tests.
4. **9 stale harness tests migrated.** `tests/test_harness.py` rewritten against the v3 API (start/advance_to_next_day/load_day_bars/step_bar) — 14 tests covering every mechanical exit rule (stop next-bar-open, target-exact-price, trailing arm+break, time stop), event detection, and a 2-day end-to-end run. Suite: **221 pass / 0 fail.**

**Remaining before routing can trade (was 3 blockers, now 1):**
- **End-to-end validation** — run the golden cases (`docs/plans/2026-06-06-routing-golden-cases.md`) on paper; then Phase-4 gate-vs-control backtest to tighten the PLACEHOLDER thresholds.

---

## ⏩ Session handoff — 2026-06-07 (continue from another machine)

**To pick up:** `git fetch origin && git checkout feature/strategy-routing` (this branch has ALL the work below — routing + restructure + install fixes). PR #1: https://github.com/quochuy201/trading-system/pull/1

**Shipped this session:**
1. **Strategy routing (P0–P2)** — auto strategy selection. Risk-manager eligibility gate (regime → ON/OFF) + research setup-routing (candidate → eligible strategy) + shared account budget. New `get_market_regime` MCP tool (raw signals only) + `tools/analysis/regime.py` (+ tests). Routing SOP `sops/_routing/v1.0.0.md`. Spec: `docs/specs/2026-06-06-strategy-routing-design.md`; plan: `docs/plans/2026-06-06-strategy-routing.md`.
2. **Directory restructure** — `sops/` is now a market→strategy tree: `sops/equity/intraday-momentum/`, `sops/options/vol-edge/`, `sops/_routing/`. Config registry ids reconciled to match (`options/vol-edge`, `equity/intraday-momentum`). All live path refs updated.
3. **install.sh fixes** — (a) merge-copy so skills/sops/cron don't nest under an existing Curator profile; (b) now copies `OPERATING_MANUAL.md` into the profile (was missing — agent ran without its constitution). **Verified on the Hermes profile**: nested sops install intact, every skill path-ref resolves, config ids resolve, no stale paths.

**Routing is WIRED but GATED OFF — 3 blockers before it can actually trade (in priority order):**
1. ~~**`iv_rank_spy` unsourced**~~ → **FIXED 2026-06-09** (see handoff above).
2. ~~**Research DD pointer dangling**~~ → **FIXED 2026-06-09** (mapping table in research SKILL.md).
3. **No end-to-end validation** — run the golden cases (`docs/plans/2026-06-06-routing-golden-cases.md`) on paper; then Phase-4 gate-vs-control backtest to tighten the PLACEHOLDER thresholds.

**Other open items:** swing SOP still doesn't exist (`sops/equity/swing/` reserved); Phase-4 backtest engine still just a spec; `iv_rank_spy` + `catalyst_density` deferred.

**Local-only (NOT pushed):** a `git stash` named `hermes-wip-archive-jun1` holds weeks-old Hermes scratch (cron experiments, Feb-2026 backtest scripts, doc stubs) — recoverable via `git stash list`; drop when sure. This stash does NOT travel to the other laptop.

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

- ~~9 stale tests in test_harness.py~~ — **FIXED 2026-06-09**: rewritten against the v3 API; suite 221 pass / 0 fail.
- ~~`place_multileg_order` qty hardcoded to 1~~ — **FIXED 2026-06-09**: `qty` param plumbed tool→adapter→alpaca; validated ≥ 1. NOTE: live order with qty > 1 not yet exercised on paper (only qty=1 spread has been placed for real).
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
