# Project Summary: Decision Audit & Performance Logging

## Artifacts Created

| File | Purpose |
|------|---------|
| `.agents/planning/decision-audit/rough-idea.md` | Initial concept |
| `.agents/planning/decision-audit/idea-honing.md` | Requirements Q&A (8 questions) |
| `.agents/planning/decision-audit/research/quantforge-patterns.md` | Research on existing logging patterns |
| `.agents/planning/decision-audit/design/detailed-design.md` | Full technical design |
| `.agents/planning/decision-audit/implementation/plan.md` | 10-step implementation plan |

## What We're Building

A passive logging and evaluation system with:
- **Transaction ledger** — auto-logs every buy/sell/cancel with account state, P&L, platform
- **Decision log** — agents record reasoning + rule tags at every decision point
- **Compliance scorer** — detects 9 violation types (panic sell, early exit, etc.)
- **Performance calculator** — win rate, profit factor, expectancy, drawdown
- **Reports** — daily, weekly, on-demand; stored in DB + markdown
- **Query + export** — filter decisions/transactions, export as CSV/JSON

## Implementation: 10 Steps

1. DB schema + models
2. Transaction ledger auto-logging (modify place_order/cancel_order)
3. log_decision MCP tool
4. Query tools
5. Compliance scorer
6. Performance calculator
7. Report generator
8. Export + cron integration
9. Update agent skills
10. E2E validation

## Next Steps

Start implementation at Step 1. Each step builds incrementally and is independently testable.
