# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Which document owns what

**One fact, one home.** Duplicated facts drift — that is the most-repeated defect in this project's history. If something belongs to another doc, **link it; do not restate it.**

| Doc | Owns | Read it when |
|---|---|---|
| **`PROJECT_STATUS.md`** | what is true *right now* — shipped work, known bugs | **first, every session** |
| **`docs/product/BUILD-PLAN.md`** | what we are *building* — ratified decisions D1–D7, architecture lock (§1.5), verification strategy (§4.5), build queue (§4.7) | before any design or build work |
| **`OPERATING_MANUAL.md`** | the risk constitution — modes, sizing, limits, breakers | before touching anything risk-related; **wins on conflict** |
| **this file** | how to *work here* — conventions, commands, invariants that rarely change | for "how do I add a tool / skill / SOP?" |

---

## ⛔ THREE RULES (owner-enforced)

Established 2026-07-25 after an independent review found ~30 defects (6 critical) in AI-authored design docs. **Every one had the same cause: a claim was written down that had never been looked at.** Rule 3 covers the other recurring class: **a value written down twice.**

### RULE 1 — Show the evidence, or write UNVERIFIED

Every factual claim about the code, the DB, a log, or the runtime carries the command and its output.

```
✅  "13 of 22 rows have price=0.0"
    $ sqlite3 tools/trading.db "select count(*) from trade_transactions where price=0"
    13
❌  "13 of 22 rows have price=0.0"      ← no output = a guess, not a fact
```

This catches 4 of the 5 real mistakes:

| Claim written | What one command would have shown |
|---|---|
| "convert the 9 priced rows into fills" | 6 of 9 prices == the plan's `entry_limit_price` — intents, not fills |
| "`fills.order_id` joins `orders.order_id`" | one is the broker's UUID, one is ours — 0 rows match |
| "`mode`/`conviction` feed the gate" | `grep -rn "DEFENSIVE" tools/` → **0 matches** |
| "the drought was caused by unreachable tools" | the cited `trades.jsonl` says **sizing**, and calls tools "SEPARATE" |

### RULE 2 — Name every file you changed

A cross-cutting fix that touched one file is incomplete. This failed ~10 times: design corrected, `spec`/`plan` left stale, so the broken instruction is what gets built.

```
✅  "Fixed C2 — changed: plan.md (Tasks 2,4), design.md (§7), spec.md (scope)"
❌  "Fixed C2."
```

### RULE 3 — Never hardcode. One value, one home.

**The test: if this value changed, how many places would I edit? More than one ⇒ it's hardcoded wrong.**

| Kind of value | Belongs in | Never in |
|---|---|---|
| Strategy logic — thresholds, scoring weights, entry/exit criteria | `sops/**` (versioned) or `skills/*/SKILL.md` | Python |
| Risk limits — sizing, caps, breakers | `config/risk_limits.{dev,live}.yaml` (D2) | code, or a second config |
| Paths | one variable per root, derived | repeated literals |
| Anything differing dev vs live | env-selected config, one switch | branches in code |
| Universe / symbols | config or DB | literals in a module |

**This is already violated, and it has already cost us** — each of these is a live example:

- **`scanner/filters.py:153-167`** — `SWING_V1` hardcodes **13 strategy thresholds** in Python, each commented with the SOP gate it mirrors. The comment `"r_rsi3_max": 10.0, # R-G5 (v1.2.0: was 15; v1.1.0: was 30)` *is a record of hand-copying a value across three SOP versions.* Change the SOP and the scanner silently keeps the old number.
- **`max_open_positions`** drifted **5 vs 10** between `config.yaml` and `OPERATING_MANUAL.md`.
- **`setup/deploy/runs/*.yaml`** carries `risk_budget` overrides nothing reads — a **4th** risk-limit source.
- **`install.sh`** used one `$REPO_DIR` for two roots at different depths → all three installers broken.

**Corollary:** a value duplicated "for convenience" is a future drift bug with a delay fuse. If code needs a strategy number, it **reads** it — it does not restate it.

### Not evidence

**A correct `file:line`** (wrong conclusions shipped *with* accurate citations — precision makes a wrong claim more persuasive) · **a green suite** (hand-built fixtures never touch production wiring; 3 of 12 gate rules pass tests and can never fire) · **"I checked."**

### Standing policy

Paper-only until D5 · gate ships in **shadow** first · D7 edge validation before real capital · kill switch never weakened. **No code can lose money before those gates clear.**

---

## How to develop

```
discuss → spec.md → design.md → adversarial review → plan.md → build → record
```

1. Read **`PROJECT_STATUS.md`** (known bugs first), then **`BUILD-PLAN.md`** (§4.7 = the queue — do not duplicate it here).
2. Work from `docs/product/features/<slug>/plan.md`, one task at a time, tests green, commit per task.
3. **Exactly three files per feature**, each named for the feature so editor tabs and search stay unambiguous:
   ```
   docs/product/features/<slug>/<slug>-spec.md
                                <slug>-design.md
                                <slug>-plan.md
   ```
   Never `design-v2.md`; **git is the version history**. Superseded drafts → `docs/_archive/<slug>-superseded/`.
4. **Adversarial review before building**, with **cold context** (repo only). Self-review found 10 issues where an independent pass found ~30 incl. 6 criticals. A finding is closed **by a commit**, not by agreement.

### Update PROJECT_STATUS.md when — (it went a month stale under a vaguer rule)

| Trigger | Add |
|---|---|
| decision ratified | one dated line + where detail lives |
| feature status change (`spec`→`design`→`plan`→`building`→`shipped`) | one dated line |
| bug found **or** closed | entry under Known bugs (closed ⇒ with evidence) |
| code ships | changelog: what changed, which files |

**Self-check:** the `Last updated:` header must match the newest dated entry. Mismatch = stale.

---

## Commands

```bash
# MCP tools server — use the launcher, NOT `uv run server.py`
tools/run_mcp.sh
#   It execs .venv/bin/python directly. `uv run` can re-resolve and emit on the stdio
#   channel, breaking the MCP handshake ("Connection closed" / TaskGroup errors on
#   fresh gateways). Fixed in 505daaf — don't undo it.
#   TRADING_TOOL_GROUPS (comma-separated, per Hermes profile) gates which tools
#   server.py registers; unset = all 61.

# Tests
cd tools && uv run --extra dev pytest tests/ -v
cd tools && uv run --extra dev pytest tests/test_broker.py -v
cd tools && uv run --extra dev pytest tests/test_broker.py::test_place_order -v

# Platform install — ⛔ ALL THREE INSTALLERS ARE BROKEN
./install.sh hermes            # see PROJECT_STATUS Known bugs; fix = features/deployment/
```

---

## Repo map

```
CLAUDE.md · OPERATING_MANUAL.md · PROJECT_STATUS.md · config.yaml · install.sh
docs/product/     BUILD-PLAN.md, features/<slug>/{spec,design,plan}.md, research/
skills/           research · trader · monitor · risk-manager · eod-review · backtest
sops/             <asset-class>/<strategy>/v<semver>.md  +  _routing/
tools/            server.py (MCP surface) + broker/ data/ scanner/ analysis/
                  persistence/ risk/ audit/ notifications/ backtest/ tests/
setup/deploy/     SOUL.md, profile.yaml, distribution.yaml, mcp.json, cron/, runs/
                  ⚠️ NOT at repo root — several docs/scripts still assume they are
```

**Package intent:** a harness-neutral agent package (markdown skills + Python MCP tools) distributed as a Hermes profile. ⚠️ **Currently aspirational** — the repo does not reach the runtime, and the runtime executes options skills with no repo counterpart. See PROJECT_STATUS Known bugs.

---

## Architecture

```
Orchestrator (setup/deploy/SOUL.md) — coordinates, never trades
  ├── research      scan + score candidates
  ├── trader        plan + place orders
  ├── monitor       track + exit positions
  ├── risk-manager  mode + sizing + circuit breakers
  ├── eod-review    journal + reflect
  └── backtest      historical replay
```

| Layer | Files | Changes require |
|---|---|---|
| Agent behaviour | `SOUL.md`, `skills/*/SKILL.md`, `sops/**` | understanding the trading domain |
| Tool implementation | `tools/server.py` + submodules | tests green, risk invariants preserved |

**Data flow:** agent → MCP tool → `broker/adapter.py` (→ `alpaca.py` live/paper · `simulation.py` backtest) → `persistence/repository.py` → SQLite (`tools/trading.db`) → `notifications/` (discord · slack · telegram, fire-and-forget).

**Target decision architecture is Pattern C** — see BUILD-PLAN §1.5, which supersedes any earlier description.

### Safety invariants (do not weaken)

- **`OPERATING_MANUAL.md` is the constitution** and overrides all other files on conflict.
- **Agents never call the broker directly** — everything goes through MCP tools (retry, ledger, kill switch).
- **SOPs are human-controlled** — agents propose to `reports/sop-changes/`, never edit `sops/`.
- **Kill switch blocks `place_order`** (`server.py:166`). ⚠️ It is the **only** hard gate today; everything else in the manual is advisory markdown. Closing this = `governance-gate`.
- **Target: exactly ONE function reaches the broker.** Order kinds differ by *parameters*, not by *function* (BUILD-PLAN §1.5). Three paths exist today — do not add a fourth.
- **Simulation broker** swaps the global `_broker` for backtests: `start_backtest_v2` (`:1998`) → `advance_to_next_day` (`:2085`) → `step_bar` (`:2132`). No future-data leakage.

### Strategy routing (shipped — not part of the deferred scanner rebuild)

`get_market_regime` (`server.py:237`) → `sops/_routing/v1.1.0.md` §1 → per-asset verdict `ON | OFF | R-ONLY | M-ONLY`.

Three semantics that must not be weakened: **`null` signal ⇒ strategy OFF** (fail-safe) · **first matching row wins**, ties → most restrictive · **the gate may only SUBTRACT** from what mode/limits allow. Equity rows use price-derived signals only, so they stay computable in backtest where `iv_rank_spy` is null by design.

### Observability — "why did nothing trade?"

Check these **before** touching thresholds; the 2026-06-23 drought was stale data, not thresholds.

| Mechanism | Where |
|---|---|
| `scan_funnel` table — mechanical per-run funnel, complete even when the agent under-logs | `persistence/db.py:246`, written by both scan tools |
| `get_daily_funnel(date)` — joins scan + decisions + ledger into a `why_zero` line | `server.py:1281` |
| Tuning bridge — EOD writes overrides, scanner reads them before every scan | `scanner/tuning.py` + `tuning_config.json` |

---

## BACKTEST RULES (non-negotiable — violating them produces misleading results)

1. **Never hardcode strategy logic** — see **RULE 3**. Python does mechanical work only (did price hit the stop?). ⚠️ Currently violated by `SWING_V1` (`scanner/filters.py:153`), which mirrors SOP thresholds in code.
2. **Backtest must use the same code path as live.** A scanner built only for backtest proves nothing. ⚠️ *Not true yet* — `backtest_enter`/`backtest_exit` are separate tools from `place_order`; see PROJECT_STATUS.
3. **Enter at next-available price, never signal price.** Scanner runs when the market is closed; you cannot buy at that close. Fill at the **next bar's open**.
4. **Gap detection:** gap UP >5% above planned entry ⇒ SKIP (don't chase); gap DOWN >3% ⇒ SKIP (thesis may be broken).
5. **The agent decides, Python doesn't.** Python advances the clock, serves data, runs mechanical checks, logs. The agent reads skills, judges catalysts, scores, sizes.
6. **Don't invoke the LLM every bar.** Start of day (research + DD) and unusual events (>3% move); everything else is mechanical.

---

## Conventions

**MCP tools (`tools/server.py`)**
- Docstring with purpose · when to use · sample input · expected output.
- State-mutating tools log to the ledger via `_log_to_ledger()` (`:68`).
- **Never raise to the agent** — return `{"error": "..."}`.
- Wrap flaky broker calls in `with_retry(fn, _retry_config)()`.
- **Adding a tool means editing `TOOL_GROUPS` (`:2799`)** — a tool in no group is unreachable by every profile. `tests/test_tool_groups.py` asserts the total; update it deliberately, never to silence a failure.

**Broker adapters** — implement `broker/adapter.py`; return the same shapes as `alpaca.py`; simulation must respect `current_time`.

**Skills (`skills/*/SKILL.md`)** — [agentskills.io](https://agentskills.io/specification) format. `description` starts with "Use when…" (triggering conditions only, never a workflow summary). `requires_tools` lists only tools actually called — all 6 skills carry it; keep it that way. **Skills define behaviour; tools define capability.**

**SOPs (`sops/<asset-class>/<strategy>/v<semver>.md`)** — versioned; changing logic means a **new version file**, never an in-place edit.

**Scanner** — ⚠️ read BUILD-PLAN first: binary gates → z-scored factor ranking, frozen 400-name universe → point-in-time rebuild + movers discovery (R1). Build deferred, but don't design against the old model. Entry points `scan_universe` (`filters.py:26`) and `scan_universe_swing` (`:170`); both apply tuning config and write a `scan_funnel` row. **The scanner outputs candidates; the agent decides.**

---

## Domain glossary

| Concept | Where | Meaning |
|---|---|---|
| Kill switch | `server.py:166` | emergency halt — closes positions, blocks new orders |
| R:R | `sops/`, `skills/trader/` | reward ÷ risk. Minimum 2:1 |
| R-multiple | (see `go-live-metrics`) | trade outcome in units of initial risk — **the** performance metric |
| ATR | `analysis/indicators.py` | volatility measure for stop placement |
| RVOL | `scanner/filters.py` | today's volume vs 20-day average |
| Regime | `analysis/regime.py` | inputs to the routing eligibility gate |
| Kelly | `OPERATING_MANUAL.md §3.4` | sizing formula, capped at quarter-Kelly |
| Compliance score | `audit/compliance.py` | fraction of decisions following SOP; <0.9 forces DEFENSIVE |

**Where the AI earns its keep over code:** interpreting news/sentiment, recognising novel conditions, adapting strategy selection, 24/7 monitoring. **Everything mechanical belongs in Python.**

---

## Configuration

- **`config.yaml`** — risk parameters, broker mode (`paper | live | simulation`), scheduling, income gating.
- **`.env`** (repo root, loaded by `server.py`) — required `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`; optional `ALPACA_BASE_URL`, `TRADING_DATA_SOURCE`, `DISCORD_WEBHOOK_URL`, `SLACK_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN`+`TELEGRAM_CHAT_ID`, `REDDIT_CLIENT_ID`+`REDDIT_CLIENT_SECRET`.
- **`TRADING_TOOL_GROUPS`** — per-profile tool gating (`server.py:2855`); unset = all tools.
- **`setup/deploy/distribution.yaml`** · **`mcp.json`** — Hermes manifest + MCP declaration. ⚠️ `mcp.json`'s `mcp_tools:` namespaces do **not** match `TOOL_GROUPS` — dead config that looks authoritative.
- **`setup/deploy/runs/*.yaml`** — ⚠️ carry `risk_budget` overrides **nothing reads** (a 4th undocumented risk source). Don't trust; resolved in `deployment`.
- **After D2:** `config/risk_limits.{dev,live}.yaml` becomes the single risk source, selected by `TRADING_ENV` bound to broker mode.
