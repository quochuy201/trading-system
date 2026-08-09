# Trading System — Strategic Improvement Plan (AI × Algorithmic × Software Engineering)

**Status:** DRAFT v2 — updated 2026-07-13 with architecture + tool design + pipeline research
**Author:** Hermes (PM/research)

> **What this is.** A consolidated, code-grounded plan covering: (1) where the system
> stands, (2) research enrichment (GitHub, X, arXiv, books), (3) a clear target system
> design, (4) a multi-phase plan, (5) detailed architecture + tool-contract design from
> the 2026-07-13 architecture discussion.
>
> **Scope discipline.** Research + design only. No code, SOP, config, cron, or skill
> was modified. Every claim about our system was verified against code (file:line cited),
> not against prior docs.

---

## 0. TL;DR (the one-page version)

1. **The single most important safety control is still missing in code.** Verified:
   `place_order()` (`tools/server.py:166`) enforces **only the kill switch**. R:R,
   position caps, daily-loss, concentration, regime eligibility, and mode are all
   *advisory markdown*. The governance gate is specced and approved but NOT built.

2. **The right integration model: LLM proposes; deterministic code gates; deterministic
   code executes.** AI in the middle (reasoning/synthesis), code on the outside
   (perception, risk, execution, audit). The LLM must never reach the broker without
   passing a gate that cannot be skipped.

3. **Engine M/R and the binary-gate scanner are obsolete.** This was confirmed 2026-07-13
   by the owner. Cross-sectional factor ranking (z-scored, regime-weighted, IC-tracked)
   replaces the 4-layer binary filter. M/R become pluggable alpha models alongside new
   strategy families (breakout, pullback-to-MA, volatility compression, event-earnings,
   sector rotation, options/vol-edge).

4. **The scanner is not the engine — the pipeline is.** The pipeline (factor computation →
   ranking → news/sentiment enrichment → LLM reasoning → gate → execution) is permanent.
   Every component inside it (factors, strategies, data sources) is swappable by config.

5. **Found bugs:** `risk/checks.py` defaults `MAX_OPEN_POSITIONS=5` vs ratified **10**.
   `TradePlan.risk_assessment: dict` is untyped. Governance gate unbuilt.

6. **The plan is 5 phases.** P0 Governance gate + typed tool contracts. P1 Memory recall +
   evaluation rigor. P2 Factor scanner. P3 Strategy expansion. P4 Data/infra hardening.

---

## 1. Method & sources

**2026-07-11 (original sweep):**
- Code review: `server.py`, `risk/checks.py`, `models.py`, `scanner/filters.py`
- GitHub: `nautilus_trader`, `TradingAgents`, `ai-hedge-fund`, `FinRL`, `freqtrade`, `vectorbt`
- X (practitioner, 4 deep syntheses): pro quant stack, LLM-agent production lessons,
  newest 2026 papers, systematic swing exit/sizing/overfitting
- Books: López de Prado, Carver, Bensdorp

**2026-07-13 (architecture + tool design):**
- X: two additional deep syntheses on (a) deterministic event-driven harness architecture
  vs. LLM-native multi-agent, and (b) agent harness patterns — thin orchestrator vs thick
  mediator, tool sandboxing, approval gates, audit trail
- Owner discussion: Engine M/R and binary gates declared obsolete, LLM-as-brains pipeline
  architecture confirmed, tool contract design spec'd

---

## 2. Where we stand — code-grounded scorecard

| Layer | Grade | State |
|-------|-------|-------|
| **1 Perception** | **B+** | Daily yfinance bars, staleness guard (5d), refresh cron. Gaps: prototyping-grade source, no dynamic universe, no provenance stamp. |
| **2 Memory** | **B** | 16 SQLite tables + tuning_config.json feedback bridge. Rich *storage*, weak *recall*. |
| **3 Reasoning** | **B–** | LLM DD + scoring. No time-scale taxonomy. LLM trusted with numbers it shouldn't own. |
| **4 Action** | **C+** | `TradePlan` carries stop/target/qty. Conviction/engine/regime/catalyst buried in untyped `dict`. |
| **5 Risk** | **D** | Only kill switch enforced. All other rules = advisory markdown. **This is the #1 gap.** |
| **6 Audit** | **B** | Append-only tables excellent. No hash-chain/replayability. No role attribution. |

**Three concrete defects:**
1. **[P0]** Governance gate unbuilt — `place_order` → kill switch → broker, nothing else.
2. **[P1]** Config drift: `checks.py` max_positions=5 vs OPERATING_MANUAL=10.
3. **[P1]** Semi-typed action contract.

**What's good and should NOT be touched:**
- Shared live/backtest code path (research-to-live parity — the nautilus principle)
- EOD→scanner feedback bridge (`tuning.py` + `tuning_config.json`)
- Repository pattern isolating all DB access
- Kill switch inside `place_order` — proves the gate pattern works
- 326 test functions (last run: 331 passing, 2026-06-27)

---

## 3. Architecture research — how the pros build these systems

### 3.1 Five architecture patterns for AI + algorithmic trading

The 2026-07-13 research identified five distinct patterns used in production:

**Pattern A: Deterministic event-driven core (nautilus_trader, institutional quant)**
- Single-threaded event loop processes timestamped events in strict chronological order
- Virtual clock — event time, never wall-clock
- Strategies are thin reactive callbacks (`on_market_data()`, `on_timer()`, `on_order_filled()`)
- Same engine for backtest and live — "research-to-live parity" enforced by architecture
- LLM is optional: call for sentiment/news, never for execution or signal math
- Used by: every professional quant firm, nautilus_trader (24.6k ⭐), QuantConnect LEAN

**Pattern B: LLM-native multi-agent (TradingAgents, ai-hedge-fund)**
- Specialized LLM agents mirror a trading desk (Analyst → Researcher debate → Trader → Risk → PM gate)
- LLM drives the pipeline — it calls tools, decides sequence, produces the plan
- PM gate at the end: approve/reject before execution
- TradingAgents v0.3.x evolution: added structured outputs, decision log, look-ahead filtering
- Used by: TradingAgents (92k ⭐), ai-hedge-fund (61k ⭐)

**Pattern C: LLM-as-brains + deterministic harness (our target)**
- Pipeline pre-computes everything (factors, sentiment, news, regime, risk, episodic memory)
- LLM receives ONE structured brief → produces ONE structured plan
- Gate validates the plan against the brief (source-verifiable)
- LLM never touches tools, never orchestrates, never reaches broker directly
- This is the convergence of ALL credible sources — the papers, the practitioners,
  the 2026-07-13 architecture discussion

**Pattern D: RL-driven (GIFT, AlphaQuanter, FinRL)**
- LLM designs the state/reward interface; RL executes
- No runtime LLM queries — the RL policy is the strategy
- Requires thousands of simulation episodes; best for HFT/market-making

**Pattern E: LLM as strategy generator, not executor (MetaPS)**
- LLM produces programmatic strategy code (Python functions mapping observations → actions)
- Code is backtested, validated, deployed — LLM is done
- No LLM in the runtime loop at all
- Best for: generating new strategy ideas from natural-language descriptions

### 3.2 Thin orchestrator vs thick mediator — what the harness looks like

The 2026-07-13 research converged on one pattern:

> **The LLM is thin and smart. The harness is thick and disciplined.**

In a thin-orchestrator system, the LLM makes most decisions (routing, tool selection,
execution sequence). In a thick-harness system, the runtime owns all of that — the LLM
is just one component inside a heavily instrumented workflow.

**For trading: prefer a thin central orchestrator backed by a thick mediator layer.**

```
  LLM (thin, smart)
    │  ONE call: receives TradingBrief → produces TradePlan
    │
  MEDIATOR (thick, deterministic)
    │  • Runs pipeline before LLM wakes up
    │  • Assembles TradingBrief from all sources
    │  • Hands brief to LLM
    │  • Receives TradePlan
    │  • Gate validates every field against the brief
    │  • Audit logs every step
    │  • Executes only if APPROVED
    │
  BROKER
```

This is exactly what the X practitioner consensus says: "all paths flow through centralized
mediators for safety and observability." The LLM proposes; the runtime enforces. "The
runtime is what pays — at 3am you want `ps`, `kill -9`, and a replay log."

### 3.3 Us vs. the field

| Dimension | Canonical practice | Our system today | Verdict |
|-----------|-------------------|------------------|---------|
| Engine | Deterministic event-driven core | Hermes cron loop, no event queue | **Lag** (Phase 4) |
| Research↔live parity | One engine, no code change (nautilus) | Shared scanner path mostly | **Match** |
| Signal generation | Cross-sectional factor ranking, LASSO, IC decay | Single-stock binary thresholds | **Lag** (Phase 2) |
| LLM role | Proposer/analyst behind a hard gate | LLM reasons AND effectively decides (no gate) | **Lag** (Phase 0) |
| Tool contracts | Typed input/output schemas, validated on every call | Flat @mcp.tool() functions, no enforcement | **Lag** (Phase 0) |
| Harness pattern | Thick mediator, thin LLM | Thin orchestrator, no mediator | **Lag** (Phase 0-1) |
| Inter-agent contracts | Typed JSON everywhere (15+ papers) | TradePlan typed core only | **Partial** (Phase 1) |
| Backtest rigor | PIT data, cost+impact model, CPCV, PBO | Walk-forward windows, small n | **Lag** (Phase 1) |
| Memory | Working+episodic+semantic, recalled | Rich storage, no recall | **Partial** (Phase 1) |
| Feedback loop | Rare in open source | EOD→scanner tuning bridge exists | **Lead** |
| Audit | Hash-chained replayable rounds | Append-only, no chain | **Partial** (Phase 4) |
| Platform | Built from scratch each time | Hermes (kanban+MCP+cron) | **Lead** |

### 3.4 Anti-patterns (what kills these systems)

- **Never let the LLM do arithmetic money depends on.** Position size, R:R, P&L — all in code.
- **Never remove the off switch.** "Connect the agent, hand it API access, go to bed" ends in liquidation.
- **Never trust a beautiful backtest.** Small-n edges + no impact model = retail death spiral.
- **Don't chase latency/HFT.** Our edge is daily/swing horizon.
- **Don't add agents for their own sake.** Value comes from deliberation, not headcount.
- **Don't over-engineer infra ahead of proof.** Upgrade when measured problems force it.
- **Don't scatter risk limits.** One source of truth. The 5-vs-10 drift is what happens when they live in two places.
- **Don't trust the LLM to follow an SOP.** Enforce the SOP in code around the LLM — the SOP follows the LLM, not the other way around.

---

## 4. The integration thesis — how AI, algo, and software fit together

> **The rule:** LLM reasons; deterministic code gates; deterministic code executes.
> The LLM is *boxed in the middle*. Perception, Risk, and Audit are code. Reasoning
> and synthesis are AI. Execution is code. Money never depends on LLM arithmetic, and
> an order never reaches the broker without passing a gate that cannot be skipped.

```
        ┌────────────────────── SOFTWARE ENGINEERING (the harness) ──────────────────────┐
        │   typed contracts • tests • deterministic time • replayable audit • kill switch │
        │                                                                                 │
        │   ┌───────────────┐    ┌──────────────┐    ┌──────────┐    ┌──────────┐         │
        │   │  PERCEPTION   │───►│    MEMORY    │───►│  GATE    │───►│ BROKER   │         │
        │   │  (ALGO + CODE)│    │ (ALGO + CODE)│    │  (CODE)  │    │  (CODE)  │         │
        │   │               │    │              │    │          │    │          │         │
        │   │ factor scanner│    │ episodic     │    │ kill sw. │    │          │         │
        │   │ news fetcher  │    │ working mem  │    │ R:R      │    │          │         │
        │   │ sentiment     │    │ risk snapshot│    │ limits   │    │          │         │
        │   │ regime class. │    │ regime state │    │ conc.    │    │          │         │
        │   │ RL model      │    │ tuning cfg   │    │ catalyst │    │          │         │
        │   └───────┬───────┘    └──────┬───────┘    │ source   │    └──────────┘         │
        │           │                   │            └────▲─────┘                        │
        │           │    TradingBrief   │                 │                              │
        │           └───────────────────┘                 │                              │
        │                          │                     │                              │
        │                          ▼                     │                              │
        │               ┌──────────────────┐             │                              │
        │               │    REASONING     │             │                              │
        │               │      (AI)        │─────────────┘                              │
        │               │                  │                                            │
        │               │ LLM: synthesize, │  TradePlan → gate validates against brief   │
        │               │ debate, propose  │  Gate APPROVED → broker executes            │
        │               │ — NO arithmetic  │  Gate REJECTED → LLM adapts or stops        │
        │               │ — NO tools       │                                            │
        │               └──────────────────┘                                            │
        │                                                                                 │
        │   ◄─────────────────── AUDIT (CODE): hash-chained decision rounds ────────────── │
        └─────────────────────────────────────────────────────────────────────────────────┘
```

**What each layer owns:**

- **Algo owns Perception + Memory raw computation** — factor ranking, regime classification,
  sentiment scoring, catalyst extraction, episodic recall. Deterministic, testable.
- **AI owns Reasoning** — multi-source synthesis, catalyst quality judgment, pattern
  recognition across time/regime, contrarian overrides with reasoning, adaptation to gate
  feedback, unstructured data comprehension. One call: TradingBrief in → TradePlan out.
- **Code owns Risk gate + Execution + Audit** — the parts where a mistake costs money.

**How the LLM is actually leveraged** (not constrained — fed):

| LLM capability | Concrete example |
|---|---|
| Multi-source synthesis | Connect MS upgrade + Reddit front-run signal + Twitter volume spike → "Catalyst real but may be priced in." |
| Catalyst quality judgment | Distinguish "earnings beat" (durable) from "CNBC mention" (noise) |
| Pattern recognition across regimes | "Last 5 Engine-R trades won when VIX<15. Today VIX=22. Reducing conviction 75→55." |
| Contrarian overrides with reasoning | "Scanner score 85 but momentum-only. Fundamentals flat. Sentiment fading. Regime shifting. SKIP." |
| Adapting to gate feedback | Gate: "R:R 1.8 < 2.0." LLM: "Widening stop to 2.0×ATR. New R:R = 2.3. Resubmitting." |
| Unstructured data comprehension | Read 8,000-word earnings transcript → "CEO said supply easing — this is more bullish than the EPS miss suggests." |

The LLM spends 100% of its context on the decision, not on orchestration. It never calls
tools. It reads a pre-assembled brief. It produces a typed plan. The gate enforces the SOP.

---

## 5. Tool contract design — how AI agents call functions safely

### 5.1 Current state (the problem)

`tools/server.py` is ~2,878 lines. Every tool is a flat `@mcp.tool()` function. Submodule
functions (`risk/checks.py`, `scanner/filters.py`) return different shapes — some JSON
strings, some dicts, no shared interface. Adding a tool always touches `server.py`. The
LLM reads docstrings and trusts them. Nothing enforces that the LLM calls the right tool
at the right time, with the right params.

### 5.2 The contract pattern

Every tool implements a standard `ToolContract` ABC. The contract is enforced by the type
system — the LLM reads schemas, the runtime enforces outcomes. Same OOP pattern you'd use
anywhere. The name "contract" signals that money and safety depend on the guarantee holding.

```python
# tools/contracts/base.py
from abc import ABC, abstractmethod

class ToolContract(ABC):
    name: str                              # "place_order"
    group: str                             # "broker", "risk", "scanner", "data"
    description: str                       # What the LLM sees

    def input_schema(self) -> dict:        # JSON Schema — what the LLM reads
        ...

    def execute(self, params: dict) -> ToolResult:
        """The LLM never calls this directly. The harness calls it.
           The gate validates the result before it reaches the broker."""
        ...
```

```python
# tools/contracts/result.py
class ToolResult:
    status: str    # PASS | FAIL | REJECTED | PARTIAL | TIMEOUT | PENDING_REVIEW
    data: any      # typed output matching the tool's output schema
    error: str     # only set on FAIL/REJECTED
    rule_id: str   # for REJECTED — which rule was violated
```

### 5.3 How the LLM calls tools (two paths, same contract)

```
                     ┌──────────────┐
                     │  REGISTRY     │  auto-discovers all ToolContract subclasses
                     └──────┬───────┘
                            │
              ┌─────────────┼─────────────┐
              ▼                           ▼
    ┌──────────────────┐        ┌──────────────────────┐
    │   FOR THE LLM     │        │   FOR THE HARNESS    │
    │                   │        │                      │
    │ input_schema()    │        │ execute()            │
    │ description       │        │ GovernanceGate       │
    │ → MCP tools list  │        │ → broker / DB / calc │
    │ → LLM decides      │        │ → ToolResult        │
    │   when + params   │        │ → audit logged       │
    └──────────────────┘        └──────────────────────┘
```

Same contract read by both: the LLM (to decide what to call) and the harness (to enforce
outcomes).

### 5.4 Target file layout

```
tools/
├── contracts/
│   ├── base.py              ← ToolContract ABC + ToolResult types
│   ├── schemas.py           ← typed input/output schemas per tool group
│   └── registry.py          ← auto-discovers all ToolContract subclasses
│
├── server.py                ← THIN (~50 lines): MCP transport only
│                               for tool in registry.discover():
│                                   mcp.tool()(wrap(tool))
│
├── scanner/
│   └── filters.py           ← class ScanCandidates(ToolContract)
├── risk/
│   ├── checks.py            ← class CheckPortfolioRisk(ToolContract)
│   └── governance.py        ← class EvaluateTrade(ToolContract)
├── broker/
│   └── alpaca.py            ← class PlaceOrder(ToolContract)
├── data/
│   └── source.py            ← class GetMarketData(ToolContract)
├── analysis/
│   └── regime.py            ← class GetMarketRegime(ToolContract)
├── persistence/
│   └── repository.py        ← class QueryTools(ToolContract)
└── notifications/
    └── broadcast.py         ← class NotifyTools(ToolContract)
```

Each file self-contained. Adding a new tool = new class implementing `ToolContract` in the
right submodule — registry finds it, MCP surfaces it, gate enforces it. Zero changes to
`server.py`.

### 5.5 Without vs. with contracts

| Without contracts | With contracts |
|---|---|
| LLM guesses params from docstring | LLM reads `input_schema()` — exact types |
| LLM parses return strings to check success | LLM matches `ToolResult.PASS` vs `ToolResult.REJECTED` |
| Nothing stops LLM calling wrong tool group | Registry + group scoping: research agent only sees scanner/data |
| Gate is optional, manual | Gate is part of `execute()` — cannot be skipped |
| Adding tool = edit server.py | Adding tool = new class in submodule |

---

## 6. Factor z-scoring — replacing binary gates

### 6.1 The problem with binary gates

Current scanner (`filters.py`) uses absolute thresholds: `RS > 2%`, `RSI3 < 10`. This
produces degenerate outputs (zero candidates from 400 names, documented Jun 2026).
The gate was tightened three times (30 → 15 → 10) without empirical validation because
the methodology has no feedback mechanism. The methodology loses peer-relative context —
NVDA up 3% vs SPY up 1% is a signal; NVDA up 3% vs SPY up 4% is not. `RS > 2%` sees both
as identical.

### 6.2 What z-scoring is

For each factor, compute the mean and standard deviation across all 400 stocks. Then
for each stock:

```
z = (stock_value - mean) / std_dev
```

Example — 63-day momentum across 400 stocks:

```
AAPL:  +12.4%  →  (+12.4 - (-0.4)) / 14.1  =  +0.91
NVDA:  +31.2%  →  (+31.2 - (-0.4)) / 14.1  =  +2.24
TSLA:  -18.7%  →  (-18.7 - (-0.4)) / 14.1  =  -1.30
```

z = 0 means exactly average. z = +1 means 1 standard deviation above average (~top 16%).
z = +2 means ~top 2.5%. The scores are unitless — you compare NVDA's +2.24 against
AAPL's +0.91 directly. Repeat for every factor, weight by regime, sum to composite.

```python
for factor in ["momentum_63d", "rsi_14", "atr_pct", "turnover", "beta"]:
    values = [stock[factor] for stock in universe]
    mean, std = np.mean(values), np.std(values)
    for stock in universe:
        stock[f"{factor}_z"] = (stock[factor] - mean) / std
```

### 6.3 Engine M/R are strategies, not engines

Engine M (momentum continuation) and Engine R (mean-reversion dip) are two specific
patterns inside ONE strategy family (trend-following). The name "Engine" implies the
system runs on them. It shouldn't.

What replaces them:
- **The pipeline** is the engine — factor computation → ranking → enrichment → LLM → gate
- **Strategies** are pluggable alpha models that classify candidates into families:
  M-continuation, R-pullback, breakout, volatility-compression, event-earnings,
  sector-rotation, options/vol-edge
- The LLM receives the factor profile and classifies which family the candidate fits
- Each strategy registers itself — adding a strategy = registering a new scorer
- Merge step combines scores with configurable weights; LLM does final conviction

---

## 7. The full pipeline design (LLM-as-brains architecture)

### 7.1 Phase 1 — Pre-compute (all Python, LLM is asleep)

```
┌─────────────────────────────────────────────────────────────┐
│                   QUANTITATIVE INPUTS                        │
├─────────────────────────────────────────────────────────────┤
│ factor_ranking.run(universe)    → top 20 by z-score composite│
│ regime.classify(SPY)            → trending_calm, vix=14.2   │
│ risk.snapshot(portfolio)        → mode=NORMAL, pos=3, PnL...│
│ rl_model.signal(tickers)        → {NVDA: long 0.82}         │
│ episodic.recall(engine, 5)      → last 5 trades, avg R=...  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                 UNSTRUCTURED INPUTS                          │
├─────────────────────────────────────────────────────────────┤
│ news.fetch(top_20)               → raw headlines + snippets │
│ social.fetch(top_20)             → X posts, Reddit threads  │
│ catalyst.extract(raw_news)       → structured catalyst objs │
│   can be: keyword+regex (cheap) or LLM-extract (expensive)  │
│                                                             │
│ Per-ticker sentiment:                                       │
│   social_score:       +0.72     (72% of posts bullish)      │
│   news_score:         +0.40     (headlines lean positive)    │
│   volume_ratio:        3.2     (mentions 3.2x normal)       │
│   hype_stage:         EARLY    (not yet saturated)           │
│   divergent:          false    (social ≠ price direction?)  │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 Phase 2 — Assemble TradingBrief (still Python)

```python
class TradingBrief:
    # Quantitative
    candidates: list[CandidateScore]       # factor profiles per ticker
    regime: RegimeSignal                   # trending_calm, vix, spy_vs_sma
    risk: RiskSnapshot                     # mode, positions, daily_pnl, limits
    episodic: list[TradeMemory]            # recent trades by engine/regime
    rl_signals: dict[str, RLSignal]        # RL model per ticker

    # Unstructured
    catalysts: dict[str, list[Catalyst]]   # per ticker, sourced
    sentiment: dict[str, SentimentSignal]  # social, news, volume, hype

    # Instructions
    instructions: str                      # "You are Research. Produce TradePlan."
```

### 7.3 Phase 3 — LLM reasons (one call, one output)

LLM receives `TradingBrief` → LLM outputs `TradePlan`.

```python
class TradePlan:
    symbol: str
    engine: str                            # strategy family
    reasoning: str                         # "MS upgrade + early social, but earnings Thurs..."
    entry_signal: str
    entry_params: EntryParams              # limit_price, order_type, zone
    size: PositionSize                     # quantity, pct_of_portfolio
    stop_loss: float
    exit_signal: str
    exit_params: ExitParams                # take_profit, trail_atr, time_stop_days
    conviction: int                        # 0-100
    r_ratio: float
    catalysts: list[str]                   # MUST be present in TradingBrief.catalysts
```

### 7.4 Phase 4 — Gate validates against the brief (Python, deterministic)

Every field in `TradePlan` is cross-checked against `TradingBrief`:

| TradePlan field | Gate checks | Violation |
|---|---|---|
| `symbol` | Must be in `brief.candidates` | REJECT |
| `engine` | Must be a registered strategy family | REJECT |
| `engine` | Must be eligible for current regime | REJECT |
| `entry_zone` | Must be within today's range ± ATR | REJECT |
| `stop_loss` | Must be 1.5–2.5× ATR below entry | REJECT |
| `r_ratio` | Must be ≥2:1 (trend) / ≥1.5:1 (reversion) | REJECT |
| `conviction` | Must be 0–100 | REJECT |
| `size.qty` | Must not exceed position cap | REDUCE or REJECT |
| `size.pct` | Must not exceed concentration limit | REDUCE or REJECT |
| `catalysts` | Every entry MUST exist in `brief.catalysts[symbol]` | REJECT |
| `daily_pnl` | Must not breach daily loss limit | REJECT + kill switch |

The LLM can propose whatever it wants. The gate doesn't trust a word. Every claim is
validated against the TradingBrief (assembled by code). If any field fails, the gate
returns `REJECTED` with the specific rule and reason. The LLM gets one retry with the
failure context. No trading happens until gate returns `APPROVED`.

### 7.5 Phase 5 — Execute (Python, LLM is done)

Gate returns `APPROVED` → `place_order` proceeds → broker executes.
Audit trail records: `(TradingBrief_hash, TradePlan_hash, GateVerdict, FillResult)`.

### 7.6 Why this pipeline, not LLM calling tools

| LLM calling tools (today) | Pipeline feeds LLM (target) |
|---|---|
| LLM calls 8–15 MCP tools per session | LLM receives 1 TradingBrief, outputs 1 TradePlan |
| LLM decides when to scan, check risk, etc. | Pipeline runs deterministically before LLM wakes |
| LLM is orchestrator + brain | LLM is ONLY brain |
| Risk checks happen if LLM remembers | Risk checks always run — gate is on the execution path |
| 2,878-line server.py monolith | ~50-line server.py + typed ToolContracts |
| SOP is markdown the LLM reads | SOP is code the gate enforces |

---

## 8. Target system design (concrete)

1. **Governance gate** — pure function inside `place_order`, reads `TradePlan` + account
   state, returns `Verdict{APPROVED|REDUCED|REJECTED|PENDING}`, fail-safe on error.
2. **Tool contracts** — every tool is a `ToolContract` subclass with typed input/output
   schemas. Registry discovers them. Server is thin transport.
3. **TradingBrief → TradePlan pipeline** — pre-compute everything, one LLM call, gate validates.
4. **Factor scanner** — 14-factor cross-sectional z-scoring, regime-weighted, IC-decay-tracked.
5. **Pluggable alpha models** — each strategy family a pluggable classifier. M and R are
   the first two, not the only two.
6. **Episodic memory recall** — structured digest handed to LLM before the scan.
7. **Evaluation rigor** — MR-1..7 compliance report, CPCV, PBO, deflated Sharpe, cost+impact
   model.
8. **Audit chain** — hash-chained decision rounds, role attribution.
9. **Single source of truth for limits** — gate reads from ONE config, killing the
   5-vs-10 drift.

---

## 9. Multi-phase plan

### Phase 0 — Safety foundation (gate + tool contracts)
- Build governance gate per approved design
- Define `ToolContract` ABC + `ToolResult` types
- Convert 2–3 tools to contract pattern (risk checks, place_order)
- Build auto-discovery registry
- Fix config-drift: one source of truth for all risk limits
- Exit: unit test per rule, integration test REJECT/REDUCE/APPROVED paths
- **Engine M/R and binary gates declared obsolete (2026-07-13) — Phase 2 replaces them**

### Phase 1 — Learning + honesty
- TradingBrief → TradePlan typed pipeline
- Episodic memory recall
- MR-1..7 compliance report
- CPCV + PBO gate on strategy changes
- Exit: strategy change can't ship without PBO gate; LLM receives episodic digest

### Phase 2 — Factor scanner + news/sentiment enrichment
- Implement 14-factor cross-sectional z-scoring (design: `design/factor-scanner-tdd.md`)
- Add news/sentiment pipeline (fetch + extract catalysts per ticker)
- Hybrid universe: core 400 + dynamic RVOL/most-actives screener
- Keep binary path as fallback, switchable by config
- Dry-run count check first: count what passes for multiple days
- Exit: non-degenerate candidate counts ≥2 weeks; A/B vs binary logged

### Phase 3 — Strategy expansion
- Pluggable alpha model registry
- Candidate families: pullback-to-MA, volatility-compression, breakout, event-earnings,
  sector-rotation, options/vol-edge
- Merge step with configurable weights, LLM final DD across all sources
- Exit: each strategy forward-validated on paper; heat/correlation caps enforced

### Phase 4 — Data + infra hardening
- `AlpacaSource` behind `MarketDataSource` seam
- PIT universe to kill survivorship
- Audit hash-chain + role attribution
- External kill-switch sentinel
- Exit: go-live checklist; gate + audit chain survive fault-injection drill

---

## 10. Sharpest adversarial findings (ranked)

1. **LLM owns the trade-execution decision.** Only kill switch enforced. Fix: Phase 0.
2. **Risk numbers have two masters.** 5 vs 10 max positions. Fix: Phase 0.
3. **Binary gates are obsolete.** Produced zero candidates. Fix: Phase 2 (owner-confirmed 2026-07-13).
4. **Strategy edges on tiny samples.** v1.x SOPs n=5–15. Fix: Phase 1 PBO gate.
5. **Backtest flatters us.** No impact model. New research: rankings FLIP with impact. Fix: Phase 1.
6. **Memory stores but doesn't recall.** Fix: Phase 1.
7. **Engine M/R are strategies, not engines.** The pipeline is the engine. Fix: Phase 2-3.
8. **Tools are flat functions with no enforcement.** server.py is a 2,878-line monolith. Fix: Phase 0 tool contracts.

---

## 11. Open questions for the owner

1. **Phase 0 sequencing:** gate alone, or gate + tool contracts in one slice?
2. **Risk source of truth:** config.yaml vs OPERATING_MANUAL.md parsed vs new `config/risk_limits.yaml`?
3. **Strategy priority in Phase 3:** which family first? Options/vol-edge move up?
4. **Go-live horizon:** real capital soon (→ Phase 4 moves up) or paper track first?
5. **News/sentiment depth:** keyword+regex extraction (cheap, always works) or LLM-powered extraction (richer, costs tokens)? Both? Tiered by candidate rank?

---

## Appendix A — Source catalog

**GitHub:** nautilus_trader (24.6k), TradingAgents (92k), ai-hedge-fund (61k), FinRL (15.7k), FinRobot (7.5k), freqtrade (52k), hummingbot (19k), vectorbt (8.3k), FinMem-LLM, agent-backtest-lab

**arXiv (2026):** 2605.12532 (AgenticAITA), 2605.16895 (Alpha Illusion), 2606.22385 (MetaPS), 2606.29771 (CLQT), 2606.31461 (CSTrader), 2605.06822 (SHARP), 2508.17565 (TradingGroup), 2603.22567 (TrustTrade), 2606.08450 (GIFT), 2602.00948 (FinEvo), 2510.14264 (AlphaQuanter), 2605.19337 (Agentic Trading Survey), 2603.29086 (market impact flips RL rankings), 2606.21228 (Fugu)

**X practitioner consensus:** LLM proposes → code gates → code executes; thin orchestrator + thick mediator; typed schemas on every tool call; external kill switch; CPCV/PBO; daily-close exits; size-for-the-gap; ¼-Kelly

**Books:** López de Prado *Advances in Financial ML*, Carver *Systematic Trading*, Bensdorp *Automated Stock Trading Systems*

## Appendix B — Code evidence (verified 2026-07-11, re-verified 2026-07-13)
- `tools/server.py:146-182` — `place_order`; only gate is kill switch (166-167); `plan_id` used only to save tx (173-175).
- `tools/server.py` — 2,878 lines, flat `@mcp.tool()` functions, no shared ToolContract ABC.
- No `tools/governance/` directory; no `GovernanceGate` reference.
- `tools/risk/checks.py:6-9` — `MAX_CONCENTRATION_PCT=20`, `MAX_OPEN_POSITIONS=5`, `DAILY_LOSS_LIMIT_PCT=3`.
- `tools/models.py:54-70` — `TradePlan` carries stop/target; conviction/engine/regime in untyped `risk_assessment: dict`.
- `tools/scanner/filters.py` — 4-layer binary filter, shared live/backtest path.
- 326 test functions in `tools/tests/`.
