# Engine B Refinement — Directional Swing (price-action options, 2–4 week holds)

**Date:** 2026-06-14
**Status:** Design — pending implementation plan
**Scope:** New SOP version `options/vol-edge/v1.1.0` refining the existing Engine B
("Directional / Big-Fish") plus supporting skill/tool/monitor changes. v1.0.0 is
left untouched (SOPs are versioned, never edited in place).

---

## 1. Goal

Refine the existing options Engine B into a disciplined **directional swing** style:

- **Hold 2–4 weeks**, then sell to take profit.
- **LLM picks the trade** by synthesizing three independent research legs.
- **Price-action entry** with intraday confirmation (no chasing the open).
- **Trailing stop + scale-out** to protect profit and minimize loss.

Everything stays **defined-risk** and subordinate to `OPERATING_MANUAL.md`. This SOP
only ever makes itself stricter than the Manual, never looser.

---

## 2. Three-leg research model

Every candidate is judged on three independent evidence streams; the LLM must
**reconcile** them and show its work in the logged rationale.

| Leg | Source | Answers |
|---|---|---|
| **1. Technical analysis** | MCP tools: `calc_technical_indicators`, price/volume, continuation-setup gates, `calc_iv_rank` / `calc_hv` / `get_put_skew` / `calc_expected_move` | Is the price-action setup real and is the option priced right? |
| **2. Web / social research** | `WebSearch` + firecrawl over r/options, r/wallstreetbets, X, high-signal accounts | What's the catalyst; how known / crowded / priced-in is it; any event the tape hasn't shown? |
| **3. LLM reasoning** | the model | Do legs 1 & 2 agree? Where they conflict, which wins and why? |

**Precedence (so the legs combine sanely):**
- **Technical is the gate with veto power** — if the setup/pricing doesn't qualify, no amount of social signal gets in.
- **Social is weighted context** — thesis-with-reasoning + fresh timestamps count; rocket-emoji / gain-screenshots discounted; crowding read **contrarian** (everyone-long-into-event = caution, not confirmation).
- **LLM reasoning is the referee** — must state explicitly how the three legs line up; on conflict, default to the **safer** structure (spread over single-leg) and/or smaller size, and say why.

**Reddit access note:** the direct crawler is blocked on reddit.com. The agent reaches r/options content via `WebSearch` (Google surfaces threads) and firecrawl for fetching — never by hitting reddit.com directly.

---

## 3. Entry mechanics — two phases

### Phase A — Pre-market (~9:00 ET): build an ARMED PLAN, do not trade

Research runs the three-leg analysis and writes a **trade plan with an entry
trigger** — not an order. The plan records:

1. **Technical gate (leg 1 — pass or skip):** one confirmed continuation setup
   present (pullback-to-EMA20 + reversal candle + ≥1.2× RVOL; consolidation/BB-
   squeeze breakout + ≥1.5× RVOL; or MACD resumption cross). Not extended
   (anti-chase). SPY regime gate inherited: UPTREND→bullish only, DOWNTREND→
   bearish only, NEUTRAL→wait.
2. **Instrument auto-select (IVR committee):**
   - `IVR < 35` → **long call/put**, 0.55–0.65 delta, **35–45 DTE**.
   - `IVR > 55` → **debit vertical** (buy ~ATM 0.45–0.55 delta, sell OTM ~1.5–2 expected-moves out), **35–45 DTE**.
   - `IVR 35–55` (neutral band) → LLM tiebreaks on IV/HV + skew + setup quality; default to **spread** when ambiguous.
   - IVR is the *lead vote*, never the lone trigger.
3. **Social/catalyst research (leg 2).**
4. **Earnings/event handling (LLM judgment):** if a confirmed earnings/event lands
   inside the option's life, the LLM decides skip / force-spread-and-downsize /
   hold-through, justified in the rationale; quant (IV-crush risk from IVR + term
   structure) retains veto.
5. **LLM synthesis (leg 3) + `notify_analysis`:** chosen structure, conviction,
   the entry-confirmation trigger, the invalidation condition, and the cutoff time.

Conviction → size **down-only**: social/LLM may shrink size from a fixed base but
**never enlarge** it; base size obeys OPERATING_MANUAL quarter-Kelly cap.

### Phase B — After open: confirm, then enter (or stand down)

The plan is **armed but unfilled**. The every-minute **monitor sentinel**
(already built) watches each armed plan:

- **Mechanical pre-filter (cheap, no LLM):** is the underlying at/through the
  trigger level with basic volume? If not → keep waiting.
- **LLM validation at the decisive moment:** when the pre-filter trips, wake the
  LLM to judge **real confirmation vs. trap** (did the breakout *hold* — e.g.
  first 15–30 min bar closes above the trigger, no engulfing reversal, RVOL
  confirms; underlying leads, then enter the option).
- **Enter:** confirmed → fire an **immediate marketable order** (see §5), then
  `notify_buy`.
- **Stand down:** invalidation hits (price closes back below trigger) or the
  cutoff passes (default 11:00 ET; hard stop end-of-session) → cancel the plan,
  log "no confirmation, stood down." A plan that never confirms is a success
  (trap avoided), not a missed trade.

Entry timing is therefore **same session, on the next monitor run after
confirmation** — never a pre-placed order on yesterday's signal.

---

## 4. Exit mechanics — hybrid (underlying trail + premium scale-out)

Governed by the monitor sentinel every minute once filled.

**Stop / trailing stop → underlying price action (low-noise):**
- Initial stop: underlying **closes** below the entry trigger / invalidation
  (close-confirmed; ignores intraday wicks — reuses existing close-based rule).
- Trail: on higher underlying closes, raise the stop under rising structure
  (prior swing low or chosen EMA). Trail only moves up.
- Underlying closes below the trailed level → exit the option, `notify_sell`.

**Profit-take → option premium, scale-out:**
- **First scale:** at **+50% of contract max gain** (premium target), sell
  **half**, lock the win.
- **Runner:** remaining half rides the underlying trailing stop (uncapped on a
  long call; to the short strike on a spread).
- **Hard guards (retained from v1.0.0):** 21-DTE hard close, 2× premium loss cap,
  kill-switch / daily-loss / gap-through-strike emergencies.

---

## 5. Order-placement rule — NO resting orders, either side

A resting limit order is passive: it fills whenever price *touches* it, with no
thesis validation at fill time. A resting **buy** limit fills on a dip into the
trap; a resting **sell** limit fills on a wick/spike and kills the runner logic.
Both defeat the confirm-then-act design.

**Rule (absolute, both sides):**
- **Entry:** only after the sentinel + LLM confirm → fire an **immediate
  marketable limit** (limit set at/just above the touched ask for a buy, IOC/day),
  **slippage-capped** at the touched price + a small buffer (default 0.5–1% on the
  option / a tick band); else cancel and re-evaluate next minute. Never a resting
  buy limit below market.
- **Profit-take:** sentinel watches the premium target mechanically; at touch it
  **wakes the LLM** to confirm real strength vs. noise, takes the scale-out half,
  decides on the runner, then fires an **immediate** order. Never a resting sell
  limit.
- **Stop:** close-confirmed via the monitor → immediate exit on a confirmed
  close-below. Never a resting stop (preserves the wick filter).

**Tradeoff (accepted):** fills only happen while the sentinel runs (market hours,
every minute) — no set-and-forget fills. This is intentional: patience and
validation over passive fills. The sentinel cron covers full market hours, so
exits as well as entries depend on its uptime.

---

## 6. Adaptive confirmation parameters — propose-and-ratify

The confirmation **logic** is fixed in the SOP. Only a bounded **parameter set**
adapts: `{confirmation_window_min, rvol_multiple, reversal_sensitivity,
entry_cutoff, regime_band, slippage_buffer}`, stored in
`confirmation_params.json` (not in code or the SOP body).

- **Bounded:** every parameter has a hard min/max in the SOP the LLM can never
  exceed (e.g. rvol_multiple ∈ [1.1, 2.0]; confirmation_window ∈ [15, 90] min).
- **Batch, not per-trade:** the EOD/weekly review analyzes *closed* confirmation
  and exit outcomes (followed-through vs. trap; stood-down-but-would-have-worked),
  **keyed to market regime** (e.g. high-VIX vs calm, trend vs chop), and proposes
  a parameter nudge with rationale + evidence. Batch review kills noise-chasing
  and the loosen-after-losses runaway loop.
- **Propose-and-ratify (governance):** the review writes a proposal to
  `reports/sop-changes/`; **nothing changes until the human approves.** Honors the
  existing CLAUDE.md rule ("SOPs are human-controlled; agents propose, never edit
  `sops/` directly") and keeps backtests reproducible.
- **Versioned + auditable:** each parameter set is timestamped so a backtest can
  pin a date and reproduce the exact rule then; every change logs old→new + reason.

---

## 7. Architecture & data flow

```
~9:00 ET   Research worker — 3-leg analysis (technical gate → IVR committee →
           social/firecrawl → LLM synthesis) → writes an ARMED PLAN with entry
           trigger + invalidation + cutoff. NO order. notify_analysis.
                               │
After open Monitor sentinel (every minute) — mechanical pre-filter:
(per min)  underlying at trigger + basic volume?  ── no ──> keep waiting
                               │ yes
           Wake LLM → real-vs-trap validation → immediate marketable order
           (notify_buy)   OR   invalidation/cutoff → stand down, log
                               │ (filled)
Per min    Monitor sentinel — hybrid exit:
           underlying-close trail (stop)  +  premium scale-out (profit, LLM-
           confirmed at touch) → immediate order → notify_sell
                               │
EOD/weekly EOD review → analyze confirmation + exit outcomes by regime →
           PARAMETER-CHANGE PROPOSAL → reports/sop-changes/ → human ratifies →
           confirmation_params.json updated (versioned)
```

---

## 8. Artifacts (new / changed)

| Artifact | Change |
|---|---|
| `sops/options/vol-edge/v1.1.0.md` | New SOP version: refined Engine B (DTE 35–45, delta 0.55–0.65, IVR committee, armed-plan entry, hybrid exit, no-resting-orders rule, adaptive-param hook). v1.0.0 untouched. |
| `skills/research/reference/options-vol-edge-dd.md` | Add the 3-leg DD procedure, social-research path (WebSearch/firecrawl, Reddit-via-search), armed-plan output format. |
| `skills/monitor/SKILL.md` | Extend to handle armed-entry confirmation (Phase B) and the hybrid exit, in addition to existing open-position monitoring. |
| `tools/monitor_sentinel.py` | Extend to watch armed plans (entry pre-filter) in addition to open positions; enforce no-resting-orders / immediate marketable orders. |
| `confirmation_params.json` | Bounded, versioned adaptive parameters. Committed default + gitignored runtime state. |
| `skills/eod-review/SKILL.md` | Add the weekly batch parameter-review-and-propose step (writes to `reports/sop-changes/`). |

---

## 9. Non-goals / out of scope

- Engine A (vol-edge income credit spreads) is unchanged.
- No naked options; defined-risk only.
- Bridge (<$3.5k) equity-swing fallback unchanged.
- No new broker; paper (Alpaca) now, broker-agnostic principles.
- Bounded-autonomous adaptation (auto-apply within rails) is explicitly deferred;
  start with propose-and-ratify, revisit only after the suggestions prove sane.

---

## 10. Open parameters to confirm during spec review

- Slippage buffer default (0.5–1% on the option / tick band).
- Entry cutoff default (11:00 ET soft, end-of-session hard).
- First-scale level (+50% of max gain) and scale fraction (half).
- Hard min/max rails for each adaptive parameter.
