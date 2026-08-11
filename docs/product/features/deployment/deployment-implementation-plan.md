# Implementation Plan: Deployment

- **Slug:** `deployment` · **Status:** ⏸ **PAUSED** (was `building`) · **Design:** [`deployment-design.md`](deployment-design.md) · **Spec:** [`deployment-spec.md`](deployment-spec.md)
- **Executor:** Claude Code · **Date:** 2026-07-25
- **Position:** BUILD-PLAN queue **#0 — prerequisite for every other feature**

## ⏸ PAUSED 2026-08-09 — owner decision, work moved to backlog

Tasks 1–9 are done and committed. **The feature's headline goal is met:** the five options
MCP tools are confirmed reachable *in the deployed profile* by real handshake, closing the
34-session 🔴 bug.

**Resumed 2026-08-10 (code only, no deploy): Tasks 11 and 12 are now done** — `86268dc`,
`fd59de4`. Both were fixed and tested against a throwaway `HERMES_HOME`; suite **353 green**.
Task 12's recorded diagnosis turned out to be wrong and is corrected in its entry below.

**Only Task 10 remains, and it needs a real install** — which the owner has not authorized
("fix the install/deployment script but do not deploy", 2026-08-10). Nothing else in the
feature can close without it.

**Do not run `./install.sh` against `~/.hermes` to test** — that is a deploy, not a build step
(`install.sh:92` reads `HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"`, so a temp target is
already supported). Two sessions have now damaged the live runtime doing exactly that; see
the 2026-08-09 entry in `PROJECT_STATUS.md`.

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
- **Status:** ☑ done — `421572e` (`install.sh:177-192`); **check met 2026-08-09** by a real install.

```
$ head -5 ~/.hermes/profiles/trading/PROVENANCE.md
- **Git SHA:** b3be775edaa3813f0ef0714bc2321472932e49b1
- **Installed at:** 2026-08-10T00:14:57Z
$ git rev-parse HEAD
b3be775edaa3813f0ef0714bc2321472932e49b1          # match
```

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
- **Status:** ◑ **partially met 2026-08-09.** The installer ran and the headline check passed;
  `verify.sh` is not green, so the task does not close.

```
[1] ok handshake completed, 61 tools reachable
[2] ok every tool the repo defines is reachable
[3] ok all 5 options tools reachable          ← ⭐ the 34-session 🔴 bug, closed by handshake
[8] ok runtime matches b3be775e
```

  **Blocked on Tasks 11–12.** Remaining when resumed: `verify.sh` green after a *pure* install
  (no hand-copied skills), install twice for Task 9's idempotency check, full suite, then close
  the 🔴 entries in `PROJECT_STATUS.md` / `ROADMAP.md` / `BUILD-PLAN.md`.

### Task 11 — 🆕 `install.sh` never copies `skills/` into the profile
- **Files:** `./install.sh`
- **What:** the `hermes` branch copies `profile.yaml`, `SOUL.md`, `OPERATING_MANUAL.md`,
  `scripts/`, and `sops/` — but **not `skills/`**. A fresh install ships a profile with no agent
  behaviour at all. `grep -n skills install.sh` matches only in the `kermes` (`:242-264`) and
  `meshclaw` (`:273-298`) branches.
- **Check:** after a clean install to a throwaway `HERMES_HOME`, all six skills present and
  `verify.sh` check 4 passes **without any hand-copying**.
- **Status:** ☑ **done 2026-08-10** — `fd59de4`. Found 2026-08-09 by `verify.sh`'s first live run:

```
[4] Skill contracts satisfied
  FAIL skill missing from profile: backtest / eod-review / monitor / research / risk-manager / trader
$ sed -n '90,238p' install.sh | grep -c skills          ->  0
```

  Fix copies the tree at `install.sh` step 4b, merging (`skills/.`) rather than replacing —
  Hermes keeps its own built-in skills in that same directory (~18 of them) and check 9
  deliberately never deletes them. Verified into a throwaway `HERMES_HOME`, no deploy:

```
[dry-run] cp -R <repo>/skills/. $T/profiles/trading/skills/
backtest ok · eod-review ok · monitor ok · research ok · risk-manager ok · trader ok
```

  First tests this installer has ever had: `tools/tests/test_install.py` (4). They run it with
  `--dry-run`, `HOME`/`HERMES_HOME` in `tmp_path`, and a stub `hermes` on `PATH` that logs every
  call — one test asserts that log is **empty**, so "dry-run is inert" is asserted, not assumed.

### Task 12 — 🆕 `verify.sh` check 5 fails installs whose crons *are* registered
- **Files:** `setup/deploy/verify.sh`
- **⚠️ The original diagnosis in this entry was wrong.** It said Hermes stores the job list
  globally and check 5 read the wrong path. The path was right; the *inference* was wrong:

```
$ cat ~/.hermes/cron/jobs.json      -> {"jobs": [], ...}          # global store EMPTY
$ hermes cron list                  -> No scheduled jobs.
$ hermes -p trading cron list       -> 7 jobs [active]            # the profile store is live
$ stat -f "%SB" ~/.hermes/profiles/trading/cron/jobs.json -> Aug 10 14:00:55
$ grep "Installed at" ~/.hermes/profiles/trading/PROVENANCE.md -> 2026-08-10T00:14:57Z
```

  `jobs.json` is written **lazily** by the scheduler when it first records a run — 14 hours
  after the install that check 5 failed. So a correct fresh install has no cache, and
  "file absent ⇒ nothing is scheduled" fails every one of them.
- **What:** consult two sources in order — the cache when it has content, then
  `hermes cron list` as the authority. An empty/unparseable cache counts as *no answer* and
  falls through (which also covers the empty global file). Neither available ⇒ **fail closed**.
  Shelling out to `hermes` is safe here: no file-only alternative exists, and the CLI honours
  `HERMES_HOME` (`HERMES_HOME=$(mktemp -d) hermes -p trading cron list` → 0 jobs vs 7 real),
  so verifying a throwaway profile stays isolated.
- **Check:** check 5 passes against a profile with registered crons; the existing negative test
  for an unregistered cron still fails.
- **Status:** ☑ **done 2026-08-10** — `86268dc`. Five new tests, **observed failing against the
  pre-fix script** before the fix was kept:

```
FAILED test_absent_cache_with_registered_crons_passes
FAILED test_cron_script_not_found_via_cli_fails
FAILED test_agent_mode_cron_without_script_is_not_a_failure
FAILED test_cron_check_fails_closed_with_no_cache_and_no_cli
FAILED test_empty_cron_cache_falls_through_to_the_cli
5 failed, 13 deselected
$ uv run --extra dev pytest tests/ -q   ->  353 passed          # 344 + 4 + 5
```

---

## Definition of Done

- [x] Exactly one installer; duplicates archived
- [x] `REPO_ROOT` / `DEPLOY_DIR` resolved separately; all paths validated up front
- [ ] `./install.sh hermes` completes end-to-end on a clean profile — it **ran** 2026-08-09 and
      exited non-zero on verification. Both causes are now fixed (Tasks 11–12); **confirming it
      needs one more install run = Task 10, not yet authorized**
- [x] `--dry-run` does real resolution and mutates nothing
- [ ] `verify.sh` green after install; **wired in so a failure fails the install** — the wiring
      is proven *live*, not just against fixtures: the install genuinely aborted on the
      verifier's verdict (`❌ Install FAILED verification – the profile is not usable as
      deployed.`). Both known causes of the red verdict are fixed; **green** needs Task 10.
- [x] **Negative tests prove `verify.sh` actually fails** when it should — 13 tests, now **18**
- [x] **Options MCP tools confirmed reachable in the deployed profile** — ⭐ **met 2026-08-09.**
      Real MCP handshake against the profile as registered: 61 tools, all 5 options tools.
      This is the original 🔴 bug and the reason the feature is queue #0.
- [x] Runtime-only skills reported as a warning, **not deleted** — asserted by test
- [ ] Provenance stamp present; both 🔴 bugs closed with evidence — **stamp met** (SHA matches
      `HEAD`, Task 5); the doc closure is Task 10

**6 of 9 met.** The feature's purpose — proving reachability in the deployed profile — is
achieved. The remainder is two defects the verifier itself surfaced (Tasks 11–12) plus the
doc closure.

## Decisions carried from spec

- **D-DEP1** canonical installer = `./install.sh` at repo root
- **D-DEP2** runtime-only skills ⇒ **warn, never delete**
- **D-DEP3** gating the trading cron on `verify.sh` ⇒ deferred until verification is proven stable
