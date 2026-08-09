# Implementation Plan: Deployment

- **Slug:** `deployment` · **Status:** `plan` · **Design:** [`deployment-design.md`](deployment-design.md) · **Spec:** [`deployment-spec.md`](deployment-spec.md)
- **Executor:** Claude Code · **Date:** 2026-07-25
- **Position:** BUILD-PLAN queue **#0 — prerequisite for every other feature**

## How to Use This Plan

Ordered, bite-sized tasks. After each, run the named check, tick the box, note the commit.

## Guardrails (read before writing code)

- **This script governs what code runs against real money.** It changes no trading logic, but a mis-deploy is a safety event.
- **Validate all paths before the first copy** — never leave a half-applied profile.
- **Never delete runtime-only content.** Report divergence; don't destroy it (D-DEP2).
- **Check reachability, not presence.** Presence is what looked fine while five tools were unusable.
- **A verifier that has never been seen to fail is not evidence** — negative tests are mandatory.
- `--dry-run` must do real path resolution.

---

## Tasks

### Task 1 — Collapse to one installer
- **Files:** `./install.sh` (canonical), delete `./setup/install.sh` + `./setup/deploy/install.sh`
- **What:** keep the repo-root installer (matches the documented command in `CLAUDE.md`, D-DEP1). Remove both duplicates — **duplication is what let them drift into failing on opposite halves.** Archive them under `docs/_archive/` for provenance.
- **Check:** exactly one `install.sh` in the repo (excluding `docs/_archive/`).
- **Status:** ☐ todo

### Task 2 — Two explicit path roots
- **Files:** `./install.sh`
- **What:** replace the single `REPO_DIR` with **`REPO_ROOT`** (sops/skills/tools/OPERATING_MANUAL) and **`DEPLOY_DIR="$REPO_ROOT/setup/deploy"`** (profile.yaml/SOUL.md/preflight.sh/cron/runs/mcp.json). Update every reference to use the correct root.
- **Check:** `grep` shows no bare `${REPO_DIR}` remains; each path references the correct variable.
- **Status:** ☐ todo

### Task 3 — Up-front path validation
- **Files:** `./install.sh`
- **What:** `require_paths()` per design §2 — verify **all** required sources exist **before any copy**, and print **every** missing path at once (not just the first).
- **Check:** temporarily rename a source dir ⇒ install exits non-zero, names it, and **copies nothing**; restore ⇒ passes.
- **Status:** ☐ todo

### Task 4 — Honest `--dry-run`
- **Files:** `./install.sh`
- **What:** `--dry-run` performs real path resolution + validation and reports exactly what would be copied/registered. **A dry run that skipped validation would have concealed this very bug.**
- **Check:** `./install.sh hermes --dry-run` on a broken path reports the failure; on a good tree, lists every action and mutates nothing.
- **Status:** ☐ todo

### Task 5 — Provenance stamp
- **Files:** `./install.sh`
- **What:** write `git_sha` + `installed_at` + `repo_root` into the deployed profile.
- **Check:** stamp present after install; SHA matches `git rev-parse HEAD`.
- **Status:** ☐ todo

### Task 6 — ⭐ `verify.sh` (checks 1–8)
- **Files:** `setup/deploy/verify.sh` (new)
- **What:** implement design §3 checks 1–8: MCP responds · **expected tools reachable in the deployed profile** · **options tools specifically** · skills present with `requires_tools ⊆ reachable` · crons registered with resolvable script paths · kanban boards exist · `OPERATING_MANUAL.md` present · provenance stamp current. Exit non-zero on any failure, with a specific message.
- **Check:** passes on a good install (see Task 8 for the negative tests).
- **Status:** ☐ todo

### Task 7 — Divergence report (check 9, warn-only)
- **Files:** `setup/deploy/verify.sh`
- **What:** list skills present in the runtime with **no repo counterpart** (today: `options-trader`, `options-exit-manager`) and each one's referenced tools. **WARN, never fail** — deleting them would remove the only running options logic (D-DEP2).
- **Check:** run against the current Hermes profile ⇒ reports both skills and notes they reference **zero** repo options tools.
- **Status:** ☐ todo

### Task 8 — ⚠️ Negative tests for the verifier
- **Files:** `tools/tests/test_deploy_verify.py` (new) or a shell harness
- **What:** deliberately break each condition and assert `verify.sh` **FAILS**: remove a skill · drop a tool from its group · unregister a cron · stop the MCP server · stale provenance. **This is the most important task in the feature** — a verifier never observed failing proves nothing, which is precisely how "everything looks fine" persisted for 34 sessions.
- **Check:** every negative case fails as expected; the positive case passes.
- **Status:** ☐ todo

### Task 9 — Wire verification into install + idempotency
- **Files:** `./install.sh`
- **What:** run `verify.sh` as the final step; a verification failure **fails the install** (non-zero). Confirm installing twice is idempotent.
- **Check:** clean end-to-end `./install.sh hermes` completes and verifies; second run yields identical profile state.
- **Status:** ☐ todo

### Task 10 — Deploy the pending work + close the bugs
- **Files:** `PROJECT_STATUS.md`, `docs/product/ROADMAP.md`, `BUILD-PLAN.md`
- **What:** run the fixed installer; confirm the **five options MCP tools are now reachable in the deployed profile**. Close both 🔴 CRITICAL entries with evidence; unblock `data-source-adapters` Task 7.
- **Check:** full suite green; `verify.sh` green; options tools reachable.
- **Status:** ☐ todo

---

## Definition of Done

- [ ] Exactly one installer; duplicates archived
- [ ] `REPO_ROOT` / `DEPLOY_DIR` resolved separately; all paths validated up front
- [ ] `./install.sh hermes` completes end-to-end on a clean profile
- [ ] `--dry-run` does real resolution and mutates nothing
- [ ] `verify.sh` green after install; **wired in so a failure fails the install**
- [ ] **Negative tests prove `verify.sh` actually fails** when it should
- [ ] Options MCP tools **confirmed reachable in the deployed profile**
- [ ] Runtime-only skills reported as a warning, **not deleted**
- [ ] Provenance stamp present; both 🔴 bugs closed with evidence

## Decisions carried from spec

- **D-DEP1** canonical installer = `./install.sh` at repo root
- **D-DEP2** runtime-only skills ⇒ **warn, never delete**
- **D-DEP3** gating the trading cron on `verify.sh` ⇒ deferred until verification is proven stable
