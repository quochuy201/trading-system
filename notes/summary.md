# Project Summary: Multi-Agent Trading System

## Overview

Transformed a rough idea for a multi-agent autonomous trading system into a detailed design and 16-step implementation plan. The system uses specialized AI agents coordinated through a hub-and-spoke architecture to execute the full trading lifecycle autonomously — scanning, analysis, execution, monitoring, and review — driven by versioned markdown SOPs that self-improve over time.

## Artifacts Created

| File | Description |
|------|-------------|
| `rough-idea.md` | Original concept for the multi-agent trading system |
| `idea-honing.md` | 15+ Q&A rounds covering markets, brokers, workflow, coordination, risk, tech stack, data sources, SOPs, MVP criteria, error handling |
| `research/agent-frameworks.md` | Evaluation of OpenClaw, Hermes, CrewAI, LangGraph, AutoGen |
| `research/multi-agent-trading-architectures.md` | Academic papers (TradingAgents, ATLAS) and industry analysis |
| `research/alpaca-api.md` | Alpaca paper trading, WebSocket streaming, options support |
| `research/backtesting-frameworks.md` | VectorBT, NautilusTrader, PyBroker comparison |
| `research/sop-driven-design.md` | SOP-Agent framework, self-improving systems, decision graphs |
| `design/detailed-design.md` | Full design document (9 sections, ~950 lines) |
| `implementation/plan.md` | 16-step implementation plan with checklist (504 lines) |
| `summary.md` | This document |

## Key Design Decisions

- **Hub-and-spoke** with central orchestrator (not event-driven or peer-to-peer) — deterministic control matters when money is at stake
- **SOP-driven agents** with filtered tool sets — agents follow markdown SOPs and can only use tools relevant to their role
- **Tool-grounded** — LLMs synthesize and decide; tools handle data, calculations, and execution
- **TradePlan → TradeTransaction model** — plans represent intent, transactions represent execution, linked by `plan_id`
- **Two-tier Monitor** — tool-only checks every 30s (no LLM cost), LLM escalation only when exit conditions approach
- **Statistical backtesting** — run N times to account for LLM non-determinism, report metric distributions
- **Framework-agnostic** — adapter layer supports MeshClaw (dev) → OpenClaw/Hermes (prod) migration

## Implementation Approach

16 incremental steps building from foundation to full system:

- **Steps 1-4**: Foundation — models, database, broker adapter, data and analysis tools
- **Steps 5-8**: Agents — Scanner, Analyst, Strategist, Executor (core trading pipeline)
- **Steps 9-10**: Orchestration — Monitor loop, full workflow with checkpointing and crash recovery
- **Steps 11-12**: Observability — Reviewer (journaling/metrics), Slack notifications
- **Steps 13-14**: Safety — Backtesting harness, kill switch, error handling hardening
- **Steps 15-16**: Polish — Dashboard, end-to-end paper trading validation

Core end-to-end trading (scan → execute → monitor → exit) is demoable by Step 10.

## MVP Success Criteria

1. Single orchestrator running one day-trading strategy on Alpaca paper trading
2. SOP-driven behavior with versioned markdown SOPs
3. Trade journaling with rationale and outcome for every trade
4. Slack notifications for trades, summaries, and alerts
5. Profitable on paper trading
6. Reliable backtesting with same code paths as live trading
7. Extensible architecture for new strategies and markets

## Next Steps

1. Review the detailed design at `design/detailed-design.md`
2. Review the implementation plan and checklist at `implementation/plan.md`
3. Begin implementation following Step 1 (project scaffolding, data models, database)

## Areas for Future Refinement

- **Dashboard tech choice**: FastAPI+HTMX vs Streamlit — decide during Step 15 based on complexity needs
- **SOP self-improvement minimum sample size**: Define the statistical threshold for SOP promotion (cold-start problem with 1-5 trades/day)
- **LLM cost estimation**: Profile cost per workflow run once agents are implemented
- **Broker API rate limits**: Document Alpaca rate limits and add throttling if needed
- **Multi-strategy concurrency**: Current design runs one workflow at a time — future work to support parallel strategies
