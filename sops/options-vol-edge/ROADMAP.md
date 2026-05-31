# Options Vol-Edge — Roadmap

Cross-machine pickup point for the options-trading program. Full design:
`docs/specs/2026-05-31-options-vol-edge-strategy-design.md`.

Origin: ported from the prior "Multi Agent Trading System with OpenClaw / Hermes" work
(`options-trader.skill`, `options-exit-manager.skill`, `swing_trading_strategy.md`,
`options_dry_run_june2_2026.md`), Natenberg vol-edge framework + this repo's equity-regime filters.

---

## Strategy version ladder

| Version | Scope | Status |
|---|---|---|
| **v1.0.0** | **"Standard + Directional lane."** Engine A (vol-edge): bull put / bear call credit spreads + debit verticals. Engine B (big-fish): momentum debit spreads + leashed single-leg longs. Small-cap account tiers, conviction-scaled sizing. | **In progress (Phase 1)** |
| v1.1.x | Refinements from paper-trade data (strike deltas, DTE windows, heat/leash tuning). | Planned |
| v1.2.0 | + Iron condors (neutral-regime path, IVR > 85, two-sided exits). | Planned |
| v1.3.0 | + Earnings-vol single-leg variant (implied-vs-actual-move). **= "Comprehensive" set complete.** | Planned |

## Implementation program (4 phases)

| Phase | Deliverable | Status |
|---|---|---|
| **1** | Strategy SOP + agent behavior (markdown only). | In progress |
| **2** | Options MCP tooling — chain/IVR/Greeks/HV20/put-skew/expected-move, multi-leg spread orders, Alpaca adapter methods, cost-capture. IVR/Greeks behind one interface usable live + backtest. | Not started |
| **3** | Paper-trade validation on Alpaca; options journal fields; end-to-end on real data. | Not started |
| **4** | **Options backtest engine** — extend `tools/backtest/` with an options simulation adapter (agent-driven bar replay, no look-ahead, multi-leg fills). Open decision: data fidelity (real Alpaca options data vs. synthetic Black-Scholes vs. hybrid). | Not started |

## Key constraints (carry forward)

- **`OPERATING_MANUAL.md` is the constitution** — this SOP defers all mode/limit/sizing-framework
  decisions to it and may only be *stricter*.
- **Defined-risk only.** Single-leg longs are the one uncapped instrument, leashed (≤ ~3% total heat).
- **Account-level backstops are non-negotiable:** 6% portfolio heat cap; −3% day / −6% week /
  −10% month → HALT. Per-trade sizing is conviction-scaled with no fixed cap, but governed by these.
- **Cost gate OFF** (`income.target_per_day_usd: 0`) — costs tracked/reported, not gated.
- **Backtest must share the live code path** (CLAUDE.md) — no strategy logic hardcoded in Python.
- **Small-cap reality:** options viability floor ≈ $3.5k; below it, equity-swing bridge (future spec).
