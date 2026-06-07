# Agent Evolution Standard

**Status:** v0.1 — governance artifact, human-ratified.
**Origin:** Adapted from Gu, *"From Model Scaling to System Scaling: Scaling the Harness in
Agentic AI"* (arXiv:2605.26112), §4.2 (trustworthy memory), §4.3 (skill routing + verification),
§5.1 (process metrics), §5.3 (safe-evolution standard). We take the framework; we do not adopt
its product claims.

> **Read this before wiring any "learning," "memory," or "self-improvement" loop into the
> trading agent.** It defines what the agent is allowed to change on its own, what requires a
> human, and how we keep a learning agent from becoming — in the paper's words — "an opaque
> accumulation of prompts, notes, and heuristics."

---

## Why this exists

The foundation model (Sonnet/Opus) does **not** learn at deployment. Its weights are frozen.
Every claim that "the agent learns from experience" therefore means one thing: **the agent writes
observations to an external store and reads them back later.** All learning is externalized into
the harness — the decision log, the ledger, memory files, SOPs, and the retrieval layer.

This has two consequences we build around:

1. **Portability is free.** Because the learning lives in files and the database, it survives a
   machine move, a model upgrade, or a switch to a different agent runtime (Hermes, etc.). The
   SOP, the logs, and this standard travel with the repo.
2. **The danger is confident wrongness, not forgetting.** The paper names two symmetric failure
   modes that are existential for a system trading real money:
   - **Stale-but-confident memory** (§4.2): a note that was true once ("AAPL IVR is high → sell
     premium") is acted on after the world changed. Retrieval still ranks it highly; acting on it
     loses money.
   - **Confident-but-unchecked routing** (§4.3): a sub-decision returns a plausible answer that no
     downstream step verifies (e.g. a fabricated IVR value, a sizing figure that doesn't add up, a
     gate labeled "pass" without the underlying check).

   Both let the agent act on a claim whose truth was never re-established. This is exactly the
   failure that produced made-up crash thresholds and a mislabeled liquidity gate in our own
   sessions. Guarding against it is the entire point of this document.

---

## The four questions (the standard)

The paper proposes that any evolving agent answer four questions explicitly (§5.3). Here are
**our** answers.

### 1. What persists?

Persistent state is kept in **four separate stores**. They are never merged, so an update to one
can never silently rewrite another. This separation is the core safety property.

| Store | Where | Mutable by agent? |
|---|---|---|
| **Guardrails** | `OPERATING_MANUAL.md`, kill switch, risk gates, circuit breakers | **Never.** Human-only. |
| **SOP thresholds** | `sops/*/v*.md` (IVR zones, deltas, DTE, sizing %, crash thresholds) | **Never directly.** Propose via `reports/sop-changes/`; human ratifies a new version. |
| **Skills** | `skills/*/SKILL.md`, reference docs | **Never directly.** Same proposal path. |
| **Memory / experience** | decision log, ledger, retrieval library, `memory/` files | **Yes** — append-only observations. Never rewrites the three above. |

**Rule:** a learned pattern can only ever enter the *memory* store. To change behavior (a
threshold, a skill, a guardrail) it must graduate through a human-ratified proposal. The agent
proposes; the human disposes.

### 2. What updates online vs. requires review?

Three tiers of trust, by how much damage a wrong update could do:

| Tier | Mechanism | Gate | Example |
|---|---|---|---|
| **Tier 1 — Retrieval** | Surface similar past situations + their outcomes as *context* at decision time | **Automatic.** Safe because it shows real past rows, invents nothing, changes no rule. | "Last 4 entries at IVR>95 → 3 losses. Here they are." |
| **Tier 2 — Statistical flag** | Periodic job aggregates the log; flags patterns that clear a sample-size floor AND a significance bar | **Automatic, but gated on N and significance.** Below the floor → stays silent. | "Across N≥30 trades, entries when SPY 3-day return < −X clustered losses." |
| **Tier 3 — Proposal** | Agent writes a threshold/skill change to `reports/sop-changes/` with evidence attached | **Human ratification required.** Never auto-applied. | "Propose crash filter: block credit entries when SPY 1-day < −Y%. Evidence: [trades]." |

**Forbidden:** the agent silently changing its own risk thresholds mid-session. That converts a
learning system into a runaway one.

### 3. What is measured?

Per §5.1, we report **outcome metrics jointly with process metrics** — never outcome alone, because
P&L hides whether the agent was disciplined or merely lucky.

| Outcome metrics | Process metrics |
|---|---|
| Realized P&L, win rate, R-multiple, drawdown | Did it call the required gates before deciding? (`WorkflowValidator`) |
| | Did sizing math reconcile to the inputs? |
| | Did it route IVR→structure per the SOP table? |
| | Regression: did a past, fixed failure recur? |
| | Drift: are decisions in identical conditions diverging over time? |

We also adopt the paper's **`pass^k` reliability check**: replay the same historical day *k* times
through the agent. At temperature 0 a disciplined agent should reach the *same* decision. Variance
across *k* runs is a reliability gap that single-run P&L conceals.

**Learning is judged by regression + drift + failure-recurrence, NOT by a single rolling win
rate.** A win rate that drifts up while old failures quietly recur is not improvement.

### 4. What is auditable?

Every state change leaves an inspectable trace:

| Change | Trace |
|---|---|
| Memory/observation write | `decisions` table row (decision_id, timestamp, market_context) |
| Trade | transaction ledger entry |
| Proposed SOP change | file in `reports/sop-changes/` with evidence + author + date |
| Ratified SOP change | new versioned file `sops/*/vX.Y.Z.md` + commit |

Behavioral evaluation alone is insufficient (§5.3, citing sleeper-agents): we rely on the **written
trace**, not on the agent's self-report, to know what changed and why.

---

## Trustworthy memory: trust is a runtime decision

The paper's central memory move (§4.2): **trust is not a property of a stored item; it is computed
at retrieval time.** A memory does not become true by being retrieved.

We implement this with three first-class fields on every retrievable memory/insight entry:

| Field | Meaning | Use at retrieval |
|---|---|---|
| `confidence` | How strong was the evidence when written (sample size, significance) | Down-weight low-confidence entries |
| `recency` | When was this written | Older = more suspect for a regime-dependent claim |
| `last_verified` | When was this last checked against live data | Stale = treat as hypothesis, not fact |

**The hard rule — retrieved memory is a hypothesis, never a substitute for a live check.**
The agent already fetches IVR/regime/greeks just-in-time via MCP tools. A retrieved insight
("this looked like a crash setup last time") may *prompt* a check; it may never *replace* the live
`calc_iv_rank` / regime fetch. This is the same hybrid pattern the paper credits Claude Code with:
persistent priors up front (`CLAUDE.md`, SOPs) + just-in-time re-verification against the live
environment (`grep`/`glob` there; broker tools here).

Durable memory without re-verification accumulates undetected drift. Live-only fetching without
distilled priors throws away every past lesson. We keep both.

---

## The hard limit this standard does NOT remove

Honesty requirement (this section must not be deleted in future edits):

**Rare tail events — crashes, regime breaks — cannot be self-learned from this account's own
logs.** A classifier needs hundreds of examples; a single account will log 0–2 genuine crashes per
year. The retrieval and statistical tiers above make *common-pattern* learning safe and real
(liquidity, IVR-band outcomes, fill quality, time-of-day effects). They do **nothing** to
manufacture crash data.

Therefore crash/tail knowledge must come from **outside** the agent's experience:
- market-wide historical data (decades of SPY/VIX — e.g. the OptionsDX history), or
- established structural indicators already in the SOP (VIX bands, regime filters).

Any "crash threshold" entering an SOP must be tagged with its provenance — `BACKTEST-CALIBRATED`,
`MARKET-HISTORY-DERIVED`, or `PLACEHOLDER-FAIL-SAFE` — and never presented as self-learned.

---

## Mapping to the harness components (reference)

For traceability against the paper's framework `P_H = Φ(R, M, C, S, O, G)`:

| Component | Our realization | This standard governs |
|---|---|---|
| R — reasoning | Sonnet / Opus (frozen) | — (model scaling, not ours) |
| M — memory | decision log, ledger, retrieval lib, `memory/` | §"trust is runtime", Q1, Q4 |
| C — context | SOPs/skills up front + JIT tool fetches | §"hypothesis not substitute" |
| S — skill routing | scheduler → strategy SOP → DD ref | Q2 (proposal-gated changes) |
| O — orchestration | `SOUL.md` workflow loop | — |
| G — governance | kill switch, gates, breakers, `compliance.py`, sop-changes | Q1, Q3, Q4 (our strongest axis) |

---

## Deployment on Hermes (cross-machine note)

This package installs onto the **Nous Research "Hermes Agent"** harness (`./install.sh hermes`,
`distribution.yaml`). Verified against internal sources (2026-05/06), Hermes has a **built-in
self-improvement loop** that interacts directly with this standard — read this before deploying.

**What Hermes does on its own:**
- **Automatic skill generation:** when Hermes successfully completes a hard task, it writes a new
  `SKILL.md` capturing the procedure. This is real, by-default behavior — its headline feature.
- **Curator (background):** archives generated skills, **deduplicates, removes hallucinated/redundant
  skills, and promotes only validated skills** to the active set. This is Hermes's own Tier-2/Tier-3
  gate — architecturally the same shape as this standard's verification requirement.
- **Memory layer:** SQLite-WAL session store, vector/episodic search, a "memory nudge counter" that
  proactively prompts the agent to record observations every N turns.

**Why this matters for a trading agent — the required adaptation:**

1. **Hermes's auto-skill-promotion writes to the *skills* store, which our standard says is
   human-ratified-only.** Hermes's "improve yourself freely" default is correct for a personal
   assistant; it is **NOT** acceptable for an autonomous agent trading real capital. On Hermes we
   MUST constrain or disable autonomous skill promotion for any risk-bearing behavior, and route
   proposed skills through `reports/sop-changes/` for human ratification. Memory/observation
   accumulation (Tier 1) may run freely; behavior changes (thresholds, skills, guardrails) may not.

2. **The Curator does NOT remove the tail-event limit.** Hermes can auto-generate skills for
   common, repeatable tasks (where it has many success examples). It cannot manufacture crash/tail
   knowledge from 0–2 crashes/year. Tail rules still come from market-wide history or structural
   indicators, with provenance tags — see the "hard limit" section above.

3. **Every harness's memory has boundary failures** (internal "State of Memory in Agent Harness"
   survey, 2026-06: Claude Code, Codex, Cursor, Copilot, AND Hermes all exhibit "stale-but-confident"
   issues). Do not assume Hermes's memory is trustworthy by default — apply the runtime-trust rule
   (confidence / recency / last_verified; retrieved = hypothesis until re-verified live).

**Net:** keep Hermes's memory + retrieval; put its autonomous skill-promotion behind this package's
human ratification gate. The frozen-model / externalized-learning principle is unchanged — Hermes
just provides more of the external machinery, which must still obey the four-store separation.

---

## Change policy for this document

This is a guardrail artifact. It is human-controlled. Changes follow the same path as SOP changes:
propose in `reports/sop-changes/`, human ratifies, commit a new version. The "hard limit" section
above is load-bearing and must survive edits.
