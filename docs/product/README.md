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
| **Product Manager** | Hermes Agent | Writes specs, designs, and implementation plans. Maintains this directory + the roadmap. Does NOT write production code. |
| **Engineer** | Claude Code | Executes the plans. Writes code + tests. Updates task status. |
| **Operator / Owner** | You | Sets priorities, approves specs, ratifies risk changes, runs the system. |

The split is deliberate: the PM keeps the *what* and *why* coherent and navigable;
the engineer owns the *how*. A plan is "done" only when its acceptance criteria pass.

---

## The Workflow (every feature goes through this)

```
  IDEA ──► SPEC ──► DESIGN ──► PLAN ──► [Claude Code builds] ──► SHIPPED
         (what &   (how, with  (tasks,                          (status
          why)     tradeoffs)   files, tests)                    updated)
```

1. **Spec** (`spec.md`) — the problem, goal, user value, scope, acceptance criteria,
   non-goals. Answers *what* and *why*. Owner approves before design.
2. **Design** (`design.md`) — architecture, data model, integration points, error
   handling, tradeoffs, the exact files touched. Answers *how*. Grounded in real code.
3. **Plan** (`plan.md`) — ordered, bite-sized tasks for Claude Code. Each task names
   files, gives acceptance criteria, and specifies tests. This is the executable unit.

Templates live in [`_templates/`](_templates/). Copy them; don't reinvent the format.

---

## Directory Layout

```
docs/product/
  README.md              ← you are here
  ROADMAP.md             ← master backlog: every feature, status, priority, links
  ARCHITECTURE-MAP.md    ← the mental model: 6-layer lens ↔ your role-agents + key files
  _templates/
    spec.md  design.md  plan.md
  features/
    <slug>/              ← one folder per ACTIVELY-SPECCED feature
      spec.md  design.md  plan.md
```

**A feature lives in the ROADMAP backlog until it is actively being spec'd** — only
then does it graduate to its own `features/<slug>/` folder with the three docs. This
prevents the empty-stub sprawl that created the original problem.

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

---

## Relationship to the Old Artifact Homes

This directory **supersedes** ad-hoc design docs going forward. The historical docs
stay where they are (they document shipped work) but new product work is specced here.
See [`ROADMAP.md`](ROADMAP.md) for the migration note and links to the legacy specs.

- `PROJECT_STATUS.md` (repo root) remains the **engineering changelog** — what shipped,
  when, with which commit. This directory is the **forward-looking product plan**.
- The Obsidian brain (`~/Obsidian/Hermes-Brain/05-Projects/trading-system.md`) holds
  the long-term research + decisions. It links here; this links back.
