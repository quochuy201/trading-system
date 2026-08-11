# Implementation Plan: Data Source Adapters

- **Slug:** `data-source-adapters` · **Status:** `plan` · **Design:** [`data-source-adapters-design.md`](data-source-adapters-design.md) · **Spec:** [`data-source-adapters-spec.md`](data-source-adapters-spec.md)
- **Executor:** Claude Code · **Date:** 2026-07-25

## How to Use This Plan

Ordered, bite-sized tasks. TDD per `CLAUDE.md`. After each task run the named tests, check the box, note the commit.

## Guardrails (read before writing code)

- **Downstream sees canonical types only** — no vendor field name may escape an adapter.
- **Missing capability ⇒ loud error, never silent substitution.** yfinance must never return daily bars when asked for intraday.
- **No LLM in the runtime data path.** Adapters are written at build time and tested.
- **Live/monitoring marks come from the execution broker**, not a third-party source (D3).
- Timestamps are **UTC ISO-8601** everywhere; the `adjusted` flag is explicit on every bar.
- Tools return JSON errors, never raise to the agent. All existing tests stay green.

---

## Tasks

### Task 1 — Canonical types + `capabilities()`
- **Files:** `tools/data/types.py` (new), `tools/data/source.py`
- **What:** `Bar`, `Quote`, `Capabilities`, `CapabilityError`. Add `capabilities()` to the ABC. `YFinanceSource` declares `daily=True, intraday=False, quotes=False, consolidated_volume=True, min_timeframe="1Day"` and its existing methods return canonical `Bar`s.
- **Tests:** `tools/tests/test_data_source.py` — yfinance returns `Bar` objects with UTC ISO-8601 `ts` and correct `adjusted`; `capabilities()` matches actual behaviour.
- **Acceptance:** canonical types exist; the current source still works through them.
- **Status:** ☐ todo

### Task 2 — Extend the interface + capability enforcement
- **Files:** `tools/data/source.py`
- **What:** add `get_intraday_bars`, `get_last_quote`, **`get_universe`** (full tradable list + liquidity fields — R1-S3 point-in-time rebuild) and **`get_movers`** (discovery beyond the universe — R1-S2) to the ABC. Base implementations raise `CapabilityError` when the corresponding capability is False, so an adapter cannot silently under-deliver.
- **Tests:** `test_data_source.py` — **`YFinanceSource.get_intraday_bars(...)` raises `CapabilityError`** and never returns daily bars; error message names the missing capability and the source.
- **Acceptance:** an unsupported request fails loudly.
- **Status:** ☐ todo

### Task 3 — `AlpacaSource` (equity: daily + intraday + quotes)
- **Files:** `tools/data/source.py` (or `tools/data/alpaca_source.py`), factory branch
- **What:** implement using `alpaca-py` (keys already in `.env`). Map bars → canonical `Bar` (UTC, `adjusted` set correctly), quotes → `Quote`, `get_universe()` from the **Assets API** (full tradable list — *not* the movers subset), `get_movers()` from the **movers/most-actives** endpoint. Declare `consolidated_volume=False` (IEX free feed). Register `"alpaca"` in the factory.
- **Tests:** `test_data_source.py` (mocked client) — canonical shapes; daily/intraday/quote paths; `capabilities()` honest about IEX volume; **`get_universe` comes from Assets and `get_movers` from movers — never conflated** (they answer different questions: universe = what we *could* trade, movers = what is *active today*).
- **Acceptance:** a second real adapter exists behind the unchanged seam.
- **Status:** ☐ todo

### Task 4 — Shared contract-conformance suite
- **Files:** `tools/tests/test_data_source_contract.py` (new)
- **What:** one parameterized suite run against **every** adapter: identical return types/keys for overlapping methods; UTC timestamps; no `None` where the contract promises a value; `capabilities()` never over-claims (calling a capability declared True must not raise).
- **Tests:** the suite itself; adding a future adapter automatically inherits it.
- **Acceptance:** adapters are interchangeable by contract, not by hope.
- **Status:** ☐ todo

### Task 5 — Role-based resolution + env binding + fail-at-boot
- **Files:** `tools/data/source.py` factory, `config/data_sources.yaml` (new), `tools/governance/limits.py` (shared env helper from `governance-gate` Task 1)
- **What:** `get_data_source(role)` where role ∈ `research | backtest` — **callers never name a vendor**; the role→adapter map lives in `config/data_sources.yaml` per env, so **a switch is one line and rollback is instant**. Env comes from the **same helper as broker mode + risk limits** (one switch, no second env var to drift); unknown/unset ⇒ dev. Keep `TRADING_DATA_SOURCE` as a test-only override. **Capability is checked at resolution** — a role whose required capability is missing raises **at startup**, never mid-session.
- **Tests:** `test_data_source.py` — dev ⇒ yfinance/cached, live ⇒ Alpaca, unknown ⇒ dev; **env matches broker mode** (live broker + dev data ⇒ startup failure); **a role requiring intraday resolved to yfinance raises at boot, not on first call**; **no caller passes a vendor name** (grep assertion); **`role="monitoring"` is rejected** — monitoring comes from the broker, not this factory.
- **Acceptance:** one environment decision drives broker + risk + data; switching is a config line.
- **Status:** ☐ todo

### Task 5b — Source-tagged cache (seam invariant #4)
- **Files:** `tools/data/cache.py`
- **What:** **add `source` to the cache key** — canonical `Bar` already carries it. This is the one piece of switch-safety that **must** exist before a second source does; retrofitting means invalidating the entire cache and losing the provenance of everything already stored.
- **Tests:** `test_data_cache.py` — ⚠️ **after resolving a different source, the cache must NOT return the previous source's rows** (the silent-corruption case: serving yfinance bars under Alpaca's name); provenance survives a round-trip.
- **Acceptance:** the cache can never serve one vendor's bars under another's name.
- **Status:** ☐ todo

### ⏸ DEFERRED to a future `data-source-switching` feature (not in scope)

Design intent is recorded in `design.md` §3a so it stays cheap to add — **do not build now**:

- **`ComparingSource(primary, candidate)`** — decorator that serves primary while logging candidate divergence (shadow mode for data; divergences reported, never averaged).
- **Role→source config table** for N providers — a factory branch suffices for two.
- **Cross-source consistency script** (was Task 8) — needed only at cutover.
- **Failover / multi-source merge**, and any 3rd provider (Polygon / Databento).

These are all **decorators over the same interface**, which is why deferring them costs nothing *provided the four seam invariants ship now* (design §3a-0).

### Task 6 — No vendor leakage (enforcement test)
- **Files:** `tools/tests/test_data_source_contract.py`
- **What:** assert downstream modules (`scanner/`, `analysis/`, monitor path) contain **no vendor-specific field names** (e.g. `filled_avg_price`, yfinance column names) — everything flows through canonical types.
- **Tests:** the grep-style assertion.
- **Acceptance:** the abstraction is real, not aspirational.
- **Status:** ☐ todo

### Task 7 — 🔴 Divergence audit + **post-install** reachability guard
- **Blocked by:** `deployment` (queue #0) — a repo-only test cannot prove runtime reachability.
- **Files:** `tools/tests/test_tool_groups.py` (repo-side), `setup/deploy/verify.sh` (runtime-side), short audit in `docs/product/research/`
- **What:** two assertions, because they answer different questions:
  1. **Repo-side:** the five options MCP tools (`get_options_chain`, `get_options_market_data`, `calc_iv_rank`, `get_put_skew`, `calc_expected_move`) are exposed in the options tool group.
  2. **⭐ Runtime-side (the one that matters):** **after `install.sh` runs**, assert those tools are reachable *in the deployed Hermes profile*. The repo and the runtime are **different systems, and only the runtime trades** — a CI-green reachability test proves nothing about Hermes. That gap is exactly how five tools stayed built-but-unreachable for 34 sessions.
  Plus: written audit of repo-vs-Hermes skill divergence (which skills exist where, which tools each references); full reconciliation handed to `deployment`.
- **Tests:** repo-side group assertion; runtime-side post-install verification invoked by the installer.
- **Acceptance:** **capability that exists but is unreachable fails a check, not a quarter of trading sessions** — and the check runs where the trading happens.
- **Status:** ☐ todo

### Task 8 — Cross-source consistency gate (before trusting Alpaca live)
- **Files:** `tools/scripts/compare_sources.py` (new)
- **What:** fetch the same symbols/date range from yfinance and Alpaca; compare OHLC within tolerance; **report discrepancies, never average them**. Run before switching the live default (D-DS1).
- **Tests:** comparison logic on fixtures (matching ⇒ pass; a seeded split-adjustment mismatch ⇒ flagged, not silently reconciled).
- **Acceptance:** we have evidence before trusting a new source with live decisions.
- **Status:** ☐ todo

### Task 9 — Docs + status
- **Files:** `PROJECT_STATUS.md`, `docs/product/ROADMAP.md`, `BUILD-PLAN.md` (D6 correction)
- **What:** record the divergence finding; **correct D6** — the options feed is built and unwired, so the FlashAlpha escalation is unnecessary; bump ROADMAP status.
- **Tests:** full suite green.
- **Acceptance:** the corrected understanding is written down where the next session will read it.
- **Status:** ☐ todo

---

## Definition of Done

- [ ] Tasks 1–9 done, boxes checked, commits noted
- [ ] Two adapters pass one shared contract suite
- [ ] Capability gaps fail loudly (yfinance intraday raises)
- [ ] No vendor field name reaches downstream code (enforced by test)
- [ ] `TRADING_ENV` drives broker + risk + data as one decision
- [ ] **Options tools proven reachable by their consumer**
- [ ] Cross-source consistency run before any live default change
- [ ] Full suite green; D6 corrected in BUILD-PLAN

## Decisions carried from spec

- **D-DS1** keep yfinance the daily default until the consistency gate passes; backtests stay on cached data
- **D-DS2** reachability test lives here; full Hermes/repo skill reconciliation goes to `deployment`
