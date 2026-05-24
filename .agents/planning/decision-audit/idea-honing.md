# Idea Honing: Decision Audit & Performance Logging

Requirements clarification through iterative Q&A.

---

## Q1: Should the system have a hard gate (like quantforge's sell guard that blocks premature sells) or just passive logging that flags violations after the fact?

**A1:** Option B — passive logging only. No blocking/gating. The gatekeeper will be a separate feature later. This feature is purely for logging, enhancement, and audit purposes.

---

## Q2: What decision points should be logged?

**A2:** The core problem is understanding **why** the AI made a specific transaction. Key concerns:

1. **Decision transparency** — why did the AI buy or sell at that moment? What rules/signals triggered it?
2. **Rule conflict detection** — do my rules create potholes or contradictions that confuse the agent? (e.g., one rule says hold, another says sell)
3. **Rule impact analysis** — does a new rule conflict with existing rules? Did adding a rule make things worse?
4. **Strategy versioning & comparison** — is the current design/rules/strategy profitable? How does it compare to previous versions of the SOP?

So: log ALL decision points (entry, exit, hold, skip, adjust) with full reasoning, the specific rules that fired, and tag everything with the SOP version so performance can be compared across versions.

---

## Q3: How do you want to consume this data? What's the output format for reviewing AI performance?

For example:
- A CLI command that prints a summary report (like quantforge's weekly review)
- A JSON/CSV export you can analyze in a spreadsheet
- An MCP tool the orchestrator calls to generate reports
- A dashboard (web UI)
- Slack summaries
- All decisions queryable via an MCP tool (e.g., "show me all exits for NVDA this week with reasoning")

What would be most useful for your workflow?

**A3:** Multiple output formats:
1. **Daily and weekly summaries** — automated reports
2. **Queryable log** — MCP tools to search/filter decisions (e.g., "show all exits this week", "show all rule conflicts")
3. **CSV/JSON export** — for external analysis in spreadsheets or notebooks

---

## Q4: What metrics matter most for evaluating trading performance vs AI performance?

I'm thinking two separate scorecards:

**Trading performance** (did the strategy make money?):
- Win rate, profit factor, expectancy, Sharpe ratio
- Avg winner vs avg loser
- Max drawdown, risk of ruin
- Performance by symbol, by strategy, by time period

**AI compliance** (did the AI follow instructions?):
- % of decisions that followed SOP rules exactly
- Number of violations by type (panic sell, early exit, ignored signal, etc.)
- Rule conflict incidents (two rules contradicted each other)
- Comparison across SOP versions (did v1.1 perform better than v1.0?)

Are these the right two dimensions, or is there something else you'd score on?

**A4:** Yes, two scorecards are correct:
1. Trading performance (profitability metrics)
2. AI compliance (rule-following metrics + version comparison)

---

## Q5: How should the decision log capture "which rules fired"?

The AI follows SOPs (like `day-trade-momentum/v1.0.0.md`) which contain specific rules. When the AI makes a decision, should it:

**Option A — Free-text reasoning:** The AI writes a natural language explanation (like quantforge's `thesis` field). You read it manually to understand why.

**Option B — Structured rule tags:** Each SOP rule gets an ID (e.g., `RSI_OVERBOUGHT`, `VOLUME_CONFIRM`, `STOP_HIT`). The AI must tag which rules triggered its decision. This enables automated compliance checking — the system can verify "rule X says hold, but the AI sold."

**Option C — Both:** Free-text reasoning for human review + structured rule tags for automated scoring.

Which approach?

**A5:** Option C — both structured rule tags AND free-text reasoning. Condition: it must not bloat context during trading sessions or degrade AI trading performance. Mitigations:
- Keep reasoning brief (1-2 sentences)
- Logging is a fire-and-forget tool call (no response needed in context)
- Rule IDs versioned alongside SOP versions

---

## Q6: When should performance reports be generated?

Options:
- **Daily summary** — auto-generated at EOD (4:15 PM ET) as part of the existing eod-review cron
- **Weekly summary** — auto-generated on weekends (like quantforge's weekly review)
- **On-demand** — via MCP tool call (e.g., `generate_performance_report("2026-05-01", "2026-05-21")`)
- **All of the above**

And should the reports be stored in the database, written to a markdown file, or both?

**A6:** All of the above — daily, weekly, and on-demand reports. Stored both in the database AND as markdown files.

---

## Q7: How should SOP version comparison work?

When you update the SOP (e.g., v1.0.0 → v1.1.0), you want to compare performance between versions. Should the system:

**A)** Automatically detect when the SOP version changes and start a new "evaluation period" — then compare metrics between periods?

**B)** Require you to manually tag a date range as "v1.0.0 era" vs "v1.1.0 era"?

**C)** Just tag every decision with the active SOP version, and let the report tool filter/group by version automatically (no explicit periods needed)?

Option C is simplest — every log entry already has `sop_version`, so `generate_performance_report(sop_version="v1.0.0")` vs `generate_performance_report(sop_version="v1.1.0")` gives you the comparison. No extra setup when you change versions.

**A7:** Option C — tag every decision with the active SOP version. Reports filter/group by version automatically. No explicit period management needed.

---

## Q8: What violation types should the compliance scorer detect?

Here's my proposed taxonomy based on your concerns:

| Violation | Description |
|-----------|-------------|
| `PANIC_SELL` | Exited before stop-loss was actually hit |
| `EARLY_EXIT` | Exited before take-profit or time-stop, without a valid rule trigger |
| `IGNORED_ENTRY_SIGNAL` | SOP criteria were met but AI didn't enter |
| `IGNORED_EXIT_SIGNAL` | Exit criteria were met but AI didn't exit |
| `OVERSIZED` | Position larger than risk rules allow |
| `UNDERSIZED` | Position significantly smaller than calculated (missed opportunity) |
| `RULE_CONFLICT` | AI cited two contradicting rules in the same decision |
| `UNTAGGED_DECISION` | AI took action without logging reasoning/rules |
| `SOP_DEVIATION` | Action doesn't match any rule in the active SOP |

Are these the right violations to track? Anything to add or remove?

**A8:** This taxonomy is sufficient for the initial implementation. Will be updated as new violation patterns are discovered in practice.

---

*Requirements clarification complete. Proceeding to design.*
