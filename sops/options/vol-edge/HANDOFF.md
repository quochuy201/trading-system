# Options Vol-Edge — Session Handoff & Next Steps

**Last updated:** 2026-05-31 · **Status:** Phase 1 COMPLETE, merged to `main`.
**Resume by:** `git pull` on `main`, then read this file + `docs/specs/2026-05-31-options-vol-edge-strategy-design.md` (§"The 4-phase program") + `sops/options-vol-edge/ROADMAP.md`. Start Phase 2 with the brainstorming skill.

---

## Where we are

The options strategy was designed and Phase 1 (the decision protocol — **markdown only, no Python**)
is fully authored, reviewed, and merged. The agent now has a complete, unambiguous protocol for
trading the options book; it cannot **execute** until Phase 2 builds the tooling.

### Phase 1 deliverables (all on `main`)
- `sops/options/vol-edge/v1.0.0.md` — the SOP (Phases 1–7: scan, structure/strike, scoring, sizing, entry gates, exit framework, journal/versioning).
- `sops/options/vol-edge/ROADMAP.md` — version ladder (v1.0.0→v1.3.0) + 4-phase program.
- `skills/research/reference/options-vol-edge-dd.md` — Research DD reference (scan + scoring rubrics).
- `skills/research/SKILL.md` — routes `options/vol-edge` SOP → the new DD reference.
- `skills/trader/SKILL.md` — options execution (structure selection, conviction sizing, multi-leg placement).
- `skills/monitor/SKILL.md` — cross-day (15:30 ET) options exit loop.
- `skills/research/reference/options-dd.md` — marked DEPRECATED (superseded).
- `docs/specs/2026-05-31-options-vol-edge-strategy-design.md` — design + 4-phase program.
- `docs/specs/2026-05-31-options-vol-edge-strategy-plan.md` — Phase 1 implementation plan.

## Decisions locked (don't relitigate without reason)
- **Two engines:** A = Vol-Edge income (bull put / bear call credit spreads + debit verticals); B = Directional "big-fish" (momentum debit spreads + **leashed single-leg longs** for the MU/AMD/INTC-style runners). Defined-risk only.
- **Breadth = "Standard + Directional".** Iron condors → v1.2.0; earnings-vol single-leg → v1.3.0 ("Comprehensive").
- **Small-cap account** ($3.5k–$10k start). Tier system reads live equity (compounding is structural). Small tier = narrow spreads ($1–$2.50).
- **Sizing:** conviction-scaled, **no fixed per-trade cap**. Grade ladder **A+ 90–100 / A 80–89 / B+ 70–79 / reject <70** (consistent across SOP, DD ref, trader skill). Manual's "≥80 / A+" DEFENSIVE gate = score ≥80 (grade A or A+).
- **Backstops HELD (non-negotiable):** 6% portfolio heat cap; single-leg total ≤3% heat; Manual circuit breakers −3% day / −6% week / −10% month → HALT; quarter-Kelly cap.
- **Defers to `OPERATING_MANUAL.md`** on everything; only ever stricter. Swing SOP overrides the day-trade 15:45 flatten; exits run a 15:30 ET cross-day loop (holds overnight).
- **Cost gate OFF** (`income.target_per_day_usd: 0`) — costs tracked/reported in EOD, never block trades.

## Known gaps / notes to carry forward
- **Engine B can't be dry-run until Phase 2** (needs live indicators + IV). A tabletop dry run of Engine A (QCOM bull put spread on a $5k Small-tier account → 1 contract, $2.50-wide, 3.6% defined risk) validated the Phase 1→6 chain on real data.
- **Forward tool-name dependencies — Phase 2 MUST build tools under these exact names** (already referenced by skills): `get_options_positions`, `get_options_market_data` (Monitor `requires_tools`), plus the chain/IVR/Greeks/multi-leg tools the SOP+skills call. If you rename, update the skills.
- **DTE window nuance:** credit spreads are 30–45 DTE (never <21). The referenced June-2 example used ~25 DTE; the SOP rolls to the next expiry ≥30 DTE.
- **Pre-existing, UNRELATED:** `tools/tests/test_harness.py` has **9 failing tests on `main`** (backtest harness v3, not touched by this work; 116 other tests pass). Worth a separate fix — see "test_harness failures" candidate task.

---

## Next steps — Phase 2: Options MCP Tooling (own brainstorm → spec → plan → build)

Goal: make the SOP executable on Alpaca paper. `alpaca-py>=0.30.0` (already a dep) supports
`OptionHistoricalDataClient` (snapshots incl. real-time Greeks + IV) and multi-leg (`mleg`) orders
via `OptionLegRequest`.

1. **Broker adapter** (`tools/broker/alpaca.py` + `adapter.py`): options chain fetch; option snapshot (Greeks + IV); multi-leg limit order placement; cancel; `get_options_positions`. Mirror the dict/list shapes of existing methods.
2. **MCP tools** (`tools/server.py`): `get_options_chain`, `get_option_snapshot`/`get_options_market_data`, `calc_iv_rank` (IVR — needs a 52-wk IV history source), `calc_hv` (HV20), `get_put_skew`, `calc_expected_move`, `get_options_positions`, `place_multileg_order`. Names must match what the skills reference. Mutating tools log to ledger + use `with_retry`; never raise — return `{"error": ...}`.
3. **One interface for IVR/Greeks usable live AND in backtest** (CLAUDE.md: backtest = live code path).
4. **Cost-capture** for the EOD cost-tracking report (token + broker fees).
5. **Tests** per tool.

Then: **Phase 3** (paper-trade validation, options journal fields, end-to-end on real data) →
**Phase 4** (options backtest engine: extend `tools/backtest/`; decide data fidelity — real Alpaca
options data ~Feb 2024+ vs synthetic Black-Scholes vs hybrid).
