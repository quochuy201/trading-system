# Options MCP Tooling — Phase 2 Design

**Date:** 2026-06-02  
**Status:** Spec  
**Depends on:** Phase 1 (merged — `sops/options-vol-edge/v1.0.0.md`, skill updates)  
**Goal:** Make the vol-edge SOP executable on Alpaca paper by building the options MCP tools, broker adapter methods, and analysis functions.

---

## Scope

Build the tooling layer that lets agents call `get_options_chain`, `get_options_market_data`, `calc_iv_rank`, `calc_hv`, `get_put_skew`, `calc_expected_move`, `get_options_positions`, and `place_multileg_order`. These tool names are already referenced by the skills and SOP — they must match exactly.

**Out of scope (Phase 3/4):** Paper-trade validation, options journal fields in EOD, options backtest simulation adapter.

---

## Architecture

### Where new code goes

| File | Change | Responsibility |
|------|--------|----------------|
| `broker/adapter.py` | +5 abstract methods | Options interface contract |
| `broker/alpaca.py` | +5 implementations | Alpaca SDK calls (OptionHistoricalDataClient, multi-leg orders) |
| `broker/simulation.py` | +5 stubs (raise NotImplementedError) | Placeholder for Phase 4 backtest |
| `analysis/options.py` | NEW file | Pure calculation functions (IV rank, HV, skew, expected move) |
| `server.py` | +8 MCP tool functions | Thin wrappers: broker call → analysis → JSON response |
| `tests/test_options.py` | NEW file | Unit tests for analysis + adapter + MCP tools |

### Design principles

1. **`server.py` stays thin** — already 1723 lines. New tools are ~15-25 lines each: validate input, call broker/analysis, return JSON. No business logic in server.py.
2. **`analysis/options.py` is pure** — takes data in, returns data out. No broker calls, no side effects. Easily testable.
3. **Broker adapter is the boundary** — all Alpaca SDK usage lives in `broker/alpaca.py`. The abstract interface returns plain dicts/lists. Same shapes whether live or simulation.
4. **Only `place_multileg_order` mutates** — it logs to ledger, checks kill switch, uses `with_retry`. All other tools are read-only.

---

## Broker Adapter — New Abstract Methods

```python
# broker/adapter.py additions

@abstractmethod
def get_option_chain(
    self,
    underlying: str,
    expiration_date_gte: str | None = None,
    expiration_date_lte: str | None = None,
    strike_price_gte: float | None = None,
    strike_price_lte: float | None = None,
    option_type: str | None = None,  # "call" | "put" | None (both)
) -> list[dict]:
    """Fetch option chain with greeks+IV for an underlying symbol."""
    ...

@abstractmethod
def get_option_snapshot(self, option_symbols: list[str]) -> list[dict]:
    """Fetch real-time snapshot (quote + greeks + IV) for specific option contracts."""
    ...

@abstractmethod
def get_option_historical_iv(
    self, underlying: str, lookback_days: int = 252
) -> list[dict]:
    """Fetch historical IV data points for IV Rank calculation.
    Returns list of {"date": "YYYY-MM-DD", "iv": float} sorted ascending."""
    ...

@abstractmethod
def get_options_positions(self) -> list[dict]:
    """Get all open option positions (filtered from all positions by asset class)."""
    ...

@abstractmethod
def place_multileg_order(
    self,
    legs: list[dict],
    order_type: str,
    limit_price: float | None = None,
    duration: str = "day",
) -> TradeTransaction:
    """Place a multi-leg option order (spreads). Each leg: {symbol, side, ratio_qty}.
    side values: buy_to_open, buy_to_close, sell_to_open, sell_to_close."""
    ...
```

---

## Alpaca Implementation Details

### `AlpacaBrokerAdapter.get_option_chain`

Uses `OptionHistoricalDataClient.get_option_chain(OptionChainRequest(...))`.

The chain response is a dict keyed by option symbol → `OptionsSnapshot`. Each snapshot has:
- `latest_quote` (bid/ask)
- `implied_volatility` (float)
- `greeks` (OptionsGreeks: delta, gamma, theta, vega, rho)

We flatten this into our standard dict shape (see Data Shapes below).

**Filtering:** `OptionChainRequest` supports `expiration_date_gte/lte`, `strike_price_gte/lte`, `type` (ContractType.CALL/PUT). We pass through MCP tool params directly.

**Contract metadata** (strike, expiration, type) is parsed from the OCC symbol format:
`{ROOT}{YYMMDD}{C|P}{strike*1000}` → e.g., `AAPL250620C00230000` = AAPL, 2025-06-20, call, $230.

### `AlpacaBrokerAdapter.get_option_snapshot`

Uses `OptionHistoricalDataClient.get_option_snapshot(OptionSnapshotRequest(symbol_or_symbols=[...]))`.

Returns the same shape as chain entries but for specific contracts (useful for monitoring open positions).

### `AlpacaBrokerAdapter.get_option_historical_iv`

Strategy: Fetch daily snapshots for ATM options over the lookback period.

Implementation:
1. Get current stock price to determine ATM strike.
2. Use `get_option_bars` with daily timeframe for a near-ATM option over `lookback_days`.
3. Alternatively: use `OptionHistoricalDataClient.get_option_chain` with a historical date range — the chain endpoint returns IV per snapshot date.

**Practical approach:** The `get_option_chain` endpoint returns snapshots with IV per contract. On each call, we extract aggregate ATM IV (average of nearest ATM call+put IV) and cache it in SQLite with date key. Over time, the cache fills organically.

For cold-start bootstrap: query `get_option_chain` for historical dates is not supported (it's a real-time endpoint). Instead, we use `get_option_bars` (OHLCV only, no IV) to get option price history, then **derive IV via Black-Scholes inversion** from the option close price + underlying close price + known strike/DTE/rate. This gives approximate historical IV suitable for ranking.

For symbols with <60 days of cached/derived data, the MCP tool returns an error indicating insufficient history.

Cache schema:
```sql
CREATE TABLE IF NOT EXISTS iv_history (
    symbol TEXT NOT NULL,       -- underlying symbol
    date TEXT NOT NULL,         -- YYYY-MM-DD
    iv REAL NOT NULL,           -- aggregate ATM implied volatility
    source TEXT NOT NULL,       -- "snapshot" (live) or "derived" (Black-Scholes inversion)
    PRIMARY KEY (symbol, date)
);
```

### `AlpacaBrokerAdapter.get_options_positions`

Uses `TradingClient.get_all_positions()` filtered by `asset_class == "us_option"`.

Returns option-specific fields: symbol, quantity, side, entry_price, current_price, unrealized_pnl, plus parsed contract details (underlying, strike, expiration, type).

### `AlpacaBrokerAdapter.place_multileg_order`

Uses `TradingClient.submit_order` with:
```python
OrderRequest(
    order_class=OrderClass.MLEG,
    type=OrderType.LIMIT,
    time_in_force=TimeInForce.DAY,
    limit_price=limit_price,
    legs=[
        OptionLegRequest(
            symbol=leg["symbol"],
            ratio_qty=leg["ratio_qty"],
            side=OrderSide(leg["side"]),  # or PositionIntent mapping
            position_intent=PositionIntent(leg["side"]),
        )
        for leg in legs
    ],
)
```

Note: `OptionLegRequest` uses `position_intent` (buy_to_open, sell_to_open, etc.) rather than simple `side`. The MCP tool accepts the `position_intent` values directly as the `side` field for clarity.

---

## Analysis Module — `analysis/options.py`

All functions are pure (data in → result out). No broker calls.

### `calc_iv_rank(current_iv: float, iv_history: list[float]) -> float`

```
IVR = (current_iv - min(history)) / (max(history) - min(history)) × 100
```

Returns 0–100. If history has <2 distinct values, returns 50.0 (neutral — insufficient data).

### `calc_hv(closes: list[float], window: int = 20) -> float`

20-day realized (historical) volatility from daily close prices. Annualized.

```
daily_returns = [ln(closes[i] / closes[i-1]) for i in range(1, len(closes))]
hv = std(daily_returns[-window:]) × √252
```

Returns annualized HV as a decimal (e.g., 0.35 = 35%).

### `calc_put_skew(chain: list[dict], target_delta: float = 0.25) -> float`

Put skew = IV of OTM put at ~target_delta / IV of OTM call at ~target_delta.

Finds the put closest to -target_delta and call closest to +target_delta from the chain, returns the ratio. >1.0 = puts are expensive (bearish skew). <1.0 = calls expensive.

### `calc_expected_move(stock_price: float, iv: float, dte: int) -> float`

```
expected_move = stock_price × iv × √(dte / 365)
```

Returns the dollar amount of the one-standard-deviation expected move.

### `implied_vol_from_price(option_price: float, stock_price: float, strike: float, dte: int, rate: float, option_type: str) -> float`

Black-Scholes inversion via Newton-Raphson (bisection fallback). Used internally by `get_option_historical_iv` to derive IV from historical option bars when live snapshots aren't available.

Returns annualized IV as decimal. Returns `NaN` if convergence fails (option price outside intrinsic bounds).

---

## MCP Tools — Signatures and Behavior

### `get_options_chain(underlying, expiration_gte, expiration_lte, strike_gte, strike_lte, option_type)`

- **When to use:** Research/Trader agent evaluating available contracts for a candidate.
- **Returns:** List of contracts with bid/ask/mid/volume/OI/IV/greeks.
- **Errors:** `{"error": "No contracts found for {underlying} with given filters"}`

### `get_options_market_data(option_symbols: str)`

- **Input:** Comma-separated option symbols (e.g., `"AAPL250620C00230000,AAPL250620P00220000"`).
- **When to use:** Monitor agent checking greeks/IV on open positions; Trader agent verifying spread pricing before order.
- **Returns:** List of snapshots with quote + IV + greeks.
- **Errors:** `{"error": "No data for symbols: ..."}`

### `get_options_positions()`

- **When to use:** Monitor agent's 15:30 ET exit loop checking open option positions.
- **Returns:** List of positions with underlying, strike, expiration, type, qty, entry_price, current_price, unrealized_pnl, greeks.
- **Errors:** Returns empty list `[]` if no option positions.

### `calc_iv_rank(symbol: str)`

- **When to use:** Research agent Phase 1 vol routing (IVR > 75 → sell premium, IVR < 25 → buy premium).
- **Behavior:** Fetches current IV from option snapshot + historical IV from cache. Calls `analysis.options.calc_iv_rank`.
- **Returns:** `{"symbol": "AAPL", "iv_rank": 82.3, "current_iv": 0.38, "iv_high_52w": 0.45, "iv_low_52w": 0.22, "data_points": 180}`
- **Errors:** `{"error": "Insufficient IV history for {symbol} (need ≥60 days, have {n})"}`

### `calc_hv(symbol: str, window: int = 20)`

- **When to use:** Research agent comparing IV to HV (SOP soft gate `SOFT_IVHV_CONFIRM`: IV/HV > 1.2 confirms rich vol).
- **Behavior:** Fetches 252 daily closes from broker, calls `analysis.options.calc_hv`.
- **Returns:** `{"symbol": "AAPL", "hv20": 0.28, "window": 20, "period_days": 252}`
- **Errors:** `{"error": "Insufficient price history for {symbol}"}`

### `get_put_skew(symbol: str, expiration: str, target_delta: float = 0.25)`

- **When to use:** Research agent soft gate `SOFT_PUTSKEW` — skew > 1.15 adds conviction to bull put spreads.
- **Behavior:** Fetches chain for the given expiration, calls `analysis.options.calc_put_skew`.
- **Returns:** `{"symbol": "AAPL", "expiration": "2025-06-20", "put_skew": 1.18, "put_iv": 0.34, "call_iv": 0.29, "target_delta": 0.25}`
- **Errors:** `{"error": "Cannot compute skew — insufficient contracts at target delta"}`

### `calc_expected_move(symbol: str, dte: int)`

- **When to use:** Trader agent Step O-2 strike selection — debit vertical short leg placed ~1 expected move OTM.
- **Behavior:** Fetches current stock price + ATM IV, calls `analysis.options.calc_expected_move`.
- **Returns:** `{"symbol": "AAPL", "expected_move": 8.45, "stock_price": 230.0, "iv": 0.32, "dte": 30}`
- **Errors:** `{"error": "Cannot get IV for {symbol}"}`

### `place_multileg_order(legs: str, order_type: str, limit_price: float | None, plan_id: str)`

- **Input:** `legs` is a JSON string: `[{"symbol": "...", "side": "sell_to_open", "ratio_qty": 1}, ...]`
- **Kill switch:** Checked before placement. Returns `{"error": "Kill switch is active", ...}` if active.
- **Ledger:** Logs action="multileg_entry" or "multileg_exit" with all leg details.
- **Retry:** Uses `with_retry` on the broker call.
- **Returns:** Transaction dict with order_id, status, legs, fill details.
- **Errors:** `{"error": "Order rejected: {reason}"}`, `{"error": "Kill switch is active", "reason": "..."}`

---

## Data Shapes

### Option chain entry (returned by `get_options_chain` and `get_options_market_data`)

```json
{
  "symbol": "AAPL250620C00230000",
  "underlying": "AAPL",
  "strike": 230.0,
  "type": "call",
  "expiration": "2025-06-20",
  "dte": 18,
  "bid": 3.40,
  "ask": 3.60,
  "mid": 3.50,
  "volume": 1200,
  "open_interest": 5400,
  "iv": 0.32,
  "greeks": {
    "delta": 0.45,
    "gamma": 0.03,
    "theta": -0.08,
    "vega": 0.15,
    "rho": 0.01
  }
}
```

### Option position (returned by `get_options_positions`)

```json
{
  "symbol": "AAPL250620P00220000",
  "underlying": "AAPL",
  "strike": 220.0,
  "type": "put",
  "expiration": "2025-06-20",
  "dte": 18,
  "quantity": -1,
  "side": "short",
  "entry_price": 2.15,
  "current_price": 1.80,
  "unrealized_pnl": 35.0,
  "unrealized_pnl_pct": 16.3,
  "iv": 0.30,
  "greeks": {
    "delta": -0.22,
    "gamma": 0.02,
    "theta": 0.05,
    "vega": -0.12,
    "rho": -0.005
  }
}
```

### Multi-leg order result (returned by `place_multileg_order`)

```json
{
  "transaction_id": "f8a2c1d3-...",
  "plan_id": "plan-opt-001",
  "order_class": "mleg",
  "order_type": "limit",
  "limit_price": 1.25,
  "status": "pending_new",
  "legs": [
    {"symbol": "AAPL250620P00220000", "side": "sell_to_open", "ratio_qty": 1},
    {"symbol": "AAPL250620P00215000", "side": "buy_to_open", "ratio_qty": 1}
  ],
  "broker_order_id": "f8a2c1d3-...",
  "timestamp": "2026-06-02T10:15:00+00:00"
}
```

---

## IV History Cache — Build Strategy

The `iv_history` SQLite table is populated opportunistically:

1. **On every `calc_iv_rank(symbol)` call:** After fetching the current ATM IV from snapshot, store today's data point (source="snapshot") if not already present.
2. **On every `get_options_chain(symbol)` call:** Extract aggregate ATM IV (avg of nearest ATM call + put IV), cache it (source="snapshot").
3. **Cold-start bootstrap:** First time a symbol is queried, if cache has <60 days:
   - Find the nearest ATM option contract (using current price + `get_option_contracts`).
   - Fetch 252 daily bars for that contract via `get_option_bars`.
   - Fetch corresponding stock daily bars.
   - Derive IV for each day via `implied_vol_from_price` (Black-Scholes inversion).
   - Store with source="derived". One-time cost per symbol (~2 API calls).

This means the cache self-fills over normal usage. Backtests (Phase 4) will pre-load the cache as part of data setup.

---

## Simulation Adapter Stubs

`broker/simulation.py` gets the 5 new methods as stubs:

```python
def get_option_chain(self, underlying, **kwargs) -> list[dict]:
    raise NotImplementedError("Options simulation requires Phase 4 implementation")

# ... same for the other 4 methods
```

Phase 4 will implement these using cached historical data + synthetic fill logic.

---

## OCC Symbol Parsing

Utility function in `analysis/options.py`:

```python
def parse_occ_symbol(symbol: str) -> dict:
    """Parse OCC option symbol into components.
    AAPL250620C00230000 → {underlying: AAPL, expiration: 2025-06-20, type: call, strike: 230.0}
    """
```

Used by `get_options_positions` to enrich position data with underlying/strike/expiration/type, and by other tools that need to extract contract metadata from Alpaca's raw symbol strings.

---

## Error Handling

All tools follow the existing pattern:
- Never raise exceptions to the agent.
- Return `{"error": "description"}` as JSON.
- Mutating tools (`place_multileg_order`) still log to ledger even on failure (with status="failed").
- Read-only tools use `with_retry` for transient network errors on broker calls.

---

## Testing Strategy

### Unit tests (`tests/test_options.py`)

**Analysis functions (pure, no mocking needed):**
- `calc_iv_rank`: normal case, edge cases (min=max, empty history, <2 values)
- `calc_hv`: known price series → known volatility
- `calc_put_skew`: synthetic chain with known deltas/IVs
- `calc_expected_move`: arithmetic verification
- `parse_occ_symbol`: various symbol formats, edge cases

**Broker adapter (mocked Alpaca SDK):**
- `get_option_chain`: mock `OptionHistoricalDataClient.get_option_chain`, verify output shape
- `get_option_snapshot`: mock snapshot response, verify greeks extraction
- `get_options_positions`: mock `get_all_positions` with option+equity mix, verify filtering
- `place_multileg_order`: mock `submit_order`, verify `OrderClass.MLEG` + leg construction
- `get_option_historical_iv`: mock `get_option_bars`, verify date/iv extraction

**MCP tool integration (mocked broker):**
- `place_multileg_order`: kill switch blocks order
- `place_multileg_order`: successful placement logs to ledger
- `calc_iv_rank`: insufficient history returns error dict
- All read tools: verify JSON output matches documented shapes

---

## Dependencies

- `alpaca-py >= 0.43.0` (already installed: 0.43.4) — provides `OptionHistoricalDataClient`, `OptionLegRequest`, `OrderClass.MLEG`, `PositionIntent`
- No new external dependencies required.

---

## Implementation Order

1. `analysis/options.py` — pure functions + `parse_occ_symbol` + `implied_vol_from_price` (BSM inversion)
2. `broker/adapter.py` — add 5 abstract methods
3. `broker/alpaca.py` — implement the 5 methods
4. `broker/simulation.py` — add stubs
5. `persistence/db.py` — add `iv_history` table creation
6. `server.py` — add 8 MCP tools
7. `tests/test_options.py` — full test coverage
8. Verify existing tests still pass (no regressions)
