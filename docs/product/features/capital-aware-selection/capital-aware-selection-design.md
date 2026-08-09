# Design: Capital-Aware Selection

- **Slug:** `capital-aware-selection` · **Status:** `design` · **Spec:** [`capital-aware-selection-spec.md`](capital-aware-selection-spec.md)
- **Author:** Claude Code · **Date:** 2026-07-25

> **The missing stage.** Pros run *alpha → **portfolio construction** → risk → execution*. We have alpha (scanner+research), risk (gate), execution (trader) — and **nothing in between**. That gap is the drought.

---

## 1. Where it sits

```
scan + research  →  candidates (signal-scored)
                          │
                    ┌─────▼──────────────────────────────┐
                    │  CAPITAL-AWARE SELECTION  (new)    │
                    │  1. affordability filter           │
                    │  2. rank by return-on-capital      │
                    │  3. greedy fill to caps            │
                    └─────┬──────────────────────────────┘
                          │  sized, affordable targets
                    governance gate → execute
```

Pure function, deterministic Python. **No LLM** — this is arithmetic (`CLAUDE.md`: everything mechanical belongs in Python).

```python
def select(candidates: list[Candidate], capital: CapitalState, limits: RiskLimits) -> list[Target]
```

---

## 2. The three steps

### Step 1 — Affordability filter (runs FIRST, before ranking and before DD)

For each candidate compute **minimum viable position cost**; drop it if that exceeds the per-trade budget.

| Asset | Minimum viable cost | Source |
|---|---|---|
| Equity | `(entry − stop) × shares` for the smallest position ≥ `min_notional` | plan's entry/stop |
| Options spread | **BPR** = `(strike_width − credit) × 100 × 1 contract` | live chain (`analysis/options.py`) |

```
budget = equity × per_trade.max_risk_pct        # % of equity ⇒ account-size-invariant
keep candidate ⟺ min_cost ≤ min(budget, buying_power_remaining)
```

⚠️ **This runs before the LLM's DD** (D-CAS3). DD is the expensive step, and 33 sessions were spent analysing names that could never be sized. Filtering first is the direct fix.

**Every exclusion is counted into `scan_funnel`** so `why_zero` can say *"12 qualified, 0 affordable"* — today that reads identically to *"0 qualified"*, which is why 33 sessions looked the same.

### Step 2 — Rank by return-on-capital (not raw signal)

| Asset | Metric |
|---|---|
| Options | `credit ÷ BPR` — the tastytrade standard; capital efficiency is *"particularly important for small accounts"* |
| Equity | expected R ÷ dollars of risk capital required |

Both are **return per dollar of buying power**, so equity and options compete on one scale (D6, cross-asset in one pass).

⚠️ **Affordability never promotes a failed candidate.** A candidate must pass its SOP gates *first*; capital efficiency only orders the survivors. Otherwise this becomes a cheap-and-bad selector.

**Tie-break:** higher signal score (D-CAS1). Capital efficiency picks the feasible set; signal quality orders within it.

### Step 3 — Greedy fill

```
for c in ranked:
    if positions_open >= limits.max_open_positions: break
    qty = fixed_fractional_size(c, equity, limits)     # existing calc_position_size math
    if cost(qty) > buying_power_remaining: continue    # a later, cheaper one may still fit
    emit Target(c, qty); buying_power_remaining -= cost(qty); positions_open += 1
```

Greedy is correct here and **deliberately not an optimizer**. Research is explicit that mean-variance produces *"unstable, concentrated portfolios that fail out of sample"*; for a handful of positions, filter + sort + fill is the whole job. `continue` (not `break`) matters — a cheaper high-ranking candidate later in the list should still be taken.

Concentration and per-trade caps are unchanged and still apply.

---

## 3. What this does NOT do

- **Doesn't touch the gate.** The gate keeps its affordability veto as a last-resort floor — but with selection respecting the budget, it should now almost never fire on size. *If it starts firing, that's a signal selection is broken.*
- **Doesn't change sizing math.** `calc_position_size` (`server.py:741`) is correct; we change **when** it's applied.
- **Doesn't need new instruments.** XSP was a workaround for this bug (D6).
- **Doesn't wait on the scanner rebuild.** Works on today's candidates (D4 deferred).

---

## 4. Stale-price honesty

BPR and entry/stop are computed at **scan time**; prices move before execution. Selection is a **planning estimate**, not a guarantee — and is labelled as such on the `Target`. The gate re-checks affordability at order time against live state. Two different jobs: selection *plans* within budget, the gate *enforces* it.

If chain data is unavailable, the candidate is **`UNAVAILABLE`, never silently ranked** (same rule as the gate's missing-input handling) — a candidate we can't price is not a candidate we can rank.

---

## 5. Verification

**Deterministic — unit tested:**
- **⭐ The AMD regression** — real `trades.jsonl` numbers ($10k account, 1–2% risk, AMD spread BPR ~$400–450): AMD is **excluded pre-ranking**, and a sizeable candidate is selected instead. This is the test that proves the drought is fixed.
- Affordability: `min_cost` exactly at budget ⇒ **kept**; one cent over ⇒ dropped (state the convention, per H4's lesson).
- Ranking: a **lower-signal affordable** candidate outranks a **higher-signal unaffordable** one; equity and options interleave correctly on one scale.
- Greedy fill: stops at `max_open_positions`; decrements buying power; **skips an unaffordable candidate and still takes a cheaper later one** (`continue`, not `break`).
- Account-size invariance: same % inputs on $10k and $100k produce proportional sizes with **no re-tuning**.
- Missing chain data ⇒ `UNAVAILABLE`, not ranked.
- `scan_funnel` distinguishes *"none qualified"* from *"none affordable"*.

**Judgment — none.** Selection is arithmetic; the LLM's judgment already happened upstream (which candidates qualify) and downstream (final DD on the shortlist).
