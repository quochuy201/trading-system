# Strategy Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the agent auto-select which strategy(ies) to apply per market-scoped session — a risk-manager eligibility gate (regime → ON/OFF) plus research setup-routing (candidate → eligible strategy), sharing one account risk budget.

**Architecture:** A new pure `get_market_regime` MCP tool returns *raw* regime signals (no decision). A versioned, human-authored `sops/_routing/v1.0.0.md` holds the ON/OFF eligibility table (§1, applied by risk-manager) and the setup-routing table (§2, applied by research). `config.yaml` gains a strategy registry. Skill/SOUL edits wire the roles together. Per `CLAUDE.md`, *no strategy logic goes in Python* — the tool only measures; the SOP decides; the LLM applies.

**Tech Stack:** Python 3.11 + FastMCP (`tools/server.py`), `pandas`/`ta` for indicators, pytest (`cd tools && uv run --extra dev pytest`), Markdown skills/SOPs.

**Spec:** [`docs/specs/2026-06-06-strategy-routing-design.md`](../specs/2026-06-06-strategy-routing-design.md). Read §10 (resolved decisions) before starting.

**Scope of this plan:** Spec rollout **P0–P2** (buildable + unit-testable now). The statistical/backtest validation (spec §8.3 gate-vs-control) **depends on the Phase-4 backtest engine and is explicitly out of scope here** — see "Deferred" at the end. Ship behind paper-only with the registry enabling a single strategy until validation lands.

---

## File Structure

| File | New/Mod | Responsibility |
|---|---|---|
| `tools/analysis/regime.py` | **New** | Pure function: SPY bars (+ injected vix/iv_rank) → raw regime snapshot dict. No decisions. |
| `tools/tests/test_regime.py` | **New** | Unit tests for the pure regime function. |
| `tools/server.py` | Mod | `get_market_regime()` MCP tool wrapper: fetch data, call pure fn, return JSON. |
| `tools/tests/test_registry.py` | **New** | Guard test: every `config.yaml` strategy id resolves to an existing `sops/<id>/` dir. |
| `config.yaml` | Mod | `strategies:` registry (enabled/disabled + per-strategy `market`). |
| `sops/_routing/v1.0.0.md` | **New** | Human-authored routing SOP: §1 eligibility table, §2 setup-routing table. |
| `skills/risk-manager/SKILL.md` | Mod | Preflight item #8 → compute eligible set from regime + §1; output block. |
| `skills/research/SKILL.md` | Mod | Consume eligible set + snapshot; route candidates via §2; group output by strategy. |
| `SOUL.md` | Mod | Session market scope; obtain eligible set; one shared budget; reword Rule 3. |
| `docs/plans/2026-06-06-routing-golden-cases.md` | **New** | Agent dry-run golden cases for the eligibility gate (LLM-applied, not pytest). |

**Boundary note:** `regime.py` is *pure* (repo + injected scalars in, dict out) so it is fully unit-testable; the flaky data fetches (vix quote, SPY IV-rank) live only in the thin `server.py` wrapper. The eligibility *decision* is LLM-applied from the SOP — validated by golden-case dry-runs (Task 9), not pytest, because encoding it in Python would violate the "no strategy logic in code" rule.

---

## Task 1: Strategy registry in config.yaml + resolver guard test

**Files:**
- Modify: `config.yaml` (append a `strategies:` block)
- Test: `tools/tests/test_registry.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tools/tests/test_registry.py
"""Guard: every strategy id in config.yaml resolves to an existing SOP directory."""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
CONFIG = ROOT / "config.yaml"


def _all_strategy_entries() -> list[dict]:
    cfg = yaml.safe_load(CONFIG.read_text())
    strat = cfg.get("strategies", {})
    return list(strat.get("enabled", [])) + list(strat.get("disabled", []))


def test_strategies_block_present():
    cfg = yaml.safe_load(CONFIG.read_text())
    assert "strategies" in cfg, "config.yaml missing strategies: registry"
    assert "enabled" in cfg["strategies"]


def test_every_strategy_id_resolves_to_sop_dir():
    for entry in _all_strategy_entries():
        sid = entry["id"]
        sop_dir = ROOT / "sops" / sid
        assert sop_dir.is_dir(), f"strategy id '{sid}' has no sops/{sid}/ directory"


def test_every_enabled_strategy_has_market_and_sop():
    cfg = yaml.safe_load(CONFIG.read_text())
    for entry in cfg["strategies"]["enabled"]:
        assert entry.get("market"), f"{entry} missing 'market'"
        assert entry.get("sop"), f"{entry} missing 'sop'"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_registry.py -v`
Expected: FAIL — `test_strategies_block_present` asserts (no `strategies:` key yet). (Note: the `id_resolves` test also depends on the directory rename in Task 3's note below; for now enable only ids whose `sops/<id>/` already exists — see Step 3.)

- [ ] **Step 3: Add the registry block to `config.yaml`**

Append at end of `config.yaml`. Use only ids whose `sops/<id>/` directory exists today so the guard test passes immediately. (`options/vol-edge` currently lives at `sops/options-vol-edge/`; until the directory restructure renames it, register it under its current path.)

```yaml
# Strategy registry — which strategies exist and are enabled for this account.
# The agent reads this list (it does not drive Python logic). The session's
# --market scope (set by the scheduler) narrows 'enabled' to that market.
strategies:
  enabled:
    - id: options-vol-edge      # current path; becomes options/vol-edge after restructure
      market: options
      sop: v1.0.0
  disabled:
    - id: day-trade-momentum    # current path; becomes equity/intraday-momentum after restructure
      market: equity
      sop: v1.0.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools && uv run --extra dev pytest tests/test_registry.py -v`
Expected: PASS (3 tests). If `pyyaml` is missing: `cd tools && uv add --dev pyyaml` then re-run.

- [ ] **Step 5: Commit**

```bash
git add config.yaml tools/tests/test_registry.py
git commit -m "feat(routing): add strategy registry to config.yaml with resolver guard test"
```

---

## Task 2: Pure regime function — price-derived signals

**Files:**
- Create: `tools/analysis/regime.py`
- Test: `tools/tests/test_regime.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tools/tests/test_regime.py
"""Tests for the pure market-regime signal function."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from persistence.repository import Repository
from analysis.regime import compute_market_regime


def _bars(symbol: str, closes: list[float]) -> list[dict]:
    """Build daily bars from a list of closes; high/low straddle close by ±1."""
    out = []
    for i, c in enumerate(closes):
        out.append({
            "symbol": symbol,
            "timestamp": f"2026-01-{(i % 28) + 1:02d}T00:00:00",
            "open": round(c, 2), "high": round(c + 1, 2),
            "low": round(c - 1, 2), "close": round(c, 2),
            "volume": 1_000_000, "timeframe": "1Day",
        })
    # make timestamps strictly increasing across months
    for i, b in enumerate(out):
        b["timestamp"] = f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}T00:00:00"
    return out


class TestRegime:
    def setup_method(self):
        self.repo = Repository(":memory:")

    def teardown_method(self):
        self.repo.close()

    def test_uptrend_above_sma50(self):
        # 60 strictly rising closes -> price above SMA50, trend up
        self.repo.save_price_bars(_bars("SPY", [100 + i for i in range(60)]))
        r = compute_market_regime(self.repo, "SPY", "2026-01-01", "2026-12-31")
        assert r["spy_vs_sma50_pct"] > 0
        assert r["spy_trend"] == "up"
        assert r["spy_tr_atr"] is not None and r["spy_tr_atr"] > 0
        assert r["vix"] is None and r["iv_rank_spy"] is None  # not injected
        assert r["as_of"] is not None

    def test_downtrend_below_sma50(self):
        self.repo.save_price_bars(_bars("SPY", [160 - i for i in range(60)]))
        r = compute_market_regime(self.repo, "SPY", "2026-01-01", "2026-12-31")
        assert r["spy_vs_sma50_pct"] < 0
        assert r["spy_trend"] == "down"

    def test_injected_vix_and_ivrank_passthrough(self):
        self.repo.save_price_bars(_bars("SPY", [100 + i for i in range(60)]))
        r = compute_market_regime(
            self.repo, "SPY", "2026-01-01", "2026-12-31",
            vix=27.5, iv_rank_spy=82.0,
        )
        assert r["vix"] == 27.5
        assert r["iv_rank_spy"] == 82.0

    def test_insufficient_data_is_failsafe_null(self):
        self.repo.save_price_bars(_bars("SPY", [100 + i for i in range(10)]))  # <21 bars
        r = compute_market_regime(self.repo, "SPY", "2026-01-01", "2026-12-31")
        assert r["spy_tr_atr"] is None
        assert r["spy_vs_sma50_pct"] is None
        assert r["spy_trend"] is None
        assert "warning" in r
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && uv run --extra dev pytest tests/test_regime.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'analysis.regime'`.

- [ ] **Step 3: Write the implementation**

```python
# tools/analysis/regime.py
"""Pure market-regime signal computation.

Returns RAW measured signals only — never a classified regime and never an
eligibility decision. The routing SOP (sops/_routing/) maps these signals to
strategy ON/OFF, and the agent applies it. Keeping the decision out of Python
is required by CLAUDE.md (no strategy logic in code).

vix and iv_rank_spy are INJECTED by the caller (the MCP tool wrapper fetches
them) so this function stays pure and unit-testable. A missing signal is left
as None; the SOP treats None as fail-safe restrictive.
"""

from datetime import datetime, timezone

from persistence.repository import Repository


def _true_range(bar: dict, prev_close: float) -> float:
    hi, lo = float(bar["high"]), float(bar["low"])
    return max(hi - lo, abs(hi - prev_close), abs(lo - prev_close))


def compute_market_regime(
    repo: Repository,
    symbol: str = "SPY",
    start: str = "2000-01-01",
    end: str = "2100-01-01",
    timeframe: str = "1Day",
    vix: float | None = None,
    iv_rank_spy: float | None = None,
) -> dict:
    """Compute raw regime signals from cached index bars.

    Args:
        repo: price-data repository.
        symbol: index proxy (default "SPY").
        start, end: clock bounds; pass current_time as `end` for no-look-ahead.
        vix: injected VIX level (None if unavailable).
        iv_rank_spy: injected SPY IV-rank 0-100 (None if unavailable).

    Returns:
        dict: {vix, spy_tr_atr, spy_vs_sma50_pct, spy_trend, iv_rank_spy, as_of}
        Price-derived fields are None (with a "warning") when data is insufficient.
    """
    as_of = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "vix": vix,
        "spy_tr_atr": None,
        "spy_vs_sma50_pct": None,
        "spy_trend": None,
        "iv_rank_spy": iv_rank_spy,
        "as_of": as_of,
    }

    bars = repo.query_price_data(symbol, start, end, timeframe)
    if len(bars) < 21:
        snapshot["warning"] = f"insufficient data: {len(bars)} bars (need >= 21)"
        return snapshot

    closes = [float(b["close"]) for b in bars]

    # spy_tr_atr: today's true range / mean true range of prior 20 bars
    trs = [_true_range(bars[i], closes[i - 1]) for i in range(1, len(bars))]
    atr20 = sum(trs[-21:-1]) / 20.0           # 20 bars before today
    tr_today = trs[-1]
    snapshot["spy_tr_atr"] = round(tr_today / atr20, 3) if atr20 > 0 else None

    # spy_vs_sma50_pct: % of latest close above/below SMA50 (None if <50 bars)
    if len(closes) >= 50:
        sma50 = sum(closes[-50:]) / 50.0
        snapshot["spy_vs_sma50_pct"] = round((closes[-1] - sma50) / sma50 * 100, 2)

    # spy_trend: position vs SMA20 + SMA20 slope (up | down | flat)
    sma20_now = sum(closes[-20:]) / 20.0
    sma20_prev = sum(closes[-21:-1]) / 20.0
    rising = sma20_now > sma20_prev
    above = closes[-1] > sma20_now
    if above and rising:
        snapshot["spy_trend"] = "up"
    elif (not above) and (not rising):
        snapshot["spy_trend"] = "down"
    else:
        snapshot["spy_trend"] = "flat"

    return snapshot
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools && uv run --extra dev pytest tests/test_regime.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add tools/analysis/regime.py tools/tests/test_regime.py
git commit -m "feat(routing): pure market-regime signal function (raw signals, no decision)"
```

---

## Task 3: `get_market_regime` MCP tool wrapper

**Files:**
- Modify: `tools/server.py` (add tool near the other analysis tools, e.g. after `get_market_data`)

- [ ] **Step 1: Add the tool** (no new pytest — pure logic is tested in Task 2; the wrapper is thin I/O. Verify by import + a live smoke call.)

```python
@mcp.tool()
def get_market_regime(index_symbol: str = "SPY", vix_symbol: str = "") -> str:
    """Return RAW market-regime signals for the strategy-routing eligibility gate.

    When to use: Risk-Manager preflight, to apply the sops/_routing/ §1 eligibility
    table. Returns measurements only — it does NOT decide which strategy runs.

    Sample input: get_market_regime("SPY")
                  get_market_regime("SPY", "VIXY")

    Expected output:
    {"vix": 18.4, "spy_tr_atr": 0.92, "spy_vs_sma50_pct": 2.3, "spy_trend": "up",
     "iv_rank_spy": 41.0, "as_of": "2026-06-06T13:30:00+00:00"}

    Any signal that cannot be measured is null; the routing SOP treats null as
    fail-safe restrictive (the dependent strategy is OFF).
    """
    _track_tool("get_market_regime")
    from analysis.regime import compute_market_regime
    from datetime import timedelta

    broker = get_broker()
    repo = get_repo()

    # Clock bound: use sim time in backtest, else now (no-look-ahead).
    if hasattr(broker, "current_time") and broker.current_time:
        end_dt = broker.current_time
    else:
        end_dt = datetime.utcnow()
    start_dt = end_dt - timedelta(days=120)  # enough for SMA50 + 20-day ATR

    # Ensure index bars are cached for the window.
    from data.cache import load_price_cache
    try:
        load_price_cache(broker, repo, [index_symbol],
                         start_dt.date().isoformat(), end_dt.date().isoformat())
    except Exception:
        pass  # fall through; pure fn returns fail-safe nulls if data is short

    # Best-effort VIX quote (null on any failure).
    vix = None
    if vix_symbol:
        try:
            q = with_retry(broker.get_market_data, _retry_config)(vix_symbol)
            vix = float(q.get("mid")) if q.get("mid") is not None else None
        except Exception:
            vix = None

    # iv_rank_spy deferred to a follow-up (see plan "Deferred"); pass None for now.
    snapshot = compute_market_regime(
        repo, index_symbol,
        start=start_dt.isoformat(), end=end_dt.isoformat(),
        vix=vix, iv_rank_spy=None,
    )
    return json.dumps(snapshot)
```

- [ ] **Step 2: Verify the tool imports and the suite still passes**

Run: `cd tools && uv run --extra dev pytest tests/ -q`
Expected: PASS — all 208 existing tests + the new regime/registry tests green; no import errors.

- [ ] **Step 3: Live smoke check (paper)**

Run: `cd tools && uv run python -c "import server; print(server.get_market_regime('SPY'))"`
Expected: a JSON line with `spy_trend` set and `spy_tr_atr` a float (vix/iv_rank_spy null). If SPY data is unavailable, price fields are null + a `warning` — acceptable (fail-safe).

- [ ] **Step 4: Commit**

```bash
git add tools/server.py
git commit -m "feat(routing): add get_market_regime MCP tool (composes regime signals)"
```

---

## Task 4: Routing SOP — `sops/_routing/v1.0.0.md`

**Files:**
- Create: `sops/_routing/v1.0.0.md`

This is the human-authored decision artifact (markdown — the LLM applies it; no Python). Keep it lean (loads on-demand per role, per spec §10.4). v1 thresholds are `PLACEHOLDER-FAIL-SAFE` per the evolution standard.

- [ ] **Step 1: Create the SOP**

```markdown
# Strategy Routing SOP — v1.0.0

**Status:** human-ratified. Versioned like any SOP — propose changes via
`reports/sop-changes/`, never edit in place. The agent APPLIES this; it never
edits it. Governed by OPERATING_MANUAL.md (constitution) and
docs/AGENT_EVOLUTION_STANDARD.md (risk-bearing skill-routing).

Inputs come from `get_market_regime`. A `null` signal in any condition →
treat the dependent strategy as **OFF** (fail-safe). On rule conflict,
**most-restrictive wins**. The gate can only SUBTRACT from what mode/limits
already allow — never add.

## §1 Eligibility Gate (Risk-Manager applies, in preflight)

Evaluate top-to-bottom against the regime snapshot. Cells are binary ON/OFF.
Sizing/throttling is NOT decided here — the global mode (NORMAL/DEFENSIVE/
HALTED) already does that (risk-manager Rule 2 forces DEFENSIVE at
spy_tr_atr > 1.5, HALTED at > 2.0).

| Regime condition | equity/intraday | equity/swing | options/vol-edge |
|---|---|---|---|
| vix > 30 OR spy_tr_atr > 2.0 (stress) `[PLACEHOLDER-FAIL-SAFE]` | OFF | OFF | OFF |
| iv_rank_spy > 70 AND abs(spy_vs_sma50_pct) < 2 (high-vol range) `[PLACEHOLDER-FAIL-SAFE]` | OFF | OFF | ON |
| spy_vs_sma50_pct > 0 AND spy_trend = up AND iv_rank_spy < 50 (uptrend) `[PLACEHOLDER-FAIL-SAFE]` | ON | ON | OFF |
| default (no row matched) | OFF | OFF | OFF |

Only strategies that are (a) in `config.yaml strategies.enabled`, (b) match the
session `--market` scope, AND (c) ON above are eligible.

## §2 Setup Routing (Research applies, per candidate, eligible strategies only)

| Candidate signature | → strategy |
|---|---|
| premarket gap > 3% AND RVOL > 2x AND fresh catalyst (<=48h) | equity/intraday-momentum |
| multi-day base/consolidation breakout, trend intact, RS > SPY | equity/swing |
| pullback to rising SMA20/50 within an uptrend | equity/swing |
| iv_rank > 70, range-bound, liquid options chain | options/vol-edge |
| (no clear match) | DROP — log "unroutable" |

A candidate routed to a strategy that is not eligible (per §1) is dropped with
log reason "ineligible: <regime reason>".

## Change log
- v1.0.0 (2026-06-06): initial. All thresholds PLACEHOLDER-FAIL-SAFE; tighten to
  BACKTEST-CALIBRATED after Phase-4 gate-vs-control validation.
```

- [ ] **Step 2: Verify it parses as part of the registry guard (no code)**

Run: `cd tools && uv run --extra dev pytest tests/test_registry.py -v`
Expected: PASS (unchanged — this task adds no enabled ids).

- [ ] **Step 3: Commit**

```bash
git add sops/_routing/v1.0.0.md
git commit -m "feat(routing): add routing SOP v1.0.0 (eligibility + setup-routing tables)"
```

---

## Task 5: Risk-Manager skill — compute eligible set

**Files:**
- Modify: `skills/risk-manager/SKILL.md`

- [ ] **Step 1: Add `get_market_regime` to `requires_tools`**

In the YAML frontmatter, append `get_market_regime` to the `requires_tools` list.

- [ ] **Step 2: Replace preflight item #8**

Find:
```
[ ] 8. Load today's strategy SOP  → e.g. sops/day-trade-momentum/v1.0.0
```
Replace with:
```
[ ] 8. Compute eligible strategy set:
        a. get_market_regime("SPY")  → regime snapshot
        b. Read config.yaml strategies.enabled; keep only those whose
           `market` matches this session's --market scope
        c. Apply sops/_routing/v1.0.0 §1 to the snapshot → {id: ON|OFF}
           (null signal → OFF; most-restrictive wins; HALTED mode → empty set;
            DEFENSIVE mode → keep set, DEFENSIVE sizing applies to every entry)
        d. log_decision(action="strategy_eligibility",
             rules_triggered=[matched §1 rows], reasoning=<regime summary>)
```

- [ ] **Step 3: Add an "Eligible Strategies" block to the Output Format section**

After the `### Mode:` block in "## Output Format", add:
```
### Eligible Strategies
- Session market scope: [equity | options]
- Regime: vix=[x] spy_tr_atr=[x] spy_vs_sma50_pct=[x]% trend=[up/down/flat] iv_rank_spy=[x]
- Eligible: [list of strategy ids that are ON] (or "none — STOP")
- Per strategy: [id] → ON/OFF ([which §1 row fired])
```

- [ ] **Step 4: Verify references resolve**

Run: `cd tools && uv run --extra dev pytest tests/test_registry.py tests/test_regime.py -q`
Expected: PASS (skill edits don't affect tests; this confirms nothing broke).

- [ ] **Step 5: Commit**

```bash
git add skills/risk-manager/SKILL.md
git commit -m "feat(routing): risk-manager computes eligible strategy set in preflight"
```

---

## Task 6: Research skill — setup routing

**Files:**
- Modify: `skills/research/SKILL.md`

- [ ] **Step 1: Add a "Strategy Routing" subsection before "The 5-Layer Due Diligence Stack"**

Insert:
```
## Strategy Routing (apply BEFORE the 5-Layer Stack)

The orchestrator passes you (a) the regime snapshot and (b) the eligible
strategy set from the Risk-Manager. Do NOT re-read regime — use the snapshot
given (single source of truth).

For each candidate from the scan:
1. Classify it against sops/_routing/v1.0.0 §2 (setup signature → strategy).
2. If the matched strategy is NOT in the eligible set → DROP, log
   action="skip", reasoning="ineligible: <regime reason>".
3. If no §2 signature matches → DROP, log "unroutable".
4. Otherwise load that strategy's DD reference (sops/<id>/dd.md) and score
   with THAT strategy's rubric.
```

- [ ] **Step 2: Update the Output Format to group by strategy**

In "## Output Format", change the `## Candidates` heading note to:
```
## Candidates (grouped by routed strategy)
### Strategy: [id]
  ### 1. [SYMBOL] — Score: [X]/100 ...
```

- [ ] **Step 3: Commit**

```bash
git add skills/research/SKILL.md
git commit -m "feat(routing): research routes candidates to eligible strategies (SOP §2)"
```

---

## Task 7: SOUL orchestrator — session scope + shared budget

**Files:**
- Modify: `SOUL.md`

- [ ] **Step 1: Replace Phase 1 step 3**

Find: `3. Load the strategy SOP for today`
Replace:
```
3. Determine session market scope (--market from the scheduler; if absent and
   only one market is enabled, use it; else STOP and request scope).
4. Obtain the eligible strategy set from the Risk-Manager (preflight item #8).
   If the eligible set is empty → STOP, log "no eligible strategy today".
```

- [ ] **Step 2: Update Phase 2 delegation**

Change the Research delegation bullet "The strategy SOP (e.g., `day-trade-momentum/v1.0.0`)" to:
```
- The regime snapshot + eligible strategy set (from Risk-Manager)
- The session market scope
```

- [ ] **Step 3: Add the shared-budget rule to Phase 3**

In Phase 3, add:
```
- All strategies active this session draw from ONE shared account risk budget.
  Rank candidates across strategies by conviction; size via quarter-Kelly on
  combined equity; place until any portfolio governor binds (max_open_positions,
  daily_loss_limit, sector concentration). Enabling a 2nd strategy does NOT add
  a 2nd budget. Account state persists across market-sessions — a later session
  sees what an earlier one already spent.
```

- [ ] **Step 4: Reword Rule 3**

Find: `3. **One workflow at a time.** Never start a new scan while positions are being monitored.`
Replace:
```
3. **One orchestration cycle at a time.** A session is scoped to one market and
   may run multiple strategies of that market, but never more than one concurrent
   scan/execute loop. Markets run as separate scheduled sessions sharing one account.
```

- [ ] **Step 5: Commit**

```bash
git add SOUL.md
git commit -m "feat(routing): orchestrator session scope + shared-budget multi-strategy"
```

---

## Task 8: Run the full suite (regression gate)

- [ ] **Step 1: Run everything**

Run: `cd tools && uv run --extra dev pytest tests/ -v`
Expected: PASS — all prior 208 tests + `test_registry.py` (3) + `test_regime.py` (4). No failures, no import errors.

- [ ] **Step 2: Commit (only if any test fixup was needed; otherwise skip)**

```bash
git add -A && git commit -m "test(routing): green full suite after routing wiring"
```

---

## Task 9: Eligibility golden cases (agent dry-run validation)

The eligibility decision is LLM-applied, so it is validated by **dry-running the
Risk-Manager agent** against fixed regime snapshots — not pytest. This is the
spec §8.1/§8.2 (deterministic rule tests + pass^k) at the agent level.

**Files:**
- Create: `docs/plans/2026-06-06-routing-golden-cases.md`

- [ ] **Step 1: Write the golden-case table**

```markdown
# Routing Eligibility — Golden Cases (agent dry-run)

Feed each snapshot to the Risk-Manager (temperature 0) with sops/_routing/v1.0.0
and config.yaml. Assert the eligible set. Run each case k=3 times; the set MUST
be identical across runs (pass^k reliability).

| # | Snapshot | Expected eligible (options scope) | Expected (equity scope) |
|---|---|---|---|
| 1 | vix=35, spy_tr_atr=2.4, trend=down | none (stress row) | none |
| 2 | vix=18, spy_tr_atr=0.9, iv_rank_spy=80, spy_vs_sma50_pct=0.5 | options/vol-edge | none |
| 3 | vix=14, spy_tr_atr=0.8, iv_rank_spy=35, spy_vs_sma50_pct=3, trend=up | none | equity/intraday + swing (when enabled) |
| 4 | all null (data outage) | none (fail-safe) | none |
| 5 | vix=null, spy_tr_atr=1.1, iv_rank_spy=null, trend=up | none (vol-edge needs iv_rank → null → OFF) | none |

PASS = eligible set matches column AND is stable across the 3 runs.
```

- [ ] **Step 2: Execute the dry-runs** (manual, paper). Record actual eligible sets next to each case. Any mismatch or run-to-run variance is a defect — fix the SOP wording (ambiguity) before proceeding, not the model.

- [ ] **Step 3: Commit the results**

```bash
git add docs/plans/2026-06-06-routing-golden-cases.md
git commit -m "test(routing): eligibility golden cases + dry-run results"
```

---

## Self-Review

**Spec coverage:** §2 hybrid (T5 gate + T6 routing) ✓; §3.1 registry (T1) ✓; §3.2 routing SOP (T4) ✓; §3.3 get_market_regime (T2/T3) ✓; §3.4 risk-mgr (T5) ✓; §3.5 research (T6) ✓; §3.6 SOUL (T7) ✓; §4 shared budget (T7 step 3) ✓; §6 governance — SOP versioned/human-authored, provenance tags, fail-safe (T4) ✓; §8.1/§8.2 validation (T9) ✓; §8.3 gate-vs-control → **Deferred** (below). §3.1 `--market` scope (T1 config + T5b + T7) ✓.

**Placeholder scan:** no TBD/TODO; the only "PLACEHOLDER-FAIL-SAFE" strings are intentional provenance tags per the evolution standard, not unfinished work.

**Type/name consistency:** `compute_market_regime(repo, symbol, start, end, timeframe, vix, iv_rank_spy)` defined in T2, called identically in T3. Snapshot keys (`vix, spy_tr_atr, spy_vs_sma50_pct, spy_trend, iv_rank_spy, as_of`) consistent across T2/T3/T4/T5/T9. Strategy ids consistent (`options-vol-edge`/`day-trade-momentum` current paths in T1, with restructure-renamed forms noted).

---

## Deferred (out of scope — depends on other work)

1. **`iv_rank_spy` signal.** Two §1 rows need it; until SPY IV is tracked in the
   `iv_history` table (reuse vol-edge Phase-2 `calc_iv_rank` machinery for symbol
   SPY), the tool passes `null` → those rows fail-safe to OFF → **vol-edge stays
   ineligible**. Follow-up task: populate SPY IV-rank and inject it in T3.
   Until then, keep `enabled` to one non-IV strategy for paper.
2. **`catalyst_density` signal** — deferred per spec §10.3.
3. **Gate-vs-control backtest (spec §8.3)** — requires the Phase-4 strategy-
   agnostic engine. Run after Phase 4; use it to tighten T4 thresholds from
   `PLACEHOLDER-FAIL-SAFE` → `BACKTEST-CALIBRATED` and ratify routing SOP v1.1.0.
4. **Directory restructure** (rename `day-trade-momentum` → `equity/intraday-
   momentum`, `options-vol-edge` → `options/vol-edge`) — separate plan; when it
   lands, update the `id` paths in `config.yaml` (T1) and the registry guard test
   still passes by construction.
```
