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

## 3. Data refresh (pre-market, before the scan)

```bash
hermes cron create '15 6 * * 1-5' --name trading-data-refresh \
  --script trading-data-refresh.sh --no-agent
```

Keeps the DB's daily bars current and consistent. If it fails, the morning
scan still runs but reports `data_stale` (loud, not silent).

## 4. IV capture (daily, after close — options IVR accrual)

```bash
hermes cron create '5 13 * * 1-5' --name trading-iv-capture \
  --script trading-iv-capture.sh --no-agent
```
Captures ATM IV30 per name into `iv_history` so per-name IV-rank (and credit-spread
routing) become usable over time. IV history cannot be backfilled — the sooner this
runs daily, the sooner IVR is trustworthy. (`5 13` PT = just after the 13:00 PT / 16:00 ET close.)
