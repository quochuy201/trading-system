# Design: Data Source Adapters

- **Slug:** `data-source-adapters` · **Status:** `design` · **Spec:** [`data-source-adapters-spec.md`](data-source-adapters-spec.md)
- **Author:** Claude Code · **Date:** 2026-07-25

> **Principle (D3):** design the interface around **what WE need**, not around any vendor's API. A thin adapter per provider translates vendor shape → our canonical types. Downstream never sees a vendor payload.

---

## 1. Two data roles, two owners

| Role | Used by | Owner | Provider |
|---|---|---|---|
| **Research / historical** | premarket scan, backtest | `MarketDataSource` | provider-independent — pick on quality/cost |
| **Live / monitoring** | open positions, stops, exits | **broker adapter** | **always the execution broker** (D3) |

The second row is the rule that prevents phantom exits: the marks you watch must be the marks you fill against. In backtest the "broker" is `SimulationBroker`, so the same rule holds with no special-casing.

---

## 2. The interface

```python
class MarketDataSource(ABC):
    # existing
    def get_daily_bars(symbols, start, end) -> dict[str, list[Bar]]
    def get_last_price(symbol) -> float | None
    # new
    def get_intraday_bars(symbols, start, end, timeframe) -> dict[str, list[Bar]]
    def get_last_quote(symbol) -> Quote | None
    def get_universe() -> list[UniverseEntry]   # full tradable list + liquidity fields (R1-S3)
    def get_movers(kind, top_n) -> list[str]    # discovery beyond the universe (R1-S2)
    def capabilities() -> Capabilities          # ← what this source can actually do
```

**Deliberately narrow.** It models our needs (6 methods), not the union of every vendor's API — that path bloats forever and still doesn't fit the next provider. Extend only when a real provider forces it.

**Why `get_universe` + `get_movers` are both here (R1 §S1–S3, decided 2026-07-25):**

- **`get_universe()`** returns the **full tradable list with liquidity fields** (Alpaca **Assets API** — not the movers subset). The scanner rebuilds its liquidity screen from this **periodically instead of freezing it**, and records membership history — that is the point-in-time universe, and it is what actually kills survivorship bias. Freezing a June-2025 screen is the bias; storing bars is not.
- **`get_movers()`** is the **discovery layer** for names outside the universe (the "blind to #401" problem) — Alpaca's movers/most-actives, free. Pull their bars on demand.

⚠️ **Both are discovery, never computation.** We fetch *bars* and compute our own indicators. Pre-computed-indicator APIs are **rejected** (R1 §S1): a screener returns only today's values ⇒ **backtest replay impossible (D7)**; vendor indicator math is unverifiable and silently divergent; and it is **signal-layer lock-in, which the adapter pattern cannot rescue** — unlike data-layer lock-in, there is no canonical form to normalize different indicator definitions into.

### Canonical types — the whole point of the adapter

```python
@dataclass(frozen=True)
class Bar:
    symbol: str; ts: str          # UTC ISO-8601, always
    open: float; high: float; low: float; close: float
    volume: int
    adjusted: bool                # explicit — split/dividend handling is a classic silent bug
    source: str                   # provenance

@dataclass(frozen=True)
class Quote:
    symbol: str; ts: str
    bid: float; ask: float; mid: float
    source: str
```

Vendor quirks — field names, pagination, auth, tz, adjusted-vs-raw — are absorbed **inside** the adapter. Downstream imports `Bar`/`Quote` and nothing else.

### Capabilities — say what you can't do

```python
@dataclass(frozen=True)
class Capabilities:
    daily_bars: bool
    intraday_bars: bool
    quotes: bool
    universe: bool
    consolidated_volume: bool     # False for Alpaca IEX (~2–3% of volume)
    min_timeframe: str            # "1Day" | "1Min" | ...
```

| Source | daily | intraday | quotes | universe | movers | consolidated volume |
|---|---|---|---|---|---|---|
| `YFinanceSource` | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| `AlpacaSource` (IEX free) | ✅ | ✅ | ✅ | ✅ (Assets) | ✅ | ❌ |

**Missing capability ⇒ loud failure, never silent substitution.** Asking yfinance for intraday raises `CapabilityError` — it must never quietly return daily bars, and a future RVOL consumer must refuse thin IEX volume rather than trust it. Same rule as the gate's `UNAVAILABLE`: **silence is the failure mode we design out.**

---

## 3. Selection — one switch, already established

```python
env = os.getenv("TRADING_ENV", "dev").lower()      # unknown/unset ⇒ dev (fail-safe)
```

`TRADING_ENV` already drives **broker mode + risk limits** (D2) and now **data source** (D3):

| `TRADING_ENV` | Broker | Risk limits | Research data | Live/monitoring data |
|---|---|---|---|---|
| `dev` | paper / simulation | `risk_limits.dev.yaml` | yfinance / cached | paper broker feed |
| `live` | live | `risk_limits.live.yaml` | Alpaca | live broker feed |

One environment decision; nothing can desync.

---

## 3a-0. ⭐ Scope: build the SEAM now, defer the MACHINERY

**We are not building a switching system.** We are building two sources with a clean seam between them. Provider *switching* — comparison runs, gradual rollout, an N-provider config table — is a **future feature**, and it will be cheap **precisely because** the seam exists.

The test for what belongs in this feature: **is it expensive to retrofit?**

### Build now — the four invariants (cheap today, costly later)

| Invariant | Why it can't wait |
|---|---|
| **1. Callers depend on the interface, never a vendor** | Retrofitting means touching every call site |
| **2. Canonical types at the boundary** (`Bar`/`Quote`) | Retrofitting means rewriting every consumer's field access |
| **3. Capability declaration** | Without it you can't tell what breaks when a source is added — you'd discover it in production |
| **4. Provenance on every datum** (`source` on each `Bar` **and in the cache key**) | Retrofitting means invalidating the whole cache, and past data's origin is unrecoverable |

These four are the seam. Each is a few lines now and a migration later.

### Defer — the switching machinery (a later feature)

- `ComparingSource` (shadow/compare before cutover)
- Role→source **config table** for N providers — a factory branch suffices for two
- Cross-source consistency script
- Failover / multi-source merge
- Any 3rd provider (Polygon, Databento)

⚠️ **`AlpacaSource` is NOT deferred** — it isn't "switching," it's **the only source that can serve the live role at all** (yfinance is daily-only, and monitoring needs intraday). It ships now out of necessity, not optionality.

### How this scales later — the interface is the extension point

Because the interface is narrow and typed, future capability arrives as **decorators**, not as edits to adapters:

```
ComparingSource(primary, candidate)   → shadow a switch
FailoverSource(primary, backup)       → resilience
CachingSource(inner)                  → already the shape of data/cache.py
```

All three are just a `MarketDataSource` wrapping other `MarketDataSource`s. **Adding behavior never touches an adapter; adding a provider never touches a consumer.** That is the whole return on getting the seam right, and it's why the interface stays at six methods rather than growing to fit each vendor.

---

## 3a. How a source switch will work (design intent — machinery deferred)

**Two adapters, two different switching semantics — this is the part that's easy to get wrong:**

| Adapter | Serves | Switchable? |
|---|---|---|
| `MarketDataSource` | research / historical bars | ✅ **config** |
| `BrokerAdapter` | **live + monitoring marks** | ❌ **not independently — it FOLLOWS the execution broker** |

**The monitoring feed is not a data-source choice at all.** You never "switch" it: it is whatever venue you execute through, because the marks you watch must be the marks you fill against (D3). Change brokers and it moves with them, automatically. So everything below applies **only** to the research/historical source.

### Resolve by ROLE, not by vendor name

```python
def get_data_source(role: str) -> MarketDataSource:
    """role: 'research' | 'backtest'.  NOT 'monitoring' — that is the broker."""
```

Callers ask for the source **for their role** and never name a vendor. The mapping lives in one table:

```yaml
# config/data_sources.yaml
dev:   { research: yfinance, backtest: cached }
live:  { research: alpaca,   backtest: cached }
```

**A switch is one line in one file.** Because it's config rather than code, **rollback is instant** — flip it back.

### Verify before you commit: `ComparingSource` (shadow mode, reused)

The same discipline as the governance gate — observe before enforcing:

```python
class ComparingSource(MarketDataSource):
    """Serves PRIMARY's data; fetches CANDIDATE too and logs divergence.
       Callers are unaffected — this is a decorator, not a switch."""
```

Run `primary=yfinance, candidate=alpaca` for a period, log every OHLC discrepancy, then flip once it's clean. **Divergences are reported, never averaged** — an averaged price is a fabricated price. This is what makes the switch *smooth* rather than a leap of faith, and it satisfies the D-DS1 consistency gate.

### Fail loudly at resolution, not at 9:31am

Capability is checked **when the source is resolved**, not when it's first called:

```python
src = get_data_source("research")
require(src.capabilities().intraday_bars, "research role needs intraday")   # raises at startup
```

A misconfigured source must fail on boot — never mid-session, and never by silently returning daily bars where intraday was expected.

### ⚠️ Gotcha: the cache must be source-tagged

`data/cache.py` sits between sources and consumers. If cached yfinance bars are served after a switch to Alpaca, you get **the old vendor's data under the new vendor's name** — a silent, near-undetectable corruption. Canonical `Bar` already carries `source`; the **cache key must include it**, and a source switch must not read another source's rows. Tested explicitly.

### What never switches

- **Monitoring** → execution broker, always.
- **Backtest** → cached/local always, never a live source. Reproducibility requires that a re-run of the same window return byte-identical bars.

---

## 4. 🔴 The divergence this feature must close

**The options data source already exists and was smoke-tested live** — `AlpacaOptionsSource` + 5 MCP tools (`get_options_chain`, `get_options_market_data`, `calc_iv_rank`, `get_put_skew`, `calc_expected_move`).

**The consumer cannot see it.** `Hermes/skills/options-trader/SKILL.md` exists only in the deployment, not the repo, and references **zero** of those tools (verified `grep -c` = 0). Its IVR gate therefore falls back to web search → stale, contradictory reads → 34 zero-trade sessions and 6 escalations for a feed **that was already built**.

```
REPO            AlpacaOptionsSource + 5 MCP tools   ──✗──   no options agent
HERMES DEPLOY   options-trader skill (IVR gate)     ──✗──   no options tools
                                                     ↑
                                          the drought lives here
```

**Fix, in two parts:**

1. **Reachability test (this feature).** Assert the options MCP tools are exposed in the options tool group and callable by the options consumer. This is the regression guard: *capability that exists but is unreachable must fail a test, not a quarter of trading sessions.*
2. **Skill reconciliation (`deployment`, parked).** The broader Hermes-vs-repo skill divergence is out of scope here — flagged, not fixed.

**This corrects D6:** the options data feed is **not a missing prerequisite**. It is built and unwired. The FlashAlpha escalation is unnecessary.

---

## 5. Adapter authorship — LLM at build time only

Writing an adapter is a bounded codegen task: read the vendor docs, map fields to canonical types, write the tests. **Claude Code does this at build time.**

⛔ **Never in the runtime data path.** A hallucinated field mapping is a wrong price is a wrong trade. The adapter pattern exists precisely so no runtime intelligence is needed — the mapping is written once, deterministically, and tested. Reject any "LLM adapts to any API at runtime" design.

---

## 6. Verification

**Deterministic — unit tested:**
- **Contract conformance:** every adapter returns identical canonical shapes/types for overlapping methods (one shared test suite parameterized over adapters).
- **Capability honesty:** yfinance intraday ⇒ `CapabilityError`; `capabilities()` matches actual behaviour for each adapter (no adapter may over-claim).
- **Canonicalization:** UTC ISO-8601 timestamps; `adjusted` flag correct; no vendor field names leak — a test greps downstream modules for vendor-specific keys.
- **Env selection:** unknown/unset ⇒ dev; live ⇒ Alpaca; env matches broker mode.
- **Reachability (the divergence guard):** options MCP tools are exposed in the options tool group.

**Cross-source consistency (gate before trusting Alpaca live):** same symbol + date range from yfinance and Alpaca must agree within tolerance on OHLC; discrepancies are reported, not averaged. Until this passes, yfinance stays the daily default (D-DS1).

**Judgment — none.** Perception is code.
