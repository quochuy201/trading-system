# Engine B Directional-Swing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refine options Engine B into a long-only, 2–4 week directional-swing strategy with armed-plan intraday entry confirmation, a hybrid exit (underlying trail + premium scale-out), bounded adaptive confirmation params, and a 3-leg (technical + social + LLM) research procedure.

**Architecture:** New SOP version `options/vol-edge/v1.1.0` (markdown) plus three new Python units in `tools/` — a bounded-params loader, an armed-plan store, and a sentinel extension — wired into the existing `monitor_sentinel.py`. No DB schema change: armed plans live in their own JSON store so the live `trade_plans` table is untouched. Skill/reference markdown documents the behavior for the LLM workers.

**Tech Stack:** Python 3.11+ (stdlib + dataclasses), pytest, existing MCP `server.py` tool layer, JSON file stores, markdown SOPs/skills.

**Spec:** `docs/superpowers/specs/2026-06-14-engine-b-directional-swing-design.md`

---

## File Structure

| File | Responsibility | New/Modify |
|---|---|---|
| `tools/confirmation_params.py` | Load + clamp bounded confirmation params to SOP rails | Create |
| `tools/confirmation_params.json` | Committed default param values | Create |
| `tools/armed_plans.py` | ArmedPlan dataclass + JSON store (arm/list/cancel/fill) | Create |
| `tools/monitor_sentinel.py` | Add armed-plan entry-trigger pass alongside exit pass | Modify |
| `tools/tests/test_confirmation_params.py` | Tests for clamping/defaults | Create |
| `tools/tests/test_armed_plans.py` | Tests for the armed-plan store | Create |
| `tools/tests/test_sentinel_armed.py` | Tests for the sentinel armed-plan pass | Create |
| `sops/options/vol-edge/v1.1.0.md` | Refined Engine B SOP | Create |
| `skills/research/reference/options-vol-edge-dd.md` | 3-leg DD + armed-plan output procedure | Modify |
| `skills/monitor/SKILL.md` | Armed-plan confirmation + hybrid exit behavior | Modify |
| `skills/eod-review/SKILL.md` | Weekly param-review-and-propose step | Modify |
| `.gitignore` | ignore runtime `armed_plans.json` state | Modify |

**Build order rationale:** params loader → armed-plan store → sentinel wiring (each depends on the prior), then the markdown docs (SOP/skills) which reference the code that now exists.

---

## Task 1: Bounded confirmation-params loader

**Files:**
- Create: `tools/confirmation_params.json`
- Create: `tools/confirmation_params.py`
- Test: `tools/tests/test_confirmation_params.py`

- [ ] **Step 1: Write the committed default params file**

Create `tools/confirmation_params.json`:

```json
{
  "version": "2026-06-14",
  "confirmation_window_min": 30,
  "rvol_multiple": 1.2,
  "entry_cutoff_et": "11:00",
  "slippage_buffer_pct": 0.75,
  "regime": "default"
}
```

- [ ] **Step 2: Write the failing test**

Create `tools/tests/test_confirmation_params.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from confirmation_params import load_params, RAILS


def test_defaults_load_and_are_within_rails():
    p = load_params()
    assert p["confirmation_window_min"] == 30
    assert p["rvol_multiple"] == 1.2
    assert p["entry_cutoff_et"] == "11:00"


def test_out_of_range_values_are_clamped(tmp_path):
    bad = tmp_path / "p.json"
    bad.write_text('{"confirmation_window_min": 999, "rvol_multiple": 0.1, '
                   '"slippage_buffer_pct": 50}')
    p = load_params(path=bad)
    assert p["confirmation_window_min"] == RAILS["confirmation_window_min"][1]  # max 90
    assert p["rvol_multiple"] == RAILS["rvol_multiple"][0]                      # min 1.1
    assert p["slippage_buffer_pct"] == RAILS["slippage_buffer_pct"][1]          # max 2.0


def test_missing_file_returns_safe_defaults(tmp_path):
    p = load_params(path=tmp_path / "does_not_exist.json")
    assert p["confirmation_window_min"] == 30
    assert p["rvol_multiple"] == 1.2
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_confirmation_params.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'confirmation_params'`

- [ ] **Step 4: Write the loader**

Create `tools/confirmation_params.py`:

```python
"""Bounded loader for adaptive confirmation parameters.

The confirmation LOGIC lives in the SOP; only these PARAMETER VALUES adapt, and
every value is clamped to a hard rail the LLM/EOD review can never exceed. This
keeps adaptation safe (no reckless rule can be written) and backtests pinnable.
"""

import json
from pathlib import Path

_DEFAULT_PATH = Path(__file__).parent / "confirmation_params.json"

# (min, max) hard rails — adaptation may move within these, never beyond.
RAILS = {
    "confirmation_window_min": (15, 90),
    "rvol_multiple": (1.1, 2.0),
    "slippage_buffer_pct": (0.25, 2.0),
}

_DEFAULTS = {
    "version": "default",
    "confirmation_window_min": 30,
    "rvol_multiple": 1.2,
    "entry_cutoff_et": "11:00",
    "slippage_buffer_pct": 0.75,
    "regime": "default",
}


def _clamp(name: str, value):
    lo, hi = RAILS[name]
    return max(lo, min(hi, value))


def load_params(path: Path | None = None) -> dict:
    """Load params, falling back to defaults, with every railed key clamped."""
    path = path or _DEFAULT_PATH
    params = dict(_DEFAULTS)
    try:
        params.update(json.loads(Path(path).read_text()))
    except Exception:
        pass  # missing/corrupt -> safe defaults
    for name in RAILS:
        if name in params:
            try:
                params[name] = _clamp(name, float(params[name]))
            except (TypeError, ValueError):
                params[name] = _DEFAULTS[name]
    # window is an int count of minutes
    params["confirmation_window_min"] = int(params["confirmation_window_min"])
    return params
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd tools && uv run --extra dev pytest tests/test_confirmation_params.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add tools/confirmation_params.py tools/confirmation_params.json tools/tests/test_confirmation_params.py
git commit -m "feat(options): bounded confirmation-params loader with hard rails"
```

---

## Task 2: Armed-plan store

**Files:**
- Create: `tools/armed_plans.py`
- Test: `tools/tests/test_armed_plans.py`
- Modify: `.gitignore`

- [ ] **Step 1: Write the failing test**

Create `tools/tests/test_armed_plans.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from armed_plans import ArmedPlan, ArmedPlanStore


def _store(tmp_path):
    return ArmedPlanStore(path=tmp_path / "armed.json")


def test_arm_and_list(tmp_path):
    s = _store(tmp_path)
    p = ArmedPlan(symbol="NVDA", direction="long", structure="long_call",
                  trigger_price=220.0, invalidation_price=215.0,
                  cutoff_et="11:00", rationale="breakout")
    s.arm(p)
    active = s.list_active()
    assert len(active) == 1
    assert active[0].symbol == "NVDA"
    assert active[0].status == "armed"


def test_cancel_marks_inactive(tmp_path):
    s = _store(tmp_path)
    p = ArmedPlan(symbol="AMD", direction="long", structure="call_debit",
                  trigger_price=170.0, invalidation_price=166.0,
                  cutoff_et="11:00", rationale="squeeze break")
    s.arm(p)
    s.cancel(p.plan_id, reason="cutoff passed")
    assert s.list_active() == []


def test_fill_marks_filled(tmp_path):
    s = _store(tmp_path)
    p = ArmedPlan(symbol="MSFT", direction="long", structure="long_call",
                  trigger_price=400.0, invalidation_price=394.0,
                  cutoff_et="11:00", rationale="pullback hold")
    s.arm(p)
    s.fill(p.plan_id)
    assert s.list_active() == []
    persisted = ArmedPlanStore(path=s.path).get(p.plan_id)
    assert persisted.status == "filled"


def test_persists_across_instances(tmp_path):
    path = tmp_path / "armed.json"
    s1 = ArmedPlanStore(path=path)
    s1.arm(ArmedPlan(symbol="NVDA", direction="long", structure="long_call",
                     trigger_price=220.0, invalidation_price=215.0,
                     cutoff_et="11:00", rationale="x"))
    s2 = ArmedPlanStore(path=path)
    assert len(s2.list_active()) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_armed_plans.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'armed_plans'`

- [ ] **Step 3: Write the store**

Create `tools/armed_plans.py`:

```python
"""Armed-plan store: pre-market trade plans that are armed but UNFILLED.

An armed plan carries an entry trigger + invalidation + cutoff. The monitor
sentinel watches these intraday and only fills (via the LLM monitor) when the
breakout confirms. Kept in its own JSON store so the live trade_plans DB table
is untouched. Statuses: armed -> filled | cancelled.
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path

_DEFAULT_PATH = Path(__file__).parent / "armed_plans.json"


def _new_id() -> str:
    return f"armed_{uuid.uuid4().hex[:10]}"


@dataclass
class ArmedPlan:
    symbol: str
    direction: str          # "long" only for v1.1.0
    structure: str          # "long_call" | "call_debit"
    trigger_price: float    # underlying level that must confirm
    invalidation_price: float
    cutoff_et: str          # e.g. "11:00"
    rationale: str
    dte_target: int = 40
    delta_target: float = 0.60
    status: str = "armed"   # armed | filled | cancelled
    cancel_reason: str = ""
    plan_id: str = field(default_factory=_new_id)


class ArmedPlanStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or _DEFAULT_PATH)

    def _read(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text())
        except Exception:
            return []

    def _write(self, rows: list[dict]) -> None:
        self.path.write_text(json.dumps(rows, indent=2, default=str))

    def arm(self, plan: ArmedPlan) -> None:
        rows = self._read()
        rows.append(asdict(plan))
        self._write(rows)

    def list_active(self) -> list[ArmedPlan]:
        return [ArmedPlan(**r) for r in self._read() if r.get("status") == "armed"]

    def get(self, plan_id: str) -> ArmedPlan | None:
        for r in self._read():
            if r.get("plan_id") == plan_id:
                return ArmedPlan(**r)
        return None

    def _set_status(self, plan_id: str, status: str, reason: str = "") -> None:
        rows = self._read()
        for r in rows:
            if r.get("plan_id") == plan_id:
                r["status"] = status
                if reason:
                    r["cancel_reason"] = reason
        self._write(rows)

    def cancel(self, plan_id: str, reason: str = "") -> None:
        self._set_status(plan_id, "cancelled", reason)

    def fill(self, plan_id: str) -> None:
        self._set_status(plan_id, "filled")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools && uv run --extra dev pytest tests/test_armed_plans.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Ignore the runtime state file**

Append to `.gitignore`:

```
# Armed-plan runtime store (pre-market plans awaiting intraday confirmation)
tools/armed_plans.json
```

- [ ] **Step 6: Commit**

```bash
git add tools/armed_plans.py tools/tests/test_armed_plans.py .gitignore
git commit -m "feat(options): armed-plan store for intraday entry confirmation"
```

---

## Task 3: Sentinel armed-plan trigger pass

**Files:**
- Modify: `tools/monitor_sentinel.py`
- Test: `tools/tests/test_sentinel_armed.py`

- [ ] **Step 1: Write the failing test**

Create `tools/tests/test_sentinel_armed.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import monitor_sentinel
from armed_plans import ArmedPlan, ArmedPlanStore


def test_armed_trigger_fires_when_price_reaches_trigger(tmp_path, monkeypatch):
    store = ArmedPlanStore(path=tmp_path / "armed.json")
    store.arm(ArmedPlan(symbol="NVDA", direction="long", structure="long_call",
                        trigger_price=220.0, invalidation_price=215.0,
                        cutoff_et="23:59", rationale="x"))
    monkeypatch.setattr(monitor_sentinel, "_armed_store", lambda: store)
    monkeypatch.setattr(monitor_sentinel, "_underlying_price", lambda s: 221.0)

    reasons = monitor_sentinel._armed_plan_triggers()
    assert any("NVDA" in r and "entry_confirm" in r for r in reasons)


def test_armed_no_trigger_below_trigger_price(tmp_path, monkeypatch):
    store = ArmedPlanStore(path=tmp_path / "armed.json")
    store.arm(ArmedPlan(symbol="NVDA", direction="long", structure="long_call",
                        trigger_price=220.0, invalidation_price=215.0,
                        cutoff_et="23:59", rationale="x"))
    monkeypatch.setattr(monitor_sentinel, "_armed_store", lambda: store)
    monkeypatch.setattr(monitor_sentinel, "_underlying_price", lambda s: 218.0)

    assert monitor_sentinel._armed_plan_triggers() == []


def test_armed_invalidation_cancels_plan(tmp_path, monkeypatch):
    store = ArmedPlanStore(path=tmp_path / "armed.json")
    store.arm(ArmedPlan(symbol="NVDA", direction="long", structure="long_call",
                        trigger_price=220.0, invalidation_price=215.0,
                        cutoff_et="23:59", rationale="x"))
    monkeypatch.setattr(monitor_sentinel, "_armed_store", lambda: store)
    monkeypatch.setattr(monitor_sentinel, "_underlying_price", lambda s: 214.0)

    reasons = monitor_sentinel._armed_plan_triggers()
    assert reasons == []                      # invalidation does not wake the LLM
    assert store.list_active() == []          # it cancels the plan
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_sentinel_armed.py -v`
Expected: FAIL — `AttributeError: module 'monitor_sentinel' has no attribute '_armed_plan_triggers'`

- [ ] **Step 3: Add the armed-plan helpers to the sentinel**

In `tools/monitor_sentinel.py`, add imports near the top (after the existing `import server` line):

```python
from armed_plans import ArmedPlanStore
```

Add these functions above `def main()`:

```python
def _armed_store() -> ArmedPlanStore:
    return ArmedPlanStore()


def _underlying_price(symbol: str) -> float | None:
    """Latest underlying price via the server tool; None on any failure."""
    try:
        data = json.loads(server.get_market_data(symbol))
        return data.get("mid") or data.get("price")
    except Exception:
        return None


def _armed_plan_triggers() -> list[str]:
    """Check each armed plan: confirm -> wake reason; invalidation -> cancel.

    Long-only (v1.1.0): trigger when underlying >= trigger_price; invalidate when
    underlying <= invalidation_price. Returns wake-reasons for confirmations only;
    invalidations are cancelled silently (no LLM wake).
    """
    reasons: list[str] = []
    store = _armed_store()
    for plan in store.list_active():
        price = _underlying_price(plan.symbol)
        if price is None:
            continue
        if price <= plan.invalidation_price:
            store.cancel(plan.plan_id, reason=f"invalidation@{price}")
            continue
        if price >= plan.trigger_price:
            reasons.append(f"{plan.symbol}:entry_confirm@{price:.2f}:{plan.plan_id}")
    return reasons
```

- [ ] **Step 4: Wire armed triggers into `main()`**

In `tools/monitor_sentinel.py`, find in `main()`:

```python
    reasons = _reasons_to_wake()
    if not reasons:
        return 0  # quiet minute, no LLM, no output
```

Replace with:

```python
    reasons = _reasons_to_wake() + _armed_plan_triggers()
    if not reasons:
        return 0  # quiet minute, no LLM, no output
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd tools && uv run --extra dev pytest tests/test_sentinel_armed.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Run the full suite to confirm no regression**

Run: `cd tools && uv run --extra dev pytest tests/ -q`
Expected: PASS (all previously-passing tests still pass; new tests included)

- [ ] **Step 7: Commit**

```bash
git add tools/monitor_sentinel.py tools/tests/test_sentinel_armed.py
git commit -m "feat(monitor): sentinel watches armed plans for intraday entry confirmation"
```

---

## Task 4: SOP v1.1.0 (markdown, no tests)

**Files:**
- Create: `sops/options/vol-edge/v1.1.0.md`

- [ ] **Step 1: Write the SOP**

Create `sops/options/vol-edge/v1.1.0.md`. Copy `v1.0.0.md` as the base, then change ONLY the Engine B sections to match the spec. The Engine B section must state:

- **Scope:** long-only, SPY UPTREND only; short/bearish path reserved but NOT active (cite spec §3).
- **Scan funnel:** Stage 1 `scan_for_candidates` (bullish) → Stage 2 options hard gates (regime, RS sign, option-chain liquidity, earnings, IVR/IV-HV/skew) → Stage 3 3-leg DD → Stage 4 armed plan.
- **DTE:** 35–45. **Long-call delta:** 0.55–0.65. **Debit vertical:** buy 0.45–0.55, sell ~1.5–2 expected-moves OTM.
- **IVR committee:** <35 long call; >55 debit spread; 35–55 LLM tiebreak (default spread).
- **Earnings:** LLM judgment (skip / force-spread+downsize / hold-through), quant veto on IV-crush.
- **Entry:** two-phase — armed plan pre-market, intraday confirmation via sentinel+LLM, NO resting orders, immediate marketable order capped by `slippage_buffer_pct`.
- **Exit:** hybrid — underlying close-based trailing stop + premium scale-out (sell half at +50% max gain, runner rides trail); retain 21-DTE/2× loss/emergency guards.
- **Adaptive confirmation params:** bounded set in `tools/confirmation_params.json`, EOD/weekly propose-and-ratify to `reports/sop-changes/`, hard rails listed.
- **Sizing:** conviction down-only; never enlarge base; obey OPERATING_MANUAL quarter-Kelly.

Header note: "Supersedes v1.0.0 for Engine B only; Engine A unchanged. v1.0.0 retained for reproducibility."

- [ ] **Step 2: Verify the file is valid and complete**

Run: `grep -ciE "long-only|35.45 DTE|scale-out|no resting|propose-and-ratify" sops/options/vol-edge/v1.1.0.md`
Expected: ≥ 4 (each key concept present)

- [ ] **Step 3: Commit**

```bash
git add sops/options/vol-edge/v1.1.0.md
git commit -m "feat(sop): options vol-edge v1.1.0 — Engine B directional-swing (long-only)"
```

---

## Task 5: Research DD reference (3-leg + armed-plan output)

**Files:**
- Modify: `skills/research/reference/options-vol-edge-dd.md`

- [ ] **Step 1: Add the 3-leg DD + armed-plan section**

Append a new section "## Engine B — Directional Swing (v1.1.0)" to `skills/research/reference/options-vol-edge-dd.md` covering:

1. **Three-leg research** — Leg 1 technical (tools, continuation-setup gates), Leg 2 social via `WebSearch` + firecrawl (r/options, r/wallstreetbets, X; Reddit reached via web search, NOT direct crawl), Leg 3 LLM synthesis. Precedence: technical = veto gate; social = weighted context (discount gain-screenshots, read crowding contrarian); LLM = referee that must log how legs reconcile; on conflict → safer structure + smaller size.
2. **IVR committee** instrument selection (same thresholds as SOP).
3. **Armed-plan output format** — the research agent emits, per qualified candidate: `symbol, direction=long, structure, trigger_price, invalidation_price, cutoff_et, dte_target, delta_target, rationale` and then calls `notify_analysis`. State explicitly: research produces an ARMED PLAN, never an order.

- [ ] **Step 2: Verify**

Run: `grep -ciE "three-leg|armed plan|trigger_price|firecrawl|WebSearch" skills/research/reference/options-vol-edge-dd.md`
Expected: ≥ 4

- [ ] **Step 3: Commit**

```bash
git add skills/research/reference/options-vol-edge-dd.md
git commit -m "docs(research): 3-leg DD + armed-plan output for Engine B v1.1.0"
```

---

## Task 6: Monitor skill — confirmation + hybrid exit

**Files:**
- Modify: `skills/monitor/SKILL.md`

- [ ] **Step 1: Add the armed-plan confirmation + hybrid-exit section**

Append a section "## Engine B Directional-Swing (v1.1.0)" to `skills/monitor/SKILL.md` covering:

1. **Entry confirmation (Phase B):** when woken by a sentinel `entry_confirm` reason, re-validate real-vs-trap (first 15–30 min bar closes above trigger, no engulfing reversal, RVOL ≥ params `rvol_multiple`); on confirm → place an IMMEDIATE marketable order (limit at/just above ask, capped by `slippage_buffer_pct`), call `armed_plans` fill + `notify_buy`; on fail or cutoff → cancel plan, log "stood down". NO resting orders.
2. **Hybrid exit:** stop trails on the underlying close (close-based; trail up only); profit scales out — sell half at +50% of max gain (premium), runner rides the underlying trail; LLM confirms at the premium-target touch (sentinel wakes it), then immediate order; NO resting sell limit. Retain 21-DTE / 2× loss / kill-switch / gap-through-strike guards. `notify_sell` on each exit.

- [ ] **Step 2: Verify**

Run: `grep -ciE "armed|marketable|scale out|no resting|close-based" skills/monitor/SKILL.md`
Expected: ≥ 4

- [ ] **Step 3: Commit**

```bash
git add skills/monitor/SKILL.md
git commit -m "docs(monitor): Engine B armed-plan confirmation + hybrid exit"
```

---

## Task 7: EOD weekly param-review step

**Files:**
- Modify: `skills/eod-review/SKILL.md`

- [ ] **Step 1: Add the weekly param-proposal step**

Append a section "## Weekly: Engine B confirmation-param review (propose-and-ratify)" to `skills/eod-review/SKILL.md` covering:

- On the weekly review, analyze CLOSED confirmation + exit outcomes keyed to regime (confirmed-and-followed-through vs. confirmed-and-trapped; stood-down-but-would-have-worked).
- If evidence supports a change, write a PROPOSAL to `reports/sop-changes/YYYY-MM-DD-engineb-confirm-params.md` with old→new values, the bounded rail each stays within (cite `tools/confirmation_params.py` RAILS), regime context, and the trade evidence.
- **NEVER edit `tools/confirmation_params.json` or `sops/` directly** — human ratifies the proposal first (matches CLAUDE.md). State that backtests pin the param `version`, so a change is reproducible.

- [ ] **Step 2: Verify**

Run: `grep -ciE "propose|ratif|reports/sop-changes|rail|never edit" skills/eod-review/SKILL.md`
Expected: ≥ 4

- [ ] **Step 3: Commit**

```bash
git add skills/eod-review/SKILL.md
git commit -m "docs(eod): weekly Engine B confirmation-param propose-and-ratify step"
```

---

## Task 8: Full-suite regression + spec cross-check

**Files:** none (verification only)

- [ ] **Step 1: Run the complete test suite**

Run: `cd tools && uv run --extra dev pytest tests/ -q`
Expected: PASS — all tests green (existing + Tasks 1–3 new tests).

- [ ] **Step 2: Confirm tool-group counts unchanged**

The new Python units are NOT new MCP tools (no `@mcp.tool()` added), so the tool-group test must still pass unchanged.
Run: `cd tools && uv run --extra dev pytest tests/test_tool_groups.py -v`
Expected: PASS (55-tool count unchanged).

- [ ] **Step 3: Spec coverage check**

Run: `ls sops/options/vol-edge/v1.1.0.md tools/confirmation_params.py tools/armed_plans.py && grep -l "armed" tools/monitor_sentinel.py`
Expected: all paths listed, no errors — every spec artifact (§9) exists.

- [ ] **Step 4: Final commit (if any verification fixes were needed)**

```bash
git add -A
git commit -m "test(options): Engine B v1.1.0 regression + spec cross-check" || echo "nothing to commit"
```

---

## Notes for the implementer

- **No DB migration.** Armed plans deliberately live in `tools/armed_plans.json`, not the `trade_plans` table — keeps the live schema untouched and the feature self-contained.
- **No new MCP tools.** Tasks 1–3 add internal Python the sentinel uses; they are not `@mcp.tool()`s, so tool-group scoping and counts are unaffected.
- **Backtest path:** the armed-plan/confirmation flow is live-trading machinery (intraday minute loop). Backtesting the confirmation logic is a follow-up (the harness steps bars differently) and is intentionally out of this plan's scope — note it for a later spec rather than faking it here.
- **Markdown tasks (4–7)** have no unit tests by nature; the `grep` verification steps are the check that the required concepts are present.
