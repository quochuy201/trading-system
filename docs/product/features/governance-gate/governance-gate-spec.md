# Spec: Deterministic Governance Gate

- **Slug:** `governance-gate`
- **Status:** `spec` · prior drafts archived at `docs/_archive/governance-gate-superseded/`
- **Priority:** `P0` — the highest-impact safety change in the roadmap
- **Owner sign-off:** ☑ approved 2026-07-25 (BUILD-PLAN §2, **D1** + **D2**)
- **Layer(s):** 5 Risk (consumes 4 Action)
- **Author:** Claude Code · **Date:** 2026-07-25

> **Note:** the archived 2026-07 drafts predate the ratified decisions, and their 17-rule set was written **without discussion** (agenda: CONTAMINATED). This spec encodes only the **D1-ratified subset** and is the authority; the archived rules are a proposal for the deferred phase, not spec.

## Problem

**The constitution is enforced by markdown persuasion, not code.** Verified in `tools/server.py:166-172` — the kill switch is the *only* hard gate on the path to the broker:

```python
if _kill_switch_state["active"]:
    return json.dumps({"error": "Kill switch is active", ...})   # server.py:166-167
broker = get_broker()
tx = with_retry(broker.place_order, _retry_config)(...)          # server.py:169 → reaches the broker
```

Everything else in the 363-line `OPERATING_MANUAL.md` is advisory: `check_portfolio_risk()` and `check_daily_limits()` (`tools/risk/checks.py:12`, `:72`) are **separate MCP tools that `place_order` never calls**. Nothing in code stops the LLM from calling `place_order()` directly and bypassing position caps, R:R minimums, the daily-loss limit, DEFENSIVE-mode constraints, and the §4.4 circuit breakers.

**Why it matters:** a single hallucinated input, mis-sized order, or "forgotten" check puts on a trade that violates our own rules — and in markets a bad action realizes losses before it can be corrected. This is the one place where a bad decision reaches money.

**Second, related problem (D2):** risk limits live in **two places already** — `config.yaml` (`risk:` and `income:` blocks) and `OPERATING_MANUAL.md` prose — and have **already drifted once** (`max_open_positions` 5 vs 10). A gate that reads a drifting number enforces the wrong rule confidently.

## Goal

Move risk enforcement from advisory markdown into a **deterministic, unbypassable Python gate inside `place_order`, before the broker call**, reading limits from **one environment-selected config**. The gate returns `APPROVED | REDUCED | REJECTED | PENDING`; only APPROVED/REDUCED reach the broker; every verdict is logged with its `rule_id`.

## User / System Value

- **Capital preservation (Mission #1):** the LLM *physically cannot* execute a trade violating the constitution, regardless of prompt drift or reasoning error.
- **Trust to automate:** more autonomy is safe once the floor is enforced by code rather than hope.
- **Auditability:** every allow/block becomes a replayable record — the foundation for per-rule telemetry (BUILD-PLAN §4.5) and the future hash-chain.

## Scope

**In scope — D1 ratified subset (Tiers 1–3, math + portfolio + mode):**
- New `tools/governance/` module: pure-function gate + verdict dataclass.
- Wired into `place_order` at the kill-switch choke point.
- **12 rules**, each traced to an `OPERATING_MANUAL` section (see design §3).
- **D2 config:** `config/risk_limits.dev.yaml` + `.live.yaml` (values as **% of equity**), selected by `TRADING_ENV` **bound to broker mode**, fail-safe to `dev`; plus a **drift detector** that fails loudly if `config.yaml` and the risk config disagree.
- `governance_decisions` audit table (verdict, rule_id, hashes) + per-rule telemetry.
- **Shadow (log-only) mode** with `GOVERNANCE_GATE_MODE = shadow | enforce`.
- Unit test per rule **in both directions**, golden cases, property invariants.

**Out of scope / non-goals**
- **Tier 4 source-verification** (`R_CATALYST_SOURCE`, `R_NEWS_FRESHNESS`, `R_EARNINGS_WINDOW`) — needs the typed `TradingBrief` from `pipeline-contracts`. **Deferred by D1**, not cancelled.
- Rules needing brief-supplied ATR/universe (`R_STOP_RANGE`, `R_ENTRY_ZONE`, `R_SYMBOL_IN_UNIVERSE`, `R_ENGINE_ELIGIBILITY`) — same reason.
- NOT rewriting `OPERATING_MANUAL.md` — it stays the oracle; the gate encodes it.
- NOT deleting `check_portfolio_risk`/`check_daily_limits` — they remain advisory pre-checks for planning.
- NOT blocking exits — risk-reducing orders always pass (except kill switch / HALTED).
- NOT position-sizing math redesign — the gate enforces caps, it doesn't compute optimal size.
- NOT a standalone always-on sentinel daemon.

## Acceptance Criteria

1. `place_order` cannot reach the broker without a gate verdict; verdict is `APPROVED`/`REDUCED` or the order is not placed.
2. All 12 rules implemented as **pure functions**, each with a unit test that **blocks** a violating case **and passes** a compliant one.
3. Each rule declares the `OPERATING_MANUAL` section it encodes; a test asserts every rule has a non-empty manual reference.
4. Gate **never fails open**: any internal exception ⇒ `REJECTED` + operator notification.
5. **Exits bypass** every rule except kill switch and HALTED — proven by test. **Entry/exit is classified by exposure change, never by order side** — a sell-to-open (short, or an options credit spread) is an ENTRY and is fully gated (F6).
5b. **No ungated route to the broker.** Both `place_order` and `place_multileg_order` call the gate; only `activate_kill_switch`'s emergency close-all is exempt. Proven by a test that enumerates broker call sites.
6. Limits are read from exactly one source (`risk_limits.<env>.yaml`); the drift detector fails startup if `config.yaml` disagrees.
7. `TRADING_ENV` unset/unrecognized ⇒ **dev** config loaded (fail-safe), and it is bound to broker mode (live broker + dev limits is impossible).
8. Every verdict is persisted to `governance_decisions` with `rule_id`, inputs hash, and mode.
9. **Shadow mode** computes and logs verdicts while blocking nothing; enforcement is a config flip.
10. Determinism: identical inputs ⇒ identical verdict (replay test).
11. All 331 existing tests stay green.

## Risks & Safety Impact

- **This feature IS the safety mechanism** — its own failure modes matter most.
- **False negative** (approves a violating trade) ⇒ money at risk. Mitigated by per-rule two-direction tests + property invariants.
- **False positive** (blocks valid trades) ⇒ a silent drought — our 34-session precedent. Mitigated by **mandatory shadow period** + zero-approvals alerting before enforcement.
- **Gate error blocking all trading:** acceptable and intended — fail-safe is REJECT, with an operator alert so it's noticed immediately.
- **Wrong limit enforced confidently** (the oracle problem): each rule cites its manual section; the drift detector prevents config divergence.
- Kill switch, mode state machine, and circuit breakers are **strengthened**, never weakened: the gate only ever *adds* enforcement.

## Open Decisions

- **D-G1: Shadow duration before enforcing** — fixed 2 weeks vs N observed orders. *(Recommend: **≥20 evaluated entry attempts AND ≥1 week**, whichever is longer — a time-only rule proves nothing in a drought.)*
- **D-G2: `R_DAILY_LOSS` auto-activates the kill switch?** *(Recommend: **yes** — `OPERATING_MANUAL` §4.3 says HALTED + activate with reason `daily_loss_limit`. The gate should enact the manual, not just refuse.)*
- **D-G3: Where does `conviction`/score come from for `R_DEFENSIVE_CONV`?** *(Recommend: an explicit `conviction` param on the trade plan; if absent in DEFENSIVE mode ⇒ **REJECTED** with `missing_conviction` — fail closed, never assume A+.)*

## References

- `OPERATING_MANUAL.md` §1 (modes), §3.1 (inputs), §4.1–4.4 (the staircase)
- `docs/product/BUILD-PLAN.md` §2 (D1, D2), §4.5 (verification strategy)
- Code: `tools/server.py:146-182`, `tools/risk/checks.py:12,72`, `config.yaml` (`risk:`, `income:`, `broker.mode`)
- Prior art (proposal only, unratified): `docs/_archive/governance-gate-superseded/`
- Vault: `[[2026-07-25-Direction-Validation-Research]]` (deterministic guardrails are the field's convergent answer)
