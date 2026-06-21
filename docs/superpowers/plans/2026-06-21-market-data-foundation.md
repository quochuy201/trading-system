# Market-Data Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the price data the scanner reads correct, consistent, and fresh — split-adjusted, consolidated-volume, single-source, with a daily refresh and a loud staleness signal — replacing the IEX/raw/two-writer patchwork.

**Architecture:** Introduce one `MarketDataSource` adapter (default = yfinance: consolidated, split-adjusted, no API key) that becomes the **single writer** of 1Day price bars. Alpaca stays the execution broker (orders/account/positions); only *data* moves off IEX. The scanner is unchanged — it still reads the local SQLite DB; we fix what flows into that DB. A validation module + staleness guard surface any corruption instead of letting it skew the scan silently.

**Tech Stack:** Python 3.11+, yfinance, pandas, SQLite (via `persistence.repository`), MCP tools (`tools/server.py`), pytest.

## Global Constraints

- Python ≥ 3.11; PEP 8; type hints on public functions; Google-style docstrings. (CLAUDE.md §6)
- MCP tools must never raise to the agent — return `{"error": "..."}` JSON. (CLAUDE.md)
- Preserve no-look-ahead: the simulation/backtest path is untouched; `SimulationBroker` still serves clock-bounded DB data. Only the **live** data-write path changes.
- Data source is **separate** from the broker. Alpaca remains the execution broker.
- **Single writer:** every 1Day price-bar write goes through `MarketDataSource`. No code writes IEX bars behind its back.
- Data-source selection is via env var `TRADING_DATA_SOURCE` (default `yfinance`) — server.py configures from env/`.env`, not `config.yaml`. (Refinement of the spec, which named `config.yaml`; documented in `.env.EXAMPLE`.)
- New dependency: `yfinance` (added to `tools/pyproject.toml`).
- Tests: `cd tools && uv run --extra dev pytest tests/ -v`. Temp DB via `Repository(":memory:")`. Test files start with `sys.path.insert(0, str(Path(__file__).parent.parent))`. No network in unit tests — mock the source.
- Bar dict shape (matches `save_price_bars`): keys `symbol, timestamp, open, high, low, close, volume, timeframe`. 1Day `timestamp` format: `"YYYY-MM-DDT00:00:00+00:00"`.
- Re-load wipes existing 1Day bars first (timestamp-format change would otherwise duplicate rows under the `(symbol, timestamp, timeframe)` PK).

---

## File Structure

- **Create** `tools/data/source.py` — `MarketDataSource` ABC, `YFinanceSource`, `get_data_source()` factory. The single data writer's source of bars + last price.
- **Create** `tools/data/validate.py` — pure validation: anomaly detection, freshness/alignment report, staleness predicate.
- **Create** `tools/tests/test_data_source.py`, `tools/tests/test_data_validate.py`, `tools/tests/test_data_cache.py`.
- **Modify** `tools/persistence/repository.py` — add `latest_price_date()` and `clear_price_data()`.
- **Modify** `tools/data/cache.py` — `load_price_cache` writes through the data source (single writer).
- **Modify** `tools/scripts/load_universe.py` — fetch via the data source (adjusted); fix the stale `--daily-end` default; wipe-before-reload; post-load validation.
- **Modify** `tools/server.py` — `get_market_data` tool → data-source last price; add `refresh_market_data` tool; add staleness fields to the scan tools.
- **Modify** `tools/pyproject.toml` — add `yfinance`.
- **Modify** `.env.EXAMPLE` — document `TRADING_DATA_SOURCE`.
- **Create** `cron/trading-data-refresh.sh` + note in `cron/README-kanban.md` — pre-market daily refresh.

---

## Task 1: MarketDataSource adapter (yfinance)

**Files:**
- Create: `tools/data/source.py`
- Create: `tools/tests/test_data_source.py`
- Modify: `tools/pyproject.toml` (add `yfinance`)

**Interfaces:**
- Produces:
  - `class MarketDataSource(ABC)` with `get_daily_bars(symbols: list[str], start: str, end: str) -> dict[str, list[dict]]` and `get_last_price(symbol: str) -> float | None`.
  - `class YFinanceSource(MarketDataSource)` with public methods above + `_normalize_bars(df: pandas.DataFrame, symbol: str, timeframe: str = "1Day") -> list[dict]`.
  - `get_data_source(name: str | None = None) -> MarketDataSource`.

- [ ] **Step 1: Add the dependency**

Edit `tools/pyproject.toml`, add to `dependencies`:

```toml
    "yfinance>=0.2.40",
```

Then run: `cd tools && uv sync` — Expected: resolves and installs yfinance.

- [ ] **Step 2: Write the failing test** (`tools/tests/test_data_source.py`)

```python
"""Tests for the MarketDataSource adapter (offline — no network)."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.source import YFinanceSource, get_data_source, MarketDataSource


def test_normalize_bars_shapes_rows_and_format():
    idx = pd.to_datetime(["2026-06-17", "2026-06-18"])
    df = pd.DataFrame(
        {"Open": [10.0, 11.0], "High": [10.5, 11.5], "Low": [9.5, 10.5],
         "Close": [10.2, 11.2], "Volume": [1000, 2000]}, index=idx)
    rows = YFinanceSource()._normalize_bars(df, "TEST")
    assert len(rows) == 2
    assert rows[0] == {
        "symbol": "TEST", "timestamp": "2026-06-17T00:00:00+00:00",
        "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.2,
        "volume": 1000.0, "timeframe": "1Day"}


def test_normalize_bars_skips_nan_close():
    idx = pd.to_datetime(["2026-06-17", "2026-06-18"])
    df = pd.DataFrame(
        {"Open": [10.0, float("nan")], "High": [10.5, float("nan")],
         "Low": [9.5, float("nan")], "Close": [10.2, float("nan")],
         "Volume": [1000, float("nan")]}, index=idx)
    rows = YFinanceSource()._normalize_bars(df, "TEST")
    assert len(rows) == 1


def test_factory_default_is_yfinance():
    src = get_data_source()
    assert isinstance(src, MarketDataSource)
    assert isinstance(src, YFinanceSource)


def test_factory_unknown_raises():
    import pytest
    with pytest.raises(ValueError):
        get_data_source("bloomberg")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_data_source.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'data.source'`.

- [ ] **Step 4: Write the implementation** (`tools/data/source.py`)

```python
"""Market data source adapter — the SINGLE writer of price bars.

Default = yfinance (consolidated, split/dividend-adjusted, no API key).
Selected via env `TRADING_DATA_SOURCE` (default "yfinance"). Alpaca remains the
execution broker; only price *data* flows through here. Swap to a paid source
(Alpaca SIP / Polygon) by adding a subclass and a factory branch — no scanner
change.
"""

import os
from abc import ABC, abstractmethod

import pandas as pd


class MarketDataSource(ABC):
    """Abstract source of historical bars and last price."""

    @abstractmethod
    def get_daily_bars(self, symbols: list[str], start: str, end: str) -> dict[str, list[dict]]:
        """Return {symbol: [bar dict, ...]} of adjusted 1Day bars in [start, end)."""

    @abstractmethod
    def get_last_price(self, symbol: str) -> float | None:
        """Return the latest available adjusted close, or None."""


class YFinanceSource(MarketDataSource):
    """yfinance-backed source. Network calls are isolated to the public methods;
    `_normalize_bars` is pure and unit-tested offline."""

    def _normalize_bars(self, df: pd.DataFrame, symbol: str, timeframe: str = "1Day") -> list[dict]:
        rows: list[dict] = []
        for ts, r in df.iterrows():
            if pd.isna(r["Close"]):
                continue
            rows.append({
                "symbol": symbol,
                "timestamp": ts.strftime("%Y-%m-%dT00:00:00+00:00"),
                "open": float(r["Open"]), "high": float(r["High"]),
                "low": float(r["Low"]), "close": float(r["Close"]),
                "volume": float(r["Volume"]), "timeframe": timeframe,
            })
        return rows

    def get_daily_bars(self, symbols: list[str], start: str, end: str) -> dict[str, list[dict]]:
        import yfinance as yf
        out: dict[str, list[dict]] = {}
        if not symbols:
            return out
        df = yf.download(symbols, start=start, end=end, auto_adjust=True,
                         progress=False, group_by="ticker", threads=True)
        for s in symbols:
            try:
                sub = df[s] if len(symbols) > 1 else df
            except KeyError:
                continue
            sub = sub.dropna(how="all")
            if not sub.empty:
                out[s] = self._normalize_bars(sub, s)
        return out

    def get_last_price(self, symbol: str) -> float | None:
        import yfinance as yf
        df = yf.download(symbol, period="5d", auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None
        closes = df["Close"].dropna()
        return float(closes.iloc[-1]) if len(closes) else None


def get_data_source(name: str | None = None) -> MarketDataSource:
    """Return the configured data source (env `TRADING_DATA_SOURCE`, default yfinance)."""
    name = (name or os.environ.get("TRADING_DATA_SOURCE", "yfinance")).lower()
    if name == "yfinance":
        return YFinanceSource()
    raise ValueError(f"unknown data source: {name!r}")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd tools && uv run --extra dev pytest tests/test_data_source.py -v`
Expected: 4 passed.

- [ ] **Step 6: Smoke-test the live fetch (network; one-off, not a unit test)**

Run:
```bash
cd tools && uv run python -c "from data.source import get_data_source as g; s=g(); b=g().get_daily_bars(['SPY','ORLY'],'2025-06-05','2025-06-16'); print('SPY bars',len(b['SPY']),'ORLY bars',len(b['ORLY'])); print('ORLY closes', [round(x['close'],2) for x in b['ORLY']]); print('SPY last', s.get_last_price('SPY'))"
```
Expected: ORLY closes continuous around 89–92 (no 1300→90 cliff); SPY last price a sane number (~700s).

- [ ] **Step 7: Commit**

```bash
cd /Users/zelyuh/workplace/trading-system
git add tools/data/source.py tools/tests/test_data_source.py tools/pyproject.toml tools/uv.lock
git commit -m "feat(data): MarketDataSource adapter (yfinance, single writer)"
```

---

## Task 2: Data validation module

**Files:**
- Create: `tools/data/validate.py`
- Create: `tools/tests/test_data_validate.py`

**Interfaces:**
- Consumes: `Repository.latest_price_date` (defined in Task 3 — used only by `freshness_report`, tested here with a stub).
- Produces:
  - `find_price_anomalies(bars: list[dict], threshold_pct: float = 35.0) -> list[dict]`
  - `is_stale(freshest_date: str | None, scan_date: str, max_age_days: int = 3) -> bool`
  - `freshness_report(repo, symbols: list[str], timeframe: str = "1Day") -> dict` returning keys `freshest, n_fresh, stale, missing, aligned`.

- [ ] **Step 1: Write the failing test** (`tools/tests/test_data_validate.py`)

```python
"""Tests for data validation (pure / in-memory)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.validate import find_price_anomalies, is_stale, freshness_report


def _bars(closes, symbol="X"):
    return [{"symbol": symbol, "timestamp": f"2026-06-{10+i:02d}T00:00:00+00:00",
             "close": c} for i, c in enumerate(closes)]


def test_find_price_anomalies_flags_split_cliff():
    out = find_price_anomalies(_bars([1348.0, 91.7, 90.0]))  # 15:1 split look-alike
    assert len(out) == 1
    assert out[0]["symbol"] == "X"
    assert out[0]["pct"] > 90


def test_find_price_anomalies_clean_series():
    assert find_price_anomalies(_bars([100, 101, 99, 102])) == []


def test_is_stale():
    assert is_stale("2026-06-12", "2026-06-20", max_age_days=3) is True
    assert is_stale("2026-06-18", "2026-06-19", max_age_days=3) is False
    assert is_stale(None, "2026-06-19") is True


class _StubRepo:
    def __init__(self, dates):
        self._d = dates
    def latest_price_date(self, symbol, timeframe="1Day"):
        return self._d.get(symbol)


def test_freshness_report_detects_patchwork():
    repo = _StubRepo({"SPY": "2026-06-18T00:00:00+00:00",
                      "AAPL": "2026-06-18T00:00:00+00:00",
                      "PM": "2026-06-12T00:00:00+00:00",
                      "ZZZ": None})
    rep = freshness_report(repo, ["SPY", "AAPL", "PM", "ZZZ"])
    assert rep["freshest"] == "2026-06-18"
    assert rep["n_fresh"] == 2
    assert rep["stale"] == ["PM"]
    assert rep["missing"] == ["ZZZ"]
    assert rep["aligned"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_data_validate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'data.validate'`.

- [ ] **Step 3: Write the implementation** (`tools/data/validate.py`)

```python
"""Price-data validation: anomaly detection + freshness/alignment report.

Pure functions over bar lists and a repository, so corruption (splits, IEX
volume, patchwork freshness) is caught loudly instead of silently skewing the
scanner.
"""

from datetime import date


def find_price_anomalies(bars: list[dict], threshold_pct: float = 35.0) -> list[dict]:
    """Flag day-over-day close moves exceeding threshold_pct (split/decimal hints)."""
    out: list[dict] = []
    prev: float | None = None
    for b in bars:
        c = float(b["close"])
        if prev is not None and prev > 0:
            chg = abs(c / prev - 1) * 100
            if chg > threshold_pct:
                out.append({"symbol": b.get("symbol"), "timestamp": b.get("timestamp"),
                            "pct": round(chg, 1), "prev": prev, "close": c})
        prev = c
    return out


def is_stale(freshest_date: str | None, scan_date: str, max_age_days: int = 3) -> bool:
    """True if data is missing or older than max_age_days vs scan_date (YYYY-MM-DD prefixes)."""
    if not freshest_date:
        return True
    f = date.fromisoformat(freshest_date[:10])
    s = date.fromisoformat(scan_date[:10])
    return (s - f).days > max_age_days


def freshness_report(repo, symbols: list[str], timeframe: str = "1Day") -> dict:
    """Per-symbol latest-bar dates → {freshest, n_fresh, stale, missing, aligned}."""
    dates = {s: repo.latest_price_date(s, timeframe) for s in symbols}
    present = {s: d[:10] for s, d in dates.items() if d}
    freshest = max(present.values()) if present else None
    stale = sorted(s for s, d in present.items() if d != freshest)
    missing = sorted(s for s, d in dates.items() if not d)
    return {
        "freshest": freshest,
        "n_fresh": sum(1 for d in present.values() if d == freshest),
        "stale": stale,
        "missing": missing,
        "aligned": (not stale) and (not missing),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools && uv run --extra dev pytest tests/test_data_validate.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/zelyuh/workplace/trading-system
git add tools/data/validate.py tools/tests/test_data_validate.py
git commit -m "feat(data): price-data anomaly + freshness validation"
```

---

## Task 3: Repository helpers (freshness + clear)

**Files:**
- Modify: `tools/persistence/repository.py` (add two methods after `query_price_data`, ~line 221)
- Modify: `tools/tests/test_models_and_persistence.py` (add a test class)

**Interfaces:**
- Produces: `Repository.latest_price_date(symbol: str, timeframe: str = "1Day") -> str | None`; `Repository.clear_price_data(timeframe: str = "1Day") -> int`.

- [ ] **Step 1: Write the failing test** (append to `tools/tests/test_models_and_persistence.py`)

```python
class TestPriceDataHelpers:
    def test_latest_price_date_and_clear(self):
        from persistence.repository import Repository
        repo = Repository(":memory:")
        repo.save_price_bars([
            {"symbol": "AAA", "timestamp": "2026-06-12T00:00:00+00:00", "open": 1,
             "high": 1, "low": 1, "close": 1, "volume": 10, "timeframe": "1Day"},
            {"symbol": "AAA", "timestamp": "2026-06-18T00:00:00+00:00", "open": 1,
             "high": 1, "low": 1, "close": 1, "volume": 10, "timeframe": "1Day"},
        ])
        assert repo.latest_price_date("AAA") == "2026-06-18T00:00:00+00:00"
        assert repo.latest_price_date("ZZZ") is None
        assert repo.clear_price_data("1Day") == 2
        assert repo.latest_price_date("AAA") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_models_and_persistence.py::TestPriceDataHelpers -v`
Expected: FAIL with `AttributeError: 'Repository' object has no attribute 'latest_price_date'`.

- [ ] **Step 3: Write the implementation** (in `tools/persistence/repository.py`, immediately after `query_price_data`)

```python
    def latest_price_date(self, symbol: str, timeframe: str = "1Day") -> str | None:
        """Return the max timestamp stored for a symbol/timeframe, or None."""
        row = self.conn.execute(
            "SELECT MAX(timestamp) AS mx FROM price_data WHERE symbol = ? AND timeframe = ?",
            (symbol, timeframe),
        ).fetchone()
        return row["mx"] if row and row["mx"] else None

    def clear_price_data(self, timeframe: str = "1Day") -> int:
        """Delete all bars of a timeframe (used before a clean re-load). Returns rows deleted."""
        cur = self.conn.execute("DELETE FROM price_data WHERE timeframe = ?", (timeframe,))
        self.conn.commit()
        return cur.rowcount
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools && uv run --extra dev pytest tests/test_models_and_persistence.py::TestPriceDataHelpers -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/zelyuh/workplace/trading-system
git add tools/persistence/repository.py tools/tests/test_models_and_persistence.py
git commit -m "feat(persistence): latest_price_date + clear_price_data helpers"
```

---

## Task 4: Route `load_price_cache` through the data source (single writer)

**Files:**
- Modify: `tools/data/cache.py`
- Create: `tools/tests/test_data_cache.py`

**Interfaces:**
- Consumes: `data.source.get_data_source` (Task 1), `Repository.save_price_bars`.
- Produces: unchanged signature `load_price_cache(broker, repo, symbols, start, end, timeframe="1Day") -> dict`. 1Day now flows from the data source; non-daily still uses `broker` (kept for that reason).

- [ ] **Step 1: Write the failing test** (`tools/tests/test_data_cache.py`)

```python
"""load_price_cache must write 1Day bars from the data source, not the broker."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import data.cache as cache
from persistence.repository import Repository


class _FakeSource:
    def get_daily_bars(self, symbols, start, end):
        return {"AAA": [{"symbol": "AAA", "timestamp": "2026-06-18T00:00:00+00:00",
                         "open": 1, "high": 1, "low": 1, "close": 2,
                         "volume": 5, "timeframe": "1Day"}]}


def test_load_price_cache_uses_data_source(monkeypatch):
    monkeypatch.setattr(cache, "get_data_source", lambda: _FakeSource())
    repo = Repository(":memory:")
    summary = cache.load_price_cache(None, repo, ["AAA"], "2026-01-01", "2026-06-20")
    assert summary["bars_loaded"] == 1
    assert repo.latest_price_date("AAA") == "2026-06-18T00:00:00+00:00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_data_cache.py -v`
Expected: FAIL — `AttributeError: module 'data.cache' has no attribute 'get_data_source'` (it imports broker currently).

- [ ] **Step 3: Rewrite `tools/data/cache.py`**

```python
"""Data tools — price cache loading and querying.

1Day bars are written by the single MarketDataSource (consolidated, adjusted).
Intraday timeframes still use the broker until the source supports them.
"""

from datetime import datetime

from broker.adapter import BrokerAdapter
from data.source import get_data_source
from persistence.repository import Repository


def load_price_cache(
    broker: BrokerAdapter,
    repo: Repository,
    symbols: list[str],
    start: str,
    end: str,
    timeframe: str = "1Day",
) -> dict:
    """Load historical bars into the SQLite cache via the single data source.

    1Day → MarketDataSource (adjusted, consolidated). Other timeframes → broker.
    """
    total = 0
    if timeframe == "1Day":
        data = get_data_source().get_daily_bars(symbols, start, end)
        for _sym, bars in data.items():
            if bars:
                repo.save_price_bars(bars)
                total += len(bars)
    else:
        for symbol in symbols:
            bars = broker.get_historical_data(
                symbol, datetime.fromisoformat(start), datetime.fromisoformat(end), timeframe)
            if bars:
                repo.save_price_bars(bars)
                total += len(bars)
    return {"symbols": symbols, "bars_loaded": total, "timeframe": timeframe}


def query_price_cache(
    repo: Repository,
    symbol: str,
    start: str,
    end: str,
    timeframe: str = "1Day",
) -> list[dict]:
    """Query cached price data from SQLite."""
    return repo.query_price_data(symbol, start, end, timeframe)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools && uv run --extra dev pytest tests/test_data_cache.py -v`
Expected: 1 passed.

- [ ] **Step 5: Run the full suite (no regressions from the rewire)**

Run: `cd tools && uv run --extra dev pytest tests/ -q`
Expected: all green (prior count + the new tests).

- [ ] **Step 6: Commit**

```bash
cd /Users/zelyuh/workplace/trading-system
git add tools/data/cache.py tools/tests/test_data_cache.py
git commit -m "refactor(data): load_price_cache writes 1Day via MarketDataSource"
```

---

## Task 5: `get_market_data` tool → consolidated last price

**Files:**
- Modify: `tools/server.py` (the `get_market_data` MCP tool, ~lines 210-224)
- Create: `tools/tests/test_get_market_data_tool.py`

**Interfaces:**
- Consumes: `data.source.get_data_source` (Task 1).
- Produces: `get_market_data(symbol)` returns JSON `{"symbol", "price", "mid", "source", "as_of"}` or `{"error": ...}`. `mid` retained == `price` for backward-compat.

- [ ] **Step 1: Write the failing test** (`tools/tests/test_get_market_data_tool.py`)

```python
"""get_market_data must return a consolidated price from the data source."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import server


class _FakeSource:
    def get_last_price(self, symbol):
        return 123.45


def test_get_market_data_uses_data_source(monkeypatch):
    monkeypatch.setattr(server, "get_data_source", lambda: _FakeSource(), raising=False)
    out = json.loads(server.get_market_data("AAPL"))
    assert out["symbol"] == "AAPL"
    assert out["price"] == 123.45
    assert out["mid"] == 123.45


def test_get_market_data_handles_missing(monkeypatch):
    class _None:
        def get_last_price(self, s): return None
    monkeypatch.setattr(server, "get_data_source", lambda: _None(), raising=False)
    out = json.loads(server.get_market_data("AAPL"))
    assert "error" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_get_market_data_tool.py -v`
Expected: FAIL (tool still calls `broker.get_market_data`; `server.get_data_source` not defined).

- [ ] **Step 3: Add the import and rewrite the tool body**

In `tools/server.py`, add near the other imports (top of file, by the `from data.cache import ...` area or after `get_broker`):

```python
from data.source import get_data_source
```

Replace the `get_market_data` tool body (keep its `@mcp.tool()` decorator and docstring) with:

```python
    _track_tool("get_market_data")
    try:
        px = get_data_source().get_last_price(symbol)
    except Exception as e:  # never raise to the agent
        return json.dumps({"error": f"data source failed: {e}"})
    if px is None:
        return json.dumps({"error": f"no price available for {symbol}"})
    return json.dumps({
        "symbol": symbol, "price": px, "mid": px,
        "source": __import__("os").environ.get("TRADING_DATA_SOURCE", "yfinance"),
        "as_of": datetime.utcnow().isoformat(),
    })
```

> Note: the VIX path in `get_market_regime` and the options code call `broker.get_market_data` directly and are intentionally unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools && uv run --extra dev pytest tests/test_get_market_data_tool.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/zelyuh/workplace/trading-system
git add tools/server.py tools/tests/test_get_market_data_tool.py
git commit -m "fix(server): get_market_data returns consolidated price (was IEX quote mid)"
```

---

## Task 6: Staleness guard in the scan tools

**Files:**
- Modify: `tools/server.py` (`scan_swing_candidates` ~2438-2445 and `scan_for_candidates` ~2357-2361 return blocks)
- Modify: `tools/tests/test_data_validate.py` (the staleness predicate is already covered; add a wiring assertion here)
- Create: `tools/tests/test_scan_staleness.py`

**Interfaces:**
- Consumes: `data.validate.freshness_report`, `data.validate.is_stale`.
- Produces: both scan tools' JSON gains `"as_of"`, `"data_stale"` (bool), `"stale_count"` (int).

- [ ] **Step 1: Write the failing test** (`tools/tests/test_scan_staleness.py`)

```python
"""Scan tools must surface data staleness instead of a silent empty result."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import server


def test_scan_swing_reports_staleness(monkeypatch):
    # Force an empty universe load so we exercise only the staleness annotation.
    monkeypatch.setattr(server, "_universe_symbols", lambda b: ["AAA"], raising=False)

    class _Repo:
        def query_price_data(self, *a, **k): return []
        def latest_price_date(self, s, tf="1Day"): return "2026-06-12T00:00:00+00:00"
    monkeypatch.setattr(server, "get_repo", lambda: _Repo())

    class _Broker:  # no current_time → live branch uses utcnow()
        pass
    monkeypatch.setattr(server, "get_broker", lambda: _Broker())

    out = json.loads(server.scan_swing_candidates("AAA"))
    assert "data_stale" in out and "as_of" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_scan_staleness.py -v`
Expected: FAIL — `KeyError: 'data_stale'`.

- [ ] **Step 3: Implement** — in `scan_swing_candidates`, before `return json.dumps({...})`, add:

```python
    from data.validate import freshness_report, is_stale
    scan_date = end.strftime("%Y-%m-%d")
    fresh = freshness_report(repo, [s for s in symbol_list if s != "SPY"])
    stale_flag = is_stale(fresh["freshest"], scan_date)
```

and extend the returned dict with:

```python
        "as_of": fresh["freshest"],
        "data_stale": stale_flag,
        "stale_count": len(fresh["stale"]) + len(fresh["missing"]),
```

Apply the same three additions to `scan_for_candidates` (compute `scan_date` from its own `end`, reuse `symbol_list`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools && uv run --extra dev pytest tests/test_scan_staleness.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/zelyuh/workplace/trading-system
git add tools/server.py tools/tests/test_scan_staleness.py
git commit -m "feat(scanner): surface data staleness (as_of/data_stale) in scan output"
```

---

## Task 7: Re-tool `load_universe.py` (adjusted source, fix default, clean reload)

**Files:**
- Modify: `tools/scripts/load_universe.py`
- Create: `tools/tests/test_load_universe_helpers.py`

**Interfaces:**
- Consumes: `data.source.get_data_source`, `Repository.clear_price_data`, `data.validate.find_price_anomalies`.
- Produces: helper `_default_daily_end() -> str` (yesterday, `YYYY-MM-DD`). Script now: fetches Stage-2 + Stage-3 bars via the data source; wipes 1Day before Stage-3; prints an anomaly summary after load.

- [ ] **Step 1: Write the failing test** (`tools/tests/test_load_universe_helpers.py`)

```python
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.load_universe import _default_daily_end


def test_default_daily_end_is_yesterday():
    assert _default_daily_end() == (date.today() - timedelta(days=1)).isoformat()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_load_universe_helpers.py -v`
Expected: FAIL — `ImportError: cannot import name '_default_daily_end'`.

- [ ] **Step 3: Implement helper + rewire** in `tools/scripts/load_universe.py`:

Add near the top (after imports):

```python
from datetime import date, timedelta

def _default_daily_end() -> str:
    """Yesterday (UTC) — avoids the previous stale hardcoded default."""
    return (date.today() - timedelta(days=1)).isoformat()
```

Change the arg default (was `default="2025-12-05"`):

```python
    ap.add_argument("--daily-end", default=_default_daily_end())
```

Replace the Stage-2 fetch (the `data.get_stock_bars(StockBarsRequest(... PREFILTER ...))` block) and the Stage-3 fetch (the `... daily_start/daily_end ...` block) with data-source calls. Concretely, at the top of `main()` after parsing args:

```python
    from data.source import get_data_source
    src = get_data_source()
```

Stage 2 per-chunk becomes:

```python
        bars_map = src.get_daily_bars(chunk, PREFILTER_START, PREFILTER_END)
        for sym, blist in bars_map.items():
            if len(blist) < 15:
                continue
            closes = [b["close"] for b in blist]
            dvols = [b["close"] * b["volume"] for b in blist]
            avg_close = sum(closes) / len(closes)
            adv = sum(dvols) / len(dvols)
            if 10 <= avg_close <= 500 and adv >= 50_000_000:
                survivors[sym] = adv
```

Before Stage 3 (clean re-load to avoid duplicate-PK rows from the format change):

```python
    deleted = repo.clear_price_data("1Day")
    print(f"Cleared {deleted} existing 1Day bars before clean reload")
```

Stage 3 per-chunk becomes:

```python
        bars_map = src.get_daily_bars(chunk, args.daily_start, args.daily_end)
        rows = [b for blist in bars_map.values() for b in blist]
        if rows:
            repo.save_price_bars(rows)
            total += len(rows)
```

After Stage 3, add a validation summary:

```python
    from data.validate import find_price_anomalies
    flagged = 0
    for sym in to_load:
        flagged += len(find_price_anomalies(
            repo.query_price_data(sym, args.daily_start, args.daily_end + "T23:59:59", "1Day")))
    print(f"Validation: {flagged} >35% single-day moves across the universe "
          f"(should be ~0 on adjusted data; investigate if high)")
```

Remove the now-unused Alpaca `StockBarsRequest`/`TimeFrame` imports **only if** nothing else in the file uses them.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools && uv run --extra dev pytest tests/test_load_universe_helpers.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/zelyuh/workplace/trading-system
git add tools/scripts/load_universe.py tools/tests/test_load_universe_helpers.py
git commit -m "refactor(load_universe): adjusted data source, yesterday default, clean reload + validation"
```

---

## Task 8: `refresh_market_data` tool, cron, and the one-time corrective re-load

**Files:**
- Modify: `tools/server.py` (add `refresh_market_data` MCP tool)
- Create: `cron/trading-data-refresh.sh`
- Modify: `cron/README-kanban.md` (document the refresh job)
- Modify: `.env.EXAMPLE` (document `TRADING_DATA_SOURCE`)
- Create: `tools/tests/test_refresh_tool.py`

**Interfaces:**
- Consumes: `data.source.get_data_source`, `_universe_symbols`, `data.validate.freshness_report`, `Repository.save_price_bars`.
- Produces: `refresh_market_data(daily_end: str = "", lookback_days: int = 400) -> str` JSON `{"refreshed": N, "bars": M, "as_of": ..., "aligned": bool}` or `{"error": ...}`.

- [ ] **Step 1: Write the failing test** (`tools/tests/test_refresh_tool.py`)

```python
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import server


class _Src:
    def get_daily_bars(self, symbols, start, end):
        return {symbols[0]: [{"symbol": symbols[0], "timestamp": "2026-06-19T00:00:00+00:00",
                              "open": 1, "high": 1, "low": 1, "close": 1, "volume": 9,
                              "timeframe": "1Day"}]}


def test_refresh_market_data(monkeypatch):
    monkeypatch.setattr(server, "get_data_source", lambda: _Src(), raising=False)
    monkeypatch.setattr(server, "_universe_symbols", lambda b: ["AAA"], raising=False)

    class _Repo:
        saved = []
        def save_price_bars(self, bars): _Repo.saved += bars
        def latest_price_date(self, s, tf="1Day"): return "2026-06-19T00:00:00+00:00"
    monkeypatch.setattr(server, "get_repo", lambda: _Repo())
    monkeypatch.setattr(server, "get_broker", lambda: object())

    out = json.loads(server.refresh_market_data("2026-06-20"))
    assert out["bars"] == 1
    assert out["refreshed"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_refresh_tool.py -v`
Expected: FAIL — `AttributeError: module 'server' has no attribute 'refresh_market_data'`.

- [ ] **Step 3: Implement the tool** (add near the scan tools in `tools/server.py`)

```python
@mcp.tool()
def refresh_market_data(daily_end: str = "", lookback_days: int = 400) -> str:
    """Refresh the universe's daily bars from the data source (single writer).

    When to use: pre-market daily (cron), or any time the scan reports data_stale.
    Fetches adjusted bars for the full universe through `daily_end` (default
    yesterday) and reports freshness. Sample: refresh_market_data("2026-06-20").
    Output: {"refreshed": 399, "bars": 144000, "as_of": "2026-06-19", "aligned": true}
    """
    _track_tool("refresh_market_data")
    from datetime import date, timedelta
    from data.validate import freshness_report
    try:
        repo = get_repo()
        symbols = _universe_symbols(get_broker())
        if "SPY" not in symbols:
            symbols.append("SPY")
        end = daily_end or (date.today() - timedelta(days=1)).isoformat()
        start = (date.fromisoformat(end) - timedelta(days=lookback_days)).isoformat()
        data = get_data_source().get_daily_bars(symbols, start, end)
        bars = 0
        for _s, blist in data.items():
            if blist:
                repo.save_price_bars(blist)
                bars += len(blist)
        fresh = freshness_report(repo, [s for s in symbols if s != "SPY"])
        return json.dumps({"refreshed": len(data), "bars": bars,
                           "as_of": fresh["freshest"], "aligned": fresh["aligned"]})
    except Exception as e:
        return json.dumps({"error": f"refresh failed: {e}"})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools && uv run --extra dev pytest tests/test_refresh_tool.py -v`
Expected: 1 passed.

- [ ] **Step 5: Add the cron script** (`cron/trading-data-refresh.sh`)

```bash
#!/usr/bin/env bash
# Pre-market daily refresh of the universe's adjusted daily bars (single writer).
# Schedule before the morning scan, e.g. 6:15 PT weekdays.
set -euo pipefail
cd "$(dirname "$0")/../tools"
exec uv run python scripts/load_universe.py
```

Then: `chmod +x cron/trading-data-refresh.sh`

Document it in `cron/README-kanban.md` under a new "## 3. Data refresh" section:

```markdown
## 3. Data refresh (pre-market, before the scan)

```bash
hermes cron create '15 6 * * 1-5' --name trading-data-refresh \
  --script trading-data-refresh.sh --no-agent
```
Keeps the DB's daily bars current and consistent. If it fails, the morning
scan still runs but reports `data_stale` (loud, not silent).
```

Add to `.env.EXAMPLE`:

```bash
# Market data source for price bars/quotes (Alpaca stays the execution broker).
# Options: yfinance (default, free, consolidated, split-adjusted).
TRADING_DATA_SOURCE=yfinance
```

- [ ] **Step 6: One-time corrective re-load (network; the real fix)**

Run:
```bash
cd /Users/zelyuh/workplace/trading-system/tools && uv run python scripts/load_universe.py
```
Expected: "Cleared N existing 1Day bars…", history batches load, "Validation: ~0 >35% single-day moves".

- [ ] **Step 7: Verify the fix against the original symptoms**

Run:
```bash
cd /Users/zelyuh/workplace/trading-system/tools && uv run python -c "
import sqlite3, json
from data.validate import freshness_report
from persistence.repository import Repository
con=sqlite3.connect('trading.db'); cur=con.cursor()
for s in ('ORLY','IBKR','SPY'):
    cur.execute(\"SELECT MIN(close),MAX(close),MAX(substr(timestamp,1,10)) FROM price_data WHERE symbol=? AND timeframe='1Day'\",(s,))
    print(s, cur.fetchone())
uni=json.load(open('universe_backtest.json'))['symbols']
rep=freshness_report(Repository(), uni)
print('aligned=',rep['aligned'],'n_fresh=',rep['n_fresh'],'stale=',len(rep['stale']),'missing=',len(rep['missing']),'as_of=',rep['freshest'])
"
```
Expected: ORLY/IBKR no longer span a split cliff (max/min ratio sane); `aligned=True`; `as_of` ≈ yesterday; `stale`/`missing` ≈ 0.

- [ ] **Step 8: Full suite + commit**

```bash
cd /Users/zelyuh/workplace/trading-system
cd tools && uv run --extra dev pytest tests/ -q && cd ..
git add tools/server.py tools/tests/test_refresh_tool.py cron/trading-data-refresh.sh cron/README-kanban.md .env.EXAMPLE
git commit -m "feat(data): refresh_market_data tool + pre-market cron + corrective reload"
```

> Note: `tools/trading.db` is gitignored — the corrective re-load changes local data only; nothing to commit there.

---

## Self-Review

**Spec coverage (Phase 2.0 + 2.1):**
- Data-source adapter (yfinance, swappable) → Task 1. ✅
- Single writer (no IEX bars behind the adapter) → Task 4 (`load_price_cache`) + Task 7 (`load_universe`). ✅
- `get_market_data` consolidated price (the wrong-price bug) → Task 5. ✅
- Data-validation check (anomalies + freshness + alignment) → Task 2, surfaced in Task 7 (load) and Task 8 (refresh). ✅
- Cross-symbol freshness alignment → Task 2 `freshness_report`, verified Task 8 Step 7. ✅
- One-time re-load → Task 8 Step 6. ✅
- Cron refresh + staleness guard + fixed `--daily-end` default → Task 8 (cron + tool), Task 6 (guard), Task 7 (default). ✅
- Re-baseline (re-run gate histogram on corrected data) → Task 8 Step 7 verifies data; the gate-histogram re-run belongs to Plan 2/3 once telemetry exists — noted, not dropped.

**Placeholder scan:** none — every code/command step has concrete content.

**Type consistency:** `get_daily_bars -> dict[str, list[dict]]` consumed consistently in Tasks 4, 7, 8; `freshness_report` keys (`freshest/n_fresh/stale/missing/aligned`) used identically in Tasks 2, 6, 8; bar-dict keys match `save_price_bars` everywhere.

**Out of scope (later plans):** scan-funnel telemetry + EOD zero-reason (Plan 2 — observability); catalyst-gate reconcile + first paper trade (Plan 3); version single-source-of-truth (Plan 4).
