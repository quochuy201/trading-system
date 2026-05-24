# Research: Existing Logging Patterns in QuantForge

## What QuantForge Already Does

### 1. Trade Journal (JSONL per day)
**Location:** `~/.meshclaw/agents/quantforge/memory/trade-journal/`
**Format:** One JSONL file per day, each line is a structured event.

**Event types:**
- `pretrade` — logged before entry, includes: symbol, direction, thesis, entry/stop/qty, confidence, mode
- `posttrade` — logged after stop adjustments or exits, includes: trade_id, outcome, pnl_r, notes
- `preclose_check` — end-of-day portfolio snapshot with per-position recommendations and reasoning

**Key insight:** The `pretrade` event captures the AI's **thesis** (reasoning) at decision time. The `posttrade` captures **why** it adjusted stops or exited. This is exactly the decision audit trail.

### 2. Sell Audit Log
**Location:** `~/.meshclaw/agents/quantforge/logs/sell_audit.jsonl`
**Format:** Every sell attempt is logged with a `guard_reason`:
- `"override"` — user forced the sell
- `"not-guarded (intraday)"` — intraday trades bypass the guard
- `"diligence verdict: SELL_ALLOWED"` — passed the due diligence check

**Key insight:** This is a **compliance log** — it records whether the AI was allowed to sell and why. This is the "did it follow instructions" audit.

### 3. Sell Guard Hook (Pre-execution gate)
**Location:** `~/.meshclaw/agents/quantforge/risk/sell_guard_hook.py`
**Mechanism:** A MeshClaw PreToolUse hook that intercepts sell commands and:
- Requires a fresh "diligence proof" file before allowing sells
- Blocks sells if the verdict is HOLD
- Logs every override for audit

**Key insight:** This is a **programmatic enforcement** of "don't panic sell" — the AI literally cannot sell without proving it ran the diligence check first. This is stronger than just logging violations after the fact.

### 4. Weekly Performance Reports
**Location:** `~/.meshclaw/agents/quantforge/memory/strategy-performance/`
**Content:** Comprehensive weekly reviews including:
- Win rate, profit factor, expectancy, avg winner/loser
- Constitution breach detection (e.g., "Rule 10 — Weekly 15% Hard Cap")
- Gate rejection analysis (which safety gates fired, which should have)
- Root cause analysis on best/worst trades
- Risk of ruin calculation
- Drawdown trajectory

**Key insight:** This is the **evaluation layer** — it scores both trading performance AND AI compliance. It explicitly calls out when the AI violated rules.

### 5. Execution Guardian (Pre-trade gate)
**Location:** `~/.meshclaw/agents/quantforge/risk/guardian.py`
**Checks:** PDT, daily loss limit, position count, cash reserve, concentration, trap detection, kill switches
**Output:** `{approved: bool, reasons: ["PASS X", "FAIL Y", ...]}`

**Key insight:** Every check produces a PASS/FAIL/SKIP/WARN verdict with explanation. This is auditable — you can see exactly which gates fired and why.

---

## Gaps in Current Trading System

Our trading system currently has:
- ✅ Trade plans (with rationale)
- ✅ Transactions (execution records)
- ✅ Journal entries (basic)
- ❌ **No decision log** — no record of what the AI considered and why at each decision point
- ❌ **No compliance scoring** — no way to check if AI followed SOP rules
- ❌ **No sell guard** — kill switch blocks ALL orders, but nothing prevents premature exits specifically
- ❌ **No performance metrics** — no win rate, profit factor, expectancy calculation
- ❌ **No violation detection** — no automated flagging of panic sells or early exits

---

## Design Patterns to Adopt

### From QuantForge:
1. **Structured decision events** (pretrade/posttrade/preclose) with reasoning captured at decision time
2. **Guard hooks** that programmatically prevent violations (not just log them)
3. **Compliance verdicts** (PASS/FAIL/WARN) at every gate
4. **Weekly automated reviews** that score performance AND compliance
5. **Override logging** — when rules are bypassed, log who/why

### Additional for our system:
6. **SOP compliance checker** — compare each decision against the active SOP rules
7. **Violation taxonomy** — categorize violations (panic_sell, early_exit, ignored_signal, oversized, etc.)
8. **Performance metrics engine** — calculate win rate, Sharpe, profit factor, expectancy from transaction history
9. **Decision replay** — ability to replay a decision with the same inputs to verify reproducibility
