# Spec: Deployment (repo → Hermes runtime)

- **Slug:** `deployment`
- **Status:** `spec`
- **Priority:** `P0` — **prerequisite for every other feature.** Nothing we build reaches the runtime until this works.
- **Owner sign-off:** ☑ unparked 2026-07-25 (BUILD-PLAN queue #0)
- **Layer(s):** operational (no trading logic)
- **Author:** Claude Code · **Date:** 2026-07-25

## Problem

### 1. There are THREE installers and **none of them can complete**

```
./install.sh                 REPO_DIR = <repo>
./setup/install.sh           REPO_DIR = ""          (empty!)
./setup/deploy/install.sh    REPO_DIR = <repo>/setup
```

`./install.sh` and `./setup/deploy/install.sh` are otherwise **near-identical copies** (261 lines each, differing on 3 lines). They fail in **complementary** ways:

| Installer | `${REPO_DIR}/deploy/…` (profile.yaml, SOUL.md, cron/, runs/, preflight.sh) | `${REPO_DIR}/{sops,skills,tools}` + `OPERATING_MANUAL.md` |
|---|---|---|
| `./install.sh` | → `<repo>/deploy/` **MISSING** ❌ (fails line 85) | → `<repo>/sops` ✅ |
| `./setup/deploy/install.sh` | → `<repo>/setup/deploy/` ✅ | → `<repo>/setup/sops` **MISSING** ❌ (fails line 87/103) |

Both run `set -euo pipefail`, so each **aborts at its first missing path** — before MCP registration (line 121), kanban board creation (124), and cron installation (128).

### 2. Root cause: one variable addressing two different roots

`deploy/` was moved to `setup/deploy/`, but `$REPO_DIR` is used for **both** the deploy assets **and** the repo content — which now live at **different depths**. Adjusting `REPO_DIR` fixes one set and breaks the other. **A single variable cannot address both.** The duplicate installers then let the two copies drift independently.

### 3. Consequence: silent divergence between repo and runtime

`./install.sh hermes` is the command documented in `CLAUDE.md`. It has been failing, so **repo changes never reach Hermes** — the runtime keeps running whatever was last successfully installed while the repo moves on. This is the mechanical root cause of:

- **Five options MCP tools built, smoke-tested, and unreachable** by the `options-trader` skill (which exists only in the Hermes deployment, references zero of them) → **34 consecutive zero-trade sessions**, 6 escalations for a feed that already existed, 33 for XSP.

**The deepest defect is not the path — it is that the failure was invisible.** A deploy that half-completes, or completes against stale content, produces no signal until someone audits by hand months later.

## Goal

**One** installer that resolves paths correctly, and a **post-install verification** that proves the runtime actually received what the repo intended — so a deployment either works or fails loudly, never silently.

## User / System Value

- **Unblocks everything.** `go-live-metrics`, `governance-gate`, `data-source-adapters` are all inert until they can deploy.
- **Ends the divergence class of bug** — the one that cost 34 trading sessions.
- **Makes "is the runtime current?" answerable** in one command instead of a manual audit.

## Scope

**In scope**
- **Collapse to ONE installer.** Delete the duplicates (duplication is what allowed the drift).
- **Two explicit path variables** — `REPO_ROOT` (sops/skills/tools/OPERATING_MANUAL) and `DEPLOY_DIR` (profile.yaml/SOUL.md/cron/runs/preflight) — each resolved independently and **validated before any copying begins**.
- **Pre-flight path check:** assert every required source path exists **up front**, listing all missing ones at once, rather than dying at the first.
- **`verify.sh` — post-install verification** (the core of this feature): MCP server responds; expected tools reachable **in the deployed profile**; skills present and matching the repo; crons registered; kanban boards exist; `OPERATING_MANUAL.md` present.
- **Verification runs automatically** at the end of install, and is independently invocable.
- **Version/provenance stamp** written into the profile (git SHA + timestamp) so the runtime can report what it's running.
- **`--dry-run`** preserved and made honest (it must exercise path resolution).

**Out of scope / non-goals**
- **Rewriting the Hermes-only skills** (`options-trader`, `options-exit-manager`) or reconciling their content with the repo — that is a **strategy** decision, tracked separately. This feature makes the divergence *visible and fixable*, not resolved.
- Kermes / MeshClaw platform paths beyond keeping them working.
- CI/CD pipelines, containerization, remote deploy.
- Any trading-logic change.

## Acceptance Criteria

1. Exactly **one** `install.sh` exists in the repo; the duplicates are removed.
2. `REPO_ROOT` and `DEPLOY_DIR` are resolved separately; **every** required source path is validated before the first copy, and **all** missing paths are reported together.
3. `./install.sh hermes` completes end-to-end on a clean profile: files copied, MCP registered, kanban boards created, crons installed.
4. `./install.sh hermes --dry-run` performs real path resolution and reports exactly what would happen — including path failures.
5. **`verify.sh` passes** after install and **fails loudly** when: a tool is unreachable, a skill is missing, a cron is absent, or the MCP server doesn't respond.
6. Verification runs automatically at the end of install; a verification failure **fails the install** (non-zero exit).
7. Verification reports **which options MCP tools are reachable in the deployed profile** — the specific regression that cost 34 sessions.
8. A provenance stamp (git SHA + install timestamp) is written into the profile and surfaced by `verify.sh`.
9. Verification detects **repo↔runtime skill divergence** (a skill present in the runtime with no repo counterpart) and reports it as a **warning**, not a failure — it's informational until the strategy decision is made.

## Risks & Safety Impact

- **No trading-logic change**, but this feature governs **what code runs against real money** — a mis-deploy is a safety event even though the script itself trades nothing.
- **Risk: a partially-applied deploy.** Mitigated by validating all paths up front, so the script fails *before* mutating the profile rather than halfway through.
- **Risk: verification that passes vacuously** (e.g. asserting a file exists rather than that the tool responds). Verification must check **reachability**, not presence — presence is what already looked fine while five tools were unusable.
- **Risk: overwriting a hand-edited runtime.** The Hermes profile currently contains skills with no repo counterpart; install must **not** silently delete them — report, don't destroy.

## Open Decisions

- **D-DEP1: Which installer becomes canonical?** *(Recommend: **`./install.sh` at repo root** — it matches the documented command in `CLAUDE.md`; fix its path handling and delete the other two.)*
- **D-DEP2: Should install overwrite runtime-only skills?** *(Recommend: **no — report as a warning**. Deleting `options-trader` would remove the only running options logic. Make divergence visible; let the owner decide.)*
- **D-DEP3: Should `verify.sh` gate the trading cron?** *(Recommend: **yes, eventually** — a failed verification should block the morning cycle, same spirit as `preflight.sh`. Defer wiring until verification has proven stable.)*

## References

- Code: `./install.sh`, `./setup/install.sh`, `./setup/deploy/install.sh`; assets at `setup/deploy/{profile.yaml,SOUL.md,preflight.sh,cron/,runs/,mcp.json}`
- `CLAUDE.md` — documents `./install.sh hermes` as *the* install command
- `PROJECT_STATUS.md` — 🔴 both critical bugs logged 2026-07-25
- `docs/product/BUILD-PLAN.md` — queue #0; `data-source-adapters` Task 7 (post-install reachability) depends on this
- Evidence: `Hermes/skills/options-trader/` (runtime-only, 0 references to repo options tools); `Hermes/trades.jsonl` (34 no-trade sessions)
