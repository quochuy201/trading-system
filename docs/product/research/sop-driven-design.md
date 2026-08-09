# SOP-Driven Agent Design & Self-Improving Systems

## SOP-Agent Framework (HPC-AI Tech + Grab, Jan 2025)

**Paper**: "Empower General Purpose AI Agent with Domain-Specific SOPs"
**Key contribution**: First framework for building domain-specific agents using natural language SOPs.

### Architecture
- SOPs represented as **decision graphs** (directed graphs)
- Each node = candidate action
- Each edge = IF condition or ALWAYS condition
- Traversed via **DFS-based selective traversal**

### How It Works
1. **SOP-Navigator** formats current SOP slice into structural prompts
2. Provides **filtered set of valid function calls** (limits action space)
3. Agent selects action → traverses to next node
4. Supports: cascaded execution, conditional branching, looping

### Key Results
- Outperforms AutoGPT by 66.2% on ALFWorld (zero-shot)
- 99.8% accuracy on grounded customer service benchmark
- Competitive with domain-specific agents (MetaGPT, AgentCoder)

### SOP Engineering
- Iterative refinement of SOPs improves robustness dramatically
- Key principles:
  - Logical completeness of every chain
  - Avoid compound logic ("or"/"and") — use simple IF-THEN
  - Match function call descriptions with action instructions
  - Crude SOP: 84% accuracy → Refined SOP: 98% accuracy

### Relevance to Our System
- **Validates our SOP-driven approach**: Natural language SOPs effectively guide agent behavior
- **Decision graph representation**: Our trading SOPs can be modeled as decision graphs
- **Filtered tool sets**: Limiting available tools per SOP step improves accuracy
- **SOP engineering**: We should iteratively refine our trading SOPs based on performance

---

## Self-Improving Agent Systems

### ATLAS Adaptive-OPRO (ACL 2026)
- Dynamically adapts prompts using real-time trading performance feedback
- Outperforms fixed prompts consistently
- **Key finding**: Reflection alone doesn't work; you need performance-based optimization

### Self-Supervised Prompt Optimization (2025)
- Meta-learning framework that optimizes system prompts over various tasks
- Iteratively updates prompts to ensure synergy between system and user prompts

### Evolving Contexts for Self-Improving LLMs (2025)
- Modifies inputs (instructions, strategies, evidence) rather than model weights
- "Context adaptation" as alternative to fine-tuning
- Applicable to our SOP evolution: modify the SOP text, not the model

### Open-Ended Evolution of Self-Improving Agents (2025)
- Scientific method as model: each innovation builds on previous artifacts
- Cumulative, open-ended improvement
- Aligns with our vision: agents update SOPs based on what works

### Self-Improving AI Agent Pipeline (Substack, 2026)
- Pipeline: simulate → evaluate → rewrite prompts
- Uses: simulate-sdk, ai-evaluation, agent-opt
- Agent catches its own failures and rewrites its own prompts

---

## Design Patterns for Our System

### 1. SOP as Decision Graph
```
Market Scan → [candidates found?]
  YES → Analyze Candidate → [meets criteria?]
    YES → Plan Trade → [risk check passes?]
      YES → Execute
      NO → Skip
    NO → Next Candidate
  NO → Wait
```

### 2. Filtered Tool Sets Per Step
- Scanning step: only data-gathering tools available
- Analysis step: only analysis/calculation tools
- Execution step: only broker API tools
- Prevents agents from "skipping ahead" or using wrong tools

### 3. Self-Improvement Loop
```
1. Agent follows SOP → makes trades
2. Record outcomes (profit/loss, win rate, etc.)
3. Periodically evaluate SOP performance
4. Generate SOP modifications (parameter tuning, rule changes)
5. Version the new SOP
6. A/B test: old SOP vs new SOP (paper trading)
7. If new SOP outperforms → promote to active
8. If not → rollback
```

### 4. SOP Versioning Strategy
- Git-style versioning for SOPs
- Each version tagged with performance metrics
- Rollback capability
- Changelog: what changed and why

### 5. Guard Against Hallucination
- Tool-grounding: agents MUST use tools for factual tasks
- Filtered action space: only valid actions available at each step
- Structured outputs: agents produce typed reports, not free-form text

---

## Sources
- SOP-Agent paper: https://arxiv.org/html/2501.09316v1
- ATLAS: https://arxiv.org/abs/2510.15949
- Self-Improving Pipeline: https://futureagi.substack.com/p/how-to-build-a-self-improving-ai
- Evolving Contexts: https://arxiv.org/html/2510.04618v1
