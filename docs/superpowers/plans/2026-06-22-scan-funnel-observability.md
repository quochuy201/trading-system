# Scan-Funnel Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist and surface the full daily decision funnel — universe → loaded → passed mechanical (M/R) → regime/staleness → per-candidate verdicts → orders — so every trading day (especially zero-trade days) is auditable and "why nothing traded" is always answerable.

**Architecture:** Add a `scan_funnel` table written mechanically by the scan tools each run (reliable, agent-independent), plus an assembly tool that joins it with the existing `decisions` (enter/skip verdicts) and `transaction_ledger` (orders) for a date. The daily performance report renders the funnel and an explicit "why-zero" line. Telemetry only — it changes no trading decision.

**Tech Stack:** Python 3.11+, SQLite (`persistence/db.py` + `repository.py`), MCP tools (`tools/server.py`), pytest. Implements spec `docs/superpowers/specs/2026-06-20-live-trading-unblock-design.md` §1.1 + §3.3.

## Global Constraints

- Python ≥ 3.11; PEP 8; type hints on public functions; Google-style docstrings.
- **Telemetry only** — records/reports; never alters a trading decision or gate.
- **Emitted even on zero-candidate / zero-decision days** (the whole point).
- The scan tools persist the funnel **mechanically** (agent-independent), so it's complete even when the agent under-logs verdicts (we saw research narrate 6 enters but persist 2).
- New persistence = one `scan_funnel` table; reuse existing `decisions` + `transaction_ledger` for verdicts/orders. Add the table to the `SCHEMA` string in `persistence/db.py` (idempotent `CREATE TABLE IF NOT EXISTS`; `init_db` runs `executescript`).
- MCP tools must never raise to the agent — return `{"error": ...}`; funnel-persistence inside the scan tools must be wrapped so a telemetry failure never breaks a scan.
- Tests: `cd tools && uv run --extra dev pytest tests/ -v`. Temp DB via `Repository(":memory:")`; test files start with `sys.path.insert(0, str(Path(__file__).parent.parent))`. Offline.

---

## File Structure

- **Modify** `tools/persistence/db.py` — add `scan_funnel` CREATE TABLE to `SCHEMA`.
- **Modify** `tools/persistence/repository.py` — `save_scan_funnel(row)`, `query_scan_funnel(date)`.
- **Modify** `tools/server.py` — scan tools persist a funnel row; new `get_daily_funnel(date)` MCP tool; `generate_performance_report` includes the funnel; `_write_report_markdown` renders it.
- **Create** `tools/tests/test_scan_funnel.py`.
- **Modify** `skills/eod-review/SKILL.md` (state why-zero) and `skills/research/SKILL.md` (log every candidate verdict).

---

## Task 1: `scan_funnel` table + repository methods

**Files:**
- Modify: `tools/persistence/db.py` (add CREATE TABLE before the closing `"""` of `SCHEMA`, ~line 245)
- Modify: `tools/persistence/repository.py` (add two methods near `save_iv_data`)
- Create: `tools/tests/test_scan_funnel.py`

**Interfaces:**
- Produces: `Repository.save_scan_funnel(row: dict) -> None`; `Repository.query_scan_funnel(date: str) -> list[dict]`. Row keys: `date, timestamp, scan_type, universe_size, loaded, scanned, passed, passed_m, passed_r, data_stale, as_of, candidates`.

- [ ] **Step 1: Write the failing test** (`tools/tests/test_scan_funnel.py`)

```python
"""Tests for scan_funnel persistence + assembly."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from persistence.repository import Repository


def _row(date="2026-06-22", **kw):
    base = dict(date=date, timestamp=f"{date}T06:40:00", scan_type="swing",
                universe_size=400, loaded=400, scanned=400, passed=11,
                passed_m=6, passed_r=5, data_stale=0, as_of="2026-06-18",
                candidates='[]')
    base.update(kw)
    return base


def test_save_and_query_scan_funnel():
    repo = Repository(":memory:")
    repo.save_scan_funnel(_row())
    rows = repo.query_scan_funnel("2026-06-22")
    assert len(rows) == 1
    assert rows[0]["passed_m"] == 6 and rows[0]["passed"] == 11
    assert rows[0]["as_of"] == "2026-06-18"
    assert repo.query_scan_funnel("2026-06-21") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_scan_funnel.py -v`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'save_scan_funnel'`.

- [ ] **Step 3: Add the table** in `tools/persistence/db.py` — insert immediately before the line `"""` that closes `SCHEMA` (right after the `iv_history` table, ~line 244):

```sql
CREATE TABLE IF NOT EXISTS scan_funnel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    scan_type TEXT NOT NULL,
    universe_size INTEGER,
    loaded INTEGER,
    scanned INTEGER,
    passed INTEGER,
    passed_m INTEGER,
    passed_r INTEGER,
    data_stale INTEGER,
    as_of TEXT,
    candidates TEXT
);
```

- [ ] **Step 4: Add repo methods** in `tools/persistence/repository.py` (after `save_iv_data_batch` / the iv methods):

```python
    def save_scan_funnel(self, row: dict) -> None:
        """Persist one scan-funnel record (mechanical scan stats for a run)."""
        self.conn.execute(
            """INSERT INTO scan_funnel
            (date, timestamp, scan_type, universe_size, loaded, scanned, passed,
             passed_m, passed_r, data_stale, as_of, candidates)
            VALUES (:date, :timestamp, :scan_type, :universe_size, :loaded, :scanned,
             :passed, :passed_m, :passed_r, :data_stale, :as_of, :candidates)""",
            row,
        )
        self.conn.commit()

    def query_scan_funnel(self, date: str) -> list[dict]:
        """All scan-funnel records for a date (newest first)."""
        rows = self.conn.execute(
            "SELECT * FROM scan_funnel WHERE date = ? ORDER BY timestamp DESC", (date,)
        ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd tools && uv run --extra dev pytest tests/test_scan_funnel.py -v`
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
cd /Users/zelyuh/workplace/trading-system
git add tools/persistence/db.py tools/persistence/repository.py tools/tests/test_scan_funnel.py
git commit -m "feat(funnel): scan_funnel table + repository persistence"
```

---

## Task 2: Scan tools persist a funnel row each run

**Files:**
- Modify: `tools/server.py` (`scan_swing_candidates` and `scan_for_candidates`, just before each `return json.dumps(...)`)
- Modify: `tools/tests/test_scan_funnel.py` (add a wiring test)

**Interfaces:**
- Consumes: `Repository.save_scan_funnel` (Task 1). Uses values already computed in the scan tool: `symbol_list`, `stock_data`, `candidates`, `fresh`/`stale_flag` (the staleness block), and the per-candidate `engine_m_pass`/`engine_r_pass`.
- Produces: a `scan_funnel` row written on every scan (mechanical; agent-independent).

- [ ] **Step 1: Write the failing test** (append to `tools/tests/test_scan_funnel.py`)

```python
def test_scan_swing_persists_funnel(monkeypatch):
    import server
    monkeypatch.setattr(server, "_universe_symbols", lambda b: ["AAA"], raising=False)

    class _Repo:
        saved = []
        def query_price_data(self, *a, **k): return []
        def latest_price_date(self, s, tf="1Day"): return "2026-06-18T00:00:00+00:00"
        def save_scan_funnel(self, row): _Repo.saved.append(row)
    monkeypatch.setattr(server, "get_repo", lambda: _Repo())
    monkeypatch.setattr(server, "get_broker", lambda: object())

    server.scan_swing_candidates("AAA")
    assert len(_Repo.saved) == 1
    row = _Repo.saved[0]
    assert row["scan_type"] == "swing"
    assert "passed" in row and "passed_m" in row and "as_of" in row
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_scan_funnel.py::test_scan_swing_persists_funnel -v`
Expected: FAIL — `_Repo.saved` is empty (no persistence yet).

- [ ] **Step 3: Implement** — in `scan_swing_candidates`, after the staleness block (`fresh = freshness_report(...)`, `stale_flag = is_stale(...)`) and before `return json.dumps({...})`, add:

```python
    # --- funnel telemetry (mechanical; never breaks the scan) ---
    try:
        from datetime import datetime as _dt
        import json as _json
        repo.save_scan_funnel({
            "date": scan_date,
            "timestamp": _dt.utcnow().isoformat(),
            "scan_type": "swing",
            "universe_size": len(symbol_list),
            "loaded": len(stock_data) - (1 if "SPY" in stock_data else 0),
            "scanned": len(stock_data) - (1 if "SPY" in stock_data else 0),
            "passed": len(candidates),
            "passed_m": sum(1 for c in candidates if c.get("engine_m_pass")),
            "passed_r": sum(1 for c in candidates if c.get("engine_r_pass")),
            "data_stale": 1 if stale_flag else 0,
            "as_of": fresh["freshest"],
            "candidates": _json.dumps([
                {"symbol": c["symbol"],
                 "m": bool(c.get("engine_m_pass")), "r": bool(c.get("engine_r_pass"))}
                for c in candidates]),
        })
    except Exception:
        pass  # telemetry must never break the scan
```

For `scan_for_candidates` (4-layer, no engine flags), add the same block with `"scan_type": "4layer"`, `passed_m`/`passed_r` set to `0`, and `candidates` = `_json.dumps([{"symbol": c["symbol"]} for c in candidates])`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools && uv run --extra dev pytest tests/test_scan_funnel.py -v`
Expected: all pass.

- [ ] **Step 5: Full suite + commit**

```bash
cd tools && uv run --extra dev pytest tests/ -q && cd ..
git add tools/server.py tools/tests/test_scan_funnel.py
git commit -m "feat(funnel): scan tools persist a funnel row each run"
```

---

## Task 3: `get_daily_funnel(date)` assembly tool

**Files:**
- Modify: `tools/server.py` (new MCP tool)
- Create: `tools/tests/test_daily_funnel.py`

**Interfaces:**
- Consumes: `Repository.query_scan_funnel` (Task 1), `Repository.query_decisions(...)`, `Repository.query_ledger(...)`.
- Produces: `get_daily_funnel(date: str = "") -> str` JSON: `{date, scan, verdicts:{entered,skipped,enter_list,skip_list}, orders, why_zero}` — populated even on zero days.

- [ ] **Step 1: Write the failing test** (`tools/tests/test_daily_funnel.py`)

```python
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import server


def test_get_daily_funnel_zero_day(monkeypatch):
    class _Repo:
        def query_scan_funnel(self, date):
            return [{"scan_type": "swing", "scanned": 400, "passed": 11,
                     "passed_m": 6, "passed_r": 5, "data_stale": 0,
                     "as_of": "2026-06-18", "candidates": "[]"}]
        def query_decisions(self, **k): return []        # agent logged nothing
        def query_ledger(self, **k): return []            # no orders
    monkeypatch.setattr(server, "get_repo", lambda: _Repo())
    out = json.loads(server.get_daily_funnel("2026-06-22"))
    assert out["scan"]["passed"] == 11
    assert out["verdicts"]["entered"] == 0
    assert out["orders"] == 0
    assert "11 passed" in out["why_zero"] and "0 entered" in out["why_zero"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_daily_funnel.py -v`
Expected: FAIL — `AttributeError: module 'server' has no attribute 'get_daily_funnel'`.

- [ ] **Step 3: Implement** (add to `tools/server.py`)

```python
@mcp.tool()
def get_daily_funnel(date: str = "") -> str:
    """Assemble the full decision funnel for a date — even on zero-trade days.

    When to use: EOD review, or any time you must answer "why did/didn't it trade?"
    Joins the mechanical scan record with the agent's enter/skip verdicts and the
    orders actually placed. Sample: get_daily_funnel("2026-06-22").
    Output: {"date","scan":{...},"verdicts":{"entered","skipped",...},"orders","why_zero"}
    """
    _track_tool("get_daily_funnel")
    from datetime import date as _date
    try:
        repo = get_repo()
        d = date or _date.today().isoformat()
        scans = repo.query_scan_funnel(d)
        scan = scans[0] if scans else {}
        decisions = repo.query_decisions(start_date=d, end_date=d, limit=2000)
        ledger = repo.query_ledger(start_date=d, end_date=d, limit=2000)
        enters = [x for x in decisions if (x.get("action") or "") == "enter"]
        skips = [x for x in decisions if (x.get("action") or "") == "skip"]
        n_orders = len([x for x in ledger if (x.get("action") or "") in ("buy", "sell")])
        passed = scan.get("passed", 0)
        if scan.get("data_stale"):
            why = f"DATA_STALE (as_of {scan.get('as_of')}) — scan ran on stale data"
        elif not scan:
            why = "no scan recorded for this date (cycle did not run)"
        elif passed == 0:
            why = f"0 passed mechanical gates of {scan.get('scanned', 0)} scanned — no setups"
        elif not enters:
            why = f"{passed} passed mechanical, 0 entered — agent skipped all (see skip_list)"
        else:
            why = f"{passed} passed, {len(enters)} entered, {n_orders} order(s) placed"
        return json.dumps({
            "date": d, "scan": scan,
            "verdicts": {"entered": len(enters), "skipped": len(skips),
                         "enter_list": [{"symbol": x.get("symbol"), "why": x.get("reasoning")} for x in enters],
                         "skip_list": [{"symbol": x.get("symbol"), "why": x.get("reasoning")} for x in skips]},
            "orders": n_orders, "why_zero": why,
        }, default=str)
    except Exception as e:
        return json.dumps({"error": f"funnel assembly failed: {e}"})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools && uv run --extra dev pytest tests/test_daily_funnel.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/zelyuh/workplace/trading-system
git add tools/server.py tools/tests/test_daily_funnel.py
git commit -m "feat(funnel): get_daily_funnel assembly tool (scan + verdicts + orders + why_zero)"
```

---

## Task 4: Render the funnel in the daily report

**Files:**
- Modify: `tools/server.py` (`generate_performance_report` adds the funnel to `metrics`; `_write_report_markdown` renders it)
- Modify: `tools/tests/test_scan_funnel.py` (assert the markdown contains the funnel)

**Interfaces:**
- Consumes: `get_daily_funnel` (Task 3).
- Produces: `metrics["funnel"]` in the report dict; a `## Scan Funnel` section + a **Why no trades** line in `report_<start>_to_<end>.md`.

- [ ] **Step 1: Write the failing test** (append to `tools/tests/test_scan_funnel.py`)

```python
def test_report_markdown_includes_funnel(monkeypatch, tmp_path):
    import server
    # funnel content the renderer should print
    monkeypatch.setattr(server, "get_daily_funnel",
                        lambda d="": '{"scan":{"scanned":400,"passed":11,"passed_m":6,"passed_r":5,"as_of":"2026-06-18","data_stale":0},"verdicts":{"entered":0,"skipped":11},"orders":0,"why_zero":"11 passed mechanical, 0 entered — agent skipped all"}',
                        raising=False)
    metrics = {"trading": {"total_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
                           "expectancy": 0.0, "total_pnl": 0.0, "avg_winner": 0.0,
                           "avg_loser": 0.0, "max_drawdown": 0.0},
               "compliance": {"total_decisions": 0, "compliant": 0,
                              "compliance_rate": 1.0, "by_type": {}},
               "funnel": server.get_daily_funnel("2026-06-22")}

    class _R:  # minimal report stub
        report_id = "r1"
    path = server._write_report_markdown(_R(), metrics, "2026-06-22", "2026-06-22")
    text = Path(path).read_text()
    assert "Scan Funnel" in text
    assert "Why no trades" in text
    assert "11 passed mechanical, 0 entered" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_scan_funnel.py::test_report_markdown_includes_funnel -v`
Expected: FAIL — "Scan Funnel" not in the markdown.

- [ ] **Step 3: Implement** — (a) in `generate_performance_report`, after building `metrics` and before saving, add the funnel keyed by the report's end date:

```python
    metrics["funnel"] = get_daily_funnel(end_date)
```

(b) in `_write_report_markdown`, after the existing `lines` are built (after the AI Compliance section, before writing the file), append:

```python
    import json as _json
    funnel_raw = metrics.get("funnel")
    if funnel_raw:
        try:
            fn = _json.loads(funnel_raw) if isinstance(funnel_raw, str) else funnel_raw
        except Exception:
            fn = {}
        sc = fn.get("scan", {}) or {}
        v = fn.get("verdicts", {}) or {}
        lines += [
            "",
            "## Scan Funnel",
            "",
            "| Stage | Value |",
            "|-------|-------|",
            f"| Scanned | {sc.get('scanned', 0)} |",
            f"| Passed mechanical | {sc.get('passed', 0)} (M {sc.get('passed_m', 0)} / R {sc.get('passed_r', 0)}) |",
            f"| Data as-of | {sc.get('as_of', 'n/a')}{' (STALE)' if sc.get('data_stale') else ''} |",
            f"| Entered | {v.get('entered', 0)} |",
            f"| Skipped | {v.get('skipped', 0)} |",
            f"| Orders placed | {fn.get('orders', 0)} |",
            "",
            f"**Why no trades:** {fn.get('why_zero', 'n/a')}",
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools && uv run --extra dev pytest tests/test_scan_funnel.py -v`
Expected: all pass.

- [ ] **Step 5: Full suite + commit**

```bash
cd tools && uv run --extra dev pytest tests/ -q && cd ..
git add tools/server.py tools/tests/test_scan_funnel.py
git commit -m "feat(funnel): render scan funnel + why-no-trades in the daily report"
```

---

## Task 5: EOD "no ambiguous zeros" + research per-candidate logging (behavior)

**Files:**
- Modify: `skills/eod-review/SKILL.md`
- Modify: `skills/research/SKILL.md`

**Interfaces:** behavior/markdown only — relies on `get_daily_funnel` (Task 3) and the existing `log_decision`.

- [ ] **Step 1: EOD — require a why-zero from the funnel.** In `skills/eod-review/SKILL.md`, in the journal/zero-trade-day section, add:

```markdown
**No ambiguous zeros (required):** On any day with 0 closed trades, call
`get_daily_funnel(<today>)` and record the `why_zero` verdict in the journal —
state explicitly whether it was: `0 passed mechanical` (no setups), `N passed,
0 entered` (agent skipped all — list why), or `DATA_STALE`. A zero-trade day is
never reported without this reason.
```

- [ ] **Step 2: Research — log EVERY candidate verdict.** In `skills/research/SKILL.md` Decision Logging section, strengthen it to:

```markdown
**Log every candidate (mandatory for the funnel):** call `log_decision` for
EACH candidate the scanner returned — `action="enter"` for every pick (with
rules_triggered + one-line thesis) AND `action="skip"` for every rejection
(with the specific veto in rules_triggered). Do not summarize only in prose:
the funnel and EOD review reconstruct the day from these logged decisions, so a
narrated-but-unlogged enter/skip is invisible. One `log_decision` per candidate.
```

- [ ] **Step 3: Verify markdown only (no tests) + commit**

```bash
cd /Users/zelyuh/workplace/trading-system
git add skills/eod-review/SKILL.md skills/research/SKILL.md
git commit -m "docs(skills): EOD why-zero from funnel + research logs every candidate verdict"
```

> After merge, run `./install.sh hermes` to deploy the two skill changes to the profiles (tool changes are live from the repo via the MCP launcher).

---

## Self-Review

**Spec coverage (§1.1 + §3.3):**
- Funnel persisted (universe→loaded→passed M/R→staleness→candidates) → Task 1 (table) + Task 2 (scan tools write it). ✅
- Per-candidate verdicts + orders joined in → Task 3 (`get_daily_funnel` reads decisions + ledger). ✅
- Emitted even on zero days → Task 3 `why_zero` + Task 4 renders it regardless of trade count. ✅
- Surfaced in the daily report → Task 4. ✅
- Replaces scratch `test_scan*.py` (archived) with one first-class tool → `get_daily_funnel`. ✅
- §3.3 no ambiguous zeros → Task 5 EOD skill. ✅
- Fixes the partial-logging gap (research narrated 6, logged 2) → Task 5 research skill (log every candidate) + Task 2 mechanical funnel is complete regardless. ✅
- Telemetry never breaks a scan → Task 2 try/except; tools return `{"error":...}` → Task 3. ✅

**Placeholder scan:** none — every step has concrete code/commands.

**Type consistency:** `scan_funnel` row keys (`date/timestamp/scan_type/universe_size/loaded/scanned/passed/passed_m/passed_r/data_stale/as_of/candidates`) identical across Task 1 (schema + repo), Task 2 (writer), Task 3 (reader). `get_daily_funnel` output keys (`scan/verdicts/orders/why_zero`) consumed identically in Task 4.

**Out of scope (YAGNI):** a standalone Discord funnel push (the EOD summary already goes to Discord and now carries the funnel); historical backfill of the funnel for past days; a funnel UI.
