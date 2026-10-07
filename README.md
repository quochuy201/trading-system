# Trading System

SOP-driven autonomous trading system, installed as a [Hermes profile](https://hermes-agent.nousresearch.com/docs/user-guide/profile-distributions) with `./install.sh hermes`.

**Paper trading only.** Current state and known bugs: [`PROJECT_STATUS.md`](PROJECT_STATUS.md). The plan: [`docs/product/ROADMAP.md`](docs/product/ROADMAP.md) and [`docs/product/BUILD-PLAN.md`](docs/product/BUILD-PLAN.md).

## Architecture

```
Orchestrator (setup/deploy/SOUL.md) — coordinates, never trades, has no MCP tools
  │  kanban boards: equity · options
  │  daily chain per board: 1-risk-regime → 2-research-scan → 3-trade-exec
  ▼
`trading` profile — one profile; each task names the skill to run
  research · trader · monitor · risk-manager · eod-review · backtest
  │
  ▼
Python MCP tools (tools/server.py) — the only path to the broker and the DB
```

Strategy logic lives in versioned SOPs (`sops/`). `OPERATING_MANUAL.md` is the risk constitution and wins on any conflict. Full map: [`docs/product/ARCHITECTURE-MAP.md`](docs/product/ARCHITECTURE-MAP.md).

The installer schedules these weekday cron jobs, in this order through the day. The times live in `install_hermes` in `install.sh`.

| Job | Runs |
|-----|------|
| `trading-data-refresh` | Refresh daily bars for the scan universe |
| `trading-equity-morning` | Preflight, then create the `equity` board's daily chain |
| `trading-options-morning` | Preflight, then create the `options` board's daily chain |
| `trading-monitor-sentinel` | Every minute in market hours: runs the monitor skill as a **full LLM session** (`hermes -p trading -z`). The no-LLM pre-check `tools/monitor_sentinel.py` exists but nothing calls it |
| `trading-iv-capture` | Capture implied volatility across the universe |
| `trading-eod` | EOD review skill: reconcile fills, go-live scorecard, journal, compliance score |

## Quick Start

### Install

```bash
git clone https://github.com/quochuy201/trading-system
cd trading-system
./install.sh hermes --dry-run   # print the plan; runs no hermes command
./install.sh hermes
```

Installing is a deploy: it changes the live Hermes runtime. It creates the `trading` profile under `$HERMES_HOME` (default `~/.hermes`), copies the orchestrator, `OPERATING_MANUAL.md`, skills, SOPs and cron scripts, registers the MCP server `trading-tools` (this checkout's `tools/run_mcp.sh`), creates the `equity` and `options` boards and the crons, and removes legacy `trading-<role>` profiles. It ends with `setup/deploy/verify.sh` and exits non-zero if verification fails.

### Configure

```bash
cp setup/deploy/.env.EXAMPLE .env   # .env is read from the repo ROOT by server.py
# Edit .env with your Alpaca API keys
```

### Run

```bash
# Install deps — uv.lock is not committed, it is regenerated per platform
(cd tools && uv sync --extra dev)

# Start the MCP tools server — use the launcher, NOT `uv run server.py`
# (`uv run` can re-resolve and write on the stdio channel, breaking the MCP handshake)
tools/run_mcp.sh

# Then chat with the orchestrator on your platform
```

## Structure

```
├── CLAUDE.md                # How to work in this repo: conventions, invariants
├── OPERATING_MANUAL.md      # Constitution: mode state machine, sizing math, circuit breakers — read first
├── PROJECT_STATUS.md        # What is true now: shipped work, known bugs
├── config.yaml              # Risk defaults, broker mode, income gating
├── install.sh               # Installer; `hermes` is the supported target
├── setup/deploy/            # What the Hermes install copies or registers
│   ├── SOUL.md              # Orchestrator
│   ├── profile.yaml         # Becomes the `trading` profile's config.yaml
│   ├── distribution.yaml    # Hermes profile manifest
│   ├── mcp.json             # Generic MCP declaration (Hermes does not read it)
│   ├── .env.EXAMPLE         # Template for the root .env
│   ├── preflight.sh         # Gate the morning crons run before creating tasks
│   ├── verify.sh            # Post-install check (uses mcp_probe.py)
│   ├── cron/                # Cron scripts the installer schedules
│   ├── runs/                # Per-asset run descriptors (verify.sh reads `board`)
│   └── profiles/            # Per-role SOULs; install.sh does not use them
├── skills/                  # One SKILL.md per role
│   ├── research/            # Scan + scored due diligence
│   │   └── reference/       # Due-diligence guides per market and strategy
│   ├── trader/              # Risk-validated order placement
│   ├── monitor/             # Stop, target, trailing and time-stop exits
│   ├── risk-manager/        # Mode, position sizing, circuit breakers
│   ├── eod-review/          # Journal, metrics, compliance score
│   └── backtest/            # Historical replay
├── sops/                    # Strategy SOPs, v<semver>.md — a logic change is a new file
│   ├── equity/
│   │   ├── swing/
│   │   └── intraday-momentum/
│   ├── options/
│   │   └── vol-edge/
│   └── _routing/            # Strategy eligibility by market regime
├── tools/                   # Python MCP server
│   ├── server.py            # MCP entry point; defines TOOL_GROUPS
│   ├── run_mcp.sh           # Launcher (use this, not `uv run server.py`)
│   ├── universe_backtest.json # Scan universe, shared by live and backtest
│   ├── broker/              # Adapter interface, Alpaca, simulation, retry
│   ├── data/                # Market and options data sources, price cache, validation
│   ├── analysis/            # Technical indicators, options math, regime
│   ├── scanner/             # Candidate filters, EOD tuning overrides
│   ├── risk/                # Portfolio risk checks
│   ├── audit/               # Compliance, drawdown, performance, reconciliation
│   ├── backtest/            # Backtest engine, harness, validator
│   ├── persistence/         # SQLite database
│   ├── notifications/       # Slack, Discord, Telegram
│   ├── scripts/             # Universe loading, parameter sweeps
│   └── tests/               # pytest suite
├── docs/                    # product/ (roadmap, build plan, feature specs), design/, _archive/
└── reports/                 # EOD journals, period reports, sop-changes/
```

## MCP Tools

`TOOL_GROUPS` in `tools/server.py` is the source of truth for which tools exist and which role sees them. A profile that sets `TRADING_TOOL_GROUPS` (comma-separated group names) sees `common` plus those groups. Unset means every tool; the Hermes installer leaves it unset.

| Group | Covers |
|-------|--------|
| `common` | Kill-switch check, decision log, notifications, account |
| `research` | Market data and price cache, news and sentiment, indicators, catalyst scoring, scanners, regime, options due diligence |
| `trader` | Position sizing and risk checks, orders (incl. multi-leg options), trade plans, transactions |
| `monitor` | Equity and options positions, prices, exit orders, EOD reconcile |
| `risk` | Daily limits, compliance, performance, regime, sizing; activates and clears the kill switch |
| `eod` | Decision and ledger queries, performance and compliance reports, daily funnel, tuning config, go-live scorecard |
| `backtest` | Simulated clock and bars, backtest entries, exits and results, plus the research and risk tools it replays |

A tool no agent should call (cron-only) goes in `UNGROUPED_BY_DESIGN` instead. `tools/tests/test_tool_groups.py` fails on any tool in neither.

## Testing

```bash
cd tools && uv run --extra dev pytest tests/ -v
```

## Supported Markets

- **Equities** (day trade + swing) — via Alpaca
- **Options** — via Alpaca
- **Crypto** — future (Coinbase/Binance adapter)
- **Prediction Markets** — future (Kalshi/Polymarket adapter)

## Platform Compatibility

| Platform | Install Method | Status |
|----------|---------------|--------|
| Hermes | `./install.sh hermes` | Supported. Dry run is tested (`tools/tests/test_install.py`); a real, owner-approved install with a green `verify.sh` is still pending (`docs/product/features/deployment/deployment-implementation-plan.md`). |
| Kermes | `./install.sh kermes` | Untested, incomplete. Links `skills/` and `sops/` only, registers no MCP server, and suggests `uv run server.py`, which breaks the MCP handshake. |
| MeshClaw | `./install.sh meshclaw` | Broken. Copies a root `SOUL.md` that does not exist (it is in `setup/deploy/`), so the script aborts. |
