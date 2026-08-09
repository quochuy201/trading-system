# Implementation Plan: <Feature Name>

> **File name:** save as `docs/product/features/<slug>/<slug>-plan.md` — named for the feature, not just `plan.md` (CLAUDE.md §How to develop).

- **Slug:** `<slug>`  ·  **Status:** `plan`  ·  **Design:** [`design.md`](design.md)
- **Executor:** Claude Code  ·  **Author:** Hermes (PM)  ·  **Date:** YYYY-MM-DD

## How to Use This Plan
Tasks are ordered and bite-sized. Do them in sequence unless marked parallel-safe.
Follow the repo's TDD + backtest rules in `CLAUDE.md`. After each task: run the named
tests, then check the box and note the commit. Do not batch-commit unrelated tasks.

## Guardrails (read before writing code)
- Preserve the kill switch, circuit breakers, mode state machine, R:R gates.
- Never hardcode strategy logic in Python (CLAUDE.md rule). Strategy lives in skills/SOPs.
- Tools return JSON errors, never raise to the agent.
- All 331 existing tests must stay green.

## Tasks

### Task 1 — <title>
- **Files:** `tools/...` (new/modified)
- **What:** precise description of the change.
- **Tests:** `tools/tests/test_...py::test_...` — cases to cover.
- **Acceptance:** the observable condition that means this task is done.
- **Status:** ☐ todo / ☐ in progress / ☐ done (commit ______)

### Task 2 — <title>
...

## Definition of Done (whole feature)
- [ ] All tasks done, boxes checked
- [ ] Every spec acceptance criterion has a passing test
- [ ] `pytest tests/ -v` green (no regressions)
- [ ] PROJECT_STATUS.md updated with a dated entry + commit
- [ ] ROADMAP.md status flipped to `shipped`
