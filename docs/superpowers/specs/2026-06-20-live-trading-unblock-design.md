# Design: Unblock Live Trading — Root-Cause Fix for "No Valid Trade on Hermes"

**Date:** 2026-06-20
**Status:** Draft — pending operator review (then implementation plan)
**Author:** brainstorming session (zelyuh + Claude)
**Scope:** Make the deployed system place valid, trustworthy paper trades; remove the dev/backtest/live confusion that hides why it doesn't.

---

## 1. Problem

After deploying to Hermes, the system places **zero valid trades**, day after day. The
operator suspects hard-coding and confusion between development/test/backtest and live
parameters. Prior debugging sessions produced a `FINAL_VERIFICATION_REPORT.md` declaring
the issue "COMPLETELY RESOLVED" — but that report never actually ran the scanner; it
described results the operator "should observe… when execution is available." The real
state was unknown.

## 2. Diagnosis (evidence-based)

Running the **real** scanner against the live SQLite DB on 2026-06-20:

- DB is fresh enough: 410 symbols, 366 daily bars each, through 2026-06-18.
- Scanner returns **5 valid Engine-M candidates** (PM, ADI, UNP, SFM, APO).
- SPY is in uptrend (+2.34% vs SMA50) → long-only strategies are eligible.

So candidates exist and the regime is favorable, yet nothing trades. The problem is
**downstream of the scanner**. Six root causes (A–F), ranked by impact — note **F (data
correctness)** was found later but is foundational: it undermines A and the filter check:

**A. Live decision path is stricter than the validated backtest path.**
The backtest runner (`tools/scripts/week_runner.py`) enters on **mechanical scanner
gates only** — it never calls `get_news`/`score_catalyst`; news/social are logged
"unavailable → NEUTRAL." But the live research skill (`skills/research/SKILL.md`,
Layer 3) makes a fresh-news catalyst **mandatory** ("You cannot recommend an entry
without a catalyst score… <5 → SKIP"). Quiet momentum-continuation large-caps rarely
have a fresh catalyst, so live rejects exactly the trades the backtest took. **The
validated edge is never executed live.** Violates CLAUDE.md rule #2 (backtest must use
the same code path as live).

**B. The "live" data pipeline is a hand-cranked backtest loader.**
The scanner reads price data only from the local SQLite DB (`repo.query_price_data`);
it never fetches at scan time. The DB is populated only by manually running
`scripts/load_universe.py`, and the universe comes from a file named
`universe_backtest.json`. There is **no daily-refresh automation**. Data silently goes
stale → recurring "candidate drought."

**C. Zero observability — a "correct zero" is indistinguishable from a "broken zero."**
Daily reports show only "Total Trades: 0." Nothing records scanned→passed→per-candidate
DD verdict→orders. The 2026-06-19 report shows "Total Decisions: 0," meaning the
research agent logged nothing at all. With no funnel telemetry, every zero looks
identical, which is *why* prior sessions resorted to verification theater.

**D. Version/parameter drift across four anchors.**
`config.yaml` enables swing **v1.3.0**; the scanner comment says it mirrors **v1.2.0**;
the scanner's returned `sop_version` string says **v1.0.0**; the latest shipped SOP is
**v1.6.0**. Humans believe v1.6.0 is live; the scanner runs v1.2.0 entry gates.

**E. AI scratch-file pollution (a consequence of C).**
Repo root holds throwaway scripts that each reinvent the same check
(`test_scan.py → test_scan_debug.py → test_scan_fixed.py → test_scanner_direct.py`,
`check_db.py`, `simple_verify.py`, `debug_*.py`, `run_nvda_backtest.py`, `test.txt`,
`testdir/`), 4 overlapping `VERIFICATION*.md` files, and scattered
`tools/backtest_state_*.json`. None are wired into the system.
*(Resolved 2026-06-20: archived to gitignored `_archive/`; `.gitignore` guards added.)*

**F. Data is not just stale — it is materially INCORRECT (added 2026-06-20).**
Two distinct, verified bugs:

- *Unadjusted (raw) prices.* `scripts/load_universe.py` and `broker/alpaca.py`
  `get_historical_data` request bars with **no `adjustment=`** parameter → Alpaca returns
  raw, split-unadjusted prices. Proven in the live DB by single-day "moves" that match
  known split ratios: **ORLY 1348.10→91.71 (15:1), IBKR 208.17→52.60 (4:1),
  FAST 81.46→40.72 (2:1)**, among 27 symbols showing >35% single-day jumps (the rest a mix
  of real earnings moves and smaller splits below the 35% filter). A split discontinuity
  corrupts SMA25/50/150, ROC50, ATR10, drop_3d and rsi3 for ~150 sessions, so the affected
  names get the wrong pass/fail verdict (a 15:1 split looks like a -93% crash → false
  Engine-R "dip" or broken Engine-M trend).
- *IEX-only feed.* Live quotes (`get_market_data`) use `feed=DataFeed.IEX` and return the
  **IEX quote midpoint**, not the consolidated last trade — for many names that mid is wide,
  stale, or one-sided (the code itself handles IEX returning 0). This is the wrong
  "current price" the operator observed.
- *Two conflicting importers → a patchwork DB (verified 2026-06-21 against Yahoo).*
  **Close prices are accurate** (DB within ~0.05% of Yahoo). But two writers populate the
  same `price_data` table with different feeds and cadences: `load_universe.py` (default
  feed → **consolidated** volume, but manual/stale) and `load_price_cache` →
  `get_historical_data` (`feed=IEX` → volume **~2–3% of real**, auto-updated only for
  symbols that happen to get touched). Snapshot on 2026-06-21: **12 symbols fresh to
  06-18, 390 stuck at 06-12, 8 frozen at 2025-12-04.** The 12 "fresh" names carry IEX
  volume (AAPL ≈1.2M shares in DB vs ≈86M real → would falsely fail the >2M-share
  liquidity gate). Cross-symbol math breaks too: relative strength compares stale stock
  bars (06-12) against fresh SPY bars (06-18) — misaligned dates. (The earlier "5
  candidates" were all stale @06-12, so that read is itself unreliable.)

This means filter quality (root cause A / the gate selectivity below) is partly a *data*
problem, not a *threshold* problem — the gates are computed on corrupted, inconsistent
inputs.

**Filter-parameter check (added 2026-06-20).** Gate-failure histogram over 400 symbols:
Engine-M eliminators are M-G4 (trend, 66%), M-G5 (RS vs SPY ≥2, 64%), M-G6 (ROC50 ≥10,
60%), then the pullback gate M-G7b (33%); only **5 pass**. Engine-R: R-G5 (drop ≥6% &
RSI3<10) eliminates **99%** → **0 pass** (expected — R is built for corrections, not this
uptrend). Verdict: the thresholds are individually defensible (Bensdorp-derived), but their
*conjunction* is very tight (~1% M pass), and they run on the corrupted data above. So
"filter params" is a real contributor but secondary to data correctness and the catalyst-gate
divergence.

**Bottom line:** "No valid trade" is not one bug. It is a validated edge the live agent
is forbidden to take (A), computed on incorrect, unadjusted, IEX-only data (F), fed by a
manual loader (B), with no instrument to see any of it (C) — and the blind debugging that
followed produced the scratch and version mess (D, E).

## 3. Decisions locked (this session)

1. **Sequencing:** Both "make it trade" and "make it clean," sequenced — observability +
   reconcile first (see why), then a first real trade, then hygiene/versioning.
2. **Reconcile A:** Mechanical scan = the **entry decision** (matches backtest).
   News/social/catalyst = a **conviction modifier** (full vs half size) **plus a
   structural-break veto only** (R-G7 for Engine-R dips). No mandatory ≥7 entry gate for
   swing. The mandatory catalyst gate stays only on `equity/intraday-momentum`. Earnings-
   in-hold-window check and gap rules remain. Rationale (operator): a candidate that
   passes the mechanical check is *strengthened*, not blocked, by good news; we have no
   way to put historical news into the backtest for now.
3. **Data freshness B:** Cron refresh **+** staleness guard (belt-and-suspenders) — a
   missed refresh must be **visible** in the funnel, never a silent zero.
4. **Cleanup E:** **Archive, don't delete** — move scratch into a gitignored archive dir.

## 4. Design

### Phase 1 — See it, then unblock it

**1.1 Scan-funnel telemetry (addresses C; prevents E).**
A single first-class diagnostic that records and persists the full funnel for a scan:

```
universe_size
 → loaded (symbols with ≥160 daily bars)   [+ data-freshness: latest bar date, stale?]
 → passed_mechanical (engine_M count, engine_R count)
 → regime (SPY trend, eligible engines)
 → per-candidate verdict: entered | skipped (reason + which DD layer) | vetoed
 → orders_placed
```

- **What it does:** turns every scan into an auditable record; emitted **even on
  zero-candidate / zero-decision days**.
- **How it's used:** the daily report + Discord summary render it; any debugging session
  reads it instead of writing a new `test_scan*.py`.
- **Depends on:** the existing scanner output (already returns scanned/passed/per-gate
  fails) and the existing `log_decision` ledger (research agent must actually call it per
  candidate — today it does not). Persist funnel rows to the DB (new lightweight
  `scan_funnel` record or reuse `decisions`).
- **Boundary:** measurement only — it changes no trading decision.

**1.2 Reconcile the live decision path (addresses A) — behavior/markdown only.**
Edit `skills/research/SKILL.md` Layer 3 and `skills/research/reference/swing-trade-dd.md`:

- Swing M/R: mechanical pass ⇒ eligible to enter. Catalyst score sets **conviction/size**
  (full vs half), not enter/skip.
- Keep the **R-G7 structural-break veto** (news can still block an Engine-R dip into
  fraud / guidance cut) and the **earnings gate** (binary risk).
- The mandatory `score_catalyst ≥ 7` gate remains **only** for `equity/intraday-momentum`.
- No Python changes; safety invariants (kill switch, risk gates, gap rules, R:R)
  untouched. Per architecture, skills define behavior.

### Phase 2 — Trustworthy data, then first real trade

**2.0 Fix data correctness (addresses F) — do this BEFORE relying on any scan.**
A scan on corrupted data is worse than no scan; this gates everything downstream.
**Decision (2026-06-20):** no SIP subscription available → substitute the *data source*
(not just the Alpaca adjustment flag). Alpaca stays the **broker** (orders/account/
positions); **data** moves to a consolidated, split-adjusted source.

- **Data-source adapter** (`tools/data/source.py`): a small `MarketDataSource` interface —
  `get_daily_bars(symbols, start, end) -> {sym: adjusted DataFrame}` and
  `get_last_price(symbol) -> float`. Implementation selected via `config.yaml`
  (`data.source: yfinance` now; `alpaca_sip` / `polygon` later — one-file swap, no scanner
  change).
- **Default = yfinance** (proven 2026-06-20): consolidated, auto-split-adjusted
  (`auto_adjust=True`), batch download for the 400-name universe, no API key. Verified that
  ORLY/IBKR/FAST return continuous adjusted series (max/min ≈1.0 vs the raw split cliffs in
  the DB) and that SPY matches the existing DB level. New dependency: `yfinance` (moderate;
  behind the adapter). Caveat: unofficial Yahoo endpoint, ~15-min delayed — acceptable
  because we fetch once pre-market into the DB (scanner reads the DB), with batch retry.
- **Single writer (fixes the patchwork):** ALL price-data writes go through the one adapter
  — retire the IEX `load_price_cache` write path (or route it through the adapter) so the
  DB has one feed and one cadence. No more two-importer patchwork (the 12-fresh / 390-stale
  / 8-frozen split found 2026-06-21).
- **Touch points:** (1) `load_universe.py` history/refresh fetches via the adapter →
  rebuilds the DB the scanner reads; (2) live `get_market_data` returns the adapter's
  last/consolidated price instead of the IEX quote mid; (3) `get_historical_data` /
  `load_price_cache` route through the adapter too (so nothing writes IEX bars behind the
  adapter's back). Backtest path unchanged (SimulationBroker still serves clock-bounded DB
  data).
- **One-time re-load:** rebuild the whole universe history through the adapter so the 390
  stale + 8 frozen symbols are corrected and consistent with SPY.
- **Data-validation check:** runs after each load and reports into the funnel — flags
  (a) any >35% single-day move (split/decimal anomaly), (b) volume that looks venue-only
  (sanity vs expected ADV), and (c) **cross-symbol freshness misalignment** (every universe
  symbol + SPY must share the same latest bar date). Corruption is caught loudly instead of
  silently skewing the scanner.
- **Re-baseline (important):** after the switch, re-load history and **re-run the gate
  histogram**; the candidate counts AND the earlier backtest numbers (v1.1.0→v1.6.0) were
  produced on raw IEX data and must be re-verified on adjusted data before they are trusted.

**2.1 Automate data freshness (addresses B).**

- **Cron:** a weekday pre-market job that refreshes (adjusted) daily bars for the universe
  before the morning scan. No-look-ahead universe selection (fixed June-2025 liquidity
  window) preserved — only the daily-bar history extends. Also fix the stale hardcoded
  default `--daily-end 2025-12-05` in `load_universe.py` (a no-arg run currently loads
  months-old data) → default to "yesterday."
- **Staleness guard:** the scan path computes data age (latest bar date vs scan date). If
  stale beyond a threshold, the funnel reports `DATA_STALE as of <date>` prominently
  instead of returning a silent empty list.
- **Boundary:** data ingestion/correctness only; does not alter scanner gates or the
  universe membership rule.

**2.2 End-to-end paper run, watching the funnel.**
Run risk → research (reconciled) → trader → monitor on paper. Confirm one candidate flows
scan → DD(conviction) → `notify_analysis` (the human-monitor checkpoint, already exists) →
trader places a paper order. Verify each stage via the Phase-1 funnel. **Milestone: one
real paper trade placed by the system's own flow.**

### Phase 3 — Harden

**3.1 Single source of truth for versions + params (addresses D + hardcoding).** Pick the
canonical live swing version; make `config.yaml`, the scanner's returned `sop_version`, and
the scanner comment agree; verify the scanner's **entry** thresholds match that version
(exit params correctly live in SOP/monitor, not the scanner). Eliminate the duplicated
constants: the liquidity gate ($10–500, ADV ≥ $50M) is currently copied in three places —
`scanner.filters.SWING_V1`, `scripts/param_sweep.py`, and `scripts/load_universe.py` — and
the vol-regime tiers (0.8 / 1.2) appear in both `param_sweep.py` and the SOP. Collapse each
to one definition imported by the rest. Document where every parameter lives.

*Hardcoding-audit result (2026-06-20):* no hidden strategy **logic** in the live decision
path — `week_runner.py` reads strategy numbers from plan params, and the date strings in
`server.py` are docstring examples only. The real "hardcoding" is (i) the duplicated SOP
constants above (no single source of truth), (ii) the stale `--daily-end` default (fixed in
2.1), and (iii) the `score_catalyst` ENTER/SKIP threshold baked in Python (made advisory in
1.2). Minor: `get_social_sentiment` classification cutoffs (65/35, mentions ≥3) are inline
heuristics in a measurement tool — acceptable, note only.

**3.2 Archive scratch pollution (addresses E).** Move root scratch
(`test_scan*.py`, `check_db.py`, `simple_verify.py`, `debug_*.py`, `run_nvda_backtest.py`,
`test.txt`, `testdir/`, `VERIFICATION*.md`, `SCANNING_FIX_SUMMARY.md`,
`FINAL_VERIFICATION_REPORT.md`) and stray `tools/backtest_state_*.json` into a gitignored
`_archive/` dir; fold any still-useful check into the Phase-1 funnel tool; add `.gitignore`
rules so scratch cannot reaccumulate. Nothing deleted.

**3.3 No more ambiguous zeros.** EOD review must state *why* a zero-trade day was zero,
quoting the funnel (`0 passed mechanical` vs `N passed, 0 entered: low conviction` vs
`DATA_STALE`).

## 5. Out of scope (YAGNI)

Historical-news backtesting; new strategies/engines; the Engine-B armed-plan options path;
Kelly re-sizing; live (real-money) mode.

## 6. Success criteria

0. **Data integrity:** historical bars are split-adjusted (ORLY/IBKR/FAST no longer show
   discontinuities); **volume matches consolidated** (no IEX ~2% bars); **all universe
   symbols + SPY share one latest bar date** (no patchwork); `get_market_data` returns a
   price matching the real market on spot-checks. The validation check reports clean and the
   gate histogram is re-run on the corrected data.
1. For any scan, the funnel shows the full chain (universe → loaded → passed → verdicts →
   orders), persisted and rendered in the daily report — including on zero days.
2. A swing candidate that passes mechanical gates and is regime-eligible can reach an order
   with **no fresh-news catalyst required**; news only changes its size or vetoes a
   structural-break dip.
3. Data is refreshed automatically pre-market; a missed refresh surfaces as `DATA_STALE`,
   never a silent zero.
4. The system places **at least one paper trade through its own flow**, visible end-to-end
   in the funnel, with `notify_analysis` fired before execution.
5. `config.yaml`, scanner `sop_version`, and scanner comment name one consistent version;
   scanner entry thresholds verified against it.
6. Root scratch archived (not deleted); `.gitignore` prevents recurrence; tests still pass.

## 7. Risks & mitigations

- **Relaxing the catalyst gate increases trade frequency / lowers selectivity.** Mitigation:
  conviction modifier still down-sizes weak-catalyst names; earnings + R-G7 vetoes remain;
  paper mode; `notify_analysis` human checkpoint; funnel makes every entry auditable.
- **Cron refresh failure.** Mitigation: the staleness guard is the backstop — it makes a
  missed refresh loud, not silent (the explicit reason for choosing belt-and-suspenders).
- **Version reconciliation changes behavior.** Mitigation: treat entry thresholds as the
  contract; only labels/config change unless a threshold genuinely mismatches the chosen
  version — and run the test suite (289 tests) before/after.

## 8. Open questions

- ~~Data feed (for 2.0)~~ **RESOLVED 2026-06-20:** no SIP subscription. Substitute the data
  source with **yfinance** (consolidated, split-adjusted, no key — proven) behind a
  `MarketDataSource` adapter; Alpaca stays the execution broker. Paid upgrade path =
  Alpaca SIP or Polygon (one-file swap). Stooq rejected (anti-bot wall); keyed free tiers
  rejected (per-symbol caps too tight for 400 names).
- Exact canonical swing version label for 3.1 (resolve during implementation against the
  v1.x SOP files; entry gates are the deciding factor).
- Exact keep/promote boundary inside `_archive/` for any script worth turning into the funnel
  tool (resolve when building 1.1).
