# Options MCP Tooling — Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the 8 MCP tools that make the options vol-edge SOP executable on Alpaca paper trading.

**Architecture:** Pure analysis functions in `analysis/options.py` → broker adapter methods in `broker/alpaca.py` → thin MCP tool wrappers in `server.py`. Only `place_multileg_order` mutates state. IV history cached in SQLite.

**Tech Stack:** Python 3.12, alpaca-py 0.43.4, SQLite, FastMCP, pytest

**Spec:** `docs/specs/2026-06-02-options-mcp-tooling-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `tools/analysis/options.py` | CREATE | Pure functions: parse_occ_symbol, calc_iv_rank, calc_hv, calc_put_skew, calc_expected_move, implied_vol_from_price |
| `tools/broker/adapter.py` | MODIFY | +5 abstract methods for options |
| `tools/broker/alpaca.py` | MODIFY | +5 Alpaca SDK implementations + OptionHistoricalDataClient init |
| `tools/broker/simulation.py` | MODIFY | +5 NotImplementedError stubs |
| `tools/persistence/db.py` | MODIFY | +iv_history table in SCHEMA |
| `tools/persistence/repository.py` | MODIFY | +save_iv_data, +query_iv_history methods |
| `tools/server.py` | MODIFY | +8 MCP tool functions |
| `tools/tests/test_options.py` | CREATE | Full test coverage |

---

### Task 1: Analysis Module — Pure Functions

**Files:**
- Create: `tools/analysis/options.py`
- Test: `tools/tests/test_options.py`

- [ ] **Step 1: Create test file with analysis function tests**

```python
"""Tests for options analysis functions and MCP tools."""

import sys
import math
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from analysis.options import (
    parse_occ_symbol,
    calc_iv_rank,
    calc_hv,
    calc_put_skew,
    calc_expected_move,
    implied_vol_from_price,
)


class TestParseOccSymbol:
    def test_standard_symbol(self):
        result = parse_occ_symbol("AAPL250620C00230000")
        assert result == {
            "underlying": "AAPL",
            "expiration": "2025-06-20",
            "type": "call",
            "strike": 230.0,
        }

    def test_put_symbol(self):
        result = parse_occ_symbol("TSLA250718P00180000")
        assert result == {
            "underlying": "TSLA",
            "expiration": "2025-07-18",
            "type": "put",
            "strike": 180.0,
        }

    def test_single_char_root(self):
        result = parse_occ_symbol("F250620C00012500")
        assert result == {
            "underlying": "F",
            "expiration": "2025-06-20",
            "type": "call",
            "strike": 12.5,
        }

    def test_five_char_root(self):
        result = parse_occ_symbol("GOOGL250620P00175000")
        assert result == {
            "underlying": "GOOGL",
            "expiration": "2025-06-20",
            "type": "put",
            "strike": 175.0,
        }

    def test_fractional_strike(self):
        result = parse_occ_symbol("SPY250620C00543500")
        assert result == {
            "underlying": "SPY",
            "expiration": "2025-06-20",
            "type": "call",
            "strike": 543.5,
        }


class TestCalcIvRank:
    def test_normal_case(self):
        # current=30, min=20, max=40 → (30-20)/(40-20) = 50%
        result = calc_iv_rank(0.30, [0.20, 0.25, 0.30, 0.35, 0.40])
        assert result == 50.0

    def test_at_high(self):
        result = calc_iv_rank(0.40, [0.20, 0.25, 0.30, 0.35, 0.40])
        assert result == 100.0

    def test_at_low(self):
        result = calc_iv_rank(0.20, [0.20, 0.25, 0.30, 0.35, 0.40])
        assert result == 0.0

    def test_above_historical_high(self):
        # current IV above all history → capped at 100
        result = calc_iv_rank(0.50, [0.20, 0.25, 0.30, 0.35, 0.40])
        assert result == 100.0

    def test_below_historical_low(self):
        result = calc_iv_rank(0.10, [0.20, 0.25, 0.30, 0.35, 0.40])
        assert result == 0.0

    def test_insufficient_data(self):
        # All same value → can't compute rank
        result = calc_iv_rank(0.30, [0.30, 0.30, 0.30])
        assert result == 50.0

    def test_empty_history(self):
        result = calc_iv_rank(0.30, [])
        assert result == 50.0


class TestCalcHv:
    def test_known_series(self):
        # 21 closes with known daily returns
        # If all daily returns are 1% → daily std ≈ 0, but let's use a real series
        import math
        # Generate prices: start at 100, alternating +1%, -1%
        closes = [100.0]
        for i in range(251):
            if i % 2 == 0:
                closes.append(closes[-1] * 1.01)
            else:
                closes.append(closes[-1] * 0.99)
        result = calc_hv(closes, window=20)
        # Daily std of alternating +1%/-1% ≈ 0.01, annualized ≈ 0.01 * sqrt(252) ≈ 0.159
        assert 0.14 < result < 0.17

    def test_constant_prices(self):
        closes = [100.0] * 30
        result = calc_hv(closes, window=20)
        assert result == 0.0

    def test_insufficient_data(self):
        # Need at least window+1 closes
        result = calc_hv([100.0, 101.0], window=20)
        assert math.isnan(result)


class TestCalcPutSkew:
    def test_normal_skew(self):
        chain = [
            {"type": "put", "greeks": {"delta": -0.25}, "iv": 0.35},
            {"type": "put", "greeks": {"delta": -0.50}, "iv": 0.30},
            {"type": "call", "greeks": {"delta": 0.25}, "iv": 0.28},
            {"type": "call", "greeks": {"delta": 0.50}, "iv": 0.30},
        ]
        result = calc_put_skew(chain, target_delta=0.25)
        # put IV at -0.25 delta = 0.35, call IV at 0.25 delta = 0.28
        assert abs(result - (0.35 / 0.28)) < 0.01

    def test_no_matching_delta(self):
        chain = [
            {"type": "put", "greeks": {"delta": -0.10}, "iv": 0.40},
            {"type": "call", "greeks": {"delta": 0.90}, "iv": 0.25},
        ]
        result = calc_put_skew(chain, target_delta=0.25)
        assert math.isnan(result)

    def test_empty_chain(self):
        result = calc_put_skew([], target_delta=0.25)
        assert math.isnan(result)


class TestCalcExpectedMove:
    def test_basic(self):
        # price=100, iv=0.32, dte=30
        # expected_move = 100 * 0.32 * sqrt(30/365) ≈ 9.17
        result = calc_expected_move(100.0, 0.32, 30)
        assert abs(result - 9.17) < 0.1

    def test_zero_dte(self):
        result = calc_expected_move(100.0, 0.32, 0)
        assert result == 0.0


class TestImpliedVolFromPrice:
    def test_atm_call(self):
        # ATM call: stock=100, strike=100, dte=30, rate=0.05
        # With IV=0.30, BS price ≈ 3.45. We verify roundtrip.
        from analysis.options import black_scholes_price
        price = black_scholes_price(100.0, 100.0, 30, 0.05, 0.30, "call")
        recovered_iv = implied_vol_from_price(price, 100.0, 100.0, 30, 0.05, "call")
        assert abs(recovered_iv - 0.30) < 0.001

    def test_otm_put(self):
        from analysis.options import black_scholes_price
        price = black_scholes_price(100.0, 90.0, 45, 0.05, 0.25, "put")
        recovered_iv = implied_vol_from_price(price, 100.0, 90.0, 45, 0.05, "put")
        assert abs(recovered_iv - 0.25) < 0.001

    def test_invalid_price_returns_nan(self):
        # Price below intrinsic → can't solve
        result = implied_vol_from_price(0.001, 100.0, 50.0, 30, 0.05, "call")
        assert math.isnan(result)
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `cd tools && uv run --extra dev pytest tests/test_options.py -v`
Expected: ImportError — `analysis.options` does not exist yet.

- [ ] **Step 3: Implement `analysis/options.py`**

```python
"""Options analysis — pure calculation functions.

No broker calls, no side effects. All functions take data in and return results.
"""

import math
from datetime import datetime, date


def parse_occ_symbol(symbol: str) -> dict:
    """Parse OCC option symbol into components.

    OCC format: {ROOT}{YYMMDD}{C|P}{strike*1000 zero-padded to 8 digits}
    Suffix is always 15 chars (6 date + 1 type + 8 strike). Root = everything before.
    """
    suffix = symbol[-15:]
    underlying = symbol[:-15]
    date_str = suffix[:6]
    option_type = "call" if suffix[6] == "C" else "put"
    strike = int(suffix[7:]) / 1000.0
    expiration = f"20{date_str[:2]}-{date_str[2:4]}-{date_str[4:6]}"
    return {
        "underlying": underlying,
        "expiration": expiration,
        "type": option_type,
        "strike": strike,
    }


def calc_iv_rank(current_iv: float, iv_history: list[float]) -> float:
    """IV Rank: where current IV sits relative to its historical range.

    Returns 0-100. Returns 50.0 if history is insufficient or has no range.
    """
    if len(iv_history) < 2:
        return 50.0
    iv_min = min(iv_history)
    iv_max = max(iv_history)
    if iv_max == iv_min:
        return 50.0
    rank = (current_iv - iv_min) / (iv_max - iv_min) * 100
    return max(0.0, min(100.0, rank))


def calc_hv(closes: list[float], window: int = 20) -> float:
    """Historical volatility from daily closes, annualized.

    Returns annualized HV as decimal (0.35 = 35%).
    Returns NaN if insufficient data (need at least window+1 closes).
    """
    if len(closes) < window + 1:
        return float("nan")
    returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    recent = returns[-window:]
    if not recent:
        return 0.0
    mean = sum(recent) / len(recent)
    variance = sum((r - mean) ** 2 for r in recent) / (len(recent) - 1)
    daily_std = math.sqrt(variance)
    return daily_std * math.sqrt(252)


def calc_put_skew(chain: list[dict], target_delta: float = 0.25) -> float:
    """Put/call IV skew at a target delta.

    Returns ratio: put_iv / call_iv. >1.0 = bearish skew.
    Returns NaN if matching contracts not found (delta tolerance: ±0.10).
    """
    if not chain:
        return float("nan")

    tolerance = 0.10
    best_put = None
    best_put_dist = float("inf")
    best_call = None
    best_call_dist = float("inf")

    for c in chain:
        delta = c.get("greeks", {}).get("delta", 0)
        iv = c.get("iv", 0)
        if not iv or iv <= 0:
            continue

        if c["type"] == "put":
            dist = abs(abs(delta) - target_delta)
            if dist < best_put_dist and dist <= tolerance:
                best_put = c
                best_put_dist = dist
        elif c["type"] == "call":
            dist = abs(delta - target_delta)
            if dist < best_call_dist and dist <= tolerance:
                best_call = c
                best_call_dist = dist

    if best_put is None or best_call is None:
        return float("nan")

    call_iv = best_call["iv"]
    if call_iv <= 0:
        return float("nan")
    return best_put["iv"] / call_iv


def calc_expected_move(stock_price: float, iv: float, dte: int) -> float:
    """One-standard-deviation expected move in dollar terms.

    expected_move = stock_price × iv × √(dte / 365)
    """
    if dte <= 0:
        return 0.0
    return stock_price * iv * math.sqrt(dte / 365)


def black_scholes_price(
    stock: float, strike: float, dte: int, rate: float, vol: float, option_type: str
) -> float:
    """Black-Scholes European option price."""
    if dte <= 0 or vol <= 0:
        # At expiration, return intrinsic
        if option_type == "call":
            return max(0.0, stock - strike)
        return max(0.0, strike - stock)

    t = dte / 365.0
    d1 = (math.log(stock / strike) + (rate + 0.5 * vol ** 2) * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)

    if option_type == "call":
        return stock * _norm_cdf(d1) - strike * math.exp(-rate * t) * _norm_cdf(d2)
    else:
        return strike * math.exp(-rate * t) * _norm_cdf(-d2) - stock * _norm_cdf(-d1)


def implied_vol_from_price(
    option_price: float,
    stock_price: float,
    strike: float,
    dte: int,
    rate: float,
    option_type: str,
) -> float:
    """Recover implied volatility from option price via bisection.

    Returns annualized IV as decimal. Returns NaN if convergence fails.
    """
    if option_price <= 0 or dte <= 0:
        return float("nan")

    # Check intrinsic bounds
    if option_type == "call":
        intrinsic = max(0.0, stock_price - strike)
    else:
        intrinsic = max(0.0, strike - stock_price)
    if option_price < intrinsic * 0.99:
        return float("nan")

    low, high = 0.01, 5.0
    for _ in range(100):
        mid = (low + high) / 2
        price = black_scholes_price(stock_price, strike, dte, rate, mid, option_type)
        if abs(price - option_price) < 0.001:
            return mid
        if price < option_price:
            low = mid
        else:
            high = mid

    return float("nan")


def _norm_cdf(x: float) -> float:
    """Standard normal CDF approximation."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools && uv run --extra dev pytest tests/test_options.py -v`
Expected: All tests in TestParseOccSymbol, TestCalcIvRank, TestCalcHv, TestCalcPutSkew, TestCalcExpectedMove, TestImpliedVolFromPrice PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/analysis/options.py tools/tests/test_options.py
git commit -m "feat(options): add analysis module with pure calculation functions

parse_occ_symbol, calc_iv_rank, calc_hv, calc_put_skew,
calc_expected_move, implied_vol_from_price (BSM bisection)"
```

---

### Task 2: Broker Adapter — Abstract Methods

**Files:**
- Modify: `tools/broker/adapter.py`

- [ ] **Step 1: Add the 5 abstract methods to `BrokerAdapter`**

Add at the end of the class (after `get_tradeable_universe`):

```python
    @abstractmethod
    def get_option_chain(
        self,
        underlying: str,
        expiration_date_gte: str | None = None,
        expiration_date_lte: str | None = None,
        strike_price_gte: float | None = None,
        strike_price_lte: float | None = None,
        option_type: str | None = None,
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
        """Get all open option positions (filtered by asset class)."""
        ...

    @abstractmethod
    def place_multileg_order(
        self,
        legs: list[dict],
        order_type: str,
        limit_price: float | None = None,
        time_in_force: str = "day",
    ) -> "TradeTransaction":
        """Place a multi-leg option order (spreads). Each leg: {symbol, side, ratio_qty}.
        side values: buy_to_open, buy_to_close, sell_to_open, sell_to_close."""
        ...
```

- [ ] **Step 2: Update FakeBroker in test_broker.py to implement new methods**

The existing `TestBrokerAdapterABC.test_concrete_implementation` test creates a `FakeBroker` subclass. It will fail because the new abstract methods aren't implemented. Add stub implementations inside that test's `FakeBroker`:

```python
            def get_option_chain(self, underlying, **kwargs):
                return []

            def get_option_snapshot(self, option_symbols):
                return []

            def get_option_historical_iv(self, underlying, lookback_days=252):
                return []

            def get_options_positions(self):
                return []

            def place_multileg_order(self, legs, order_type, **kwargs):
                return TradeTransaction(symbol="TEST", side="buy", quantity=1)
```

- [ ] **Step 3: Run existing broker tests to verify no regression**

Run: `cd tools && uv run --extra dev pytest tests/test_broker.py -v`
Expected: All existing tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tools/broker/adapter.py tools/tests/test_broker.py
git commit -m "feat(options): add 5 abstract broker methods for options trading"
```

---

### Task 3: Alpaca Adapter — Options Implementation

**Files:**
- Modify: `tools/broker/alpaca.py`
- Test: `tools/tests/test_options.py` (append)

- [ ] **Step 1: Add imports and OptionHistoricalDataClient to `AlpacaBrokerAdapter.__init__`**

At the top of `broker/alpaca.py`, add to the existing imports:

```python
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import (
    OptionChainRequest,
    OptionSnapshotRequest,
    OptionBarsRequest,
)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.requests import GetOptionContractsRequest, OptionLegRequest, OrderRequest
from alpaca.trading.enums import OrderClass, PositionIntent, ContractType
```

In `__init__`, add after `self.data_client`:

```python
        self.option_data_client = OptionHistoricalDataClient(
            self.api_key, self.secret_key
        )
```

- [ ] **Step 2: Implement `get_option_chain`**

Add to `AlpacaBrokerAdapter`:

```python
    def get_option_chain(
        self,
        underlying: str,
        expiration_date_gte: str | None = None,
        expiration_date_lte: str | None = None,
        strike_price_gte: float | None = None,
        strike_price_lte: float | None = None,
        option_type: str | None = None,
    ) -> list[dict]:
        from analysis.options import parse_occ_symbol
        from datetime import date as date_type

        kwargs = {"underlying_symbol": underlying}
        if expiration_date_gte:
            kwargs["expiration_date_gte"] = expiration_date_gte
        if expiration_date_lte:
            kwargs["expiration_date_lte"] = expiration_date_lte
        if strike_price_gte is not None:
            kwargs["strike_price_gte"] = strike_price_gte
        if strike_price_lte is not None:
            kwargs["strike_price_lte"] = strike_price_lte
        if option_type:
            kwargs["type"] = ContractType.CALL if option_type == "call" else ContractType.PUT

        req = OptionChainRequest(**kwargs)
        chain = self.option_data_client.get_option_chain(req)

        results = []
        today = date_type.today()
        for sym, snapshot in chain.items():
            parsed = parse_occ_symbol(sym)
            exp_date = date_type.fromisoformat(parsed["expiration"])
            dte = (exp_date - today).days

            bid = float(snapshot.latest_quote.bid_price) if snapshot.latest_quote else 0.0
            ask = float(snapshot.latest_quote.ask_price) if snapshot.latest_quote else 0.0

            greeks = {}
            if snapshot.greeks:
                greeks = {
                    "delta": snapshot.greeks.delta,
                    "gamma": snapshot.greeks.gamma,
                    "theta": snapshot.greeks.theta,
                    "vega": snapshot.greeks.vega,
                    "rho": snapshot.greeks.rho,
                }

            results.append({
                "symbol": sym,
                "underlying": parsed["underlying"],
                "strike": parsed["strike"],
                "type": parsed["type"],
                "expiration": parsed["expiration"],
                "dte": dte,
                "bid": bid,
                "ask": ask,
                "mid": round((bid + ask) / 2, 4) if (bid + ask) > 0 else 0.0,
                "volume": int(snapshot.latest_trade.size) if snapshot.latest_trade else 0,
                "open_interest": 0,  # Not in snapshot; available via get_option_contracts
                "iv": float(snapshot.implied_volatility) if snapshot.implied_volatility else 0.0,
                "greeks": greeks,
            })
        return results
```

- [ ] **Step 3: Implement `get_option_snapshot`**

```python
    def get_option_snapshot(self, option_symbols: list[str]) -> list[dict]:
        from analysis.options import parse_occ_symbol
        from datetime import date as date_type

        req = OptionSnapshotRequest(symbol_or_symbols=option_symbols)
        snapshots = self.option_data_client.get_option_snapshot(req)

        results = []
        today = date_type.today()
        for sym, snapshot in snapshots.items():
            parsed = parse_occ_symbol(sym)
            exp_date = date_type.fromisoformat(parsed["expiration"])
            dte = (exp_date - today).days

            bid = float(snapshot.latest_quote.bid_price) if snapshot.latest_quote else 0.0
            ask = float(snapshot.latest_quote.ask_price) if snapshot.latest_quote else 0.0

            greeks = {}
            if snapshot.greeks:
                greeks = {
                    "delta": snapshot.greeks.delta,
                    "gamma": snapshot.greeks.gamma,
                    "theta": snapshot.greeks.theta,
                    "vega": snapshot.greeks.vega,
                    "rho": snapshot.greeks.rho,
                }

            results.append({
                "symbol": sym,
                "underlying": parsed["underlying"],
                "strike": parsed["strike"],
                "type": parsed["type"],
                "expiration": parsed["expiration"],
                "dte": dte,
                "bid": bid,
                "ask": ask,
                "mid": round((bid + ask) / 2, 4) if (bid + ask) > 0 else 0.0,
                "iv": float(snapshot.implied_volatility) if snapshot.implied_volatility else 0.0,
                "greeks": greeks,
            })
        return results
```

- [ ] **Step 4: Implement `get_option_historical_iv`**

```python
    def get_option_historical_iv(
        self, underlying: str, lookback_days: int = 252
    ) -> list[dict]:
        from analysis.options import implied_vol_from_price, parse_occ_symbol
        from datetime import date as date_type, timedelta

        # Find longest-DTE ATM contract
        price_data = self.get_market_data(underlying)
        stock_price = price_data["mid"]
        if stock_price <= 0:
            return []

        contracts_req = GetOptionContractsRequest(
            underlying_symbols=[underlying],
            strike_price_gte=str(stock_price * 0.95),
            strike_price_lte=str(stock_price * 1.05),
            status="active",
        )
        contracts = self.trading_client.get_option_contracts(contracts_req)
        if not contracts:
            return []

        # Pick the call with the longest DTE
        today = date_type.today()
        best_contract = None
        best_dte = 0
        for c in contracts:
            exp = c.expiration_date if isinstance(c.expiration_date, date_type) else date_type.fromisoformat(str(c.expiration_date))
            dte = (exp - today).days
            if dte > best_dte and c.type == "call":
                best_dte = dte
                best_contract = c

        if not best_contract:
            return []

        # Fetch historical bars for this option contract
        contract_symbol = best_contract.symbol
        parsed = parse_occ_symbol(contract_symbol)
        strike = parsed["strike"]
        exp_date = date_type.fromisoformat(parsed["expiration"])

        end = today
        start = end - timedelta(days=lookback_days + 30)  # padding for weekends

        opt_bars_req = OptionBarsRequest(
            symbol_or_symbols=contract_symbol,
            start=datetime(start.year, start.month, start.day),
            end=datetime(end.year, end.month, end.day),
            timeframe=TimeFrame(1, TimeFrameUnit.Day),
        )
        opt_bars = self.option_data_client.get_option_bars(opt_bars_req)

        # Fetch stock bars for same period
        stock_bars = self.get_historical_data(
            underlying,
            datetime(start.year, start.month, start.day),
            datetime(end.year, end.month, end.day),
            "1Day",
        )
        stock_by_date = {b["timestamp"][:10]: b["close"] for b in stock_bars}

        # Derive IV for each day
        results = []
        rate = 0.05  # risk-free rate approximation
        bars_list = opt_bars.get(contract_symbol, []) if isinstance(opt_bars, dict) else []

        for bar in bars_list:
            bar_date = bar.timestamp.strftime("%Y-%m-%d")
            option_close = float(bar.close)
            stock_close = stock_by_date.get(bar_date)
            if not stock_close or option_close <= 0:
                continue
            bar_date_obj = date_type.fromisoformat(bar_date)
            dte = (exp_date - bar_date_obj).days
            if dte <= 0:
                continue
            iv = implied_vol_from_price(
                option_close, stock_close, strike, dte, rate, parsed["type"]
            )
            if not math.isnan(iv):
                results.append({"date": bar_date, "iv": iv})

        results.sort(key=lambda x: x["date"])
        return results
```

Add `import math` at the top of `broker/alpaca.py` if not already present.

- [ ] **Step 5: Implement `get_options_positions`**

```python
    def get_options_positions(self) -> list[dict]:
        from analysis.options import parse_occ_symbol
        from datetime import date as date_type

        positions = self.trading_client.get_all_positions()
        option_positions = [p for p in positions if str(getattr(p, 'asset_class', '')) == 'us_option']

        if not option_positions:
            return []

        # Enrich with greeks via snapshot
        option_symbols = [p.symbol for p in option_positions]
        snapshots = {}
        try:
            req = OptionSnapshotRequest(symbol_or_symbols=option_symbols)
            snap_data = self.option_data_client.get_option_snapshot(req)
            snapshots = {sym: s for sym, s in snap_data.items()}
        except Exception:
            pass  # greeks unavailable — return positions without them

        today = date_type.today()
        results = []
        for p in option_positions:
            parsed = parse_occ_symbol(p.symbol)
            exp_date = date_type.fromisoformat(parsed["expiration"])
            dte = (exp_date - today).days
            qty = int(p.qty)

            entry = {
                "symbol": p.symbol,
                "underlying": parsed["underlying"],
                "strike": parsed["strike"],
                "type": parsed["type"],
                "expiration": parsed["expiration"],
                "dte": dte,
                "quantity": qty,
                "side": "long" if qty > 0 else "short",
                "entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "unrealized_pnl": float(p.unrealized_pl),
                "unrealized_pnl_pct": float(p.unrealized_plpc) * 100,
            }

            # Merge greeks from snapshot
            snap = snapshots.get(p.symbol)
            if snap:
                entry["iv"] = float(snap.implied_volatility) if snap.implied_volatility else 0.0
                if snap.greeks:
                    entry["greeks"] = {
                        "delta": snap.greeks.delta,
                        "gamma": snap.greeks.gamma,
                        "theta": snap.greeks.theta,
                        "vega": snap.greeks.vega,
                        "rho": snap.greeks.rho,
                    }
            results.append(entry)
        return results
```

- [ ] **Step 6: Implement `place_multileg_order`**

```python
    def place_multileg_order(
        self,
        legs: list[dict],
        order_type: str,
        limit_price: float | None = None,
        time_in_force: str = "day",
    ) -> TradeTransaction:
        tif = TimeInForce.GTC if time_in_force == "gtc" else TimeInForce.DAY
        o_type = OrderType.LIMIT if order_type == "limit" else OrderType.MARKET

        option_legs = [
            OptionLegRequest(
                symbol=leg["symbol"],
                ratio_qty=float(leg["ratio_qty"]),
                position_intent=PositionIntent(leg["side"]),
            )
            for leg in legs
        ]

        req = OrderRequest(
            type=o_type,
            time_in_force=tif,
            order_class=OrderClass.MLEG,
            legs=option_legs,
            limit_price=limit_price,
        )

        order = self.trading_client.submit_order(req)

        return TradeTransaction(
            transaction_id=str(order.id),
            symbol=legs[0]["symbol"] if legs else "",
            side=legs[0]["side"] if legs else "",
            order_type=order_type,
            quantity=int(legs[0]["ratio_qty"]) if legs else 0,
            price=float(order.filled_avg_price) if order.filled_avg_price else 0.0,
            broker_order_id=str(order.id),
            status=str(order.status.value) if order.status else "submitted",
        )
```

- [ ] **Step 7: Add adapter tests to `tests/test_options.py`**

Append to the test file:

```python
from unittest.mock import MagicMock, patch


class TestAlpacaOptionsAdapter:
    def _make_adapter(self):
        with patch.dict("os.environ", {
            "ALPACA_API_KEY": "test-key",
            "ALPACA_SECRET_KEY": "test-secret",
        }):
            with patch("broker.alpaca.TradingClient") as mock_tc, \
                 patch("broker.alpaca.StockHistoricalDataClient") as mock_dc, \
                 patch("broker.alpaca.OptionHistoricalDataClient") as mock_oc:
                from broker.alpaca import AlpacaBrokerAdapter
                adapter = AlpacaBrokerAdapter()
                adapter._mock_tc = mock_tc.return_value
                adapter._mock_oc = mock_oc.return_value
                return adapter

    def test_get_option_chain_shape(self):
        adapter = self._make_adapter()
        mock_snapshot = MagicMock()
        mock_snapshot.latest_quote = MagicMock(bid_price=3.40, ask_price=3.60)
        mock_snapshot.latest_trade = MagicMock(size=500)
        mock_snapshot.implied_volatility = 0.32
        mock_snapshot.greeks = MagicMock(delta=0.45, gamma=0.03, theta=-0.08, vega=0.15, rho=0.01)

        adapter.option_data_client.get_option_chain.return_value = {
            "AAPL250620C00230000": mock_snapshot
        }
        result = adapter.get_option_chain("AAPL")
        assert len(result) == 1
        assert result[0]["underlying"] == "AAPL"
        assert result[0]["strike"] == 230.0
        assert result[0]["type"] == "call"
        assert result[0]["iv"] == 0.32
        assert result[0]["greeks"]["delta"] == 0.45
        assert result[0]["bid"] == 3.40
        assert result[0]["ask"] == 3.60

    def test_get_options_positions_filters_options(self):
        adapter = self._make_adapter()
        stock_pos = MagicMock()
        stock_pos.symbol = "AAPL"
        stock_pos.asset_class = "us_equity"

        opt_pos = MagicMock()
        opt_pos.symbol = "AAPL250620P00220000"
        opt_pos.asset_class = "us_option"
        opt_pos.qty = "-1"
        opt_pos.avg_entry_price = "2.15"
        opt_pos.current_price = "1.80"
        opt_pos.unrealized_pl = "35.0"
        opt_pos.unrealized_plpc = "0.163"

        adapter.trading_client.get_all_positions.return_value = [stock_pos, opt_pos]
        adapter.option_data_client.get_option_snapshot.return_value = {}

        result = adapter.get_options_positions()
        assert len(result) == 1
        assert result[0]["underlying"] == "AAPL"
        assert result[0]["type"] == "put"
        assert result[0]["side"] == "short"

    def test_place_multileg_order(self):
        adapter = self._make_adapter()
        mock_order = MagicMock()
        mock_order.id = "mleg-order-001"
        mock_order.filled_avg_price = None
        mock_order.status = MagicMock(value="pending_new")
        adapter.trading_client.submit_order.return_value = mock_order

        legs = [
            {"symbol": "AAPL250620P00220000", "side": "sell_to_open", "ratio_qty": 1},
            {"symbol": "AAPL250620P00215000", "side": "buy_to_open", "ratio_qty": 1},
        ]
        tx = adapter.place_multileg_order(legs, "limit", limit_price=1.25)
        assert tx.broker_order_id == "mleg-order-001"
        assert tx.status == "pending_new"

        # Verify the SDK was called with correct structure
        call_args = adapter.trading_client.submit_order.call_args[0][0]
        assert call_args.order_class == OrderClass.MLEG
        assert len(call_args.legs) == 2
```

- [ ] **Step 8: Run tests**

Run: `cd tools && uv run --extra dev pytest tests/test_options.py -v`
Expected: All PASS.

- [ ] **Step 9: Commit**

```bash
git add tools/broker/alpaca.py tools/tests/test_options.py
git commit -m "feat(options): implement Alpaca broker adapter for options

get_option_chain, get_option_snapshot, get_option_historical_iv,
get_options_positions (with greeks enrichment), place_multileg_order"
```

---

### Task 4: Simulation Adapter Stubs

**Files:**
- Modify: `tools/broker/simulation.py`

- [ ] **Step 1: Add the 5 stub methods at the end of `SimulationBrokerAdapter`**

```python
    def get_option_chain(self, underlying, **kwargs) -> list[dict]:
        raise NotImplementedError("Options simulation requires Phase 4 implementation")

    def get_option_snapshot(self, option_symbols) -> list[dict]:
        raise NotImplementedError("Options simulation requires Phase 4 implementation")

    def get_option_historical_iv(self, underlying, lookback_days=252) -> list[dict]:
        raise NotImplementedError("Options simulation requires Phase 4 implementation")

    def get_options_positions(self) -> list[dict]:
        raise NotImplementedError("Options simulation requires Phase 4 implementation")

    def place_multileg_order(self, legs, order_type, **kwargs):
        raise NotImplementedError("Options simulation requires Phase 4 implementation")
```

- [ ] **Step 2: Run simulation tests to verify no regression**

Run: `cd tools && uv run --extra dev pytest tests/test_simulation.py -v`
Expected: All existing tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tools/broker/simulation.py
git commit -m "feat(options): add simulation adapter stubs for Phase 4"
```

---

### Task 5: Persistence — IV History Table

**Files:**
- Modify: `tools/persistence/db.py`
- Modify: `tools/persistence/repository.py`

- [ ] **Step 1: Add `iv_history` table to SCHEMA in `db.py`**

Add at the end of the SCHEMA string (before the closing `"""`):

```sql
CREATE TABLE IF NOT EXISTS iv_history (
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    iv REAL NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (symbol, date)
);
```

- [ ] **Step 2: Add repository methods for IV history**

Add to `Repository` class in `repository.py`:

```python
    def save_iv_data(self, symbol: str, date: str, iv: float, source: str = "snapshot") -> None:
        """Cache a single IV data point. Idempotent (INSERT OR IGNORE)."""
        self.conn.execute(
            "INSERT OR IGNORE INTO iv_history (symbol, date, iv, source) VALUES (?, ?, ?, ?)",
            (symbol, date, iv, source),
        )
        self.conn.commit()

    def save_iv_data_batch(self, rows: list[dict]) -> None:
        """Batch insert IV data points. Each row: {symbol, date, iv, source}."""
        self.conn.executemany(
            "INSERT OR IGNORE INTO iv_history (symbol, date, iv, source) VALUES (:symbol, :date, :iv, :source)",
            rows,
        )
        self.conn.commit()

    def query_iv_history(self, symbol: str, min_days: int = 60) -> list[float]:
        """Return list of historical IV values for a symbol, sorted ascending by date.
        Returns empty list if fewer than min_days data points exist."""
        rows = self.conn.execute(
            "SELECT iv FROM iv_history WHERE symbol = ? ORDER BY date ASC",
            (symbol,),
        ).fetchall()
        if len(rows) < min_days:
            return []
        return [r["iv"] for r in rows]

    def count_iv_history(self, symbol: str) -> int:
        """Return number of cached IV data points for a symbol."""
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM iv_history WHERE symbol = ?",
            (symbol,),
        ).fetchone()
        return row["cnt"] if row else 0
```

- [ ] **Step 3: Run persistence tests to verify no regression**

Run: `cd tools && uv run --extra dev pytest tests/test_models_and_persistence.py -v`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add tools/persistence/db.py tools/persistence/repository.py
git commit -m "feat(options): add iv_history table and repository methods"
```

---

### Task 6: MCP Tools in server.py

**Files:**
- Modify: `tools/server.py`

- [ ] **Step 1: Add the 8 MCP tools at the end of server.py (before the backtest section)**

Find the comment `# --- Backtest Tools ---` in server.py and insert above it:

```python
# --- Options Tools ---


@mcp.tool()
def get_options_chain(
    underlying: str,
    expiration_gte: str | None = None,
    expiration_lte: str | None = None,
    strike_gte: float | None = None,
    strike_lte: float | None = None,
    option_type: str | None = None,
) -> str:
    """Get the option chain for an underlying symbol with greeks and IV.

    When to use: Research agent evaluating available contracts, Trader agent selecting strikes.

    Sample input: get_options_chain("AAPL", expiration_gte="2025-06-20", expiration_lte="2025-07-18", option_type="put")

    Expected output:
    [{"symbol": "AAPL250620P00220000", "underlying": "AAPL", "strike": 220.0,
      "type": "put", "expiration": "2025-06-20", "dte": 18, "bid": 3.40, "ask": 3.60,
      "mid": 3.50, "volume": 1200, "open_interest": 0, "iv": 0.32,
      "greeks": {"delta": -0.25, "gamma": 0.03, "theta": -0.08, "vega": 0.15, "rho": -0.01}}]
    """
    _track_tool("get_options_chain")
    try:
        broker = get_broker()
        chain = with_retry(broker.get_option_chain, _retry_config)(
            underlying,
            expiration_date_gte=expiration_gte,
            expiration_date_lte=expiration_lte,
            strike_price_gte=strike_gte,
            strike_price_lte=strike_lte,
            option_type=option_type,
        )
        if not chain:
            return json.dumps({"error": f"No contracts found for {underlying} with given filters"})

        # Cache ATM IV opportunistically
        _cache_atm_iv(underlying, chain)

        return json.dumps(chain)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_options_market_data(option_symbols: str) -> str:
    """Get real-time snapshot (quote + IV + greeks) for specific option contracts.

    When to use: Monitor agent checking greeks on open positions, Trader agent verifying spread pricing.

    Sample input: get_options_market_data("AAPL250620C00230000,AAPL250620P00220000")

    Expected output:
    [{"symbol": "AAPL250620C00230000", "underlying": "AAPL", "strike": 230.0,
      "type": "call", "expiration": "2025-06-20", "dte": 18, "bid": 3.40, "ask": 3.60,
      "mid": 3.50, "iv": 0.32, "greeks": {"delta": 0.45, ...}}]
    """
    _track_tool("get_options_market_data")
    try:
        symbols = [s.strip() for s in option_symbols.split(",") if s.strip()]
        if not symbols:
            return json.dumps({"error": "No symbols provided"})
        broker = get_broker()
        data = with_retry(broker.get_option_snapshot, _retry_config)(symbols)
        if not data:
            return json.dumps({"error": f"No data for symbols: {option_symbols}"})
        return json.dumps(data)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_options_positions() -> str:
    """Get all open option positions with greeks.

    When to use: Monitor agent's 15:30 ET exit loop checking open option positions.

    Sample input: (no arguments)

    Expected output:
    [{"symbol": "AAPL250620P00220000", "underlying": "AAPL", "strike": 220.0,
      "type": "put", "dte": 18, "quantity": -1, "side": "short",
      "entry_price": 2.15, "current_price": 1.80, "unrealized_pnl": 35.0,
      "unrealized_pnl_pct": 16.3, "iv": 0.30, "greeks": {"delta": -0.22, ...}}]

    Returns empty list [] if no option positions open.
    """
    _track_tool("get_options_positions")
    try:
        broker = get_broker()
        positions = with_retry(broker.get_options_positions, _retry_config)()
        return json.dumps(positions)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def calc_iv_rank(symbol: str) -> str:
    """Calculate IV Rank for an underlying — where current IV sits vs 52-week range.

    When to use: Research agent Phase 1 vol routing (IVR > 75 = sell premium, IVR < 25 = buy premium).

    Sample input: calc_iv_rank("AAPL")

    Expected output:
    {"symbol": "AAPL", "iv_rank": 82.3, "current_iv": 0.38, "iv_high_52w": 0.45,
     "iv_low_52w": 0.22, "data_points": 180}

    If insufficient history:
    {"error": "Insufficient IV history for AAPL (need ≥60 days, have 12)"}
    """
    _track_tool("calc_iv_rank")
    try:
        from analysis.options import calc_iv_rank as _calc_iv_rank
        from datetime import date as date_type

        broker = get_broker()
        repo = get_repo()

        # Get current ATM IV from chain snapshot
        chain = with_retry(broker.get_option_chain, _retry_config)(symbol)
        if not chain:
            return json.dumps({"error": f"Cannot get option chain for {symbol}"})

        current_iv = _get_atm_iv(chain)
        if current_iv is None:
            return json.dumps({"error": f"Cannot determine ATM IV for {symbol}"})

        # Cache today's IV
        today = date_type.today().isoformat()
        repo.save_iv_data(symbol, today, current_iv, "snapshot")

        # Check cache — bootstrap if needed
        data_points = repo.count_iv_history(symbol)
        if data_points < 60:
            _bootstrap_iv_cache(symbol, broker, repo)
            data_points = repo.count_iv_history(symbol)

        iv_history = repo.query_iv_history(symbol, min_days=60)
        if not iv_history:
            return json.dumps({
                "error": f"Insufficient IV history for {symbol} (need ≥60 days, have {data_points})"
            })

        rank = _calc_iv_rank(current_iv, iv_history)
        return json.dumps({
            "symbol": symbol,
            "iv_rank": round(rank, 1),
            "current_iv": round(current_iv, 4),
            "iv_high_52w": round(max(iv_history), 4),
            "iv_low_52w": round(min(iv_history), 4),
            "data_points": len(iv_history),
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def calc_hv(symbol: str, window: int = 20) -> str:
    """Calculate historical (realized) volatility from stock prices, annualized.

    When to use: Research agent comparing IV to HV (soft gate SOFT_IVHV_CONFIRM: IV/HV > 1.2 confirms rich vol).

    Sample input: calc_hv("AAPL", 20)

    Expected output:
    {"symbol": "AAPL", "hv20": 0.28, "window": 20, "period_days": 252}
    """
    _track_tool("calc_hv")
    try:
        from analysis.options import calc_hv as _calc_hv
        from datetime import datetime as dt, timedelta
        import math

        broker = get_broker()
        end = dt.now()
        start = end - timedelta(days=365)
        bars = with_retry(broker.get_historical_data, _retry_config)(
            symbol, start, end, "1Day"
        )
        if len(bars) < window + 1:
            return json.dumps({"error": f"Insufficient price history for {symbol}"})

        closes = [b["close"] for b in bars]
        hv = _calc_hv(closes, window)
        if math.isnan(hv):
            return json.dumps({"error": f"Insufficient price history for {symbol}"})

        return json.dumps({
            "symbol": symbol,
            f"hv{window}": round(hv, 4),
            "window": window,
            "period_days": len(bars),
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_put_skew(symbol: str, expiration: str, target_delta: float = 0.25) -> str:
    """Calculate put/call IV skew at a target delta for a specific expiration.

    When to use: Research agent soft gate SOFT_PUTSKEW — skew > 1.15 adds conviction to bull put spreads.

    Sample input: get_put_skew("AAPL", "2025-06-20", 0.25)

    Expected output:
    {"symbol": "AAPL", "expiration": "2025-06-20", "put_skew": 1.18,
     "put_iv": 0.34, "call_iv": 0.29, "target_delta": 0.25}
    """
    _track_tool("get_put_skew")
    try:
        from analysis.options import calc_put_skew as _calc_put_skew
        import math

        broker = get_broker()
        chain = with_retry(broker.get_option_chain, _retry_config)(
            symbol,
            expiration_date_gte=expiration,
            expiration_date_lte=expiration,
        )
        if not chain:
            return json.dumps({"error": f"No contracts found for {symbol} at {expiration}"})

        skew = _calc_put_skew(chain, target_delta)
        if math.isnan(skew):
            return json.dumps({"error": "Cannot compute skew — insufficient contracts at target delta"})

        # Extract the IVs used
        puts = [c for c in chain if c["type"] == "put" and c.get("greeks", {}).get("delta")]
        calls = [c for c in chain if c["type"] == "call" and c.get("greeks", {}).get("delta")]
        best_put = min(puts, key=lambda c: abs(abs(c["greeks"]["delta"]) - target_delta), default=None)
        best_call = min(calls, key=lambda c: abs(c["greeks"]["delta"] - target_delta), default=None)

        return json.dumps({
            "symbol": symbol,
            "expiration": expiration,
            "put_skew": round(skew, 3),
            "put_iv": round(best_put["iv"], 4) if best_put else 0,
            "call_iv": round(best_call["iv"], 4) if best_call else 0,
            "target_delta": target_delta,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def calc_expected_move(symbol: str, dte: int) -> str:
    """Calculate the one-standard-deviation expected move for a stock over N days.

    When to use: Trader agent Step O-2 strike selection — debit vertical short leg ~1 expected move OTM.

    Sample input: calc_expected_move("AAPL", 30)

    Expected output:
    {"symbol": "AAPL", "expected_move": 8.45, "stock_price": 230.0, "iv": 0.32, "dte": 30}
    """
    _track_tool("calc_expected_move")
    try:
        from analysis.options import calc_expected_move as _calc_expected_move

        broker = get_broker()
        # Get stock price
        market_data = with_retry(broker.get_market_data, _retry_config)(symbol)
        stock_price = market_data.get("mid", 0)
        if stock_price <= 0:
            return json.dumps({"error": f"Cannot get price for {symbol}"})

        # Get ATM IV from chain
        chain = with_retry(broker.get_option_chain, _retry_config)(symbol)
        if not chain:
            return json.dumps({"error": f"Cannot get IV for {symbol}"})

        iv = _get_atm_iv(chain)
        if iv is None:
            return json.dumps({"error": f"Cannot get IV for {symbol}"})

        move = _calc_expected_move(stock_price, iv, dte)
        return json.dumps({
            "symbol": symbol,
            "expected_move": round(move, 2),
            "stock_price": round(stock_price, 2),
            "iv": round(iv, 4),
            "dte": dte,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def place_multileg_order(
    legs: str,
    order_type: str,
    limit_price: float | None = None,
    plan_id: str = "",
) -> str:
    """Place a multi-leg option order (spread). Blocked when kill switch is active.

    When to use: Trader agent placing credit/debit spreads per the vol-edge SOP.

    Sample input: place_multileg_order(
        '[{"symbol": "AAPL250620P00220000", "side": "sell_to_open", "ratio_qty": 1},
          {"symbol": "AAPL250620P00215000", "side": "buy_to_open", "ratio_qty": 1}]',
        "limit", limit_price=1.25, plan_id="plan-opt-001")

    Expected output:
    {"transaction_id": "f8a2c1d3-...", "plan_id": "plan-opt-001", "order_class": "mleg",
     "order_type": "limit", "limit_price": 1.25, "status": "pending_new",
     "legs": [...], "broker_order_id": "f8a2c1d3-...", "timestamp": "..."}

    If kill switch active:
    {"error": "Kill switch is active", "reason": "daily loss limit breached"}
    """
    _track_tool("place_multileg_order")
    if _kill_switch_state["active"]:
        return json.dumps({"error": "Kill switch is active", "reason": _kill_switch_state["reason"]})

    try:
        parsed_legs = json.loads(legs)
    except (json.JSONDecodeError, TypeError) as e:
        return json.dumps({"error": f"Invalid legs JSON: {e}"})

    if not parsed_legs:
        return json.dumps({"error": "No legs provided"})

    try:
        broker = get_broker()
        tx = with_retry(broker.place_multileg_order, _retry_config)(
            legs=parsed_legs,
            order_type=order_type,
            limit_price=limit_price,
        )
        tx.plan_id = plan_id

        # Determine if this is entry or exit
        action = "multileg_entry"
        if any("close" in leg.get("side", "") for leg in parsed_legs):
            action = "multileg_exit"

        # Log to ledger
        _log_to_ledger(
            action=action,
            symbol=parsed_legs[0]["symbol"],
            quantity=int(parsed_legs[0].get("ratio_qty", 1)),
            order_type=order_type,
            price=tx.price,
            status=tx.status,
            broker_order_id=tx.broker_order_id,
            plan_id=plan_id,
            notes=json.dumps({"legs": parsed_legs, "limit_price": limit_price}),
        )

        if plan_id:
            get_repo().save_transaction(tx)

        result = {
            "transaction_id": tx.transaction_id,
            "plan_id": plan_id,
            "order_class": "mleg",
            "order_type": order_type,
            "limit_price": limit_price,
            "status": tx.status,
            "legs": parsed_legs,
            "broker_order_id": tx.broker_order_id,
            "timestamp": tx.timestamp.isoformat() if tx.timestamp else "",
        }
        return json.dumps(result)
    except Exception as e:
        _log_to_ledger(
            action="multileg_entry",
            symbol=parsed_legs[0]["symbol"] if parsed_legs else "",
            quantity=0,
            order_type=order_type,
            price=0,
            status="failed",
            plan_id=plan_id,
            notes=str(e),
        )
        return json.dumps({"error": f"Order rejected: {e}"})


# --- Options Helper Functions ---


def _get_atm_iv(chain: list[dict]) -> float | None:
    """Extract aggregate ATM IV from chain (average of nearest ATM call + put IV)."""
    if not chain:
        return None
    calls = [c for c in chain if c["type"] == "call" and c.get("iv", 0) > 0 and c.get("greeks")]
    puts = [c for c in chain if c["type"] == "put" and c.get("iv", 0) > 0 and c.get("greeks")]
    if not calls and not puts:
        return None
    # ATM = closest to |delta| = 0.50
    atm_call_iv = None
    atm_put_iv = None
    if calls:
        atm_call = min(calls, key=lambda c: abs(c["greeks"]["delta"] - 0.50))
        atm_call_iv = atm_call["iv"]
    if puts:
        atm_put = min(puts, key=lambda c: abs(abs(c["greeks"]["delta"]) - 0.50))
        atm_put_iv = atm_put["iv"]
    if atm_call_iv and atm_put_iv:
        return (atm_call_iv + atm_put_iv) / 2
    return atm_call_iv or atm_put_iv


def _cache_atm_iv(underlying: str, chain: list[dict]) -> None:
    """Opportunistically cache today's ATM IV from a chain fetch."""
    from datetime import date as date_type
    iv = _get_atm_iv(chain)
    if iv is not None:
        try:
            repo = get_repo()
            repo.save_iv_data(underlying, date_type.today().isoformat(), iv, "snapshot")
        except Exception:
            pass


def _bootstrap_iv_cache(symbol: str, broker, repo) -> None:
    """Cold-start: derive historical IV from option bars via BSM inversion."""
    try:
        historical = broker.get_option_historical_iv(symbol)
        if historical:
            rows = [{"symbol": symbol, "date": h["date"], "iv": h["iv"], "source": "derived"} for h in historical]
            repo.save_iv_data_batch(rows)
    except Exception:
        pass
```

- [ ] **Step 2: Run the full test suite to check for syntax errors and no regressions**

Run: `cd tools && uv run --extra dev pytest tests/test_options.py tests/test_broker.py tests/test_models_and_persistence.py -v`
Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add tools/server.py
git commit -m "feat(options): add 8 MCP tools for options trading

get_options_chain, get_options_market_data, get_options_positions,
calc_iv_rank (with cache + bootstrap), calc_hv, get_put_skew,
calc_expected_move, place_multileg_order (kill switch + ledger)"
```

---

### Task 7: MCP Tool Integration Tests

**Files:**
- Modify: `tools/tests/test_options.py` (append)

- [ ] **Step 1: Add integration tests for MCP tools**

Append to `tests/test_options.py`:

```python
import json


class TestMcpToolIntegration:
    """Test MCP tools with mocked broker — verify JSON shapes and kill switch."""

    def _setup_server(self):
        """Patch the broker in server.py."""
        import server
        mock_broker = MagicMock()
        server._broker = mock_broker
        server._kill_switch_state = {"active": False, "triggered_at": None, "reason": None}
        # Mock repo with in-memory db
        from persistence.repository import Repository
        repo = Repository(":memory:")
        server._repo = repo
        return mock_broker, repo

    def test_place_multileg_order_kill_switch_blocks(self):
        import server
        server._kill_switch_state = {"active": True, "triggered_at": None, "reason": "test halt"}
        result = json.loads(server.place_multileg_order(
            '[{"symbol": "AAPL250620P00220000", "side": "sell_to_open", "ratio_qty": 1}]',
            "limit", 1.25, "plan-001",
        ))
        assert result["error"] == "Kill switch is active"
        assert result["reason"] == "test halt"

    def test_place_multileg_order_success(self):
        mock_broker, repo = self._setup_server()
        import server
        mock_tx = TradeTransaction(
            transaction_id="tx-001", symbol="AAPL250620P00220000",
            side="sell_to_open", order_type="limit", quantity=1,
            price=0.0, broker_order_id="mleg-001", status="pending_new",
        )
        mock_broker.place_multileg_order.return_value = mock_tx

        result = json.loads(server.place_multileg_order(
            '[{"symbol": "AAPL250620P00220000", "side": "sell_to_open", "ratio_qty": 1},'
            ' {"symbol": "AAPL250620P00215000", "side": "buy_to_open", "ratio_qty": 1}]',
            "limit", 1.25, "plan-opt-001",
        ))
        assert result["status"] == "pending_new"
        assert result["order_class"] == "mleg"
        assert result["plan_id"] == "plan-opt-001"
        assert len(result["legs"]) == 2

    def test_calc_iv_rank_insufficient_history(self):
        mock_broker, repo = self._setup_server()
        import server
        # Return a chain with one ATM contract
        mock_broker.get_option_chain.return_value = [
            {"type": "call", "iv": 0.30, "greeks": {"delta": 0.50, "gamma": 0, "theta": 0, "vega": 0, "rho": 0}},
        ]
        mock_broker.get_option_historical_iv.return_value = []  # no history

        result = json.loads(server.calc_iv_rank("AAPL"))
        assert "error" in result
        assert "Insufficient" in result["error"]

    def test_get_options_positions_empty(self):
        mock_broker, repo = self._setup_server()
        import server
        mock_broker.get_options_positions.return_value = []
        result = json.loads(server.get_options_positions())
        assert result == []

    def test_place_multileg_invalid_json(self):
        self._setup_server()
        import server
        result = json.loads(server.place_multileg_order("not json", "limit", 1.0, ""))
        assert "error" in result
        assert "Invalid legs JSON" in result["error"]
```

- [ ] **Step 2: Run all options tests**

Run: `cd tools && uv run --extra dev pytest tests/test_options.py -v`
Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add tools/tests/test_options.py
git commit -m "test(options): add MCP tool integration tests

Kill switch blocking, successful multileg placement, insufficient
IV history error, empty positions, invalid JSON handling."
```

---

### Task 8: Verify Full Test Suite

**Files:** None (verification only)

- [ ] **Step 1: Run the full test suite (excluding known-failing test_harness.py)**

Run: `cd tools && uv run --extra dev pytest tests/ -v --ignore=tests/test_harness.py`
Expected: All tests PASS. The 9 failing tests in `test_harness.py` are pre-existing and unrelated (documented in HANDOFF.md).

- [ ] **Step 2: Run just test_harness.py to confirm no new failures**

Run: `cd tools && uv run --extra dev pytest tests/test_harness.py -v 2>&1 | tail -5`
Expected: Same 9 failures as before — no new failures introduced.

- [ ] **Step 3: Quick smoke test — import server and verify tools registered**

Run: `cd tools && uv run python -c "from server import mcp; print([t.name for t in mcp._tools.values() if 'option' in t.name.lower() or 'multileg' in t.name.lower() or 'iv_rank' in t.name.lower() or 'hv' == t.name.lower() or 'skew' in t.name.lower() or 'expected' in t.name.lower()])"`
Expected: List containing `get_options_chain`, `get_options_market_data`, `get_options_positions`, `calc_iv_rank`, `calc_hv`, `get_put_skew`, `calc_expected_move`, `place_multileg_order`.

---

## Summary

8 tasks, ~9 commits. Each task produces independently testable code:
1. Pure analysis functions (no dependencies)
2. Abstract interface (contract)
3. Alpaca implementation (SDK integration)
4. Simulation stubs (Phase 4 placeholder)
5. Persistence (IV cache)
6. MCP tools (thin wrappers)
7. Integration tests (end-to-end shapes)
8. Regression verification
