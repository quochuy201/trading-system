# Agent Frameworks Research

## Summary

Evaluated frameworks for multi-agent orchestration relevant to our trading system.

---

## OpenClaw vs Hermes (Primary Candidates)

### OpenClaw
- **Type**: Multi-agent gateway / control plane
- **Language**: TypeScript
- **Architecture**: Control-plane-first — single long-running process that owns sessions, routing, tool execution, and state
- **Multi-agent**: Designed to orchestrate multiple agents across multiple channels with access controls
- **Skills**: Human-authored SKILL.md files loaded from workspace/personal/shared/plugin scopes — explicit, auditable
- **Memory**: File-backed, explicit — identity in SOUL.md, skills manually authored
- **Scheduling**: Gateway-layer scheduling for multi-agent coordination
- **Best for**: Multi-user, multi-channel systems; enterprise governance; predictable agent behavior

### Hermes (Nous Research)
- **Type**: Single self-improving agent runtime
- **Language**: Python
- **Architecture**: Agent-loop-first — synchronous "do, learn, improve" cycle
- **Multi-agent**: Can spawn isolated subagents for parallel tasks, but centered on one primary agent
- **Skills**: Auto-generates skills from successful workflows (procedural memory)
- **Memory**: Layered — persistent notes, searchable SQLite session history, procedural knowledge
- **Learning**: Self-improving — converts successful workflows into reusable skills automatically
- **Best for**: Single capable agent that improves over time; privacy-first; Python-native

### Key Difference
- **OpenClaw** = breadth (many agents, many channels, explicit control)
- **Hermes** = depth (one agent that gets smarter over time)

### Recommendation for Our System
**OpenClaw** aligns better with our hub-and-spoke architecture (central orchestrator + specialist agents). However, **Hermes's self-improving loop** is exactly what we want for SOP evolution. Consider:
- OpenClaw for the orchestration layer
- Hermes-style procedural learning for individual agent self-improvement

---

## CrewAI vs LangGraph vs AutoGen

### CrewAI
- **Architecture**: Role-based agent teams
- **Stars**: 45,900+ GitHub
- **Learning curve**: 2-3 days
- **Strengths**: Fastest time to production, YAML config, intuitive role-based model, A2A protocol support
- **Weaknesses**: Less control over execution flow, debugging harder, scaling limits at 10+ agents
- **Production**: Yes (v1.12, March 2026)
- **Best for**: Fast prototyping, team-based automation, <6-8 agents per workflow

### LangGraph
- **Architecture**: Graph-based state machines
- **Stars**: 44,600+ GitHub
- **Learning curve**: 2-3 weeks
- **Strengths**: Explicit control flow, built-in checkpointing, LangSmith observability, replay/time-travel debugging, human-in-the-loop native
- **Weaknesses**: Steep learning curve, higher maintenance overhead
- **Production**: Yes (v1.0 GA)
- **Best for**: Complex stateful workflows, compliance/auditability, long-running pipelines

### AutoGen (Microsoft)
- **Status**: ⚠️ MAINTENANCE MODE — no new features, bug fixes only
- **Recommendation**: Avoid for new projects. Microsoft shifted to Agent Framework.

### Recommendation for Our System
**LangGraph** is the strongest fit because:
1. Our trading workflow is inherently stateful (positions, portfolio state, risk limits)
2. We need deterministic execution paths (money at stake)
3. Checkpointing enables recovery from agent failures
4. Human-in-the-loop for risk override scenarios

However, since we're targeting OpenClaw/Hermes as the runtime, LangGraph concepts (state machines, checkpointing) should inform our architecture design rather than being a direct dependency.

---

## Framework Comparison Table

| Feature | OpenClaw | Hermes | CrewAI | LangGraph |
|---------|----------|--------|--------|-----------|
| Multi-agent | ✅ Native | ⚠️ Subagents | ✅ Native | ✅ Native |
| Self-improving | ❌ Manual | ✅ Auto | ❌ | ❌ |
| SOP support | ✅ SKILL.md | ✅ Skills | ⚠️ YAML roles | ❌ Custom |
| State management | File-backed | SQLite | Session-based | Checkpointing |
| Python | ❌ TypeScript | ✅ | ✅ | ✅ |
| Hub-and-spoke | ✅ | ⚠️ | ⚠️ | ✅ |
| Tool grounding | ✅ | ✅ | ✅ | ✅ |

---

## Sources
- https://userorbit.com/blog/hermes-agent-vs-openclaw
- https://www.marsdevs.com/blog/langgraph-vs-crewai-vs-autogen
- https://anthemcreation.com/artificial-intelligence/hermes-vs-openclaw-learning-orchestrating-ai-agents/
- https://pickaxe.co/post/hermes-agent-vs-openclaw
