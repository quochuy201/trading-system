# Trading Morning Cycle Examples (updated 2026-06-19)

## Exact Create Commands (from 2026-06-19 autonomous cron run, IDs t_99687dcd etc.)

```bash
# After date, profile list, unblock stale, mcp list verification
hermes kanban --board trading create "2026-06-19 1-risk-regime (preflight per OPERATING_MANUAL §§1-2; mode, eligible strategies; paper mode)" --assignee trading-risk --skill trading-risk-manager --body "Run preflight checklist per OPERATING_MANUAL.md and trading-risk-manager skill. ..." --json

# Then research with --parent t_99687dcd , --skill trading-research , ID=t_58c10abd
hermes kanban --board trading create "2026-06-19 2-research-scan ..." --assignee trading-research --skill trading-research --body "..." --parent t_99687dcd --json

# Trader with 2 parents, ID=t_2baf2a44 , skill=trading-trader
hermes kanban --board trading create "2026-06-19 3-trade-exec ..." --assignee trading-trader --skill trading-trader --body "..." --parent t_99687dcd --parent t_58c10abd --json

# Monitor ID=t_da021ead , skill=trading-monitor
hermes kanban --board trading create "2026-06-19 4-monitor-checkpoints (07:30/09:00/11:00/12:45 PT...)" --assignee trading-monitor --skill trading-monitor --body "..." --parent t_2baf2a44 --json

# EOD ID=t_c7d9707b , skill=trading-eod-review
hermes kanban --board trading create "2026-06-19 5-eod-review (13:15 PT...)" --assignee trading-eod --skill trading-eod-review --body "..." --parent t_da021ead --json
```

Then:
```bash
hermes kanban --board trading dispatch   # spawns risk t_99687dcd (pid 68328)
hermes kanban --board trading show t_99687dcd  # verify running, heartbeat, children, graph
```

## Patch Template for PROJECT_STATUS.md (used this run)

Use after sufficient read_file (full top section), then:

patch tool with unique old_string (Last updated + first header), new_string = updated last-updated + full new ## ⏩ Morning Cycle section (include exact IDs, pids, states, commands, "MCP gating fixed via domain skills", "System healthy for paper trading day") + old header.

Avoids partial view by reading 40+ lines first.

## Final Cron Summary Format (ultra-concise, artifacts-first, no narration)

t_99687dcd running (pid=68328, heartbeat), new graph t_58c10abd/t_2baf2a44/t_da021ead/t_c7d9707b created+linked, stale unblocked, PROJECT_STATUS.md patched, MCP gating resolved with domain skills, reference materialized. System healthy for paper trading day.

## Pitfalls Addressed This Run
- Used domain skills (trading-risk-manager etc.) instead of kanban-worker → resolved "missing MCP trading tools" (now 'all' + skill loads proper context).
- Sequential create with --parent + --json + show verification before summary.
- Prepended new cycle section + bumped tests count + Last updated.
- Created missing references/trading-morning-cycle-examples.md via write_file.
- Unblock before new graph.
- Cron list showed active jobs (no recreation needed this time).

Update skill version to 3.6.0 after this. Use full workdir on crons. Always start with `date`.

See also trading-profile-audit.md for full maintenance checklist.
