# Implementation Plan: Capital-Aware Selection

- **Slug:** `capital-aware-selection` · **Status:** `plan`
- **Design:** [`capital-aware-selection-design.md`](capital-aware-selection-design.md) · **Spec:** [`capital-aware-selection-spec.md`](capital-aware-selection-spec.md)
- **Executor:** Claude Code · **Date:** 2026-07-25

## Dependencies

- **Needs `data-source-adapters`** — options BPR requires live chain data (`credit`, `strike_width`). Equity-only selection can ship first if that slips.
- Independent of the scanner rebuild (D4, deferred) — works on today's candidates.

## Guardrails

- **Deterministic Python only.** No LLM in this path — it's arithmetic.
- **RULE 3:** thresholds (`min_notional`, budgets, caps) come from `risk_limits.{env}.yaml` / SOP — **never literals in this module**.
- **Affordability must never promote a candidate that failed its SOP gates.** Filter, then rank the survivors.
- Sizing math is unchanged — reuse `calc_position_size` (`server.py:741`); only its *timing* changes.
- Missing chain data ⇒ `UNAVAILABLE`, never silently ranked.
- All existing tests stay green.

---

## Tasks

### Task 1 — Cost model (`min_viable_cost`)
- **Files:** `tools/selection/cost.py` (new)
- **What:** per-candidate minimum viable position cost. Equity: `(entry − stop) × shares` for the smallest position ≥ `min_notional` (D-CAS2). Options spread: **BPR** = `(strike_width − credit) × 100 × 1`. Returns `None` + reason when inputs are missing.
- **Tests:** `tools/tests/test_selection.py` (new) — equity and spread costs on hand-computed examples (assert exact); missing chain data ⇒ `None` + reason, **never 0**; thresholds read from config, not literals.
- **Status:** ☐ todo

### Task 2 — Affordability filter + funnel counting
- **Files:** `tools/selection/filter.py` (new), `tools/persistence/db.py` (`scan_funnel`)
- **What:** drop candidates whose `min_viable_cost` > `min(per-trade budget, buying power)`. Budget = `equity × per_trade.max_risk_pct`. **Count exclusions into `scan_funnel`** with reason `unaffordable`.
- **Tests:** exactly at budget ⇒ **kept**; one cent over ⇒ dropped (convention stated, per H4); `scan_funnel` records the count; `why_zero` can distinguish **"none qualified"** from **"none affordable"**.
- **Status:** ☐ todo

### Task 3 — Return-on-capital ranking
- **Files:** `tools/selection/rank.py` (new)
- **What:** options `credit ÷ BPR`; equity expected-R ÷ risk capital. **One scale across asset classes** (D6). Tie-break on signal score (D-CAS1).
- **Tests:** a **lower-signal affordable** candidate outranks a **higher-signal unaffordable** one; equity and options interleave correctly; ⚠️ **a candidate failing its SOP gates is never ranked**, regardless of capital efficiency.
- **Status:** ☐ todo

### Task 4 — Greedy fill
- **Files:** `tools/selection/select.py` (new)
- **What:** iterate ranked candidates; size via existing `calc_position_size`; skip if cost > remaining buying power (**`continue`, not `break`** — a cheaper later candidate must still be taken); decrement capital; stop at `max_open_positions`.
- **Tests:** respects position cap; decrements buying power; **skips an unaffordable candidate and still takes a cheaper later one**; concentration cap still applies; empty input ⇒ empty output, no crash.
- **Status:** ☐ todo

### Task 5 — ⭐ AMD regression test
- **Files:** `tools/tests/test_selection.py`, fixture from `Hermes/trades.jsonl`
- **What:** reproduce the real case — $10k account, 1–2% risk, AMD spread BPR ~$400–450 vs ~$100–200 budget. Assert AMD is **excluded pre-ranking** and a sizeable candidate is selected instead.
- **Acceptance:** **this is the test that proves the drought is fixed.** It must fail against the current selection path and pass after.
- **Status:** ☐ todo

### Task 6 — Account-size invariance
- **Files:** `tools/tests/test_selection.py`
- **What:** same % inputs on $10k and $100k accounts ⇒ proportional sizes, **no re-tuning**, no literals anywhere in the path (RULE 3).
- **Tests:** the above; plus a grep assertion that `tools/selection/` contains no numeric strategy/risk literals.
- **Status:** ☐ todo

### Task 7 — Wire into the pipeline
- **Files:** research/trader path, `tools/server.py` (MCP tool `select_candidates`)
- **What:** run selection **after scan+gates, before DD** (D-CAS3 — stop paying for analysis on unbuildable positions). Expose as an MCP tool returning ranked affordable targets with their `return_on_capital` and cost.
- **Tests:** `tools/tests/test_tool_groups.py` — tool exposed in `research`/`trader`; end-to-end: scan → select → shortlist contains only affordable candidates.
- **Status:** ☐ todo

### Task 8 — Docs + status
- **Files:** `PROJECT_STATUS.md`, `docs/product/ROADMAP.md`, `BUILD-PLAN.md`
- **What:** record shipped; note the gate's size-veto should now rarely fire — **if it starts firing, selection is broken** (a standing signal worth watching).
- **Status:** ☐ todo

---

## Definition of Done

- [ ] Tasks 1–8 done, tests green
- [ ] **⭐ AMD regression passes** — the historical unaffordable pick is excluded and a sizeable one chosen
- [ ] Equity + options ranked on one scale (D6)
- [ ] `why_zero` distinguishes "none qualified" from "none affordable"
- [ ] Account-size invariant; **zero literals** in `tools/selection/` (RULE 3)
- [ ] No risk control weakened — gate unchanged
- [ ] `PROJECT_STATUS.md` + ROADMAP updated

## Decisions carried from spec

- **D-CAS1** tie-break → higher signal score
- **D-CAS2** equity minimum → configured **minimum notional**, not 1 share
- **D-CAS3** filter runs **before** DD
