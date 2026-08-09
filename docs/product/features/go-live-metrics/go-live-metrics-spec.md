# Spec: Go-Live Metrics (Trade-Outcome Capture)

- **Slug:** `go-live-metrics`
- **Status:** `spec`
- **Priority:** `P0` — blocks ALL evidence (D5 go-live, D7 edge validation)
- **Owner sign-off:** ☑ approved 2026-07-25 (ratified in BUILD-PLAN §2, D5)
- **Layer(s):** 6 Audit (writes), 4 Action (fill write-back at the order path)
- **Author:** Claude Code · **Date:** 2026-07-25

## Problem

**We cannot measure a single thing about our own trading, and the counter is not running.**

Verified by direct audit of `tools/trading.db` (2026-07-25):

| Check | Result |
|---|---|
| `trade_transactions` rows | 22 |
| Rows with `price = 0.0` (no fill price) | **13 of 22** |
| plan_ids with both entry + exit | 7 |
| **…of those, R-computable** | **1** |
| `performance_metrics` / `journal_entries` / `portfolio_snapshots` | **0 rows each** |

**Root cause (exact, in code):** `place_order()` (`tools/server.py:146-182`) saves the transaction **at submit time**:

```python
tx = with_retry(broker.place_order, _retry_config)(...)   # server.py:169
tx.plan_id = plan_id
if plan_id:
    get_repo().save_transaction(tx)                        # server.py:175  ← written ONCE, never updated
```

At submit time Alpaca returns `filled_avg_price = None`, and `alpaca.py:110` maps that to `price=0.0`:

```python
price=float(order.filled_avg_price) if order.filled_avg_price else 0.0,   # alpaca.py:110
```

So the row is an **order acknowledgement** (`status` = `pending_new`/`accepted`), not a fill — and **nothing ever revisits it.** Compounding this, `BrokerAdapter` (`tools/broker/adapter.py`) has **no `get_order`/order-status method at all**, so there is currently no mechanism to re-check an order's outcome.

Three further gaps:
- `TradeTransaction` (`tools/models.py:74-84`) has **no** `filled_qty`, `filled_avg_price`, `filled_at`, or **commission/fees** fields.
- **No round-trip identity** — entries/exits group only by `plan_id`, which is ambiguous in practice (FLR on one plan_id: buy 311 → sell 311 → sell 267 → buy 267).
- **Nothing populates `performance_metrics`** (schema exists, `db.py:49`; 0 rows).

**Why it matters:** paper trading currently produces **zero usable evidence**. D5 (go-live) requires ≥100 closed trades with positive expectancy in R; D7 requires results **net of costs**. Both are unmeasurable today, and **this cannot be reconstructed retroactively** — an unrecorded fill price is lost forever. Every week unfixed is a week of trading that cannot count.

## Goal

Every order that fills is recorded with its **actual fill price, quantity, time, and fees**; every closed position is reduced to a **round-trip trade with an R-multiple**; and a **scorecard** reports progress against the D5 go-live ladder on demand. After this ships, the evidence clock runs by itself.

## User / System Value

- **Operability:** we can answer "does this system make money?" with data instead of belief.
- **Capital preservation:** D5 gates real money behind measured expectancy; without this the gate is unenforceable and go-live becomes a guess.
- **Edge validation:** D7 requires net-of-cost results — impossible without fee capture.
- **Compounding:** every later feature (scanner rebuild, strategy families) is judged by these metrics. Fix the ruler before measuring anything.

## Scope

**In scope** *(architecture revised 2026-07-25 → three layers; see `design.md` rev 2)*
- **Split intent from reality:** new `orders` table (intent, incl. `intended_price` for slippage) + new **`fills`** table (reality, append-only, one row per execution). This replaces extending the conflated `trade_transactions`.
- `BrokerAdapter.get_order(broker_order_id)` + implementations (`alpaca.py`, `simulation.py`) — the missing primitive.
- **Fill reconciliation** — poll non-terminal orders, INSERT fills, set terminal status.
- **Round-trip construction** — `round_trips` as a **rebuildable cache** (running-position FIFO) with realized net P&L, **R-multiple** (plan's stop as recorded at entry) and **slippage**.
- **`v_performance_current` VIEW** (cannot go stale); `performance_metrics` repurposed as an EOD snapshot log with `expectancy_r`.
- **`get_go_live_scorecard()`** MCP tool — D5 ladder progress.
- **Honest migration** of the existing 22 rows: 9 → fills, 13 → `unknown_historical` with no fill (structurally excluded from metrics).

**Out of scope / non-goals**
- NOT the governance gate (separate feature).
- NOT the backtest engine's benchmark arms (D7's other half).
- NOT changing any trading/strategy logic — this feature is **observation only** and must not alter a single trading decision.
- NOT a dashboard/UI — one MCP tool + the EOD report is enough.

## Acceptance Criteria

1. `BrokerAdapter.get_order(id)` exists, is implemented by `alpaca.py` and `simulation.py`, and returns a consistent dict (status, filled_qty, filled_avg_price, filled_at, fees).
2. After an order fills, its `trade_transactions` row has a **non-zero** `filled_avg_price` and a `filled_at` timestamp; `status` is terminal (`filled`/`partially_filled`/`cancelled`/`rejected`/`expired`).
3. Reconciliation is **idempotent** — running it twice produces no duplicate/conflicting rows.
4. A closed position yields exactly one `round_trips` row with entry price, exit price, initial stop, realized P&L (net of fees), and `r_multiple`.
5. `r_multiple` = (exit − entry) ÷ (entry − initial_stop) for longs, verified by unit test incl. a hand-computed example.
6. `performance_metrics` is populated by the EOD job with `total_trades`, `win_rate`, `expectancy_r`, `profit_factor`, `max_drawdown`.
7. `get_go_live_scorecard()` returns each D5 criterion with current value + pass/fail (e.g. `trades 1/100`, `expectancy +0.10R`, `gate ✅`).
8. The 13 historically-unrecoverable rows are labelled and **excluded** from metrics, never silently counted as zero-price trades.
9. All existing tests stay green; **no trading decision changes** as a result of this feature.

## Risks & Safety Impact

- **Kill switch / circuit breakers / sizing / R:R:** untouched. This feature only *reads* the broker and *writes* audit records.
- **Main risk — a write-back bug corrupting good data.** Mitigation: reconciliation only ever transitions a transaction from **non-terminal → terminal**; a terminal row is never rewritten (append-only in spirit).
- **Second risk — miscomputed R silently producing wrong go-live evidence.** Mitigation: R is computed *only* when entry, exit, and the plan's initial stop are all present; otherwise the round-trip is marked `r_uncomputable` and excluded. **Never estimate a missing stop.**
- **Partial fills** could double-count. Mitigation: round-trip construction works from *filled quantity*, and quantity must net to zero to close.
- **Fail-safe:** if reconciliation fails, orders still execute normally — this path must never block trading. Errors are logged, not raised.

## Open Decisions

- **D-A: Reconciliation trigger** — poll on a schedule vs. broker fill stream. *(Recommend: **poll** — simplest, no new infra, runs in the existing monitor/EOD cadence; a stream can replace it later behind the same interface.)*
- **D-B: Sample floor for D5** — 100 vs 200 closed trades. *(Recommend: **100** to start reporting, flag 200 as "convincing" in the scorecard — report both rather than picking one.)*
- **D-C: Backtest trades in the same table?** *(Recommend: **no** — keep `round_trips` for live/paper only; backtest keeps `backtest_trades`. Mixing them would contaminate the go-live sample. The scorecard may show them side by side, never summed.)*

## References

- `docs/product/BUILD-PLAN.md` §2 (D5, D7), "Go-live measurement" section, §4.5 verification strategy
- `PROJECT_STATUS.md` — 🔴 CRITICAL known bug (fill write-back), logged 2026-07-25
- Code: `tools/server.py:146-182` (`place_order`), `tools/broker/alpaca.py:110`, `tools/models.py:74-84`, `tools/persistence/db.py:25` (`trade_transactions`), `:49` (`performance_metrics`), `tools/persistence/repository.py:79-109`
- Vault: `[[2026-07-25-Direction-Validation-Research]]` (why measurement is the gate), `[[Tharp Insights]]` (expectancy per R as the metric)
