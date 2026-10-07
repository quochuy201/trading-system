# Product Docs — Single Source of Truth

This directory is the **product management home** for the trading system. It exists
because the project outgrew ad-hoc notes: design docs were scattered across
`design/`, `docs/specs/`, `docs/superpowers/`, `.superpowers/sdd/`, and the Obsidian
brain, with no master index tying them together.

**If you are picking up this project — start here, then read [`ROADMAP.md`](ROADMAP.md).**

---

## Roles

| Role | Who | Responsibility |
|------|-----|----------------|
| **Builder** | Claude Code | Writes specs, designs, and implementation plans, then builds them: code + tests. Maintains this directory + the roadmap. Updates task status. |
| **Operator** | Hermes Agent | Operates the system: runs it, logs, analyzes results, feeds them back. |
| **Owner** | You | Sets priorities, approves specs, ratifies risk changes, authorizes installs. |

The split is deliberate and was decided in [`BUILD-PLAN.md`](BUILD-PLAN.md) §1: Claude Code
writes spec → design → plan → build; Hermes operates. A plan is "done" only when its
acceptance criteria pass.

---

## The Workflow (every feature goes through this)

```
  IDEA ──► SPEC ──► DESIGN ──► PLAN ──► [Claude Code builds] ──► SHIPPED
         (what &   (how, with  (tasks,                          (status
          why)     tradeoffs)   files, tests)                    updated)
```

1. **Spec** (`<slug>-spec.md`) — the problem, goal, user value, scope, acceptance criteria,
   non-goals. Answers *what* and *why*. Owner approves before design.
2. **Design** (`<slug>-design.md`) — architecture, data model, integration points, error
   handling, tradeoffs, the exact files touched. Answers *how*. Grounded in real code.
3. **Plan** (`<slug>-implementation-plan.md`) — ordered, bite-sized tasks for Claude Code. Each task names
   files, gives acceptance criteria, and specifies tests. This is the executable unit.

Exactly these three files per feature; git is the version history (never `design-v2.md`).
Templates live in [`_templates/`](_templates/). Copy and rename them; don't reinvent the format.

---

## Directory Layout

```
docs/product/
  README.md              ← you are here
  ROADMAP.md             ← master backlog: every feature, status, priority, links
  BUILD-PLAN.md          ← ratified decisions D1–D7, build waves, verification, build queue (§4.7)
  ARCHITECTURE-MAP.md    ← the mental model: 6-layer lens ↔ your role-agents + key files
  _templates/
    spec.md  design.md  implementation-plan.md
  research/              ← research inputs (e.g. R1-scanner-redesign.md); not specs
  features/
    <slug>/              ← one folder per ACTIVELY-SPECCED feature
      <slug>-spec.md  <slug>-design.md  <slug>-implementation-plan.md
  changes/
    <slug>/              ← one folder per change to existing behaviour
      change.md          ← the change note (+ the workflow's acceptance/locked-tests JSON)
```

**A feature lives in the ROADMAP backlog until it is actively being spec'd** — only
then does it graduate to its own `features/<slug>/` folder with the three docs. This
prevents the empty-stub sprawl that created the original problem.

**A change is not a feature.** A fix, cleanup or refactor of existing behaviour gets one
note in `changes/<slug>/`, not a feature folder (first one: `dead-config-cleanup`, 2026-10-07).

---

## Status Vocabulary (used in ROADMAP + every doc header)

| Status | Meaning |
|--------|---------|
| `backlog` | Captured, not yet spec'd. Lives only as a ROADMAP entry. |
| `spec` | Spec written, awaiting owner approval. |
| `design` | Spec approved; design in progress/written. |
| `plan` | Design approved; implementation plan ready for Claude Code. |
| `building` | Claude Code is executing the plan. |
| `shipped` | Merged, tests green, acceptance criteria met. |
| `parked` | Deliberately deferred (record why). |
| `paused` | Build stopped part-way by owner decision; finished tasks stay done (record why and what unblocks it). |

---

## Relationship to the Old Artifact Homes

This directory **supersedes** ad-hoc design docs going forward. The historical docs
were removed from git in `570f314` (2026-08-08); recover any with
`git show 570f314^:<path>`. New product work is specced here.
See [`ROADMAP.md`](ROADMAP.md) for the migration note and the legacy paths.

- `PROJECT_STATUS.md` (repo root) remains the **engineering changelog** — what shipped,
  when, with which commit. This directory is the **forward-looking product plan**.
- The project page in the owner's Obsidian vault (`05-Projects/trading-system.md`) holds
  the long-term research + decisions. It links here; this links back.
