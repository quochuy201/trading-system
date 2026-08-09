# R1 — Scanner Redesign (Research & Decisions)

**Status:** research — in progress · **Last updated:** 2026-07-09
**Owner question (verbatim):** "we download and store daily bar data of 400 stock,
I don't think that's a good approach; research how pro algo traders do it."

Part of the [ROADMAP](../ROADMAP.md) research queue (R1). Becomes one or more
backlog features once the sub-items below are decided.

## The core question
Do pros (a) warehouse a fixed universe's bars locally, (b) query a vendor on demand,
or (c) use a server-side screener for a DYNAMIC candidate list then pull detail only
for the shortlist? And what do they store the data in?

## Current state (verified from code + DB, 2026-07-09)
- **Universe:** fixed list of 400 names. `scripts/load_universe.py`: all active/tradable
  US equities (Alpaca assets API) -> liquidity gate (price $10-500, 20d avg $vol >= $50M,
  measured June 2025) -> top 400 by dollar volume -> frozen into `universe_backtest.json`
  (count=400). Loader docstring admits survivorship bias ("active today").
- **Storage:** SQLite `price_data` in `trading.db` — 167,783 rows (154,582 daily `1Day`
  + 13,201 hourly `1Hour`), 410 symbols, ~409 daily bars each (~1.5 yr). Row-oriented.
  Whole DB = 23 MB.
- **Source:** `data/source.py` defaults to **yfinance** (`TRADING_DATA_SOURCE` default
  "yfinance"; Alpaca available as an alternate source).
- **Model:** batch "pull-and-store" the whole universe's history locally; scanner reads
  over stored bars each day.

## Research finding (x_search — X practitioner consensus, 2026-07-09)
The premise is **half wrong**: local storage of a fixed *liquid* universe with a nightly
ETL IS best practice for daily systematic scanning (fast, cheap after ingest, no rate
limits during ranking, reproducible backtests). The real weaknesses are three layers
underneath it:
1. **Source** — yfinance is prototyping-grade ("gaps, inconsistencies, rate limits —
   not suitable for production scanning or backtesting"). Pros use Polygon / Databento / Alpaca.
2. **Storage engine** — SQLite (row-oriented) is weak for cross-sectional scans
   ("close+volume across N names over a date range"). Pros use columnar: Parquet + DuckDB
   (embedded, no server) or ArcticDB (Arrow-based, used by Man Group).
3. **Fixed lens** — scanning the same 400 daily misses movers outside the list. Pros keep
   the fixed universe for systematic factors AND layer a server-side screener /
   most-actives / RVOL feed for the day's movers, then pull detail for the shortlist (hybrid).
Bonus: survivorship bias, already documented in the loader.
Sources: X practitioner posts (Databento/Polygon/Alpaca; DuckDB+Parquet; ArcticDB;
most-actives screeners), synthesised via x_search/Grok. Tool names are industry-standard;
storage claims to be hardened against official docs if we commit to the engine swap.

## Decisions log

### D-R1.1 — Database engine (2026-07-09): stay on SQLite in dev; keep it swappable
- **Decision:** Keep SQLite for the development phase (simple, cheap, zero-ops). Do NOT
  stand up a server DB (Postgres/MySQL/ClickHouse) now — over-engineering for a
  single-process system, and a dead DB daemon could take down the kill-switch path.
  Reassess a "real" DB only after the project is proven to work and be profitable.
- **Why it's already scalable:** all DB access is behind the Repository pattern
  (`persistence/db.py` = one connection factory; `persistence/repository.py` = 522-line
  `Repository`; all code + tests go through it). Swapping engines is localized to `persistence/`.
- **Swap friction (all inside `persistence/`, a migration-day task, NOT now):**
  `sqlite3.connect`/`sqlite3.Row`/PRAGMAs in db.py; ~10x `INSERT OR REPLACE` / `INSERT OR
  IGNORE` -> `ON CONFLICT`; 54x `?` placeholders -> `%s`; `AUTOINCREMENT` (5 tables) ->
  `SERIAL`/`IDENTITY`.
- **Recommended but DEFERRED hygiene:** make the DB path an env var
  (`DATABASE_URL`, default `sqlite:///trading.db`) so a future swap is config, not code
  (~5 lines). Not done yet — owner chose to capture the decision and move on.
- **Market-data columnar (DuckDB + Parquet):** deferred. At 167K rows / 23 MB there is no
  performance problem today; SQLite is fine. Revisit if scans get slow or the universe
  goes dynamic, after profitability is proven.

## ✅ DECIDED 2026-07-25 — S1/S2/S3 resolved: keep local bars; add discovery, fix the universe

**Owner question:** *"is there a data source that has all the indicators so we can filter candidates rather than store locally and compute ourselves? I think a local source of truth is best, but is it worth it?"*

### What daily bars actually serve (verified in code)

| Purpose | Code | Screener-API replaceable? |
|---|---|---|
| Live scanning — indicators to filter candidates (**needs ≥160 bars/symbol** for SMA150/ROC50, `scanner/filters.py:178,201`) | `scanner/filters.py` | ✅ in principle |
| Market regime — SPY trend/ATR | `analysis/regime.py` | ✅ (one symbol) |
| **Backtest replay** — bar-by-bar simulation | `broker/simulation.py`, `scripts/week_runner.py`, `scripts/param_sweep.py` | ❌ **impossible** |

### Pre-computed-indicator APIs exist…

Alpha Vantage (50+ indicators, MCP-compatible), Financial Modeling Prep, TradingView screener APIs, EODHD. The capability is real and cheap.

### …but they cannot replace local storage here. Four reasons, the first decisive:

1. **Backtest dies.** A screener returns *today's* values; you cannot ask "what was RSI on 2025-08-14 for the names that qualified then." **D7 edge validation is a hard gate** and requires historical replay.
2. **Unverifiable math.** Vendor RSI(14) with Wilder smoothing vs our SMA assumption ⇒ live and backtest disagree **silently**. That outsources the definition of our own signals.
3. **Reproducibility.** Vendors revise formulas and backfill; past results stop being reproducible.
4. **Signal-layer lock-in** — which the adapter pattern **cannot** rescue: every vendor computes indicators differently, so there is no canonical form to normalize to. (Data-layer lock-in is solvable; signal-layer is not.)

### The "wasteful 400" framing is quantitatively wrong — but two real problems hide under it

- **Cost reality:** 400 symbols × ~400 bars = **160K rows / 23 MB**. At 2,000 symbols ≈ 115 MB. Storage/compute is **not** a constraint. Matches the earlier R1 finding that local ETL of a liquid universe *is* best practice.
- **Survivorship bias — REAL.** ⚠️ But a screener API makes it **worse**: a live screener returns only currently-listed names *by definition*. Switching would **entrench** the bias. The bias comes from *freezing* a June-2025 liquidity screen, not from storing bars.
- **Blind to name #401 — REAL** (S2). The fixed list misses movers outside it.

### DECISION

> **Local bars remain the source of truth and we compute our own indicators. A screener is a DISCOVERY layer, never a COMPUTATION layer.**

1. **Keep local storage + own indicator math** — required for backtest, verifiable, reproducible, cheap.
2. **S3 — fix the universe, don't shrink it.** Rebuild the liquidity screen periodically instead of freezing it, and **record membership history** → that is the point-in-time universe, and it is what actually kills survivorship bias.
3. **S2 — add dynamic discovery.** Use Alpaca's movers / most-actives (free, already available) to surface names outside the list, then pull their bars on demand. Solves #401 with no purchase.
4. **S1 — do NOT buy an indicator API.** (Data-source swap to Alpaca still proceeds per D3 — that is bars, not indicators.)

**Knock-on:** if the D4 factor research lands on 4–6 factors rather than SMA150/ROC50, the ≥160-bar minimum may fall — shrinking storage further, though storage was never the binding constraint.

---

## Open sub-items (superseded by the decision above — kept for provenance)
- **S1 — Data source:** yfinance -> Alpaca. The `MarketDataSource` ABC seam exists
  (2 methods: `get_daily_bars`, `get_last_price`) and source.py's docstring explicitly
  intends the swap: "swap to a paid source (Alpaca SIP / Polygon) by adding a subclass
  and a factory branch — no scanner change." BUT `AlpacaSource` is NOT implemented — the
  factory only returns `YFinanceSource`; unknown names raise. `alpaca-py` is installed and
  keys are present (load_universe uses Alpaca for the asset LIST, but bars still come via
  yfinance). Swap = write ONE `AlpacaSource` class + one factory `elif` + set
  `TRADING_DATA_SOURCE=alpaca`. CAVEAT to verify: Alpaca FREE feed = IEX (partial volume,
  ~2-3% of consolidated) — fine for EOD daily bars, weaker for live intraday RVOL; full
  SIP / Polygon / Databento cost money (defer to post-profit). **NEXT.**
- **S2 — Dynamic candidates:** fixed 400 vs. server-side most-actives/movers + shortlist
  (closest to the "blind to name #401" pain).
- **S3 — Universe / survivorship:** point-in-time universe to kill survivorship bias.
- **S4 — Scoring/factors:** the 14-factor `design/factor-scanner-tdd.md` (engines M/R) —
  overlaps R4 (new strategies); likely defer there.

---

## Research kickoff — 2026-07-25 (D4: build deprioritized, research STARTED)

**D4 decision (BUILD-PLAN §2):** the scanner rebuild (binary gates → z-scored factor
ranking) is **deprioritized in build order** — it's an *improvement*, not a safety fix,
it's not a go-live blocker, and z-scoring on a survivorship-biased / stale universe is
garbage-in. Build it **after** the data foundation (S1 data source + S3 point-in-time
universe) **and after edge validation (D7)** — prove the *current* approach has edge before
adding sophistication. **But research starts now** (this section) so the design is ready
when the build slot opens.

**Already established — do NOT re-derive:**
- Local ETL of a fixed liquid universe + nightly scan = correct base pattern (R1 finding above).
- Scoring = cross-sectional **z-score per factor → combine → rank** (continuous score, not
  binary pass/fail). Edge comes from combining several **weakly-predictive, uncorrelated**
  factors — not one strong signal. Keep the set **small and independent**; every factor
  needs a one-line **economic rationale** (factors without it decay fast live); prune
  correlated factors (VIF). Start **4–6 factors, equal/simple weight**, validate by
  Information Coefficient + OOS — **NOT a 14-factor optimizer.** (Source: vault note
  `2026-07-25-Capital-Aware-Selection-Research` + alpha-construction findings.)
- The scanner is the **quantitative half of the signal-scoring stage**; research enrichment
  is the qualitative half. Its continuous score feeds **capital-aware selection** (rank by
  return-on-capital) — which is separable and ships earlier, on the current scanner.

**Open questions to answer during design (the S4 track):**
1. **Which 4–6 factors** for M (momentum) and R (reversion), each with an economic rationale
   — and are they independent (low pairwise correlation on our universe)?
2. **Normalization** — z-score lookback; cross-sectional (across today's universe) vs
   time-series (per name); outlier winsorization.
3. **Combination** — equal vs simple fixed weights; whether/how regime modulates them (keep minimal).
4. **Integration** — how the continuous score feeds capital-aware selection + regime eligibility.
5. **Validation** — measure each factor's IC on our universe OOS before trusting it; retire decayed factors.
6. **`design/factor-scanner-tdd.md`** (the pre-existing, never-implemented 14-factor design) —
   mine it for factor *definitions*, but treat the 14-count and weights as **unratified**.

**Cross-asset requirement (D6, decided 2026-07-25):** the scan/search phase must cover
**equity + options + index in ONE phase** — options candidates are identified here, not via a
separate parallel path (that divergence is what let the options track starve for 34 sessions).
Shape: universe → shared factors/signals → per candidate, which **strategy families** are
eligible (equity-swing-M/R, options-vol-edge if IVR/liquidity qualify) → price each eligible
(candidate × strategy) pair → **capital-aware ranking by return-on-capital ACROSS asset
classes**. So on a small account a cheap equity swing can correctly out-rank an unaffordable
options spread, judged by one metric instead of two starving pipelines. Implementation lands in
`capital-aware-selection` + `strategy-routing` — **not a new subsystem**. Requires an
options-data feed (IV/greeks/OI/quotes) to price options candidates at all.
**⛔ XSP is dropped** — not a fix, and adopting it would have been a covert strategy change
(index-vol harvesting). If index-vol is ever wanted, it enters as its own strategy family (Wave 3).

**Scope guard:** research/design track only — **no implementation until the build slot opens (post-D7).**
