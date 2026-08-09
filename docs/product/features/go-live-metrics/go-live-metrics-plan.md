# Implementation Plan: Go-Live Metrics

- **Slug:** `go-live-metrics` · **Status:** `plan` · **Design:** [`go-live-metrics-design.md`](go-live-metrics-design.md) · **Spec:** [`go-live-metrics-spec.md`](go-live-metrics-spec.md)
- **Executor:** Claude Code · **Date:** 2026-08-08 · **Rev 3** — three-layer architecture — work begun on implementation

## How to Use This Plan

Ordered, bite-sized tasks. TDD per `CLAUDE.md`: write the test, watch it fail, implement, watch it pass. After each task run the named tests, check the box, note the commit. Do not batch unrelated tasks.

## Guardrails (read before writing code)

- **This feature must not change a single trading decision.** It observes and records only. If a change would alter what/when/how much we trade — stop and flag.
- Preserve kill switch, circuit breakers, mode state machine, R:R gates.
- **`fills` is append-only. No code path may ever UPDATE or DELETE a fill.**
- Reconciliation must **never** block or fail order placement — catch, log, continue.
- MCP tools return JSON errors, never raise to the agent.
- **Never estimate a missing stop or fee.** Missing ⇒ NULL + reason + visibly excluded. `0.0` is a lie.
- All existing tests (331) must stay green.

---

## Tasks

### Task 1 — `orders` + `fills` tables and models
- **Files:** `tools/persistence/db.py`, `tools/models.py`, `tools/persistence/repository.py`
- **What:** create both tables per design §3a/§3b (+ index on `fills.order_id`). Add `Order` and `Fill` dataclasses. Repository: `save_order`, `set_order_terminal`, `insert_fill`, `get_fills_for_order`, `get_open_orders`. Migration is guarded (no-op if already applied).
- **Tests:** `tools/tests/test_models_and_persistence.py` — save/load both entities; migration idempotent; **`insert_fill` twice with the same `fill_id` does not duplicate**; no update/delete method exists on fills.
- **Acceptance:** both tables exist; existing DB migrates cleanly; fills are insert-only by construction.
- **Status:** ☐ todo

### Task 2 — Broker adapter: TWO methods, different jobs (design §4a)
- **Files:** `tools/broker/adapter.py`, `tools/broker/alpaca.py`, `tools/broker/simulation.py`
- **What:** ⚠️ **`get_order()` must NOT be the fill source** — it returns *cumulative* `filled_qty`/`filled_avg_price`, so appending from repeated polls double-counts (poll at 50 filled, poll at 100, append both ⇒ 150). Add **two** methods:
  1. **`get_account_activities(activity_type, page_token, page_size) -> list[dict]`** — the **fill source**. Alpaca `GET /v2/account/activities/FILL` returns **discrete executions**: `qty` is *this* execution (never `cum_qty`), each with a **stable unique `id`** and an `order_id`. Simulation: return the executions it modelled.
  2. **`get_order(broker_order_id) -> dict`** — **status only.** Needed because cancelled/rejected/expired orders **never appear** in FILL activities.
- **Tests:** `tools/tests/test_broker.py` — activities return per-execution rows (assert `qty` ≠ `cum_qty` on a partial); pagination via `page_token`; both adapters agree on shape; `get_order` returns status and is **never used to build a fill** (assert no fill-shaped fields are consumed from it).
- **Acceptance:** the fill source is per-execution, not a cumulative snapshot.
- **Status:** ☐ todo

### Task 3 — `place_order` writes an `orders` row
- **Files:** `tools/server.py` (`place_order`, ~line 146-182)
- **What:** add a `regime` column to `trade_plans`, written at **plan creation** from the session preflight value (F8). On submit, INSERT into `orders` capturing `intended_price` (limit/signal price), `mode`, gate verdict fields (nullable until the gate ships), and `regime_at_entry` **inherited from the plan via `plan_id`**. ⚠️ **Do NOT call `get_market_regime` in the order path** — network call + failure mode in the hot path, and it would be the wrong (submit-time) regime. Keep writing `trade_transactions` during cutover; it becomes read-only in Task 8.
- **Tests:** `tools/tests/test_reconcile.py::test_place_order_records_intent` — an order row exists with `intended_price` set and `terminal_status IS NULL`; **`regime_at_entry` matches the plan's `regime`**; **order with no plan ⇒ `regime_at_entry IS NULL`, never fabricated**; **assert the order path makes no regime call** (no network in `place_order`).
- **Acceptance:** every placed order produces exactly one `orders` row; **no change to order-placement behaviour**; regime captured where it's known.
- **Status:** ☐ todo

### Task 4 — `sync_fills()` (cursor) + `sync_orders_terminal()` (status)
- **Files:** `tools/audit/reconcile.py` (new), `sync_state` cursor row in `tools/persistence/db.py`
- **What:** two routines, not one:
  1. **`sync_fills()` — cursor-based, NOT per-order polling.** Persist the last seen activity `id`; loop `get_account_activities(FILL, direction=asc, page_token=cursor)`, `INSERT OR IGNORE INTO fills` with **`fill_id` = the broker's activity id**, advance the cursor, repeat until an empty page. **Dedup is structural** — a replay is a primary-key conflict, not logic you have to get right. One call covers **all** orders (not one per open order), and the *same code path backfills history* from an earlier cursor.
  2. **`sync_orders_terminal()`** — for orders still non-terminal with **no fills**, call `get_order()` and set `terminal_status` (cancelled/rejected/expired). These never appear in the FILL feed.
  Per-item try/except so one bad record can't abort the batch.
- **Tests:** `tools/tests/test_reconcile.py` — **idempotency: run `sync_fills()` twice ⇒ zero duplicate rows** (PK conflict, not a dedup branch); a partial fill followed by a completing fill yields **two rows whose qty sums to the order qty** (⚠️ the double-count regression test); cursor advances and resumes correctly; an early cursor backfills; cancelled order gets terminal status via `get_order` with **no** fill row; one bad record doesn't stop the batch.
- **Acceptance:** fills are per-execution and idempotent by construction; **no code path derives a fill from `get_order()`**.
- **Status:** ☐ todo

### Task 5 — `round_trips` + `round_trip_fills` + deterministic IDs + ⭐ rebuild invariant
- **Files:** `tools/persistence/db.py`, `tools/audit/round_trips.py` (new), `tools/audit/ids.py` (new)
- **What:** both tables per design §3c/§3c-bis. `ids.py` holds the **canonicalizing hash helpers** (§3c-ter): UTC ISO-8601 timestamps, fixed decimal precision, sorted collections, `"|"` delimiters. `round_trip_id = sha256(first_entry_fill_id|last_exit_fill_id)[:16]`; `content_hash = sha256(sorted all fill_ids)[:16]`. Running-position FIFO over `fills` (qty-weighted prices, fee summation, flip-split, mode/regime carry-through). **`rebuild_round_trips()`** truncates + recomputes **both** tables.
- **Tests:** `tools/tests/test_round_trips.py` — simple pair · partial fills · scale-out · **FLR flip case ⇒ exactly 2 trips (long then short)** · open position ⇒ no row · **⭐ rebuild invariant: build → corrupt cache → rebuild ⇒ byte-identical incl. `round_trip_id`** · rebuild idempotent · link table maps every composing fill with correct `entry`/`exit` leg.
  **ID tests (`tools/tests/test_ids.py`, new):** same inputs ⇒ same ID **across processes** (compute in a subprocess, compare); ID **unaffected** by dict/set ordering, float `repr`, timezone representation, or wall-clock; delimiter prevents the `"ab"+"c" == "a"+"bc"` collision; a **late middle fill keeps `round_trip_id` stable but changes `content_hash`**; **no `round_trip_id` is ever a UUID** (assert no randomness in the derived path).
- **Acceptance:** FLR yields 2 correct trips; **rebuild reproduces the cache byte-identically, IDs included**; IDs are provably deterministic.
- **Status:** ☐ todo

### Task 6 — R-multiple + slippage
- **Files:** `tools/audit/round_trips.py`
- **What:** `r_multiple` from the trip + `trade_plans.stop_loss` **as recorded at entry** (long/short formulas, design §4). Missing plan / null stop / denominator ≤ 0 ⇒ `NULL` + `r_uncomputable_reason`. `slippage` = entry vs `orders.intended_price`, sign-adjusted per side.
- **Tests:** `tools/tests/test_round_trips.py` — hand-computed long R (assert exact to 4dp); short R; missing stop ⇒ NULL+reason; denominator ≤ 0 ⇒ NULL+reason; **never silently 0**; slippage sign correct for buy and for sell.
- **Acceptance:** hand-computed R matches exactly; uncomputable cases carry a reason.
- **Status:** ☐ todo

### Task 6b — Equity history + daily portfolio snapshot (unblocks the circuit breakers)
- **Files:** `tools/broker/adapter.py`, `tools/broker/alpaca.py`, `tools/broker/simulation.py`, `tools/server.py` (`get_portfolio_state`), EOD path
- **What:** add `get_portfolio_history(period, timeframe) -> {timestamps[], equity[]}` (Alpaca `/v2/account/portfolio/history`; simulation from its equity curve). Compute `drawdown_5d_pct` / `drawdown_20d_pct` from it (short cache ≈5 min). Extend `get_portfolio_state()` to surface them. Write one `portfolio_snapshots` row per day (durable copy + backtest; **broker remains the source of truth**).
- **Tests:** `tools/tests/test_broker.py` + `tools/tests/test_reconcile.py` — both adapters return the same shape; drawdown-from-peak computed correctly on a known series (assert exact); **fetch failure ⇒ `UNAVAILABLE`, never 0/"no drawdown"**; daily snapshot idempotent (one row per day).
- **Acceptance:** `drawdown_5d/20d` computable **today**, with no warmup and no dependence on prior recording — the governance gate's §4.4 breakers become armable.
- **Status:** ☐ todo

### Task 7 — `v_performance_current` view + snapshot log
- **Files:** `tools/persistence/db.py` (view), `tools/audit/performance.py`
- **What:** create the view per design §3d (GROUP BY mode, strategy). Compute path-dependent metrics (`max_drawdown`, `sharpe`) in Python. Repurpose the existing `performance_metrics` table as an **EOD snapshot log** (add `expectancy_r` column).
- **Tests:** `tools/tests/test_audit.py` — fixture set with **known expectancy** (assert exact); NULL-R trades excluded from `expectancy_r` but counted in `total_trades`; `r_excluded` correct; **paper/live never summed**; empty set ⇒ no crash, NULLs not zeros; **F10: a NULL-`net_pnl` row must not silently understate `win_rate`** — excluded from *both* numerator and denominator (`COUNT(net_pnl)`); zero-denominator ⇒ NULL, not a divide-by-zero.
- **Acceptance:** the view returns correct live metrics with no job having to run.
- **Status:** ☐ todo

### Task 8 — `trade_transactions`: LEAVE IT ALONE (no code)
- **Files:** none
- **What:** **nothing.** No migration, no deletion, no schema change. It keeps being written as today (`server.py:175`) — harmless dual-write, useful as a cutover safety net. `orders`/`fills` are the source of truth; nothing in this feature reads `trade_transactions`.
  ⛔ **Do not migrate it** (6 of its 9 non-zero prices are the plan's limit price — intents, not executions; converting them would fabricate go-live evidence). ⛔ **Do not delete it** (`save_transaction` is a live tool in the `monitor` + `trader` skills; removal is a real refactor, out of scope). See `design.md` §6.
- **Tests:** `tools/tests/test_reconcile.py::test_legacy_table_untouched` — `fills` never contains a row sourced from `trade_transactions`; no new code path reads it.
- **Acceptance:** zero legacy rows influence any metric, and the table is otherwise unchanged.
- **Status:** ☐ todo

### Task 9 — `get_go_live_scorecard()` MCP tool
- **Files:** `tools/server.py` (new `@mcp.tool()`, `eod` group)
- **What:** return the D5 ladder — trades vs floor 100 / convincing 200, `expectancy_r`, regimes covered (distinct `regime_at_entry`), paper-vs-backtest %, gate live?, D7 status, `r_excluded`, and `verdict` (`READY` only if **all** pass; unknown ≠ pass). Docstring per repo convention.
- **Tests:** `tools/tests/test_scorecard.py` (new) + `tools/tests/test_tool_groups.py` (tool exposed in `eod`) — all-pass ⇒ READY; any fail/unknown ⇒ NOT READY; exclusions surfaced; JSON error on failure, never raises.
- **Acceptance:** returns today's real state (`trades 0/100`, `verdict NOT READY`).
- **Status:** ☐ todo

### Task 10 — Wire into monitor + EOD + daily report
- **Files:** monitor path / `tools/monitor_sentinel.py`, EOD job, daily report renderer, `skills/eod-review/SKILL.md`
- **What:** `reconcile_fills()` in the monitor cadence and at EOD; then `rebuild_round_trips()`; write the EOD snapshot row; render a **Go-Live Scorecard** block in the daily report; EOD skill reports scorecard progress.
- **Tests:** `tools/tests/test_reconcile.py` (integration) — an EOD pass populates trips + snapshot; a reconciliation exception does **not** abort EOD or affect orders.
- **Acceptance:** one EOD cycle end-to-end produces metrics + scorecard.
- **Status:** ☐ todo

### Task 11 — Integration proof + docs
- **Files:** `PROJECT_STATUS.md`, `docs/product/ROADMAP.md`, this plan
- **What:** place a paper order → reconcile → confirm a `round_trips` row with a **real non-zero fill price** and a computed R. Close the 🔴 CRITICAL bug in `PROJECT_STATUS.md` with evidence; bump ROADMAP to `shipped`.
- **Tests:** full suite green (331 + new).
- **Acceptance:** **a real paper trade appears as a measurable round trip.** This is the proof the bug is dead.
- **Status:** ☐ todo

---

## Definition of Done (whole feature)

- [ ] All 11 tasks done, boxes checked, commits noted
- [ ] Full suite green (331 existing + new)
- [ ] End-to-end: submit → fill → reconcile → round trip → view → scorecard
- [ ] **⭐ Rebuild invariant test passes** — `round_trips` fully reproducible from `fills`
- [ ] `fills` provably append-only (no UPDATE/DELETE path exists)
- [ ] Migration honest: 13 unrecoverable rows excluded, never counted
- [ ] Zero trading-behaviour changes (diff touches no strategy/sizing/gate logic)
- [ ] `PROJECT_STATUS.md` bug closed with evidence; ROADMAP `shipped`

## Decisions carried from spec

- **D-A** reconciliation trigger → **poll** (stream can replace internals later behind the same function)
- **D-B** sample floor → report **both** 100 (floor) and 200 (convincing)
- **D-C** backtest trades stay in `backtest_trades` — **never** summed with live/paper round trips
