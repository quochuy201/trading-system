# Design: Deterministic Governance Gate

- **Slug:** `governance-gate` · **Status:** `design` · **Spec:** [`governance-gate-spec.md`](governance-gate-spec.md)
- **Author:** Claude Code · **Date:** 2026-07-25
- **Prior drafts** (2026-07-07/09/13) archived at `docs/_archive/governance-gate-superseded/` — they contain **unratified, agent-fabricated** rule detail (agenda: CONTAMINATED). Kept for provenance only; **git is the version history**, so this file is the single living design.

---

## 1. Where it sits

```
LLM  ──►  place_order()  ──►  [ KILL SWITCH ]  ──►  [ GOVERNANCE GATE ]  ──►  broker
                                  (exists)              (this feature)
                                                             │
                                                    APPROVED → place
                                                    REDUCED  → place at clamped qty
                                                    REJECTED → return reason to LLM
                                                    PENDING  → notify operator, don't place
```

The gate is a **pure function** in `tools/governance/gate.py`, called inside `place_order` (`server.py:146-182`) at the same choke point as the kill switch. It performs **no** network/broker/DB I/O and consults **no** markdown at runtime — it receives everything it needs.

```python
def evaluate(proposal: TradeProposal, state: AccountState, limits: RiskLimits) -> Verdict
```

The LLM never learns the gate exists; it just receives a rejection with a reason and adapts.

---

## 2. The verdict

```python
@dataclass(frozen=True)
class Verdict:
    status: str            # APPROVED | REDUCED | REJECTED | PENDING | UNAVAILABLE
    rule_id: str           # e.g. "R_MAX_POSITIONS"; "R_OK" when nothing fired
    reason: str            # human-readable, includes the computed values
    manual_ref: str        # e.g. "OPERATING_MANUAL §4.1"  ← the oracle link
    adjusted_quantity: int | None = None      # set only for REDUCED
    side_effects: tuple[str, ...] = ()        # REQUESTED actions — the gate never performs them
```

**Evaluation order:** Tier 1 → 2 → 3. **First blocking rule wins** (short-circuit on REJECTED). REDUCED rules are *cumulative* — each clamps quantity further, and the smallest survives.

### ⚠️ `side_effects` — the gate decides, the caller acts (review finding F3)

`OPERATING_MANUAL` §4.3 requires that a daily-loss breach **activate the kill switch**. But activating it writes global state — a side effect that would break the gate's purity, and with it three things purity buys us:

| Purity buys | A side effect inside the gate would cost |
|---|---|
| Cheap testing (no broker/DB needed) | Every test must mock + reset global kill-switch state |
| Replay/audit via `inputs_hash` | **Replaying history would re-trigger a live kill switch** |
| Safe shadow mode | **Shadow mode could halt real trading** — the "blocks nothing" mode trips the switch (this is finding F7) |

**Resolution — functional core, imperative shell.** The gate *declares* what should happen; the caller performs it:

```python
Verdict(status="REJECTED", rule_id="R_DAILY_LOSS",
        reason="day P&L -3.2% ≤ -3.0% limit",
        manual_ref="OPERATING_MANUAL §4.3",
        side_effects=("ACTIVATE_KILL_SWITCH:daily_loss_limit",))   # a REQUEST, not an action
```

```python
verdict = gate.evaluate(proposal, state, limits)   # pure — computes only
if gate_mode == "enforce":
    for effect in verdict.side_effects:
        perform(effect)             # the shell acts
else:                               # shadow
    log_would_have(effect)          # records intent, changes nothing
```

§4.3 is still enacted in enforce mode; the gate stays pure, testable and replayable; and **shadow mode becomes genuinely side-effect-free.**

**Residual risk (named deliberately):** if the caller forgets to perform an effect, the kill switch silently never arms — the F4 "dead control" shape again. Mitigations: **exactly one** place in the codebase performs side effects, and a test asserts that an enforce-mode `R_DAILY_LOSS` verdict *actually results in an armed kill switch*.

*Alternative considered and rejected:* let a separate monitor watch daily P&L and arm the switch, keeping the gate a pure blocker. Cleaner boundary, but a 5-minute monitor cadence leaves a window for orders to slip through; having the gate request the effect closes it immediately.

---

## 3. The 12 rules (D1-ratified scope)

Every rule cites the manual section it encodes. **The manual is the oracle** — tests prove the implementation matches the rule, review proves the rule is right.

### Tier 1 — Hard stops (checked on ALL orders, including exits)

| # | `rule_id` | Condition | Manual | Verdict |
|---|---|---|---|---|
| 1 | `R_KILL_SWITCH` | kill switch active | §9 | REJECTED |
| 2 | `R_HALTED_MODE` | `mode == HALTED` **and** order is an entry | §1 | REJECTED |

> HALTED requires *closing* positions — so exits must still pass. Only the kill switch blocks everything.

### Tier 2 — Portfolio-level (entries only; exits bypass)

| # | `rule_id` | Condition | Manual | Verdict |
|---|---|---|---|---|
| 3 | `R_DAILY_LOSS` | realized day P&L ≤ −`daily.loss_limit_pct` | §4.3 | REJECTED **+ activate kill switch** (`daily_loss_limit`) — D-G2 |
| 4 | `R_CIRCUIT_5D` | drawdown from peak ≥ `circuit_breakers.drawdown_5d_pct` over 5 trading days | §4.4 | REJECTED (see §3a) |
| 5 | `R_CIRCUIT_20D` | drawdown from peak ≥ `drawdown_20d_pct` over rolling 20 days | §4.4 | REJECTED (see §3a) |
| 6 | `R_MAX_POSITIONS` | open positions ≥ `portfolio.max_open_positions` | §3.1, §4.1 | REJECTED |

### Tier 3 — Entry-level (entries only; exits bypass)

| # | `rule_id` | Condition | Manual | Verdict |
|---|---|---|---|---|
| 7 | `R_RISK_PER_TRADE` | `qty × (entry − stop)` > `E × per_trade.max_risk_pct` | §3.2, §4.1 | **REDUCED** (clamp to max qty); REJECTED if clamped qty < 1 |
| 8 | `R_CONCENTRATION` | position value > `E × portfolio.max_concentration_pct` | §4.1 | **REDUCED** (clamp) |
| 9 | `R_RR_MIN` | `(target − entry) / (entry − stop)` < `per_trade.min_rr` | §4.1 | REJECTED |
| 10 | `R_STOP_PRESENT` | stop missing, or on the wrong side of entry | §4.1 | REJECTED |
| 11 | `R_DEFENSIVE_CONV` | `mode == DEFENSIVE` and `conviction < defensive.min_conviction` (**missing ⇒ REJECTED**, D-G3) | §1 | REJECTED |
| 12 | `R_DEFENSIVE_SIZE` | `mode == DEFENSIVE` | §1 | **REDUCED** (× `defensive.size_multiplier`) |

**`R_STOP_PRESENT` (10) is new but non-negotiable:** without a stop there is no `R`, so the trade is unmeasurable *and* unsized. It is the enforcement counterpart of `go-live-metrics`' "never estimate a stop."

### 3a. Equity history — where the circuit breakers get their data (⚠️ review finding F4)

**The trap:** rules 4 and 5 need *drawdown from peak equity* over 5/20 days. `portfolio_snapshots` has **0 rows** — nothing writes it. A naive implementation (`no history ⇒ drawdown 0 ⇒ pass`) yields a **dead safety control that looks alive**: it sits in the rule list, passes its tests, logs `R_OK` on every order, and can never fire. Worse than no breaker, because it manufactures false confidence.

**The resolution — the broker already has it.** Alpaca serves `GET /v2/account/portfolio/history` (equity time series, `timeframe=1D`). We do **not** need to have been recording equity; there is **no warmup period**; the breakers can compute today. This follows D3: **the execution broker is authoritative for account state.**

- **New adapter method:** `BrokerAdapter.get_portfolio_history(period, timeframe) -> {timestamps[], equity[]}` — Alpaca via the endpoint above; `simulation.py` from the simulated equity curve (so backtest exercises the same rules).
- **Gate purity preserved:** the *caller* fetches history, computes `drawdown_5d_pct` / `drawdown_20d_pct`, and passes them in `AccountState`. The gate performs no I/O.
- **Caching:** multi-day drawdown moves slowly — a short cache (≈5 min) keeps the order path fast without meaningfully staling the measure.
- **Local `portfolio_snapshots` is still written daily** (in `go-live-metrics`) — but for **durability, backtest, and cross-checking the broker**, *not* as the gate's source of truth. Broker = truth; snapshot = durable copy.

**Third verdict state — `UNAVAILABLE`.** If history can't be fetched (API failure) or is genuinely insufficient, the rule returns **`UNAVAILABLE`**, never `pass`:

- **Paper:** `UNAVAILABLE` does not block trading, but is logged and shown as **INACTIVE** in the scorecard + per-rule telemetry — an unarmed control must be visible.
- **Go-live (D5):** **"all safety rules armed" is a go-live criterion.** You may reasonably paper trade without a 20-day breaker; you may not risk real money without one.

This generalizes: **any rule that cannot be computed reports `UNAVAILABLE` and is surfaced.** Silence is the failure mode we're designing out.

### Explicitly DEFERRED (not built now — needs `pipeline-contracts`)

`R_CATALYST_SOURCE`, `R_NEWS_FRESHNESS`, `R_EARNINGS_WINDOW`, `R_SYMBOL_IN_UNIVERSE`, `R_ENTRY_ZONE`, `R_STOP_RANGE`, `R_ENGINE_ELIGIBILITY` — all require the typed `TradingBrief`. Deferred by **D1**; revisit when queue #5 lands. *Their thresholds in the archived drafts remain unratified.*

### What the gate does NOT judge

Catalyst quality, sentiment interpretation, pattern classification, whether conviction 85 is "correct". **It verifies facts and arithmetic, never opinions.** If the gate could judge quality, we wouldn't need the LLM.

---

## 4. Entry vs exit — classify by EXPOSURE, never by side (⚠️ review finding F6)

**The bug:** the archived draft classified every `sell` as an exit. But **a sell on a flat position opens a short — that is an entry.** And this is not hypothetical: **options credit spreads are sell-to-open**, so the entire options track would have been classified as "exits" and skipped every Tier 2–3 rule.

```python
def is_entry(side, qty, symbol, positions) -> bool:
    """Entry = exposure INCREASES. Never infer from side alone."""
    current = signed_position(symbol, positions)      # + long, − short, 0 flat
    delta   = qty if side == "buy" else -qty
    return abs(current + delta) > abs(current)
```

| Current | Order | New | Classification |
|---|---|---|---|
| flat 0 | buy 100 | +100 | **entry** (long open) |
| flat 0 | **sell 100** | −100 | **ENTRY** (short / sell-to-open) ← the bug |
| long 100 | buy 50 | +150 | **entry** (scale-in) |
| long 100 | sell 50 | +50 | exit (partial close) |
| long 100 | sell 100 | 0 | exit (full close) |
| short −100 | sell 50 | −150 | **entry** (adding to short) |
| short −100 | buy 50 | −50 | exit (cover) |

**Flips are REJECTED, not classified.** `long 100 + sell 300` both closes 100 long *and* opens 200 short — it is simultaneously an exit and an entry, so no single verdict is correct. The gate returns `R_AMBIGUOUS_FLIP` with instructions to split it into two orders (close, then open). This removes an entire class of ambiguity rather than guessing, and mirrors how the round-trip builder splits flips.

Exits bypass Tiers 2–3. Blocking an exit for poor R:R is nonsensical — you want out regardless.

## 4a. ⭐ ONE execution choke point (architectural invariant)

**Today there are three routes to the broker** (verified in `server.py`): `place_order` (:169), `place_multileg_order` (:1895), and `activate_kill_switch`'s close-all (:1071). Guarding each one individually is fragile — you can forget a door, and a fourth can appear later.

> **INVARIANT: exactly ONE function reaches the broker.** Order kinds differ by *parameters*, not by *function*. Helpers build the request; one function executes it.

```
place_equity_order(...)  ─┐
place_spread_order(...)  ─┤  helpers / thin MCP tools — agent-facing, may be many
close_position(...)      ─┤  (each just builds a typed OrderRequest)
liquidate_all(...)       ─┘
                             ↓
                    execute_order(request: OrderRequest)      ← THE ONLY broker path
                             ↓
              validate → kill switch → GATE → broker adapter → record order + ledger
```

**`OrderRequest` unifies single- and multi-leg** — always a list of legs; an equity order is simply a **1-leg** order. No branching at the choke point.

```python
@dataclass(frozen=True)
class OrderRequest:
    legs: tuple[Leg, ...]          # 1 leg = equity; N legs = spread
    intent: str                    # OPEN | CLOSE | LIQUIDATE
    plan_id: str
    intended_price: float | None
    ...
```

**Vendor differences stay *below* the choke point.** The broker adapter still exposes `place_order` / `place_multileg_order` because Alpaca's API differs — the adapter picks based on leg count. That's exactly the adapter's job (same principle as D3): absorb vendor shape, present one interface upward.

**The agent-facing surface is unchanged.** MCP tools keep their names and ergonomic signatures (a single mega-tool with a dozen optional params would be worse for the LLM). They become **thin wrappers** that build an `OrderRequest` and call the one function. *Many tools, one execution path.*

### ⚠️ The trap this surfaces: the kill switch would block its own liquidation

`activate_kill_switch` arms the switch, **then** closes all positions. If liquidation now flows through the single choke point, `R_KILL_SWITCH` — which blocks *all* orders — would block the very liquidation it just triggered. Today this is invisibly avoided by calling the broker directly.

**Resolution — declare intent, don't bypass the path:** `intent = LIQUIDATE` is the *only* thing that passes `R_KILL_SWITCH`, and it is heavily logged. This is strictly better than today, where the exemption exists by *being a different code path* (invisible, unauditable) rather than by *declaring itself* (explicit, tested, logged).

**Multileg gate scope (proportionate):** Tier 1 + Tier 2 are instrument-agnostic and apply immediately. Tier 3 needs options-aware definitions (R:R on a spread ≠ R:R on a stock; "risk" is max-loss-of-spread) — deferred to the options phase, recorded as `gate_tier3 = 'UNAVAILABLE_OPTIONS'`, **never a silent pass** (§3a rule).

---

## 5. D2 — risk config (ships inside this feature)

### Files

`config/risk_limits.dev.yaml` and `config/risk_limits.live.yaml` — complete, independent sets (no inheritance/overlay to reason about). Values as **% of equity** ⇒ account-size-invariant, so paper $100k and live $10k need no re-tuning.

```yaml
version: 1
env: dev
per_trade:
  max_risk_pct: 1.0            # OPERATING_MANUAL §3.1 R_pct
  min_rr: 2.0                  # §4.1
portfolio:
  max_open_positions: 10       # §3.1 N_max (human-ratified 5→10, 2026-06-11)
  max_concentration_pct: 20.0  # §4.1
daily:
  loss_limit_pct: 3.0          # §4.3 DLL_pct
circuit_breakers:
  drawdown_5d_pct: 6.0         # §4.4
  drawdown_20d_pct: 10.0       # §4.4
defensive:
  size_multiplier: 0.5         # §1
  min_conviction: 80           # §1
```

### Selection — one switch, bound to the broker

```python
env = os.getenv("TRADING_ENV", "dev").lower()
if env not in ("dev", "live"):
    env = "dev"                      # fail-safe: unknown ⇒ dev
assert_broker_mode_matches(env)      # live broker + dev limits ⇒ startup FAILURE
```

`TRADING_ENV` drives **broker mode + risk limits + data source** together (D3). Live money can never run on dev limits.

### Drift detector (the bug that already bit us)

At startup, compare every risk key in `config.yaml` against the loaded `risk_limits.<env>.yaml`. **Any disagreement fails startup loudly.** `max_open_positions` has already drifted 5 vs 10 once; this makes a repeat impossible. Migration path: risk keys move to `risk_limits.*.yaml` (the source of truth); `config.yaml` keeps broker/schedule/scanner.

### Ownership (this is how "safety only tightens" is enforced)

**Automation writes `tuning_config.json` only. Nothing automated may write `risk_limits.*.yaml`** — human-owned, git-versioned (git *is* the version history; no custom versioning). Enforced by ownership, not a rule engine.

---

## 6. Fail-safe

```python
try:
    verdict = gate.evaluate(proposal, state, limits)
except Exception as e:
    verdict = Verdict("REJECTED", "R_GATE_ERROR", f"Gate internal error: {e}", "fail-safe")
    notify_operator(verdict)
```

**The gate never fails open.** This inverts today's behaviour, where every rule but the kill switch fails open (the LLM simply doesn't call the advisory tool).

---

## 7. Audit + telemetry

```sql
CREATE TABLE IF NOT EXISTS governance_decisions (
    decision_id TEXT PRIMARY KEY,
    order_id    TEXT,  plan_id TEXT,  symbol TEXT,  side TEXT,
    proposed_qty INTEGER,  adjusted_qty INTEGER,
    status      TEXT NOT NULL,        -- APPROVED|REDUCED|REJECTED|PENDING
    rule_id     TEXT NOT NULL,        -- R_OK when nothing fired
    reason      TEXT,  manual_ref TEXT,
    account_mode TEXT,                -- NORMAL|DEFENSIVE|HALTED
    gate_mode   TEXT NOT NULL,        -- shadow | enforce
    inputs_hash TEXT,                 -- determinism/replay
    env         TEXT,  created_at TEXT
);
```

Also written to `orders.gate_verdict` / `orders.gate_rule_id` (from `go-live-metrics`), so gate outcomes join to actual trade outcomes.

**Monitoring (BUILD-PLAN §4.5):** per-`rule_id` verdict distribution; a rule firing ~never (dead) or ~always (false-positive machine) is a defect signal; **zero approvals over N sessions ⇒ ALERT** — exactly what would have surfaced the 34-session drought on day 3.

---

## 8. Rollout — shadow first (non-negotiable)

`GOVERNANCE_GATE_MODE = shadow | enforce` (default **shadow**).

1. **Shadow:** compute + log every verdict, **block nothing**. Orders flow as today.
2. **Review:** after **≥20 evaluated entry attempts AND ≥1 week** (D-G1), inspect what *would* have been rejected and why. This measures the false-positive rate **before it can cost an opportunity**.
3. **Enforce:** flip the flag. Rollback is flipping it back.

Ship to paper only; no real-money path exists (D5).

---

## 9. Verification (BUILD-PLAN §4.5)

**Deterministic — unit tested:**
- **One test per rule, BOTH directions** — a violating case blocked *and* a compliant case passed. ⚠️ A gate that rejects everything passes all "should block" tests; the pass-side test is what catches it.
- **Golden cases:** hand-verified proposals + expected verdicts (regression protection).
- **Property invariants:** no APPROVED order exceeds `max_open_positions`; `REDUCED` qty ≤ proposed and ≥ 1; an exit is never blocked except by kill switch; risk of any approved order ≤ `E × max_risk_pct`.
- **Fail-safe:** an exception inside any rule ⇒ REJECTED + notify (inject a raising rule).
- **Determinism:** same inputs ⇒ same verdict and same `inputs_hash`.
- **Config:** unknown `TRADING_ENV` ⇒ dev; live broker + dev env ⇒ startup failure; drift detector catches a mismatched `max_open_positions`.
- **Manual traceability:** every rule has a non-empty `manual_ref`.

**Judgment — none.** The gate makes no judgments by design; that's the boundary that makes it testable.

**The oracle caveat, restated:** these tests prove the gate implements the rules *as written*. They cannot prove the rules are *right* — that's a human review against `OPERATING_MANUAL.md`, which is why every rule carries its section reference.
