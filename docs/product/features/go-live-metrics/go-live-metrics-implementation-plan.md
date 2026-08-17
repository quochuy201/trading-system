# Implementation Plan: Go-Live Metrics

- **Slug:** `go-live-metrics` · **Status:** `plan` · **Design:** [`go-live-metrics-design.md`](go-live-metrics-design.md) · **Spec:** [`go-live-metrics-spec.md`](go-live-metrics-spec.md)
- **Executor:** Claude Code · **Date:** 2026-08-08 · **Rev 3** — three-layer architecture · **Status: building** (Task 1 done 2026-08-16)

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
- **Status:** ☑ **done** — `22dc627` (2026-08-16). 15 tests added, suite 368 (was 353) — *a floor, not evidence*.
  - ⚠️ **Scope of proof: storage contract only.** Every fill test is a hand-built `Fill` against `:memory:` SQLite. No broker fill has been stored; nothing reads Alpaca's activity feed until Tasks 2+4. Proven: **the table cannot double-count a replay and cannot be mutated after the fact.** Not proven: that we capture fills correctly.
  - **Tests were checked by mutation, not by reading.** `INSERT OR IGNORE` → `INSERT OR REPLACE` fails three tests independently: `assert 1.0 == 150.25` (stored execution rewritten), `assert True is False` (replay reported as new), and the source-level guard. Do this for every task — the repo has already shipped rules that pass tests and can never fire.
  - `Fill.fill_id` has **no default factory** — a generated id would mint a fresh row per poll and destroy the structural dedup. Asserted by `test_fill_id_is_never_generated`.
  - `insert_fill` is `INSERT OR IGNORE`, returns `True` on insert / `False` on replay. `test_insert_fill_never_overwrites` re-inserts the same `fill_id` with a different price and asserts the **original** row survives — `INSERT OR REPLACE` would have deleted and reinserted it.
  - Append-only is checked structurally, not by convention: `test_no_fill_mutation_path_exists` greps the repository source for `UPDATE fills` / `DELETE FROM fills` / `INSERT OR REPLACE INTO fills` and asserts the only fill-touching methods are `insert_fill` and `get_fills_for_order`.
  - `save_order` deliberately keeps `plan_id` / `gate_*` / `regime_at_entry` NULL when unknown (`test_order_nullables_stay_null`) — Task 3 fills `regime_at_entry` from the plan.
  - Migration proven on the real dev DB, run twice: both tables + `idx_fills_order` created, `trade_transactions` 22 → 22, `trade_plans` 13 → 13, `price_data` 172232 → 172232.
  - ⚠️ The plan's baseline of "28 txn rows, 14 with price=0.0" is the **live profile** DB. The repo's `tools/trading.db` has **22 rows, 13 at price=0.0** (the figure CLAUDE.md cites). Task 11's evidence must name which DB it measured.

### Task 2 — Broker adapter: TWO methods, different jobs (design §4a)
- **Files:** `tools/broker/adapter.py`, `tools/broker/alpaca.py`, `tools/broker/simulation.py`
- **What:** ⚠️ **`get_order()` must NOT be the fill source** — it returns *cumulative* `filled_qty`/`filled_avg_price`, so appending from repeated polls double-counts (poll at 50 filled, poll at 100, append both ⇒ 150). Add **two** methods:
  1. **`get_account_activities(activity_type, page_token, page_size) -> list[dict]`** — the **fill source**. Alpaca `GET /v2/account/activities/FILL` returns **discrete executions**: `qty` is *this* execution (never `cum_qty`), each with a **stable unique `id`** and an `order_id`. Simulation: return the executions it modelled.
  2. **`get_order(broker_order_id) -> dict`** — **status only.** Needed because cancelled/rejected/expired orders **never appear** in FILL activities.
- **Tests:** `tools/tests/test_broker.py` — activities return per-execution rows (assert `qty` ≠ `cum_qty` on a partial); pagination via `page_token`; both adapters agree on shape; `get_order` returns status and is **never used to build a fill** (assert no fill-shaped fields are consumed from it).
- **Acceptance:** the fill source is per-execution, not a cumulative snapshot.
- **Status:** ☑ **done** — `85d12aa` (2026-08-16). 15 tests; suite 383.
  - **Verified against the live paper account, not a fixture.** 250 real FILL activities, 186 orders, **31 filled in more than one execution**, **64 rows where `qty != cum_qty`**. Real order `b38bacd0` (SHOP sell 100) read through the new adapter: `qty` 80 + 20 = **100** (correct); `cum_qty` 80 + 100 = **180** (the double-count). The design's warning is now a measured fact.
  - Cursor sweep verified end to end: 3 pages × 100, 250 unique ids, empty page terminates — this is exactly the loop Task 4 drives.
  - **The fixture is that real payload captured verbatim.** Two things I would have got wrong by guessing: every numeric arrives as a **string** (`"price": "8"`), and `id` is `"<timestamp>::<uuid>"`, not a bare UUID.
  - `get_order()` returns `{order_id, status, symbol, qty_requested}` — **no** `filled_qty`/`filled_avg_price`/`price`/`qty`, so it is structurally unusable as a fill source. Asserted, both adapters.
  - Mutation-checked: pointing the fill source at `cum_qty` fails with `assert [80, 100] == [80, 20]`.
  - ⚠️ `get_account_activities` and `get_order` are **abstract** — a new adapter must decide rather than silently returning "no fills". `FakeBroker` in `test_broker.py` updated accordingly.
  - Fractional qty raises rather than truncating (0 of 250 real rows are fractional; a floored share is a wrong position nothing downstream can detect).

### Task 3 — `place_order` writes an `orders` row
- **Files:** `tools/server.py` (`place_order`, ~line 146-182)
- **What:** add a `regime` column to `trade_plans`, written at **plan creation** from the session preflight value (F8). On submit, INSERT into `orders` capturing `intended_price` (limit/signal price), `mode`, gate verdict fields (nullable until the gate ships), and `regime_at_entry` **inherited from the plan via `plan_id`**. ⚠️ **Do NOT call `get_market_regime` in the order path** — network call + failure mode in the hot path, and it would be the wrong (submit-time) regime. Keep writing `trade_transactions` during cutover; it becomes read-only in Task 8.
- **Tests:** `tools/tests/test_reconcile.py::test_place_order_records_intent` — an order row exists with `intended_price` set and `terminal_status IS NULL`; **`regime_at_entry` matches the plan's `regime`**; **order with no plan ⇒ `regime_at_entry IS NULL`, never fabricated**; **assert the order path makes no regime call** (no network in `place_order`).
- **Acceptance:** every placed order produces exactly one `orders` row; **no change to order-placement behaviour**; regime captured where it's known.
- **Status:** ☑ **done** — `a83b5ca` (2026-08-16). 20 tests; suite 403.
  - **Real-path evidence:** the `regime` ALTER ran against the dev DB — 13 existing plans preserved, column added, **0 rows backfilled** with a guessed regime, idempotent across two `init_db` passes. ⚠️ `CREATE TABLE IF NOT EXISTS` is a **no-op on an existing table**, so a new column never reaches a deployed DB. Added a guarded `_COLUMN_MIGRATIONS` pass in `db.py`; every future column goes there.
  - **Three honest-data decisions, each mutation-checked:**
    1. `intended_price` borrows the plan's entry level **only when the order is that plan's entry leg** (same side). Mutating it to always borrow fails with `assert 210.0 is None` — an exit would have carried the entry price and produced a confidently wrong slippage in Task 6.
    2. `save_order` is a **plain INSERT**, not `INSERT OR REPLACE`. `broker_order_id` is UNIQUE, so REPLACE silently deletes an earlier real placement — mutating it back fails with `assert 'TSLA' == 'NVDA'`. Found by a test that expected 2 rows and got 1.
    3. Recording **never blocks trading**: the order is already live, so a DB failure is logged, never returned. Mutating the handler to re-raise surfaces `sqlite3.IntegrityError` to the agent — which could read as "not placed" and invite a double-submit.
  - No regime call in the order path, guarded twice: monkeypatching `get_market_regime` to raise, and asserting the name does not appear in `place_order`'s source.
  - `mode` is `paper | live | simulation` derived from the active broker. Simulation gets its own value rather than being mislabelled paper — D-C says backtest results are never summed with live/paper.

  ### ⚠️ Finding for Task 4 — the join key (resolve before writing fills)

  `fills.order_id` is documented in design §3b as `TradeActivity.order_id → FK orders`. That is the **broker's** id, while `orders.order_id` is **ours** — so `fills.order_id = orders.order_id` matches **zero rows**. This is verbatim the defect CLAUDE.md's RULE 1 table already records ("one is the broker's UUID, one is ours — 0 rows match").

  Task 3 makes the correct join available: `orders.broker_order_id` is now populated on every row (asserted by `test_place_order_records_intent`). **Task 4 must join `fills.order_id = orders.broker_order_id`**, and `fills.order_id` must keep storing the broker's id — fills arrive from the activity feed for orders we never recorded (backfill, and the 6 orphan paper positions), so translating at insert time would either drop them or invent an `orders` row. Recommend renaming the column to `fills.broker_order_id` while the table still has 0 rows, so the join key is self-documenting and this cannot be reintroduced.

### Task 4 — `sync_fills()` (cursor) + `sync_orders_terminal()` (status)
- **Files:** `tools/audit/reconcile.py` (new), `sync_state` cursor row in `tools/persistence/db.py`
- **What:** two routines, not one:
  1. **`sync_fills()` — cursor-based, NOT per-order polling.** Persist the last seen activity `id`; loop `get_account_activities(FILL, direction=asc, page_token=cursor)`, `INSERT OR IGNORE INTO fills` with **`fill_id` = the broker's activity id**, advance the cursor, repeat until an empty page. **Dedup is structural** — a replay is a primary-key conflict, not logic you have to get right. One call covers **all** orders (not one per open order), and the *same code path backfills history* from an earlier cursor.
  2. **`sync_orders_terminal()`** — for orders still non-terminal with **no fills**, call `get_order()` and set `terminal_status` (cancelled/rejected/expired). These never appear in the FILL feed.
  Per-item try/except so one bad record can't abort the batch.
- **Tests:** `tools/tests/test_reconcile.py` — **idempotency: run `sync_fills()` twice ⇒ zero duplicate rows** (PK conflict, not a dedup branch); a partial fill followed by a completing fill yields **two rows whose qty sums to the order qty** (⚠️ the double-count regression test); cursor advances and resumes correctly; an early cursor backfills; cancelled order gets terminal status via `get_order` with **no** fill row; one bad record doesn't stop the batch.
- **Acceptance:** fills are per-execution and idempotent by construction; **no code path derives a fill from `get_order()`**.
- **Status:** ☑ **done** — `ab79200` (2026-08-16). 22 tests; suite 444.
  - **Real broker executions are now in our tables — 250 of them.** Run against the live paper account:
    ```
    run 1                      inserted=250 skipped=0   failed=0 pages=3
    run 2                      inserted=0   skipped=0   failed=0 pages=0   (cursor resumed)
    after a full cursor rewind inserted=0   skipped=250 failed=0 pages=3
    fills stored: 250 · distinct fill_ids: 250
    ```
    The third line is the proof: re-importing all 250 real executions yields 250 primary-key conflicts and **zero** duplicates. Idempotency is structural, not a branch that must be right.
  - Read back out of `fills`, order `b38bacd0`: `partial_fill qty=80 @120.5` + `fill qty=20 @121.91` = **100**. `cum_qty` would have said 180. Real orders now stored with up to **7 executions** (7 fills/311 shares — the FLR order PROJECT_STATUS cites).
  - **Rewinding the cursor IS the backfill** — same code path as the daily sync, no separate import script.
  - Per-record `try/except`; the cursor advances **past** a failure on purpose (not advancing wedges the sync forever) and `failed` is returned so the gap is visible and recoverable.
  - **Mutation-checked** (on committed code): `qty`→`cum_qty` fails with `assert 180 == 100`; freezing the cursor on failure fails two tests; `INSERT OR IGNORE`→`OR REPLACE` fails three.
  - ⚠️ **Join key renamed, per owner decision: `fills.order_id` → `fills.broker_order_id`.** It always held the *broker's* id while `orders.order_id` is *ours*, so joining them matched zero rows — the defect CLAUDE.md's RULE 1 table records. `test_fills_join_orders_on_broker_order_id` asserts both directions: the right join returns the row, the wrong one returns `[]`. The migration renames in place and **refuses to run against a populated table** (`fills` is append-only; no silent data migration).
  - Found while building it: `SCHEMA`'s `CREATE INDEX ON fills(broker_order_id)` ran *before* the rename and failed on a legacy table. Migrations now run first in `init_db`.
  - **Deviation from the plan text:** `sync_orders_terminal()` checks every non-terminal order, not only those "with no fills". Restricting it would leave filled orders non-terminal forever and `get_open_orders()` growing without bound. It still reads **status only** — `get_order()` exposes no qty or price, asserted by `test_terminal_sync_reads_only_status`.
  - Not yet exercised on real data: `sync_orders_terminal` returned `checked=0` because the dev DB's `orders` table is empty — nothing has been placed through `place_order` yet. Task 11 is where that closes.

### Task 5 — `round_trips` + `round_trip_fills` + deterministic IDs + ⭐ rebuild invariant
- **Files:** `tools/persistence/db.py`, `tools/audit/round_trips.py` (new), `tools/audit/ids.py` (new)
- **What:** both tables per design §3c/§3c-bis. `ids.py` holds the **canonicalizing hash helpers** (§3c-ter): UTC ISO-8601 timestamps, fixed decimal precision, sorted collections, `"|"` delimiters. `round_trip_id = sha256(first_entry_fill_id|last_exit_fill_id)[:16]`; `content_hash = sha256(sorted all fill_ids)[:16]`. Running-position FIFO over `fills` (qty-weighted prices, fee summation, flip-split, mode/regime carry-through). **`rebuild_round_trips()`** truncates + recomputes **both** tables.
- **Tests:** `tools/tests/test_round_trips.py` — simple pair · partial fills · scale-out · **FLR flip case ⇒ exactly 2 trips (long then short)** · open position ⇒ no row · **⭐ rebuild invariant: build → corrupt cache → rebuild ⇒ byte-identical incl. `round_trip_id`** · rebuild idempotent · link table maps every composing fill with correct `entry`/`exit` leg.
  **ID tests (`tools/tests/test_ids.py`, new):** same inputs ⇒ same ID **across processes** (compute in a subprocess, compare); ID **unaffected** by dict/set ordering, float `repr`, timezone representation, or wall-clock; delimiter prevents the `"ab"+"c" == "a"+"bc"` collision; a **late middle fill keeps `round_trip_id` stable but changes `content_hash`**; **no `round_trip_id` is ever a UUID** (assert no randomness in the derived path).
- **Acceptance:** FLR yields 2 correct trips; **rebuild reproduces the cache byte-identically, IDs included**; IDs are provably deterministic.
- **Status:** ☑ **done** — `0a6c509` (2026-08-16). 37 tests (16 ids + 21 round trips); suite 481.
  - **The system can measure a trade for the first time.** Built from the 250 real executions Task 4 imported: **61 round trips across 55 symbols**, 180 fill links, 41 wins, gross P&L **+3106.72**.
    ```
    PANW  long  qty= 48  332.55 -> 354.21  pnl= 1039.84
    OKTA  long  qty= 57  135.43 -> 147.60  pnl=  693.67
    HWM   long  qty= 48  279.07 -> 265.21  pnl= -665.28
    ```
  - ⭐ **The rebuild invariant holds on real data** — rebuilding all 61 trips produces byte-identical rows, `round_trip_id` and `content_hash` included. Only possible because ids are derived, not random; mutating `round_trip_id` to a UUID fails **9 tests**.
  - **The FLR ambiguity is resolved.** PROJECT_STATUS records `buy 311 → sell 311 → sell 267 → buy 267` as an identity problem `plan_id` grouping cannot answer. Running-position tracking answers it deterministically — **15 fills → 2 trips**:
    ```
    long  qty=311  49.24 -> 50.57  pnl=414.84   (7 entry fills, 3 exit)
    short qty=267  50.71 -> 48.61  pnl=561.65   (2 entry fills, 3 exit)
    ```
  - Entry/exit are quantity-weighted, so partials and scale-outs need no special case; a single fill that flips the position is split across both trips and links to each with a different leg.
  - **Honest-data decisions:** `total_fees` is `0.0` **with `fees_attributable=0`** — Alpaca's fill activities carry no fee data and account-level fees have no `order_id`, so per-trade attribution does not exist and the flag stops `net_pnl` being silently overstated (design §3b-bis; D7 evaluates cost at portfolio level). `initial_stop` / `r_multiple` / `slippage` stay **NULL for Task 6** — a 0.0 would later be indistinguishable from a measurement. An open position yields **no row**. Orphan fills still measure, with plan context NULL.
  - `round_trip_id` is never stamped onto `fills` — that would need an UPDATE and break append-only immutability.
  - **Mutation-checked** (committed code): UUID id → 9 failures · no delimiter → 2 · unsorted `content_hash` → 1 · plain mean instead of qty-weighted → 1.
  - ⚠️ **Process note:** after a mutation restore, `touch` the restored files. Python validates its bytecode cache on whole-second source mtime, so a `git checkout` in the same second as the `.pyc` write leaves the cache falsely valid and the "restored" run silently executes the MUTATED code while `inspect.getsource` shows the correct source.

### Task 6 — R-multiple + slippage
- **Files:** `tools/audit/round_trips.py`
- **What:** `r_multiple` from the trip + `trade_plans.stop_loss` **as recorded at entry** (long/short formulas, design §4). Missing plan / null stop / denominator ≤ 0 ⇒ `NULL` + `r_uncomputable_reason`. `slippage` = entry vs `orders.intended_price`, sign-adjusted per side.
- **Tests:** `tools/tests/test_round_trips.py` — hand-computed long R (assert exact to 4dp); short R; missing stop ⇒ NULL+reason; denominator ≤ 0 ⇒ NULL+reason; **never silently 0**; slippage sign correct for buy and for sell.
- **Acceptance:** hand-computed R matches exactly; uncomputable cases carry a reason.
- **Status:** ☑ **done** — `5b61d28` (2026-08-16). 21 tests; suite 502.
  - Hand-computed to 4dp: long entry 150.25 / stop 147.10 / exit 158.40 ⇒ `8.15/3.15 = 2.5873`; short entry 50.71 / stop 52.20 / exit 48.61 ⇒ `2.10/1.49 = 1.4094`.
  - **Four refusals, none of which may become 0.0** — a zero R is a real outcome (exited at entry) and must stay distinguishable from "could not compute":

    | reason | meaning |
    |---|---|
    | `no_order_recorded` | the fill predates intent capture — unrecoverable history |
    | `no_plan_recorded` | order exists, no plan — an ad-hoc trade |
    | `stop_is_zero_placeholder` | `TradePlan.stop_loss` defaults to **0.0**; treating that as a stop gives `risk == entry_price` and a plausible-looking R that is fiction |
    | `non_positive_risk` | stop on the wrong side of entry |
  - Slippage is sign-normalised so **positive always means worse** either way: a long that paid above intent and a short that sold below it both report positive. No reference ⇒ NULL, never 0.0 (which would read as "filled exactly at intent").
  - **Mutation-checked:** uncomputable→0.0 fails 5 tests · zero-stop accepted fails 3 (`stop=0.0 produced 0.0666…`) · short slippage not inverted fails 3 · non-positive risk allowed through fails 3 (incl. `ZeroDivisionError`).
  - ⚠️ **Honest result on real data: 0 of 61 real trips are R-computable.** All 61 report `no_order_recorded` — `orders` has **0 rows**, because every one of the 250 imported executions predates Task 3's intent capture. This is PROJECT_STATUS's "cannot be reconstructed retroactively", now measured rather than asserted. The machinery is proven by the hand-computed tests; the historical dataset lacks the inputs. **The first R-computable trade is one placed after Task 3 shipped.**
  - 📌 **Decision for the owner, deliberately not taken here:** **16 of 186** broker orders appear in the legacy `trade_transactions` table *and* link to a plan with a usable `stop_loss`. Backfilling `orders` from those rows would make up to 16 trips R-measurable. Task 8 fences `trade_transactions` off — that fence is about not fabricating *fills* from it, and backfilling *intent* is a different operation, but adjacent enough to need a decision rather than a commit.
  - Note: an entry spanning several orders takes its intent from the **first** entry fill's order; distinct intended prices across one entry are not blended.

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
