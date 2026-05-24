# Trading System

Multi-agent autonomous trading system packaged as a [Hermes Profile Distribution](https://hermes-agent.nousresearch.com/docs/user-guide/profile-distributions). Installs on Hermes, Kermes, or MeshClaw with one command.

## Architecture

```
Orchestrator (SOUL.md)
  ├── Research Agent → scans market, analyzes candidates, ranks opportunities
  ├── Trader Agent   → plans trades, validates risk, executes orders
  └── Monitor Agent  → tracks positions, triggers exits
```

**4 agents**, hub-and-spoke communication, SOP-driven behavior.

## Quick Start

### Install

```bash
# Hermes (one command)
hermes profile install github.com/you/trading-system --alias

# Kermes
./install.sh kermes

# MeshClaw
./install.sh meshclaw
```

### Configure

```bash
cp .env.EXAMPLE .env
# Edit .env with your Alpaca API keys
```

### Run

```bash
# Start the MCP tools server
cd tools && uv run server.py

# Then chat with the orchestrator on your platform
```

## Structure

```
├── OPERATING_MANUAL.md      # Constitution: mode state machine, sizing math, circuit breakers — read first
├── SOUL.md                  # Orchestrator agent (workflow coordinator)
├── distribution.yaml        # Hermes profile manifest
├── config.yaml              # Model + risk + schedule settings
├── mcp.json                 # MCP tools server declaration
├── install.sh               # Cross-platform installer
├── skills/
│   ├── research/            # Research agent (scan + analyze)
│   │   ├── SKILL.md
│   │   └── reference/       # Market-specific due diligence
│   │       ├── equities-dd.md
│   │       ├── options-dd.md
│   │       ├── crypto-dd.md
│   │       └── prediction-markets-dd.md
│   ├── trader/SKILL.md      # Trader agent (plan + execute)
│   └── monitor/SKILL.md     # Monitor agent (track + exit)
├── sops/                    # Strategy SOPs (versioned)
│   └── day-trade-momentum/
│       └── v1.0.0.md
├── cron/                    # Scheduled jobs
│   ├── market-scan.json     # 9:45 AM ET — scan + trade
│   ├── position-monitor.json # Every 5 min — check positions
│   └── eod-review.json      # 4:15 PM ET — review + journal
└── tools/                   # Python MCP server
    ├── server.py            # MCP entry point (20+ tools)
    ├── broker/              # Broker adapters (Alpaca, simulation)
    ├── data/                # Price cache
    ├── analysis/            # Technical indicators
    ├── risk/                # Portfolio risk checks
    ├── persistence/         # SQLite database
    └── notifications/       # Slack alerts
```

## MCP Tools (20+)

| Category | Tools |
|----------|-------|
| Broker | `place_order`, `cancel_order`, `get_positions`, `get_account` |
| Data | `get_market_data`, `get_historical_data`, `get_latest_bars`, `load_price_cache`, `query_price_cache` |
| Analysis | `calc_technical_indicators` |
| Risk | `calc_position_size`, `check_portfolio_risk`, `check_daily_limits`, `get_portfolio_state` |
| Persistence | `save_trade_plan`, `save_transaction`, `get_trade_plan` |
| Notifications | `send_notification` |
| Safety | `check_kill_switch`, `activate_kill_switch`, `clear_kill_switch` |

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
| Hermes | `hermes profile install` | ✅ |
| Kermes | `./install.sh kermes` | ✅ |
| MeshClaw | `./install.sh meshclaw` | ✅ |
