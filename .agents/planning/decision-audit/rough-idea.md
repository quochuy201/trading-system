# Rough Idea: Decision Audit & Performance Logging

A logging and evaluation component for the trading system that captures:

1. **Decision Audit Log** — records every AI decision with reasoning, so I can verify the AI follows instructions, doesn't panic sell, and doesn't exit too early.

2. **Transaction Log** — detailed execution records for evaluating trading performance (win rate, P&L, strategy effectiveness).

Combined, these let me evaluate both **AI performance** (did it follow the SOP?) and **trading performance** (did the strategy make money?).

Key concerns:
- AI should not panic sell before stop-loss is hit
- AI should not exit positions too early (before target or time-stop)
- AI should follow the SOP rules exactly
- I need to be able to review and score AI compliance
- I need trading metrics (win rate, avg P&L, Sharpe, etc.)
