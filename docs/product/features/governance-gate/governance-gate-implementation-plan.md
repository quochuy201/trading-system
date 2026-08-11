# Implementation Plan: Governance Gate

- **Slug:** `governance-gate` · **Status:** `plan` · **Design:** [`governance-gate-design.md`](governance-gate-design.md) · **Spec:** [`governance-gate-spec.md`](governance-gate-spec.md)
- **Executor:** Claude Code · **Date:** 2026-07-25 · Prior draft archived at `docs/_archive/governance-gate-superseded/`

## How to Use This Plan

Ordered, bite-sized tasks. TDD per `CLAUDE.md`. After each task run the named tests, check the box, note the commit. Do not batch unrelated tasks.

## ⚠️ Cross-feature dependency (F9)

**This feature is blocked-by `go-live-metrics` Task 1** (creates the `orders` table). Task 9 here stamps `orders.gate_verdict` / `gate_rule_id`, and Task 10b's single-choke-point refactor writes `orders` rows — neither works until that table exists.

**Build order:** `go-live-metrics` Task 1 → then this feature. The two also share `tools/execution.py` (created here, writes `orders` defined there), so they must not be built in parallel by different sessions.

## Guardrails (read before writing code)

- **The gate never fails open.** Any exception ⇒ `REJECTED` + operator notification.
- **Exits always pass** except kill switch / HALTED. Never block a risk-reducing order for R:R or size.
- **Ship in shadow mode.** Enforcement is a separate, deliberate flip after review.
- **Never weaken an existing control** — the gate only ever *adds* enforcement. Kill switch stays exactly where it is.
- **Automation must never write `risk_limits.*.yaml`** (human-owned, git-versioned).
- Every rule carries its `OPERATING_MANUAL` section — the manual is the oracle.
- Tools return JSON errors, never raise to the agent. All 331 existing tests stay green.

---

## Tasks

### Task 1 — D2 risk config + loader + fail-safe selection
- **Files:** `config/risk_limits.dev.yaml`, `config/risk_limits.live.yaml` (new), `tools/governance/limits.py` (new)
- **What:** both YAML files per design §5 (% of equity, complete sets, no inheritance). Loader: `TRADING_ENV` → dev|live, **unknown/unset ⇒ dev**, typed `RiskLimits` dataclass, `assert_broker_mode_matches(env)` so a live broker can never run dev limits.
- **Tests:** `tools/tests/test_governance_limits.py` (new) — dev/live load; unknown env ⇒ dev; missing env ⇒ dev; live broker + dev env ⇒ raises at startup; every documented key present and typed.
- **Acceptance:** limits load from exactly one file, selected by one switch, fail-safe to dev.
- **Status:** ☐ todo

### Task 2 — Drift detector
- **Files:** `tools/governance/limits.py`
- **What:** at startup compare risk keys in `config.yaml` against loaded `risk_limits.<env>.yaml`; **any mismatch fails loudly** with both values named. Migrate risk keys to be sourced from the risk file (config.yaml keeps broker/schedule/scanner).
- **Tests:** `tools/tests/test_governance_limits.py` — matching config passes; a seeded `max_open_positions` 5-vs-10 mismatch raises with a message naming both.
- **Acceptance:** the historical 5-vs-10 drift is now impossible to ship.
- **Status:** ☐ todo

### Task 3 — Verdict + proposal/state types
- **Files:** `tools/governance/verdict.py`, `tools/governance/types.py` (new)
- **What:** frozen `Verdict` (status, rule_id, reason, `manual_ref`, adjusted_quantity); `TradeProposal` (symbol, side, qty, entry, stop, target, conviction, plan_id); `AccountState` (equity, mode, open positions, day P&L, 5d/20d drawdown, kill-switch flag, trades today).
- **Tests:** `tools/tests/test_governance_gate.py` (new) — types immutable; `Verdict` requires a non-empty `rule_id`.
- **Acceptance:** the gate's whole input/output surface is typed and pure.
- **Status:** ☐ todo

### Task 4 — Tier 1 rules + exposure-based entry/exit classifier (F6)
- **Files:** `tools/governance/rules.py`, `tools/governance/gate.py` (new)
- **What:** `R_KILL_SWITCH` (all orders), `R_HALTED_MODE` (entries only — HALTED must still allow closing). **`is_entry(side, qty, symbol, positions)` classified by EXPOSURE CHANGE, never by side** (design §4): entry ⟺ `abs(current + delta) > abs(current)`. Flips ⇒ `R_AMBIGUOUS_FLIP` REJECTED with "split into two orders".
- **Tests:** `test_governance_gate.py` — kill switch blocks entry **and** exit; HALTED blocks entry, **allows exit**. Classifier truth table, all 7 rows of design §4, especially: **sell-on-flat ⇒ ENTRY** (short / options sell-to-open — the F6 bug), adding-to-short ⇒ entry, cover ⇒ exit, **flip ⇒ REJECTED not silently classified**.
- **Acceptance:** a sell-to-open is gated like any other entry; exits survive HALTED; nothing survives the kill switch.
- **Status:** ☐ todo

### Task 5 — Tier 2 portfolio rules
- **Files:** `tools/governance/rules.py`
- **What:** `R_DAILY_LOSS` (§4.3 — REJECT **and activate kill switch**, D-G2), `R_CIRCUIT_5D`, `R_CIRCUIT_20D` (§4.4), `R_MAX_POSITIONS` (§3.1/§4.1). Entries only.
- **Tests:** each rule blocked-case + passed-case; boundary values (exactly at the limit ⇒ still allowed, one tick past ⇒ blocked); daily-loss breach actually sets the kill switch; **all four bypass on exits**.
- **Acceptance:** portfolio limits enforced in code with correct boundary semantics.
- **Status:** ☐ todo

### Task 6 — Tier 3 entry rules
- **Files:** `tools/governance/rules.py`
- **What:** `R_RISK_PER_TRADE` (REDUCED clamp; REJECT if clamped < 1), `R_CONCENTRATION` (REDUCED clamp), `R_RR_MIN`, `R_STOP_PRESENT` (missing/wrong-side stop ⇒ REJECT), `R_DEFENSIVE_CONV` (**missing conviction ⇒ REJECT**, D-G3), `R_DEFENSIVE_SIZE` (REDUCED × multiplier).
- **Tests:** both directions each; **REDUCED rules are cumulative and the smallest qty wins**; clamped qty never exceeds proposed and never < 1; missing stop and missing conviction both fail *closed*.
- **Acceptance:** sizing/R:R/mode constraints enforced; reductions are correct and never grow an order.
- **Status:** ☐ todo

### Task 7 — Gate orchestration + fail-safe + `side_effects` (F3/F7)
- **Files:** `tools/governance/gate.py`
- **What:** `evaluate()` — Tier 1 → 2 → 3, first REJECT short-circuits, REDUCED cumulative. **The gate NEVER performs a side effect**: `R_DAILY_LOSS` returns `side_effects=("ACTIVATE_KILL_SWITCH:daily_loss_limit",)` — a *request* the caller executes (design §2). Wrap everything: any exception ⇒ `R_GATE_ERROR` REJECTED + `notify_operator`. Compute `inputs_hash` for determinism/replay.
- **Tests:** ordering (Tier-1 violation reported even when Tier-3 also fails); **injected raising rule ⇒ REJECTED + notified, never approved**; determinism (same inputs ⇒ same verdict + hash); **`gate.evaluate()` touches NO global state — assert kill switch unchanged after a `R_DAILY_LOSS` verdict**; verdict is replayable without re-triggering effects.
- **Acceptance:** the gate is pure, deterministic, cannot fail open, and **declares** effects rather than performing them.
- **Status:** ☐ todo

### Task 8 — Property-based invariants + golden cases
- **Files:** `tools/tests/test_governance_properties.py`, `tools/tests/fixtures/gate_golden_cases.json` (new)
- **What:** generated proposals asserting always-true invariants — no APPROVED order exceeds `max_open_positions`; approved risk ≤ `E × max_risk_pct`; `1 ≤ REDUCED qty ≤ proposed`; exits never blocked except Tier 1. Plus hand-verified golden cases.
- **Tests:** the above.
- **Acceptance:** invariants hold across generated inputs, not just hand-picked ones.
- **Status:** ☐ todo

### Task 9 — `governance_decisions` table + telemetry
- **Files:** `tools/persistence/db.py`, `tools/persistence/repository.py`
- **What:** table per design §7; persist every verdict incl. `gate_mode`, `env`, `inputs_hash`. Also stamp `orders.gate_verdict` / `gate_rule_id` (joins gate outcomes to trade outcomes).
- **Tests:** `tools/tests/test_governance_gate.py` — verdicts persisted for APPROVED and REJECTED alike (not only blocks); per-`rule_id` counts queryable.
- **Acceptance:** every decision is auditable and replayable.
- **Status:** ☐ todo

### Task 10 — Wire into `place_order`, SHADOW mode default
- **Files:** `tools/server.py` (`place_order`, ~line 146-182)
- **What:** call the gate immediately after the kill-switch check. `GOVERNANCE_GATE_MODE` (default **shadow**): shadow ⇒ log verdict **and log side-effect *intent* only**, place the order regardless; enforce ⇒ honour the verdict (REDUCED adjusts qty; REJECTED/PENDING return without placing) **and execute `verdict.side_effects` here — this is the ONE place in the codebase that performs them** (F3).
- **Tests:** `tools/tests/test_governance_integration.py` (new) — **shadow: a would-be-rejected order still places, verdict logged, and the kill switch is NOT armed** (F7); enforce: order not placed **and an `R_DAILY_LOSS` verdict DOES arm the kill switch** (guards the F3 residual risk — a declared-but-never-performed effect is a dead control); REDUCED places at clamped qty; `place_order` behaviour otherwise unchanged in shadow.
- **Acceptance:** shadow mode observes **with zero side effects**; enforce mode actually enacts §4.3.
- **Status:** ☐ todo

### Task 10b — ⭐ Consolidate to ONE execution choke point (architectural invariant)
- **Files:** `tools/execution.py` (new), `tools/server.py` (`place_order` :146, `place_multileg_order` :1842, `activate_kill_switch` :1071)
- **What:** introduce `OrderRequest` (legs tuple — 1 leg = equity, N = spread; `intent` = OPEN|CLOSE|LIQUIDATE) and **`execute_order(request)` as the single function that reaches the broker**. Fixed sequence: validate → kill switch → **gate** → broker adapter → record order + ledger. Rewrite all three existing paths as **thin wrappers** that build an `OrderRequest` and call it — **MCP tool names and signatures unchanged** (agent-facing surface stays ergonomic). Vendor branching (single vs multileg) moves **into the broker adapter**, below the choke point. `intent=LIQUIDATE` is the *only* thing permitted past `R_KILL_SWITCH`, and is heavily logged.
- **Tests:** `test_governance_integration.py` + `test_execution.py` (new) —
  **(a) grep-style invariant test: `broker.place_order` / `broker.place_multileg_order` are called from EXACTLY ONE module (`execution.py`)** — this is the test that stops a fourth door appearing;
  (b) an equity order and a spread order take the identical path and both hit the gate;
  (c) enforce: multileg blocked by HALTED / daily-loss / max-positions; Tier 3 records `UNAVAILABLE_OPTIONS`;
  (d) shadow: logged, placed, **kill switch not armed**;
  (e) **`intent=LIQUIDATE` succeeds while the kill switch is ACTIVE** (guards the self-blocking trap), and every other intent is refused;
  (f) existing `place_order` / `place_multileg_order` behaviour unchanged for callers.
- **Acceptance:** **exactly one function reaches the broker**, proven by test — not "every door is guarded", but "there is only one door".
- **Status:** ☐ todo

### Task 11 — Zero-approvals alert
- **Files:** `tools/audit/` (alerting), EOD path
- **What:** if N consecutive sessions produce zero APPROVED entries while entries were attempted ⇒ notify operator with the rejection-reason distribution.
- **Tests:** seeded all-rejected history triggers the alert; a healthy mix does not.
- **Acceptance:** a drought surfaces in days, not 34 sessions.
- **Status:** ☐ todo

### Task 12 — Shadow review + enforcement flip (GATED — needs owner sign-off)
- **Files:** `PROJECT_STATUS.md`, `docs/product/ROADMAP.md`
- **What:** after **≥20 evaluated entry attempts AND ≥1 week** (D-G1), report what *would* have been blocked and why; owner reviews false positives; then flip to `enforce`. Record evidence.
- **Tests:** full suite green.
- **Acceptance:** enforcement enabled **only** after a reviewed shadow period. ⚠️ **Do not flip without sign-off.**
- **Status:** ☐ todo

---

## Definition of Done (whole feature)

- [ ] Tasks 1–11 done (12 gated on shadow review + owner sign-off)
- [ ] 12 rules implemented, **each with a block-case AND a pass-case test**
- [ ] Every rule carries a non-empty `manual_ref`
- [ ] Property invariants + golden cases green
- [ ] Gate provably cannot fail open (injected-exception test)
- [ ] Exits bypass everything except kill switch / HALTED
- [ ] One config source; drift detector active; unknown env ⇒ dev; live+dev impossible
- [ ] Shipped in **shadow** with verdicts logged and zero trading impact
- [ ] Full suite green (331 + new)
- [ ] `PROJECT_STATUS.md` + ROADMAP updated

## Decisions carried from spec

- **D-G1** shadow period → ≥20 evaluated entries **and** ≥1 week
- **D-G2** `R_DAILY_LOSS` also activates the kill switch (enacts §4.3)
- **D-G3** missing conviction in DEFENSIVE ⇒ REJECT (fail closed)
