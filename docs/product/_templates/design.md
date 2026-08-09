# Design: <Feature Name>

> **File name:** save as `docs/product/features/<slug>/<slug>-design.md` — named for the feature, not just `design.md` (CLAUDE.md §How to develop).

- **Slug:** `<slug>`  ·  **Status:** `design`  ·  **Spec:** [`spec.md`](spec.md)
- **Author:** Hermes (PM)  ·  **Date:** YYYY-MM-DD

## Summary
2-3 sentences: the chosen approach and why.

## Approaches Considered
| Approach | Pros | Cons | Verdict |
|----------|------|------|---------|
| A. ... | | | chosen / rejected |
| B. ... | | | |

Recommendation + reasoning.

## Architecture
How it fits the existing system. Diagram (ASCII ok). Name the real modules/agents.

## Data Model
New/changed dataclasses, DB tables, JSON shapes. Exact field names + types.

## Integration Points (exact files)
| File | Change | Why |
|------|--------|-----|
| `tools/...` | new / modified | ... |

For each MODIFIED file, show a before/after sketch of the critical edit.

## Control Flow
Step-by-step of the feature at runtime. Where does it sit in the call path?
What can it NOT bypass (for safety-critical features)?

## Error Handling & Fail-Safe
What happens on error, missing data, ambiguity? Default to the SAFE outcome and say so.

## Testing Strategy
Unit vs integration. What must be pure/testable-offline. Key cases + edge cases.

## Rollout / Migration
How it ships without breaking the 331 existing tests. Backward compatibility. Flags.

## Self-Review Checklist
- [ ] Aligns with OPERATING_MANUAL.md and risk rules
- [ ] No unhandled kill-switch / circuit-breaker interaction
- [ ] Exits/risk-reducing actions never blocked
- [ ] Clear, testable success metrics
- [ ] No contradictions with the spec
