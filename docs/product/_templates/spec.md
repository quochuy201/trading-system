# Spec: <Feature Name>

> **File name:** save as `docs/product/features/<slug>/<slug>-spec.md` — named for the feature, not just `spec.md` (CLAUDE.md §How to develop).

- **Slug:** `<slug>`
- **Status:** `spec`  <!-- backlog | spec | design | plan | building | shipped | parked -->
- **Priority:** `P0 | P1 | P2`
- **Owner sign-off:** ☐ pending / ☑ approved (date)
- **Layer(s):** <which of the 6 pipeline layers this touches — see ARCHITECTURE-MAP.md>
- **Author:** Hermes (PM)  ·  **Date:** YYYY-MM-DD

## Problem
What is broken or missing TODAY? Ground it in real code/behavior (cite files + lines).
Why does it matter (safety / money / maintainability / reproducibility)?

## Goal
One-paragraph statement of the desired end state. Measurable where possible.

## User / System Value
Who benefits and how. For a trading system, tie to capital preservation, edge, or
operability. "So that ___" statements.

## Scope
- **In scope:** bullet list of what this feature includes.
- **Out of scope / non-goals:** what it explicitly does NOT do (prevents scope creep).

## Acceptance Criteria
Numbered, testable conditions. Each should be verifiable by a test or a manual check.
1. ...
2. ...

## Risks & Safety Impact
Impact on kill switch, circuit breakers, position sizing, R:R, compliance, modes.
What could this feature break? What is the fail-safe behavior?

## Open Decisions
Questions requiring owner input, each with a recommended default so work isn't blocked.
- **D1:** ... (recommend: ...)

## References
- OPERATING_MANUAL.md §...
- Related specs / research notes / Obsidian links
