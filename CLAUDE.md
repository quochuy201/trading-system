# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Which document owns what

**One fact, one home.** Duplicated facts drift — that is the most-repeated defect in this project's history. If something belongs to another doc, **link it; do not restate it.**

| Doc | Owns | Read it when |
|---|---|---|
| **`PROJECT_STATUS.md`** | what is true *right now* — shipped work, known bugs | **first, every session** |
| **`docs/product/BUILD-PLAN.md`** | what we are *building* — ratified decisions D1–D7, architecture lock (§1.5), verification strategy (§4.5), build queue (§4.7) | before any design or build work |
| **`OPERATING_MANUAL.md`** | the risk constitution — modes, sizing, limits, breakers | before touching anything risk-related; **wins on conflict** |
| **`docs/product/ARCHITECTURE-MAP.md`** | how the pieces fit — role-agents ↔ 6-layer pipeline, per-layer state | to find where something lives |
| **this file** | how to *work here* — conventions, commands, invariants that rarely change | for "how do I add a tool / skill / SOP?" |

## ⛔ THREE RULES (owner-enforced)

Established 2026-07-25 after an independent review found ~30 defects (6 critical) in AI-authored design docs. **Every one had the same cause: a claim was written down that had never been looked at.** Rule 3 covers the other recurring class: **a value written down twice.** (Detail: PROJECT_STATUS 2026-07-25 entry.)

### RULE 1 — Show the evidence, or write UNVERIFIED

Every factual claim about the code, the DB, a log, or the runtime carries the command and its output.

```
✅  "13 of 22 rows have price=0.0"
    $ sqlite3 tools/trading.db "select count(*) from trade_transactions where price=0"
    13
❌  "13 of 22 rows have price=0.0"      ← no output = a guess, not a fact
```

One command would have caught 4 of the 5 real mistakes — e.g. "`fills.order_id` joins `orders.order_id`" (one is the broker's UUID, one is ours: 0 rows match), and "the drought was caused by unreachable tools" (the cited `trades.jsonl` says **sizing**).

### RULE 2 — Name every file you changed

A cross-cutting fix that touched one file is incomplete. This failed ~10 times: design corrected, `spec`/`plan` left stale, so the broken instruction is what gets built.

```
✅  "Fixed C2 — changed: implementation-plan.md (Tasks 2,4), design.md (§7), spec.md (scope)"
❌  "Fixed C2."
```

### RULE 3 — Never hardcode. One value, one home.

**The test: if this value changed, how many places would I edit? More than one ⇒ it's hardcoded wrong.**

| Kind of value | Belongs in | Never in |
|---|---|---|
| Strategy logic — thresholds, scoring weights, entry/exit criteria | `sops/**` (versioned) or `skills/*/SKILL.md` | Python |
| Risk limits — sizing, caps, breakers | `config/risk_limits.{dev,live}.yaml` (D2; until then `config.yaml`) | code, or a second config |
| Paths | one variable per root, derived | repeated literals |
| Anything differing dev vs live | env-selected config, one switch | branches in code |
| Universe / symbols | config or DB | literals in a module |

**Live violations** (each tracked in PROJECT_STATUS Known bugs):

- **`SWING_V1`** in `scanner/filters.py` hardcodes **13 strategy thresholds** in Python, each copied from a swing-SOP gate; its comment pins them to v1.2.0. SOPs v1.3–v1.6 happen not to change a gate, but nothing checks that: change a gate in the SOP and the scanner silently keeps the old number.
- **`max_open_positions`**: `risk/checks.py` defaults to **5**; `config.yaml` and `OPERATING_MANUAL.md` say **10** (ratified 2026-06-11). The live check uses 5. Fix belongs to D2 (`governance-gate`).

**Corollary:** a value duplicated "for convenience" is a future drift bug with a delay fuse. If code needs a strategy number, it **reads** it — it does not restate it.

### Not evidence

**A correct `file:line`** (wrong conclusions shipped *with* accurate citations — and line numbers drift; **name the symbol instead**) · **a green suite** (hand-built fixtures never touch production wiring; the 07-25 review found two gate rules that would pass their tests yet could never fire) · **"I checked."**

### Standing policy

Paper-only until D5 · gate ships in **shadow** first · D7 edge validation before real capital · kill switch never weakened. **No code can lose money before those gates clear.**

## How to develop

```
discuss → spec.md → design.md → adversarial review → implementation-plan.md → build → record
```

1. Read **`PROJECT_STATUS.md`** (known bugs first), then **`BUILD-PLAN.md`** (§4.7 = the queue — do not duplicate it here).
2. Work from `docs/product/features/<slug>/<slug>-implementation-plan.md`, one task at a time, tests green, commit per task.
3. **A feature has exactly three files**, each named for the feature: `docs/product/features/<slug>/<slug>-{spec,design,implementation-plan}.md`. Never `design-v2.md`; **git is the version history**. A **change** to existing behaviour (fix, cleanup, refactor) gets one note instead: `docs/product/changes/<slug>/change.md`.
4. **Adversarial review before building**, with **cold context** (repo only). Self-review found 10 issues where an independent pass found ~30 incl. 6 criticals. A finding is closed **by a commit**, not by agreement.

**Update `PROJECT_STATUS.md`** when a decision is ratified, a feature changes status, a bug is found or closed (closed ⇒ with evidence), or code ships (what changed, which files). **Self-check:** its `Last updated:` header must match the newest dated entry.

## Commands

```bash
# MCP tools server — use the launcher, NOT `uv run server.py`
tools/run_mcp.sh
#   Execs .venv/bin/python directly. `uv run` can re-resolve and emit on the stdio
#   channel, breaking the MCP handshake (fixed in 505daaf — don't undo it).
#   TRADING_TOOL_GROUPS (comma-separated, per Hermes profile) gates which tools
#   server.py registers; unset = all. tests/test_tool_groups.py asserts the total.

# Tests (uv, or the venv directly where uv isn't installed)
cd tools && uv run --extra dev pytest tests/ -v
cd tools && .venv/bin/python -m pytest tests/ -q
cd tools && .venv/bin/python -m pytest tests/test_broker.py::TestAlpacaBrokerAdapter::test_place_market_order -v
#   The deploy-script tests (test_deploy_preflight/verify) need a populated
#   trading.db and the hermes CLI; they fail on a fresh clone.

# Install — the one installer. Status: docs/product/features/deployment/
./install.sh hermes
```

## Repo map

```
CLAUDE.md · OPERATING_MANUAL.md · PROJECT_STATUS.md · README.md · config.yaml · install.sh
docs/product/     BUILD-PLAN.md, ROADMAP.md, ARCHITECTURE-MAP.md, research/,
                  features/<slug>/<slug>-{spec,design,implementation-plan}.md,
                  changes/<slug>/change.md
docs/design/      pre-BUILD-PLAN designs — superseded, read the banner first
skills/           research · trader · monitor · risk-manager · eod-review · backtest
sops/             <asset-class>/<strategy>/v<semver>.md  +  _routing/
tools/            server.py (MCP surface) + broker/ data/ scanner/ analysis/ risk/
                  persistence/ audit/ backtest/ notifications/ scripts/ tests/
setup/deploy/     SOUL.md, profile.yaml, distribution.yaml, mcp.json, cron/, runs/,
                  preflight.sh, verify.sh — ⚠️ NOT at repo root
```

**Package intent:** a harness-neutral agent package (markdown skills + Python MCP tools) distributed as a Hermes profile. The runtime only changes when someone runs `./install.sh hermes`; check PROJECT_STATUS for how far behind the repo it is.

## Architecture

Orchestrator (`setup/deploy/SOUL.md`) coordinates six skills over Hermes kanban boards; it never trades. Full map: `docs/product/ARCHITECTURE-MAP.md`. Target decision architecture: **Pattern C**, BUILD-PLAN §1.5.

| Layer | Files | Changes require |
|---|---|---|
| Agent behaviour | `SOUL.md`, `skills/*/SKILL.md`, `sops/**` | understanding the trading domain |
| Tool implementation | `tools/server.py` + submodules | tests green, risk invariants preserved |

**Data flow:** agent → MCP tool → `broker/adapter.py` (→ `alpaca.py` live/paper · `simulation.py` backtest) → `persistence/repository.py` → SQLite (`tools/trading.db`) → `notifications/` (discord · slack · telegram, fire-and-forget).

### Safety invariants (do not weaken)

- **`OPERATING_MANUAL.md` is the constitution** and overrides all other files on conflict.
- **Agents never call the broker directly** — everything goes through MCP tools (retry, ledger, kill switch).
- **SOPs are human-controlled** — agents propose to `reports/sop-changes/`, never edit `sops/`.
- **The kill switch blocks new orders** — `place_order` and `place_multileg_order` check it first. ⚠️ It is the **only** hard gate today; everything else in the manual is advisory markdown. Closing this = `governance-gate`.
- **Target: exactly ONE function reaches the broker** (BUILD-PLAN §1.5). Three paths exist today — `place_order`, `place_multileg_order`, and the close-all inside `activate_kill_switch`. Do not add a fourth.
- **Routing** (`get_market_regime` → `sops/_routing/v1.1.0.md`): `null` signal ⇒ strategy OFF · first matching row wins, ties → most restrictive · the gate may only SUBTRACT. Never weaken these.
- **Simulation broker** swaps the global `_broker` for backtests (`start_backtest_v2` → `advance_to_next_day` → `step_bar`). No future-data leakage.

### Observability — "why did nothing trade?"

Check these **before** touching thresholds; the 2026-06-23 drought was stale data, not thresholds.

- **`scan_funnel` table** — mechanical per-run funnel, written by both scan tools, complete even when the agent under-logs.
- **`get_daily_funnel(date)`** — joins scan + decisions + ledger into a `why_zero` line.
- **Tuning bridge** — `scan_universe_swing` (not `scan_universe`) and the risk-check tools read `tools/scanner/tuning_config.json`. ⚠️ Nothing updates the file: commit `4c78ff6` truncated the EOD skill (348→68 lines) and the monitor skill (548→129), and the `generate_tuning_config` step was lost with it (PROJECT_STATUS Known bugs).
- **`get_go_live_scorecard()`** — D5 readiness; **`run_eod_reconcile()`** turns broker fills into round trips.

## BACKTEST RULES (non-negotiable — violating them produces misleading results)

1. **Never hardcode strategy logic** — RULE 3. Python does mechanical work only (did price hit the stop?).
2. **Backtest must use the same code path as live.** A scanner built only for backtest proves nothing. ⚠️ Not true yet — `backtest_enter`/`backtest_exit` are separate tools from `place_order` (PROJECT_STATUS Known bugs).
3. **Enter at next-available price, never signal price.** Scanner runs when the market is closed; fill at the **next bar's open**.
4. **Gap detection:** gap UP >5% above planned entry ⇒ SKIP (don't chase); gap DOWN >3% ⇒ SKIP (thesis may be broken).
5. **The agent decides, Python doesn't.** Python advances the clock, serves data, runs mechanical checks, logs. The agent reads skills, judges catalysts, scores, sizes.
6. **Don't invoke the LLM every bar.** Start of day (research + DD) and unusual events (>3% move); everything else is mechanical.

## Conventions

**MCP tools (`tools/server.py`)**
- Docstring with purpose · when to use · sample input · expected output.
- State-mutating tools log to the ledger via `_log_to_ledger()`.
- **Never raise to the agent** — return `{"error": "..."}`.
- Wrap flaky broker calls in `with_retry(fn, _retry_config)()`.
- **Adding a tool means editing `TOOL_GROUPS` in `server.py`** — a tool in no group is unreachable by every profile. A tool that must stay out of every group (e.g. one only cron calls) goes in `UNGROUPED_BY_DESIGN` instead. `tests/test_tool_groups.py` fails on any tool that is in neither, and asserts the total; update it deliberately, never to silence a failure.

**Broker adapters** — implement `broker/adapter.py`; return the same shapes as `alpaca.py`; simulation must respect `current_time`.

**Skills (`skills/*/SKILL.md`)** — [agentskills.io](https://agentskills.io/specification) format. `description` starts with "Use when…" (triggering conditions only, never a workflow summary). `requires_tools` lists only tools actually called and mirrors a `TOOL_GROUPS` entry. **Skills define behaviour; tools define capability.**

**SOPs (`sops/<asset-class>/<strategy>/v<semver>.md`)** — versioned; changing logic means a **new version file**, never an in-place edit.

**Scanner** — read BUILD-PLAN D4 + `docs/product/research/R1-scanner-redesign.md` first: the rebuild (z-scored factors, point-in-time universe) is deferred, but don't design against the old model. Entry points `scan_universe` and `scan_universe_swing` in `scanner/filters.py`. **The scanner outputs candidates; the agent decides.**

## Domain glossary

| Concept | Where | Meaning |
|---|---|---|
| Kill switch | `check_kill_switch` / `activate_kill_switch` | emergency halt — closes positions, blocks new orders |
| R:R | `sops/`, `skills/trader/` | reward ÷ risk. Minimum 2:1 |
| R-multiple | `audit/round_trips.py` | trade outcome in units of initial risk — **the** performance metric |
| ATR | `analysis/indicators.py` | volatility measure for stop placement |
| RVOL | `scanner/filters.py` | today's volume vs 20-day average |
| Regime | `analysis/regime.py` | raw inputs to the routing eligibility gate |
| Kelly · compliance score | `OPERATING_MANUAL.md` | sizing cap (quarter-Kelly) · fraction of decisions following SOP — both manual rules, not enforced in code |

**Where the AI earns its keep over code:** interpreting news/sentiment, recognising novel conditions, adapting strategy selection, 24/7 monitoring. **Everything mechanical belongs in Python.**

## Configuration

- **`config.yaml`** — risk parameters, broker mode (`paper | live | simulation`), scheduling, income gating, strategy registry.
- **`.env`** (repo root, loaded by `server.py`) — required `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`; optional `ALPACA_BASE_URL`, `DISCORD_WEBHOOK_URL`, `SLACK_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN`+`TELEGRAM_CHAT_ID`, `REDDIT_CLIENT_ID`+`REDDIT_CLIENT_SECRET`. Template: `setup/deploy/.env.EXAMPLE`.
- **`TRADING_TOOL_GROUPS`** · **`TRADING_DATA_SOURCE`** · **`TRADING_OPTIONS_SOURCE`** — env switches; unset = all tools · `yfinance` · `alpaca`.
- **`setup/deploy/distribution.yaml`** · **`mcp.json`** — Hermes manifest + a generic MCP declaration. Hermes never reads `mcp.json` (it keys servers under `mcp_servers:` in the profile config); `install.sh` points Kermes users at it.
- **`setup/deploy/runs/*.yaml`** — per-asset run descriptors. Only `board` is read (by `verify.sh` check 6). Risk limits never go here.
