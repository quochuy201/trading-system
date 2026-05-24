# Multi-Agent Trading System Architectures (Papers, Books, Social Media)

## Academic Papers

### TradingAgents (UCLA, Dec 2024)
**Paper**: "TradingAgents: Multi-Agents LLM Financial Trading Framework"
**GitHub**: https://github.com/TauricResearch/TradingAgents
**Key insight**: Simulates a real trading firm's organizational structure.

**Architecture**:
- **Analyst Team** (4 parallel agents): Fundamental, Sentiment, News, Technical analysts
- **Researcher Team**: Bull vs Bear debaters (multi-round natural language debate)
- **Trader Agent**: Synthesizes all inputs, makes buy/sell/hold decisions
- **Risk Management Team**: 3 perspectives (aggressive, neutral, conservative) deliberate
- **Fund Manager**: Final approval and execution

**Communication Protocol**:
- Structured documents (not just chat) to avoid "telephone effect"
- Agents produce concise reports, not lengthy conversations
- Natural language debate ONLY for researcher and risk management deliberation
- Global state shared across agents

**Results**: 23-26% cumulative returns in 3 months, Sharpe ratios >5.0, max drawdown <2%

**Relevance to our system**: Very close to our design. Key differences:
- They use multiple backbone LLMs (fast models for data retrieval, deep models for reasoning)
- Structured communication prevents context corruption
- Debate mechanism improves decision quality

---

### ATLAS (ACL 2026)
**Paper**: "Adaptive Trading with LLM AgentS Through Dynamic Prompt Optimization and Multi-Agent Coordination"

**Key innovation**: **Adaptive-OPRO** — dynamically adapts prompts using real-time stochastic feedback
- Prompts evolve based on trading performance (self-improving!)
- Outperforms fixed prompts consistently
- Reflection-based feedback alone does NOT provide systematic gains

**Architecture**:
- Central trading agent with order-aware action space
- Outputs correspond to executable market orders (not abstract signals)
- Multi-agent coordination for information synthesis

**Relevance**: Validates our SOP self-improvement concept. Key takeaway: prompt optimization with performance feedback works; simple reflection does not.

---

### Price-Driven Multi-Agent LLMs for HFT (2025)
**Paper**: arxiv.org/html/2509.09995v3

Notes that multi-agent frameworks like TradingAgent and FINMEM augment LLMs for long-horizon investment by leveraging fundamental and sentiment-based inputs.

---

### End-to-End Tool-Orchestrated Agentic RL Framework (2025)
**Key critique of existing multi-agent trading frameworks**:
- Suffer from inefficiency
- Produce inconsistent signals
- Lack end-to-end optimization to learn coherent strategy from market feedback

**Solution**: Reinforcement learning to optimize the entire agent pipeline end-to-end.

**Relevance**: Validates our concern about tool-grounding. Agents must use tools for factual tasks, not rely on LLM reasoning alone.

---

### MountainLion (2025)
"A Multi-Modal LLM-Based Agent System for Interpretable and Adaptive Financial Trading"
- Multi-modal (text + charts + data)
- Coordinates specialized LLM-based agents
- Emphasis on interpretability

---

## Social Media & News

### Bloomberg/CNA: "I built an AI trading platform in six days" (Apr 2026)
**Author**: Darri Eythorsson (hydrologist, not a trader)
**Key points**:
- Built production-grade system: 50 modules, 3 exchanges, news/Reddit/Twitter ingestion
- Uses LLM for market analysis, probability estimation, Kelly criterion sizing
- Trades prediction markets (Polymarket, Kalshi)
- 14 of Polymarket's 20 most profitable accounts are bots
- 30%+ of Polymarket wallets are AI agents
- All built on same few foundation models → correlation risk

**Warning**: "Model monoculture" — thousands of agents using same LLMs converge on same decisions simultaneously. Systemic risk.

**Relevance**: Validates feasibility of our approach. Also highlights importance of differentiated strategies.

---

### Bloomberg: "AI Agents Are Becoming Day Traders, But Gains Are Elusive" (May 2026)
- Jake Nesler's AI bot "argued with itself" over whether to chase NVIDIA momentum — decided against it, avoiding $10K loss
- Only 10-30% of bot users achieve consistent profitability
- Key challenge: agents trained on same data/models tend to crowd same trades

---

### Reddit r/algotrading Themes (2025-2026)
- Growing interest in LLM-powered trading agents
- Skepticism about LLM reasoning for actual alpha generation
- Consensus: LLMs better for information synthesis than direct prediction
- Popular approach: LLM for analysis + traditional quant for execution
- Alpaca most popular broker API for retail algo trading

### Reddit r/ai_trading Themes
- Focus on crypto bots with AI decision-making
- Multi-agent architectures gaining traction
- Common failure: overfitting to backtest data
- Key advice: paper trade extensively before going live

---

## Key Architectural Patterns Across All Sources

### 1. Specialist Agent Roles (Universal Pattern)
Every successful system uses specialized agents:
- Data gatherers (per data type)
- Analysts (fundamental, technical, sentiment)
- Strategists/Researchers (often with opposing views)
- Risk managers
- Executors

### 2. Structured Communication > Chat
TradingAgents paper shows structured reports outperform free-form chat:
- Prevents "telephone effect" (information loss over long conversations)
- Each agent produces a typed report
- Global state accessible to all agents

### 3. Debate Mechanism for Better Decisions
Bull vs Bear debate (TradingAgents) and multi-perspective risk assessment improve decision quality by forcing consideration of opposing views.

### 4. Tool-Grounding is Essential
All successful systems ground agents in tools for:
- Data retrieval (APIs, databases)
- Calculations (technical indicators, risk metrics)
- Execution (broker APIs)
- LLM reasoning alone is insufficient for factual/computational tasks

### 5. Self-Improvement via Performance Feedback
ATLAS paper shows: dynamic prompt optimization based on trading results works. Simple reflection does not. Our SOP versioning + performance-based updates aligns with this finding.

---

## Sources
- TradingAgents: https://arxiv.org/html/2412.20138v3
- ATLAS: https://arxiv.org/abs/2510.15949
- CNA Commentary: https://www.channelnewsasia.com/commentary/agentic-ai-trading-finance-claude-openai-6088811
- Bloomberg/Yahoo: AI Agents Are Becoming Day Traders (May 2026)
- GitHub TradingAgents: https://github.com/TauricResearch/TradingAgents
