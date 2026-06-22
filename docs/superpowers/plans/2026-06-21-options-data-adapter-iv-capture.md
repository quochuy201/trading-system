# Options Data Adapter + IV-Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a swappable `OptionsDataSource` adapter that fetches perishable options data **live** (sanity-gated) and accrues per-name **IV history** daily, so per-name IV-rank becomes usable over time — the foundation for the options scanner/routing (spec §6 plan 1).

**Architecture:** Mirror the Plan-1 `MarketDataSource` pattern. A new `tools/data/options_source.py` wraps the existing broker option methods + the existing ATM-IV/rank math; the *only* persisted options data is `iv_history` (already a table). Live fetches are sanity-gated; captured IV points are anomaly-validated. A daily `capture_iv_universe` job + cron extends today's SPY-only accrual to the whole universe. Reuses existing code — does not rebuild IV math.

**Tech Stack:** Python 3.11+, Alpaca options (INDICATIVE feed), SQLite (`iv_history`), MCP tools, pytest.

## Global Constraints

- Python ≥ 3.11; PEP 8; type hints on public functions; Google-style docstrings.
- **Fetch-live for perishable data** (chains, greeks, quotes, current IV) — **never persist them.** The *only* stored options data is `iv_history`.
- **Sanity-gate every live fetch**; **anomaly-validate every captured IV point.**
- `OptionsDataSource` adapter is **swappable** via env `TRADING_OPTIONS_SOURCE` (default `alpaca`); Alpaca stays the execution broker.
- MCP tools must never raise to the agent — return `{"error": "..."}` JSON.
- **DRY:** reuse the existing `_get_atm_iv` logic (relocated to a shared home), `Repository.save_iv_data_batch / query_iv_history / count_iv_history`, and `analysis.options.calc_iv_rank`. No second ATM-IV or rank implementation.
- Tests: `cd tools && uv run --extra dev pytest tests/ -v`. Temp DB via `Repository(":memory:")`; test files start with `sys.path.insert(0, str(Path(__file__).parent.parent))`. **Unit tests must not hit the network** — pass a fake broker.
- `iv_history` row shape (existing): `{symbol, date, iv, source}`; `query_iv_history(symbol, min_days=60) -> list[float]` (ASC by date; returns `[]` if fewer than `min_days` points).

---

## File Structure

- **Modify** `tools/analysis/options.py` — add `atm_iv(chain)` (relocated from `server.py:_get_atm_iv`, the shared pure ATM-IV extractor).
- **Modify** `tools/server.py` — import/use `atm_iv` (replace the local `_get_atm_iv` body with a thin re-export to avoid touching call sites); add the `capture_iv_universe` MCP tool.
- **Create** `tools/data/options_validate.py` — pure `sanity_check_quote(contract)` and `iv_anomaly(prev_iv, new_iv, max_jump_pct)`.
- **Create** `tools/data/options_source.py` — `OptionsDataSource` ABC, `AlpacaOptionsSource`, `get_options_source()` factory.
- **Create** `tools/tests/test_options_validate.py`, `tools/tests/test_options_source.py`.
- **Create** `cron/trading-iv-capture.sh` + a note in `cron/README-kanban.md`.
- **Modify** `.env.EXAMPLE` — document `TRADING_OPTIONS_SOURCE`.

---

## Task 1: Relocate `atm_iv` to the shared options module (DRY)

**Files:**
- Modify: `tools/analysis/options.py` (add `atm_iv`)
- Modify: `tools/server.py` (`_get_atm_iv` at ~1819 → delegate to the shared fn)
- Test: `tools/tests/test_data_analysis.py` (append a test)

**Interfaces:**
- Produces: `analysis.options.atm_iv(chain: list[dict]) -> float | None`.

- [ ] **Step 1: Write the failing test** (append to `tools/tests/test_data_analysis.py`)

```python
class TestAtmIv:
    def test_atm_iv_averages_nearest_half_delta(self):
        from analysis.options import atm_iv
        chain = [
            {"type": "C", "iv": 0.30, "greeks": {"delta": 0.50}},
            {"type": "P", "iv": 0.34, "greeks": {"delta": -0.50}},
            {"type": "C", "iv": 0.90, "greeks": {"delta": 0.95}},  # far ITM, ignored
        ]
        assert atm_iv(chain) == 0.32

    def test_atm_iv_none_when_no_iv(self):
        from analysis.options import atm_iv
        assert atm_iv([{"type": "C", "iv": 0, "greeks": {"delta": 0.5}}]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_data_analysis.py::TestAtmIv -v`
Expected: FAIL with `ImportError: cannot import name 'atm_iv'`.

- [ ] **Step 3: Add `atm_iv` to `tools/analysis/options.py`** (paste the exact existing logic from `server.py:_get_atm_iv`)

```python
def atm_iv(chain: list[dict]) -> float | None:
    """Aggregate ATM IV: average of the call and put whose |delta| is nearest 0.50.

    Returns None if no suitable contract is found. (Relocated from server.py for
    reuse by the options data source.)
    """
    calls = [c for c in chain if c.get("type", "").upper() == "C" and c.get("iv", 0) > 0]
    puts = [c for c in chain if c.get("type", "").upper() == "P" and c.get("iv", 0) > 0]
    if not calls and not puts:
        return None
    ivs = []
    if calls:
        best_call = min(calls, key=lambda c: abs(abs(c.get("greeks", {}).get("delta", 0)) - 0.50))
        if abs(abs(best_call.get("greeks", {}).get("delta", 0)) - 0.50) < 0.15:
            ivs.append(best_call["iv"])
    if puts:
        best_put = min(puts, key=lambda c: abs(abs(c.get("greeks", {}).get("delta", 0)) - 0.50))
        if abs(abs(best_put.get("greeks", {}).get("delta", 0)) - 0.50) < 0.15:
            ivs.append(best_put["iv"])
    if not ivs:
        all_with_delta = [c for c in chain if c.get("iv", 0) > 0 and c.get("greeks", {}).get("delta")]
        if all_with_delta:
            best = min(all_with_delta, key=lambda c: abs(abs(c["greeks"]["delta"]) - 0.50))
            return best["iv"]
        return None
    return sum(ivs) / len(ivs)
```

- [ ] **Step 4: Point `server.py:_get_atm_iv` at the shared fn** — replace the body of `_get_atm_iv` (≈ `server.py:1819`) with a delegation, leaving all call sites unchanged:

```python
def _get_atm_iv(chain: list[dict]) -> float | None:
    from analysis.options import atm_iv
    return atm_iv(chain)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd tools && uv run --extra dev pytest tests/test_data_analysis.py -v && cd tools && uv run --extra dev pytest tests/ -q`
Expected: new tests pass; full suite green (the relocation is behavior-preserving).

- [ ] **Step 6: Commit**

```bash
cd /Users/zelyuh/workplace/trading-system
git add tools/analysis/options.py tools/server.py tools/tests/test_data_analysis.py
git commit -m "refactor(options): relocate atm_iv to analysis.options (shared, DRY)"
```

---

## Task 2: Options validation (sanity gate + IV anomaly)

**Files:**
- Create: `tools/data/options_validate.py`
- Create: `tools/tests/test_options_validate.py`

**Interfaces:**
- Produces: `sanity_check_quote(contract: dict, max_rel_spread: float = 0.25) -> tuple[bool, str]`; `iv_anomaly(prev_iv: float | None, new_iv: float, max_jump_pct: float = 50.0) -> bool`.

- [ ] **Step 1: Write the failing test** (`tools/tests/test_options_validate.py`)

```python
"""Tests for options sanity/anomaly validation (pure, offline)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.options_validate import sanity_check_quote, iv_anomaly


def _q(bid=2.0, ask=2.1, iv=0.30):
    return {"bid": bid, "ask": ask, "mid": (bid + ask) / 2, "iv": iv,
            "greeks": {"delta": 0.5}}


def test_sanity_ok():
    ok, reason = sanity_check_quote(_q())
    assert ok and reason == ""


def test_sanity_rejects_one_sided():
    ok, reason = sanity_check_quote(_q(bid=0.0))
    assert not ok and "bid" in reason.lower()


def test_sanity_rejects_crossed():
    ok, _ = sanity_check_quote(_q(bid=2.5, ask=2.0))
    assert not ok


def test_sanity_rejects_wide_spread():
    ok, _ = sanity_check_quote(_q(bid=1.0, ask=2.0))  # 67% rel spread
    assert not ok


def test_sanity_rejects_absurd_iv():
    ok, _ = sanity_check_quote(_q(iv=7.0))
    assert not ok


def test_iv_anomaly():
    assert iv_anomaly(0.30, 0.60) is True       # +100% jump
    assert iv_anomaly(0.30, 0.33) is False       # +10%
    assert iv_anomaly(None, 0.30) is False       # no prior → not anomalous
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_options_validate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'data.options_validate'`.

- [ ] **Step 3: Implement** (`tools/data/options_validate.py`)

```python
"""Options data validation — sanity-gate live quotes, flag IV anomalies.

Pure functions so corruption from the INDICATIVE feed (synthetic/one-sided
quotes) is rejected before it sizes a trade or poisons the IV series.
"""


def sanity_check_quote(contract: dict, max_rel_spread: float = 0.25) -> tuple[bool, str]:
    """Return (ok, reason). Rejects missing/one-sided/crossed/too-wide quotes and absurd IV."""
    bid = float(contract.get("bid") or 0.0)
    ask = float(contract.get("ask") or 0.0)
    iv = float(contract.get("iv") or 0.0)
    if bid <= 0 or ask <= 0:
        return False, "missing/one-sided bid or ask"
    if ask < bid:
        return False, "crossed quote (ask < bid)"
    mid = (bid + ask) / 2
    if mid > 0 and (ask - bid) / mid > max_rel_spread:
        return False, f"spread too wide ({(ask - bid) / mid:.0%} > {max_rel_spread:.0%})"
    if not (0 < iv < 5):
        return False, f"implausible IV ({iv})"
    return True, ""


def iv_anomaly(prev_iv: float | None, new_iv: float, max_jump_pct: float = 50.0) -> bool:
    """True if new_iv jumps more than max_jump_pct vs the prior captured point."""
    if prev_iv is None or prev_iv <= 0:
        return False
    return abs(new_iv / prev_iv - 1) * 100 > max_jump_pct
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools && uv run --extra dev pytest tests/test_options_validate.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/zelyuh/workplace/trading-system
git add tools/data/options_validate.py tools/tests/test_options_validate.py
git commit -m "feat(options): sanity-gate + IV-anomaly validation"
```

---

## Task 3: `OptionsDataSource` adapter (live fetch, sanity-gated)

**Files:**
- Create: `tools/data/options_source.py`
- Create: `tools/tests/test_options_source.py`

**Interfaces:**
- Consumes: `data.options_validate.sanity_check_quote` (Task 2); a broker exposing `get_option_chain(underlying=...)` and `get_option_snapshot(list)`.
- Produces:
  - `class OptionsDataSource(ABC)` with `get_chain(symbol, dte_min=30, dte_max=45) -> list[dict]` and `get_snapshot(option_symbols) -> list[dict]`.
  - `class AlpacaOptionsSource(OptionsDataSource)` (constructed with a broker).
  - `get_options_source(broker, name=None) -> OptionsDataSource`.

- [ ] **Step 1: Write the failing test** (`tools/tests/test_options_source.py`)

```python
"""OptionsDataSource: live fetch is sanity-gated (offline, fake broker)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.options_source import AlpacaOptionsSource, get_options_source, OptionsDataSource


class _FakeBroker:
    def get_option_chain(self, underlying):
        return [
            {"type": "C", "iv": 0.3, "greeks": {"delta": 0.5}, "dte": 40, "bid": 2.0, "ask": 2.1, "mid": 2.05},
            {"type": "C", "iv": 0.3, "greeks": {"delta": 0.4}, "dte": 40, "bid": 0.0, "ask": 2.0, "mid": 1.0},  # one-sided → dropped
            {"type": "C", "iv": 0.3, "greeks": {"delta": 0.3}, "dte": 200, "bid": 1.0, "ask": 1.1, "mid": 1.05}, # out of DTE → dropped
        ]
    def get_option_snapshot(self, syms):
        return [{"symbol": syms[0], "bid": 1.0, "ask": 1.05, "mid": 1.025, "iv": 0.3, "greeks": {"delta": 0.5}}]


def test_get_chain_filters_dte_and_sanity():
    src = AlpacaOptionsSource(_FakeBroker())
    out = src.get_chain("AAPL", dte_min=30, dte_max=45)
    assert len(out) == 1            # one-sided dropped, out-of-DTE dropped
    assert out[0]["greeks"]["delta"] == 0.5


def test_factory_returns_adapter():
    assert isinstance(get_options_source(_FakeBroker()), OptionsDataSource)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_options_source.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'data.options_source'`.

- [ ] **Step 3: Implement** (`tools/data/options_source.py`)

```python
"""Options data source adapter — fetch perishable options data LIVE, sanity-gated.

Default = Alpaca (INDICATIVE feed). Swappable via env `TRADING_OPTIONS_SOURCE`.
The ONLY persisted options data is iv_history (see capture_iv_universe); chains,
greeks, and quotes are never stored.
"""

import os
from abc import ABC, abstractmethod

from data.options_validate import sanity_check_quote


class OptionsDataSource(ABC):
    @abstractmethod
    def get_chain(self, symbol: str, dte_min: int = 30, dte_max: int = 45) -> list[dict]:
        """Live option chain for symbol, filtered to [dte_min, dte_max] and sanity-gated."""

    @abstractmethod
    def get_snapshot(self, option_symbols: list[str]) -> list[dict]:
        """Live quote+greeks+IV for specific contracts, sanity-gated."""


class AlpacaOptionsSource(OptionsDataSource):
    def __init__(self, broker):
        self._broker = broker

    def get_chain(self, symbol: str, dte_min: int = 30, dte_max: int = 45) -> list[dict]:
        chain = self._broker.get_option_chain(underlying=symbol)
        out = []
        for c in chain:
            dte = c.get("dte", 0)
            if not (dte_min <= dte <= dte_max):
                continue
            ok, _ = sanity_check_quote(c)
            if ok:
                out.append(c)
        return out

    def get_snapshot(self, option_symbols: list[str]) -> list[dict]:
        snaps = self._broker.get_option_snapshot(option_symbols)
        return [s for s in snaps if sanity_check_quote(s)[0]]


def get_options_source(broker, name: str | None = None) -> OptionsDataSource:
    """Return the configured options data source (env `TRADING_OPTIONS_SOURCE`, default alpaca)."""
    name = (name or os.environ.get("TRADING_OPTIONS_SOURCE", "alpaca")).lower()
    if name == "alpaca":
        return AlpacaOptionsSource(broker)
    raise ValueError(f"unknown options data source: {name!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools && uv run --extra dev pytest tests/test_options_source.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/zelyuh/workplace/trading-system
git add tools/data/options_source.py tools/tests/test_options_source.py
git commit -m "feat(options): OptionsDataSource adapter (live, sanity-gated)"
```

---

## Task 4: Read-only `iv_rank` from accrued history

**Files:**
- Modify: `tools/data/options_source.py` (add `iv_rank` to the ABC + Alpaca impl, taking a repo)
- Modify: `tools/tests/test_options_source.py` (add a test)

**Interfaces:**
- Consumes: `Repository.query_iv_history(symbol, min_days)`, `analysis.options.calc_iv_rank(current_iv, iv_history)`.
- Produces: `OptionsDataSource.iv_rank(repo, symbol, min_days=60) -> dict` → `{"symbol","iv_rank","current_iv","data_points"}` or `{"error","data_points"}`. **Read-only** (no fetch, no save) — relies on `capture_iv_universe` having accrued history.

- [ ] **Step 1: Write the failing test** (append to `tools/tests/test_options_source.py`)

```python
def test_iv_rank_reads_history_only():
    from persistence.repository import Repository
    repo = Repository(":memory:")
    rows = [{"symbol": "AAA", "date": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
             "iv": 0.20 + (i % 40) * 0.005, "source": "snapshot"} for i in range(70)]
    repo.save_iv_data_batch(rows)
    src = AlpacaOptionsSource(_FakeBroker())
    out = src.iv_rank(repo, "AAA")
    assert out["data_points"] >= 60
    assert 0 <= out["iv_rank"] <= 100

def test_iv_rank_insufficient_history():
    from persistence.repository import Repository
    repo = Repository(":memory:")
    repo.save_iv_data("AAA", "2026-06-01", 0.3, "snapshot")
    out = AlpacaOptionsSource(_FakeBroker()).iv_rank(repo, "AAA")
    assert "error" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_options_source.py -k iv_rank -v`
Expected: FAIL — `AttributeError: 'AlpacaOptionsSource' object has no attribute 'iv_rank'`.

- [ ] **Step 3: Implement** — add to the ABC:

```python
    @abstractmethod
    def iv_rank(self, repo, symbol: str, min_days: int = 60) -> dict:
        """IV-rank from accrued iv_history (read-only). {symbol,iv_rank,current_iv,data_points} or {error,...}."""
```

and to `AlpacaOptionsSource`:

```python
    def iv_rank(self, repo, symbol: str, min_days: int = 60) -> dict:
        from analysis.options import calc_iv_rank
        hist = repo.query_iv_history(symbol, min_days=min_days)
        if not hist:
            return {"error": f"insufficient IV history for {symbol}",
                    "data_points": repo.count_iv_history(symbol)}
        current_iv = hist[-1]
        return {"symbol": symbol, "iv_rank": round(calc_iv_rank(current_iv, hist), 1),
                "current_iv": round(current_iv, 4), "data_points": len(hist)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools && uv run --extra dev pytest tests/test_options_source.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/zelyuh/workplace/trading-system
git add tools/data/options_source.py tools/tests/test_options_source.py
git commit -m "feat(options): read-only iv_rank from accrued history"
```

---

## Task 5: `capture_iv_universe` daily job + MCP tool

**Files:**
- Modify: `tools/data/options_source.py` (add `capture_iv` to the Alpaca impl)
- Modify: `tools/server.py` (add `capture_iv_universe` MCP tool)
- Create: `tools/tests/test_capture_iv.py`

**Interfaces:**
- Consumes: `analysis.options.atm_iv` (Task 1), `data.options_validate.iv_anomaly` (Task 2), `Repository.query_iv_history / save_iv_data_batch`.
- Produces: `AlpacaOptionsSource.capture_iv(repo, symbols, today) -> dict` (`{"captured","skipped","anomalies"}`); MCP `capture_iv_universe(symbols: str = "") -> str`.

- [ ] **Step 1: Write the failing test** (`tools/tests/test_capture_iv.py`)

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.options_source import AlpacaOptionsSource
from persistence.repository import Repository


class _Broker:
    def get_option_chain(self, underlying):
        return [{"type": "C", "iv": 0.30, "greeks": {"delta": 0.5}, "dte": 40, "bid": 2, "ask": 2.1, "mid": 2.05},
                {"type": "P", "iv": 0.34, "greeks": {"delta": -0.5}, "dte": 40, "bid": 2, "ask": 2.1, "mid": 2.05}]
    def get_option_snapshot(self, s): return []


def test_capture_iv_writes_history():
    repo = Repository(":memory:")
    out = AlpacaOptionsSource(_Broker()).capture_iv(repo, ["AAA", "BBB"], today="2026-06-21")
    assert out["captured"] == 2
    assert repo.count_iv_history("AAA") == 1
    assert abs(repo.query_iv_history("AAA", min_days=1)[0] - 0.32) < 1e-6  # avg of 0.30/0.34
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_capture_iv.py -v`
Expected: FAIL — `AttributeError: ... 'capture_iv'`.

- [ ] **Step 3: Implement** — add to `AlpacaOptionsSource`:

```python
    def capture_iv(self, repo, symbols: list[str], today: str) -> dict:
        """Capture today's ATM IV30 for each symbol into iv_history (anomaly-gated)."""
        from analysis.options import atm_iv
        from data.options_validate import iv_anomaly
        rows, skipped, anomalies = [], 0, 0
        for sym in symbols:
            try:
                chain = self._broker.get_option_chain(underlying=sym)
            except Exception:
                skipped += 1
                continue
            iv = atm_iv(chain)
            if iv is None:
                skipped += 1
                continue
            prior = repo.query_iv_history(sym, min_days=1)
            if iv_anomaly(prior[-1] if prior else None, iv):
                anomalies += 1
                continue
            rows.append({"symbol": sym, "date": today, "iv": iv, "source": "snapshot"})
        if rows:
            repo.save_iv_data_batch(rows)
        return {"captured": len(rows), "skipped": skipped, "anomalies": anomalies}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools && uv run --extra dev pytest tests/test_capture_iv.py -v`
Expected: 1 passed.

- [ ] **Step 5: Add the MCP tool** in `tools/server.py` (near the other options tools):

```python
@mcp.tool()
def capture_iv_universe(symbols: str = "") -> str:
    """Capture today's ATM IV30 for the universe into iv_history (daily accrual job).

    When to use: once daily after the close (cron), so per-name IV-rank accrues.
    Sample: capture_iv_universe("")  — full universe;  capture_iv_universe("AAPL,MSFT")
    Output: {"captured": 380, "skipped": 18, "anomalies": 2, "as_of": "2026-06-21"}
    """
    _track_tool("capture_iv_universe")
    from datetime import date
    from data.options_source import get_options_source
    try:
        broker = get_broker()
        repo = get_repo()
        syms = [s.strip() for s in symbols.split(",") if s.strip()] or _universe_symbols(broker)
        today = date.today().isoformat()
        res = get_options_source(broker).capture_iv(repo, syms, today)
        res["as_of"] = today
        return json.dumps(res)
    except Exception as e:
        return json.dumps({"error": f"iv capture failed: {e}"})
```

- [ ] **Step 6: Run full suite + commit**

```bash
cd tools && uv run --extra dev pytest tests/ -q && cd ..
git add tools/data/options_source.py tools/server.py tools/tests/test_capture_iv.py
git commit -m "feat(options): capture_iv_universe daily IV accrual job + MCP tool"
```

---

## Task 6: IV-capture cron + docs + seed run

**Files:**
- Create: `cron/trading-iv-capture.sh`
- Modify: `cron/README-kanban.md`, `.env.EXAMPLE`

**Interfaces:** consumes `capture_iv_universe` (Task 5).

- [ ] **Step 1: Create `cron/trading-iv-capture.sh`**

```bash
#!/usr/bin/env bash
# Daily after-close ATM IV30 capture for the universe → iv_history (per-name IVR accrual).
# Heavy (one chain fetch per name); the watchlist may be narrowed later for cost.
set -euo pipefail
cd "$(dirname "$0")/../tools"
exec uv run python -c "from server import capture_iv_universe; print(capture_iv_universe(''))"
```

Then: `chmod +x cron/trading-iv-capture.sh`

- [ ] **Step 2: Document in `cron/README-kanban.md`** (new section)

```markdown
## 4. IV capture (daily, after close — options IVR accrual)

```bash
hermes cron create '5 13 * * 1-5' --name trading-iv-capture \
  --script trading-iv-capture.sh --no-agent
```
Captures ATM IV30 per name into `iv_history` so per-name IV-rank (and credit-spread
routing) become usable over time. IV history cannot be backfilled — the sooner this
runs daily, the sooner IVR is trustworthy. (`5 13` PT = just after the 13:00 PT / 16:00 ET close.)
```

Add to `.env.EXAMPLE`:

```bash
# Options data source (Alpaca stays the execution broker). Default: alpaca (INDICATIVE feed).
TRADING_OPTIONS_SOURCE=alpaca
```

- [ ] **Step 3: Seed run + sanity-check it works live (network; small set first)**

Run:
```bash
cd /Users/zelyuh/workplace/trading-system/tools && uv run python -c "from server import capture_iv_universe; print(capture_iv_universe('AAPL,MSFT,NVDA,SPY,QQQ'))"
```
Expected: `{"captured": N, ...}` with N ≥ 1 (some names may skip if the INDICATIVE chain lacks ATM IV — that's acceptable; the cron will retry daily). Confirm rows landed:
```bash
cd /Users/zelyuh/workplace/trading-system/tools && uv run python -c "from persistence.repository import Repository; r=Repository(); print({s: r.count_iv_history(s) for s in ['AAPL','MSFT','NVDA','SPY']})"
```

- [ ] **Step 4: Commit**

```bash
cd /Users/zelyuh/workplace/trading-system
git add cron/trading-iv-capture.sh cron/README-kanban.md .env.EXAMPLE
git commit -m "feat(options): daily IV-capture cron + docs"
```

---

## Self-Review

**Spec coverage (spec §4.1 + §6 plan 1):**
- `OptionsDataSource` adapter, swappable, default Alpaca → Tasks 3–5. ✅
- Fetch-live + sanity-gate perishable data → Task 2 (gate) + Task 3 (applied). ✅
- Store-only IV history; daily accrual extending SPY-only → Task 5 + Task 6 cron. ✅
- Anomaly-validate captured IV → Task 2 (`iv_anomaly`) + Task 5 (applied). ✅
- `iv_rank` read-only for the future scanner → Task 4. ✅
- DRY ATM-IV (no second impl) → Task 1 relocation. ✅
- env `TRADING_OPTIONS_SOURCE` → Task 3 + Task 6 `.env.EXAMPLE`. ✅

**Placeholder scan:** none — every step has concrete code/commands.

**Type consistency:** `get_chain/get_snapshot/iv_rank/capture_iv` signatures consistent between the ABC, the impl, and the tests; `iv_history` row keys (`symbol/date/iv/source`) match `save_iv_data_batch`; `atm_iv(chain) -> float|None` consistent in Tasks 1 and 5.

**Decisions for the operator (flagged, not silently baked):**
- The cron captures the **full universe** (~400 chain fetches/day — heavy on the INDICATIVE feed). Narrowing to a curated optionable watchlist is a tuning point (noted in the cron script). Coverage vs. cost is the operator's call.
- Capture runs **after the close** (consistent daily IV30 snapshot). If INDICATIVE post-close data is thin, move the cron to ~12:45 PT (pre-close).

**Out of scope (later plans):** the mechanical `scan_universe_options` + routing matrix (plan 2); DD/execution wiring (plan 3); the equity-proxy validation harness (plan 4).
