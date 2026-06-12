# Cron jobs for the kanban layout (Hermes v2 install)

Two jobs replace the old monolithic `full-workflow` cron. The legacy specs
(`market-scan.json` etc.) are for the deprecated single-profile install.

## 1. Morning orchestrator (agent job, weekdays 9:35 ET)

```bash
hermes -p trading-orchestrator cron create '35 9 * * 1-5' \
  --name trading-morning \
  "Run the daily cycle from SOUL.md: diagnostics, create today's task graph on the trading board (risk-regime -> research-scan -> trade-exec, monitor checkpoints, eod), dispatch, supervise until the morning chain completes."
```

## 2. Dispatcher ticker (no-agent script, every 5 min during market hours)

Keeps scheduled monitor/eod tasks and retries flowing without an LLM call.

```bash
hermes cron create '*/5 9-16 * * 1-5' \
  --name trading-kanban-tick \
  --script trading-kanban-tick.sh --no-agent
```

Note: Hermes cron schedules run in the machine's local timezone — adjust the
hour fields if the host is not in US/Eastern.
