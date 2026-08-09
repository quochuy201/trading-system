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
- **Status:** ☑ done — `0aced42`. `find . -name install.sh -not -path '*/_archive/*'` → `./install.sh` only.

### Task 2 — Two explicit path roots
- **Files:** `./install.sh`
- **What:** replace the single `REPO_DIR` with **`REPO_ROOT`** (sops/skills/tools/OPERATING_MANUAL) and **`DEPLOY_DIR="$REPO_ROOT/setup/deploy"`** (profile.yaml/SOUL.md/preflight.sh/cron/runs/mcp.json). Update every reference to use the correct root.
- **Check:** `grep` shows no bare `${REPO_DIR}` remains; each path references the correct variable.
- **Status:** ☑ done — `21900d9`. `grep -n REPO_DIR install.sh` → 0 matches; `install.sh:4-5` define `REPO_ROOT` / `DEPLOY_DIR`.

### Task 3 — Up-front path validation
- **Files:** `./install.sh`
- **What:** `require_paths()` per design §2 — verify **all** required sources exist **before any copy**, and print **every** missing path at once (not just the first).
- **Check:** temporarily rename a source dir ⇒ install exits non-zero, names it, and **copies nothing**; restore ⇒ passes.
- **Status:** ☑ done — `3365aee` (`require_paths`, `install.sh:29-41`, called at `:96` before the first copy). Verified against an incomplete tree: **all 5** missing paths printed at once, exit 1, 0 files copied (see Task 4 evidence).

### Task 4 — Honest `--dry-run`
- **Files:** `./install.sh`
- **What:** `--dry-run` performs real path resolution + validation and reports exactly what would be copied/registered. **A dry run that skipped validation would have concealed this very bug.**
- **Check:** `./install.sh hermes --dry-run` on a broken path reports the failure; on a good tree, lists every action and mutates nothing.
- **Status:** ☑ done — `8a4e650`. Validation already ran under `--dry-run`; the defect found was the **reported verdict**: `run` echoed `preflight.sh` and returned 0, so every dry run printed `✅ Passed – system ready.` having verified nothing. Now prints `(not run – no verdict)`.

```
$ ./install.sh hermes --dry-run           # good tree
... every cp/chmod/mcp add/cron create listed as [dry-run]
[dry-run] .../preflight.sh (not run – no verdict)          exit 0
$ find ~/.hermes/profiles/trading ~/.hermes/scripts -type f -newermt <run start>
  (only state/gateway.heartbeat + cron/ticker_* — written by the running
   gateway, not the installer; no install-owned file touched, no PROVENANCE.md)

$ <incomplete tree>/install.sh hermes --dry-run
MISSING: .../skills
MISSING: .../OPERATING_MANUAL.md
MISSING: .../setup/deploy/SOUL.md
MISSING: .../setup/deploy/preflight.sh
MISSING: .../setup/deploy/runs                              exit 1, 0 files copied
```

### Task 5 — Provenance stamp
- **Files:** `./install.sh`
- **What:** write `git_sha` + `installed_at` + `repo_root` into the deployed profile.
- **Check:** stamp present after install; SHA matches `git rev-parse HEAD`.
- **Status:** ◑ code landed (`421572e`, `install.sh:177-192`) — **check NOT met.** Writing the stamp requires a real install, which is Task 10; `~/.hermes/profiles/trading/PROVENANCE.md` does not exist yet. Do not tick this until that run produces a stamp whose SHA matches `git rev-parse HEAD`.

### Task 6 — ⭐ `verify.sh` (checks 1–8)
- **Files:** `setup/deploy/verify.sh` (new)
- **What:** implement design §3 checks 1–8: MCP responds · **expected tools reachable in the deployed profile** · **options tools specifically** · skills present with `requires_tools ⊆ reachable` · crons registered with resolvable script paths · kanban boards exist · `OPERATING_MANUAL.md` present · provenance stamp current. Exit non-zero on any failure, with a specific message.
- **Check:** passes on a good install (see Task 8 for the negative tests).
- **Status:** ☑ done — `setup/deploy/verify.sh` + `setup/deploy/mcp_probe.py`.

**Checks 1–3 do a real MCP handshake, not introspection.** `mcp_probe.py` spawns the
command *as registered for the profile* and speaks line-delimited JSON-RPC
(`initialize` → `notifications/initialized` → `tools/list`). That exercises
`run_mcp.sh`, the venv, and any `TRADING_TOOL_GROUPS` on the registration — verified
by watching the reachable count track the gating:

```
$ mcp_probe.py --command tools/run_mcp.sh                             -> 61 tools
$ ... --env TRADING_TOOL_GROUPS=research                              -> 24 tools
$ ... --env TRADING_TOOL_GROUPS=monitor                               -> 17 tools
$ ... --env TRADING_TOOL_GROUPS=eod                                   -> 13 tools
```

It deliberately does **not** shell out to `hermes`: the CLI has no tool-enumeration
subcommand (`hermes_cli/subcommands/mcp.py` → `serve/add/remove/list/test/login/
reauth/picker/catalog/install`), and a verifier must still work while the CLI is
mid-upgrade. Check 2's expected set is the repo's own tool list probed under the same
env — a repo-vs-runtime diff, never a hardcoded count (**RULE 3**). Boards for check 6
are read from `setup/deploy/runs/*.yaml`, their one home.

Green on an intact profile (full output in Task 8's fixture):

```
[1] ok handshake completed, 61 tools reachable      [5] ok all registered cron scripts resolve
[2] ok every tool the repo defines is reachable     [6] ok board 'equity' / 'options' present
[3] ok all 5 options tools reachable                [7] ok present
[4] ok every skill's requires_tools is reachable    [8] ok runtime matches 46b8f63a
✅ verification passed                                                          exit 0
```

⚠️ **Found while building this:** the first draft of checks 4 and 5 crashed on a
Python `SyntaxError`, produced empty output, and my shell read empty as "no problems"
— both printed **`ok`**. A vacuous pass, in the very script written to abolish vacuous
passes, inside one hour. Both now fail closed when the check cannot run. This is the
whole argument for Task 8.

### Task 7 — Divergence report (check 9, warn-only)
- **Files:** `setup/deploy/verify.sh`
- **What:** list skills present in the runtime with **no repo counterpart** (today: `options-trader`, `options-exit-manager`) and each one's referenced tools. **WARN, never fail** — deleting them would remove the only running options logic (D-DEP2).
- **Check:** run against the current Hermes profile ⇒ reports both skills and notes they reference **zero** repo options tools.
- **Status:** ☑ done — `verify.sh` check 9, warn-only. Covered by
  `test_runtime_only_skill_warns_without_failing`, which asserts exit 0, the warning
  text, **and that the skill directory still exists afterwards** (D-DEP2).
  ◑ Running it against the *live* Hermes profile is deferred with Task 10.

### Task 8 — ⚠️ Negative tests for the verifier
- **Files:** `tools/tests/test_deploy_verify.py` (new) or a shell harness
- **What:** deliberately break each condition and assert `verify.sh` **FAILS**: remove a skill · drop a tool from its group · unregister a cron · stop the MCP server · stale provenance. **This is the most important task in the feature** — a verifier never observed failing proves nothing, which is precisely how "everything looks fine" persisted for 34 sessions.
- **Check:** every negative case fails as expected; the positive case passes.
- **Status:** ☑ done — `tools/tests/test_deploy_verify.py`, 13 tests: one per broken
  condition (each asserting non-zero exit **and** the specific message), the intact
  positive case, and the warn-only case. Every fixture is built in `tmp_path` and
  passed via `--hermes-home`; nothing touches the real `~/.hermes`.

```
$ cd tools && uv run --extra dev pytest tests/test_deploy_verify.py -v
13 passed in 11.87s
$ cd tools && uv run --extra dev pytest tests/ -q
344 passed, 10 warnings in 21.68s          # 331 + 13
```

The positive case matters as much as the negatives: without it, a verifier that always
failed would also make every negative test green.

### Task 9 — Wire verification into install + idempotency
- **Files:** `./install.sh`
- **What:** run `verify.sh` as the final step; a verification failure **fails the install** (non-zero). Confirm installing twice is idempotent.
- **Check:** clean end-to-end `./install.sh hermes` completes and verifies; second run yields identical profile state.
- **Status:** ◑ wiring done, **check unmet.** `install.sh` step 14 runs `verify.sh` as the
  last step, after every mutation (design §6 ordering), and returns 1 on failure.

```
$ bash -n install.sh                                          syntax OK
$ ./install.sh hermes --dry-run | tail -1
[dry-run] .../setup/deploy/verify.sh hermes (not run – no verdict)     exit 0
```

  Failure really does fail the install — `set -e` propagates a non-zero function out of
  the `case` branch, demonstrated rather than assumed:

```
$ f() { return 1; }; case x in x) f ;; esac; echo REACHED
exit=1        # REACHED not printed
```

  **Not yet met:** "clean end-to-end install completes and verifies" and the
  idempotency check both require running the real installer — that is Task 10, and it
  needs the `hermes` CLI to register MCP servers, crons and boards.

### Task 10 — Deploy the pending work + close the bugs
- **Files:** `PROJECT_STATUS.md`, `docs/product/ROADMAP.md`, `BUILD-PLAN.md`
- **What:** run the fixed installer; confirm the **five options MCP tools are now reachable in the deployed profile**. Close both 🔴 CRITICAL entries with evidence; unblock `data-source-adapters` Task 7.
- **Check:** full suite green; `verify.sh` green; options tools reachable.
- **Status:** ☐ todo

---

## Definition of Done

- [x] Exactly one installer; duplicates archived
- [x] `REPO_ROOT` / `DEPLOY_DIR` resolved separately; all paths validated up front
- [ ] `./install.sh hermes` completes end-to-end on a clean profile — **needs Task 10**
- [x] `--dry-run` does real resolution and mutates nothing
- [ ] `verify.sh` green after install; **wired in so a failure fails the install** —
      wiring done and the failure path demonstrated; *green after a real install* needs Task 10
- [x] **Negative tests prove `verify.sh` actually fails** when it should — 13 tests
- [ ] Options MCP tools **confirmed reachable in the deployed profile** — reachable
      through the repo launcher (61 tools, all 5 options tools); **the deployed profile
      is unconfirmed**, which is the original 🔴 bug and the reason Task 10 exists
- [x] Runtime-only skills reported as a warning, **not deleted** — asserted by test
- [ ] Provenance stamp present; both 🔴 bugs closed with evidence — stamp code landed,
      never yet written by a real install

**5 of 9 met.** Every unmet item reduces to the same blocker: no real install has run.

## Decisions carried from spec

- **D-DEP1** canonical installer = `./install.sh` at repo root
- **D-DEP2** runtime-only skills ⇒ **warn, never delete**
- **D-DEP3** gating the trading cron on `verify.sh` ⇒ deferred until verification is proven stable
