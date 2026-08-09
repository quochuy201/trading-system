# Design: Go-Live Metrics (Trade-Outcome Capture)

- **Slug:** `go-live-metrics` · **Status:** `design` · **Spec:** [`go-live-metrics-spec.md`](go-live-metrics-spec.md)
- **Author:** Claude Code · **Date:** 2026-07-25 · **Rev 2** — three-layer architecture (supersedes the additive-column draft)

> **Design principle:** record **immutable facts at the moment they happen** — the planned stop at entry, the actual fill price at fill, fees as charged. Never plan to reconstruct them later. A fill price not captured is lost forever.

---

## 1. The architectural error we are fixing

`trade_transactions` tries to be **two things at once**: a record of *what we asked for* and a record of *what actually happened*. It is written at submit time with the intent — and reality has nowhere to land. That is why `price = 0.0` sits there permanently in 13 of 22 rows.

**The fix is to split intent from reality.** This kills the *class* of bug, not just this instance.

```
1. INTENT    trade_plans → orders            what we asked for   (written once)
2. REALITY   fills                           what happened       (append-only, immutable)
3. DERIVED   round_trips → metrics           rebuilt from layer 2
```

## 2. Table vs view — the rule

> **Facts are tables. Derivations are views — unless the derivation is procedural or carries point-in-time context, in which case it is a materialized table with a mandatory rebuild.**

| Entity | Kind | Rationale |
|---|---|---|
| `trade_plans` | **TABLE** (exists) | Intent at plan time. Not recomputable. |
| `orders` | **TABLE** (new) | Intent at submit: `intended_price`, gate verdict, mode, regime. Facts. |
| `fills` | **TABLE** (new) ⭐ | **The source of truth.** Immutable, append-only, one row per execution. |
| `round_trips` | **materialized TABLE** (new) + `rebuild()` | Pairing is procedural (running-position FIFO with flip-split) and carries point-in-time context. A cache, **not** a source of truth. |
| `v_performance_current` | **VIEW** (new) | Set aggregation over `round_trips`. Cannot go stale — structurally eliminates the "0 rows because nothing ran" failure. |
| `performance_metrics` | **TABLE** (exists, repurposed) | Now purely an **EOD snapshot log** ("what did we report on date X"). Not the live source. |

**Path-dependent metrics** (`max_drawdown`, `sharpe`) need ordered cumulative P&L and stddev — awkward in SQLite. The view carries the set-based metrics; path-dependent ones are computed in Python for the scorecard.

---

## 3. Schema

### 3a. `orders` — INTENT (new)

```sql
CREATE TABLE IF NOT EXISTS orders (
    order_id         TEXT PRIMARY KEY,
    plan_id          TEXT,                    -- FK trade_plans
    broker_order_id  TEXT UNIQUE,
    symbol           TEXT NOT NULL,
    side             TEXT NOT NULL,           -- buy | sell
    order_type       TEXT NOT NULL,
    qty_requested    INTEGER NOT NULL,
    intended_price   REAL,                    -- limit/signal price → slippage reference
    submitted_at     TEXT NOT NULL,
    terminal_status  TEXT,                    -- NULL until terminal; then filled|partially_filled|cancelled|rejected|expired|unknown_historical
    gate_verdict     TEXT,                    -- APPROVED|REDUCED|REJECTED|PENDING  (per-rule telemetry, BUILD-PLAN §4.5)
    gate_rule_id     TEXT,
    regime_at_entry  TEXT,                    -- inherited from trade_plans.regime (see below)
    mode             TEXT NOT NULL            -- paper | live
);
```

**⚠️ `regime_at_entry` source (review finding F8).** `get_market_regime` is called by the **risk-manager at preflight — once per session**, not at submit time. So:

- **Do NOT compute regime inside the order path.** It would add a network call plus a failure mode to the hot path — and would be the *wrong* regime anyway: what matters is the regime **when the decision was made**, not when the order happened to be submitted.
- **Add a `regime` column to `trade_plans`**, written at plan creation from the session's preflight value. `orders.regime_at_entry` **inherits it via `plan_id`** and is denormalized onto the order on purpose (orders must stand alone as facts; plans can be edited).
- No plan (manual/ad-hoc order) ⇒ `regime_at_entry = NULL`, never fabricated.

This is the point-in-time rule again: **capture the fact where and when it is known.** A later lookup would silently rewrite history, because the regime calculation itself is versioned.

### 3b. `fills` — REALITY (new) ⭐

**Source: Alpaca Account Activities (`GET /v2/account/activities/FILL`), NOT `get_order()`.** See §4a for why this matters.

```sql
CREATE TABLE IF NOT EXISTS fills (
    fill_id      TEXT PRIMARY KEY,            -- = TradeActivity.id (broker's stable unique execution id)
    order_id     TEXT NOT NULL,               -- = TradeActivity.order_id → FK orders
    symbol       TEXT NOT NULL,
    side         TEXT NOT NULL,               -- buy | sell
    qty          INTEGER NOT NULL,            -- TradeActivity.qty — THIS execution only (NOT cum_qty)
    price        REAL NOT NULL,               -- actual per-share execution price
    fill_type    TEXT NOT NULL,               -- fill | partial_fill
    filled_at    TEXT NOT NULL,               -- transaction_time
    mode         TEXT NOT NULL                -- paper | live
);
CREATE INDEX IF NOT EXISTS idx_fills_order ON fills(order_id);
```

**`fill_id` is the broker's own activity id** — so **dedup is structural**: re-inserting the same execution is a primary-key conflict, not a logic bug. Idempotency by construction rather than by careful coding.

**One row per execution.** A partial fill is two rows. The only legal operation is INSERT — never UPDATE, never DELETE.

**Fees are NOT on this table** — see §3b-bis.

### 3b-bis. `account_fees` — fees, honestly (new)

Alpaca's `TradeActivity` carries **no fee data**. Regulatory fees arrive as separate **non-trade activities** (`FEE`, `PTC`, …) which have **no `order_id`** — so per-fill fee attribution is **not available from the broker**.

```sql
CREATE TABLE IF NOT EXISTS account_fees (
    fee_id      TEXT PRIMARY KEY,             -- NTA activity id
    activity_type TEXT NOT NULL,              -- FEE | PTC | CFEE | ...
    symbol      TEXT,                         -- often NULL
    net_amount  REAL NOT NULL,
    date        TEXT NOT NULL,
    mode        TEXT NOT NULL
);
```

**Consequence, stated plainly:** `round_trips.net_pnl` is **net of anything the broker attributes to the trade, but gross of unattributable account-level fees**. D7's "net of transaction costs" is therefore evaluated at the **portfolio level** (sum of `account_fees` over the window), not per trade. Every round trip carries `fees_attributable = 0|1` so this is never silently overstated. **Do not invent a per-trade fee allocation** — an estimate here would corrupt the exact number D7 depends on.

### 3b-ter. `portfolio_snapshots` — daily equity (existing table, **0 rows — nothing writes it**)

Needed by the governance gate's §4.4 circuit breakers (drawdown from peak over 5/20 days) and by `max_drawdown` in the scorecard.

**Source of truth is the broker, not us.** Alpaca serves `GET /v2/account/portfolio/history` (equity time series) — so drawdown is computed from **broker-provided history**, with **no warmup period** and no dependence on us having recorded anything. This follows D3: the execution broker is authoritative for account state.

- **New:** `BrokerAdapter.get_portfolio_history(period, timeframe) -> {timestamps[], equity[]}` (Alpaca endpoint above; `simulation.py` from the simulated equity curve).
- **We still write `portfolio_snapshots` once per day** — for **durability, backtest, and cross-checking the broker**, *not* as the authoritative source. Broker = truth; snapshot = durable copy that survives a broker change.
- Existing `get_portfolio_state()` (`server.py:838`) is extended to surface `drawdown_5d_pct` / `drawdown_20d_pct` so live portfolio health is checkable on demand.
- If the fetch fails, dependent rules report **`UNAVAILABLE`**, never "no drawdown" — see `governance-gate/design.md` §3a.

**Why this matters (review finding F4):** without it, the two circuit-breaker rules would have been **dead controls that look alive** — present, tested, logging `R_OK`, and unable to ever fire.

### 3c. `round_trips` — DERIVED CACHE (new)

```sql
CREATE TABLE IF NOT EXISTS round_trips (
    round_trip_id  TEXT PRIMARY KEY,           -- DERIVED (see §3c-bis) — never random
    content_hash   TEXT NOT NULL,              -- hash of ALL composing fills → detects amendment
    plan_id        TEXT,
    symbol         TEXT NOT NULL,
    strategy       TEXT,  sop_version TEXT,
    direction      TEXT,                      -- long | short
    quantity       INTEGER,
    entry_price    REAL,  entry_at TEXT,      -- qty-weighted avg of entry fills
    exit_price     REAL,  exit_at  TEXT,
    initial_stop   REAL,                      -- trade_plans.stop_loss AS PLANNED AT ENTRY
    gross_pnl      REAL,  total_fees REAL,
    net_pnl        REAL,                      -- ← D7 net of costs
    r_multiple     REAL,                      -- NULL when uncomputable
    r_uncomputable_reason TEXT,
    slippage       REAL,                      -- entry_price − orders.intended_price
    regime_at_entry TEXT,
    mode           TEXT NOT NULL,
    rebuilt_at     TEXT
);
```

### 3c-bis. `round_trip_fills` — the link (derived, rebuilt with round_trips)

A round trip spans **many** fills — one-to-many, not one-to-one:

```
Buy 300  → fills: 100 @150.10 (A), 200 @150.15 (B)
Sell 300 → fills: 150 @154.00 (C), 150 @154.20 (D)
= 4 fill rows → 1 round trip   (entry = qty-weighted avg of A+B; exit of C+D)
```

```sql
CREATE TABLE IF NOT EXISTS round_trip_fills (
    round_trip_id TEXT NOT NULL,
    fill_id       TEXT NOT NULL,
    leg           TEXT NOT NULL,               -- entry | exit
    PRIMARY KEY (round_trip_id, fill_id)
);
```

⚠️ **Do NOT put `round_trip_id` on `fills`.** Round trips are computed later, so stamping fills would require an `UPDATE` — breaking the append-only immutability the whole design rests on. The link is *derived*, so it lives in a derived table and is truncated/rebuilt alongside `round_trips`.

### 3c-ter. ⭐ ID discipline (applies system-wide)

> **Facts get generated IDs. Derived rows get IDs derived from the facts they came from.**

| Row type | ID source | Why |
|---|---|---|
| `fills` (fact) | **broker's** activity id | Globally unique; makes dedup structural |
| `orders` (fact) | generated once at submit | Written once, never rebuilt |
| `round_trips` (derived) | **computed hash** | Must survive rebuild — a random UUID makes the rebuild invariant unpassable and dangles every external reference |

```
round_trip_id = sha256(first_entry_fill_id + "|" + last_exit_fill_id)[:16]   # stable IDENTITY
content_hash  = sha256("|".join(sorted(all composing fill_ids)))[:16]        # detects AMENDMENT
```

Identity is bounded by first-entry/last-exit (two trips can never share both), so a late middle fill **keeps the ID stable** while `content_hash` changes — references survive, amendments are still detectable.

**Rules for any generated/derived ID (test these):**

1. **Deterministic** — same inputs ⇒ same ID, every time, on every machine.
2. **No ambient inputs** — never hash wall-clock time, `random`, PID, locale, or memory addresses. Only the facts.
3. **Canonicalize before hashing** — UTC ISO-8601 timestamps, fixed decimal precision for floats (never raw `repr`), **sorted** collections (dict/set iteration order is not a contract).
4. **Always delimit** — `a + "|" + b`, never bare concatenation (`"ab"+"c" == "a"+"bc"` is a real collision).
5. **Stable across restarts and rebuilds** — a rebuild must reproduce byte-identical IDs.

### 3d. `v_performance_current` — VIEW (new)

```sql
CREATE VIEW IF NOT EXISTS v_performance_current AS
SELECT mode, strategy,
       COUNT(*)                                              AS total_trades,
       -- F10: COUNT(net_pnl) excludes NULL-P&L rows from BOTH sides; NULLIF guards /0.
       -- (`SUM(net_pnl > 0)` alone yields NULL for NULL rows → silently understated win rate.)
       SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) * 1.0
         / NULLIF(COUNT(net_pnl), 0)                         AS win_rate,
       AVG(r_multiple)                                       AS expectancy_r,   -- NULLs auto-excluded
       COUNT(r_multiple)                                     AS r_computable_trades,
       COUNT(*) - COUNT(r_multiple)                          AS r_excluded,
       SUM(CASE WHEN net_pnl > 0 THEN net_pnl ELSE 0 END) /
         NULLIF(ABS(SUM(CASE WHEN net_pnl < 0 THEN net_pnl ELSE 0 END)), 0) AS profit_factor,
       SUM(net_pnl)                                          AS total_net_pnl
FROM round_trips
GROUP BY mode, strategy;
```

`GROUP BY mode` guarantees **paper and live are never summed**.

---

## 4a. ⭐ Fill capture — cursor sync, NOT per-order polling

**The trap (found in adversarial review):** `get_order()` returns **cumulative** `filled_qty` / `filled_avg_price`. Polling it repeatedly and appending would **double-count** — poll at 50 filled, poll again at 100 filled, append both ⇒ 150 qty. An append-only fills table is fundamentally incompatible with a cumulative-snapshot API.

**The fix — two different jobs, two different endpoints:**

| Need | Endpoint | Why |
|---|---|---|
| **Fills** (the facts) | `GET /v2/account/activities/FILL` | Returns **discrete executions**: `qty` is *this* execution (not `cum_qty`), each with a **stable unique `id`**. |
| **Terminal status** of orders that never filled | `get_order(id)` | Cancelled / rejected / expired orders **never appear** in FILL activities, so they need a direct lookup. |

### `sync_fills()` — cursor-based

```
cursor = last seen TradeActivity.id            (persisted)
loop:
  GET /v2/account/activities/FILL?direction=asc&page_token=<cursor>&page_size=100
  for each activity:  INSERT OR IGNORE INTO fills (fill_id = activity.id, ...)
  cursor = last activity.id
until empty page
```

Why this is strictly better than per-order polling:

- **Idempotent by construction** — `fill_id` = broker activity id is the PK, so a replay is a no-op. No "have I seen this fill?" logic to get wrong.
- **No cumulative/incremental confusion** — `qty` is already per-execution.
- **One call covers all orders** (not one call per open order) — fewer requests, no rate-limit pressure.
- **Same code path backfills history** — it's just an earlier cursor.
- **Catches fills for orders we failed to record**, closing the gap that created this bug.

`sync_orders_terminal()` runs alongside: for orders still non-terminal with no fills, call `get_order()` and set `terminal_status` (cancelled/rejected/expired).

---

## 4. Round-trip construction (procedural — hence a table, not a view)

**Input:** `fills` joined to `orders`, per `(symbol, mode)`, ordered by `filled_at`.

1. Track signed running position. Buy adds, sell subtracts — using **`fills.qty`**, never `qty_requested`.
2. Opening from flat → start a trip; accumulate entry fills.
3. **Position returns to zero ⇒ the trip closes.** Emit one row.
4. Entry/exit prices = **qty-weighted averages** of their fills (partials and scale-outs handled for free).
5. `total_fees` = Σ commission+fees over every fill in the trip.
6. **Position flips sign in one fill** → split it: close at zero, open a new trip with the remainder.

This resolves the FLR ambiguity (`buy 311 → sell 311 → sell 267 → buy 267`) deterministically: **trip #1 long**, then **trip #2 short**. Note it is *not* derivable from `plan_id` grouping — which is exactly why position-tracking replaces it.

### R-multiple

```
long:   r = (exit − entry) / (entry − initial_stop)
short:  r = (entry − exit) / (initial_stop − entry)
```

`initial_stop` comes from `trade_plans.stop_loss` **as recorded at entry**. Missing plan, null stop, or denominator ≤ 0 ⇒ **`r_multiple = NULL` + `r_uncomputable_reason`**. **Never estimate a stop.**

### Slippage

`slippage = entry_price − orders.intended_price` (sign-adjusted for side). This is the number that reveals whether paper trading is lying — and it exists *only* because intent and reality are separate rows.

---

## 5. ⭐ The rebuild invariant (the most important property)

```python
rebuild_round_trips()   # truncate + recompute round_trips AND round_trip_fills from fills + orders + trade_plans
```

**`round_trips` is a cache. `fills` is the truth.** The invariant:

> Rebuilding from `fills` must reproduce `round_trips` **exactly — byte-identical, including IDs**.

This is only achievable because IDs are **derived, not generated** (§3c-ter). With a random `round_trip_id` the invariant is unpassable by construction, and every external reference to a round trip dangles after each rebuild. The test compares `round_trip_id` + `content_hash` per row.

This is what buys the right to be wrong later: if the R formula or the pairing logic has a bug, fix it and **recompute all history**. Had we stored only a final R, the bug would be permanent. This is the single most important test in the feature.

---

## 6. Legacy `trade_transactions` — LEAVE IT ALONE (decided 2026-07-25)

> ⚠️ **Read this before touching `trade_transactions` in any future session.**

**Decision: do nothing to it.** No migration, no deletion, no schema change. It keeps being written exactly as it is today (`server.py:175`) — that's a harmless dual-write and a safety net during cutover.

| Table | Role from now on |
|---|---|
| **`orders` + `fills`** | ✅ **the source of truth** for all metrics, round trips, and the D5 scorecard |
| `trade_transactions` | ⚪ legacy. Still written, **never read** by anything in this feature. Ignore it. |

**Three things a future session might be tempted to do — don't:**

1. ⛔ **Don't migrate it into `fills`.** An earlier draft specified converting the 9 non-zero-price rows. That was the bug: **6 of those 9 are byte-exact copies of the plan's `entry_limit_price`** (AAPL 271.21, APLD 35.47, FLR 49.25, QCOM 168.27, MARA 11.65, AAL 16.13) — **intents, not executions**. Converting them would manufacture data that feeds the go-live decision. The other 13 have `price = 0.0`.
2. ⛔ **Don't delete it (yet).** `save_transaction` is a live MCP tool declared in **both** the `monitor` and `trader` skills' `requires_tools`, with three `repository.py` methods (`:79`, `:93`, `:109`). Dropping the table means editing two skills and removing a tool — a real refactor, deliberately **not** in scope. Revisit only after the new path has captured a verified round trip.
3. ⛔ **Don't treat its 22 rows as history.** They are the *output* of the fill-capture bug, not a record of trading. The measurement clock starts at the first order after this feature ships.

**Principle:** a migration may **re-file** existing facts; it may never **manufacture** facts that were not recorded.

---

## 7. Runtime flow

```
place_order()  → INSERT orders (intent, gate verdict, regime, mode)
                       │
sync_fills()           → get_account_activities(FILL, cursor)  → INSERT fills   ← per-execution, append-only
sync_orders_terminal() → get_order(id)  [status ONLY]          → set terminal_status
                       │                  (cancelled/rejected/expired never appear in the FILL feed)
rebuild_round_trips()  → recompute cache
                       │
v_performance_current  → always-live metrics ─┐
                                              ├→ get_go_live_scorecard()  (D5 ladder)
performance_metrics    → EOD snapshot row ────┘
```

⚠️ **`get_order()` is NEVER the fill source** — it returns *cumulative* `filled_qty`/`filled_avg_price`, so appending across polls double-counts (50 filled, then 100 ⇒ 150). Fills come only from the Activities feed, where `qty` is per-execution and each row carries a stable broker id. See §4a.

**Broker interface additions** — `BrokerAdapter` currently has **neither** method (verified). Add:

```python
@abstractmethod
def get_order(self, broker_order_id: str) -> dict:
    """→ {broker_order_id, status, fills:[{qty, price, commission, fees, filled_at}], ...}"""
```

Canonical status map: `pending` / `partially_filled` (non-terminal) · `filled` / `cancelled` / `rejected` / `expired` (terminal). Reconciliation only ever moves an order **non-terminal → terminal**, and only ever **INSERTs** fills.

**Fail-safe:** reconciliation catches its own exceptions and logs; it must **never** block or alter order placement. MCP tools return JSON errors, never raise.

---

## 8. Honest-data rules

1. Unrecoverable history is **labelled and structurally excluded** (no fills ⇒ no round trip).
2. `fees_estimated` flag whenever the broker reported no fees — D7's "net of costs" can never be silently overstated.
3. Exclusions are **always reported** (`r_excluded` in the view, surfaced in the scorecard). A shrinking denominator must be visible.
4. `mode` is on every row; paper and live are never mixed.
5. Missing → `NULL` + reason. **`0.0` is a lie** — that is what survived 22 rows.

---

## 9. Verification (per BUILD-PLAN §4.5)

**Deterministic — unit tested:**
- **Rebuild invariant** (⭐): build → mutate cache → rebuild ⇒ identical. Rebuild is idempotent.
- Round-trip builder: simple pair · partial fills · scale-out · **FLR flip case ⇒ exactly 2 trips** · open position ⇒ no row.
- R math: hand-computed long (exact), short, missing stop ⇒ NULL+reason, denominator ≤ 0 ⇒ NULL+reason.
- Slippage sign for buy and sell.
- Fills are append-only: no code path UPDATEs `fills`.
- Reconciliation idempotency: run twice ⇒ no duplicate fills.
- View: paper/live isolation; `r_excluded` correct; empty set ⇒ no crash.
- Migration: 22 rows ⇒ 22 orders + 9 fills + 13 `unknown_historical`, contributing 0 to metrics.

**Judgment — none.** That is the point: this feature is the instrument that makes judgment measurable.

**Integration proof:** a paper order → reconcile → a `round_trips` row with a **real non-zero** fill price. That single pass is the proof the bug is dead.
