# Design: Deployment (repo → Hermes runtime)

- **Slug:** `deployment` · **Status:** `design` · **Spec:** [`deployment-spec.md`](deployment-spec.md)
- **Author:** Claude Code · **Date:** 2026-07-25

> **Principle:** a deployment must **work or fail loudly — never silently half-succeed.** The path bug cost one command; the *silence* cost 34 trading sessions.

---

## 1. The two roots (this is the whole bug)

Deploy assets and repo content live at **different depths**:

```
<repo>/                          ← REPO_ROOT   : sops/ skills/ tools/ OPERATING_MANUAL.md
<repo>/setup/deploy/             ← DEPLOY_DIR  : profile.yaml SOUL.md preflight.sh cron/ runs/ mcp.json
```

A single `$REPO_DIR` cannot address both — set it for one and the other breaks. That is exactly what happened: `deploy/` moved under `setup/`, one copy of the installer had its `REPO_DIR` "fixed," and the two copies now fail on opposite halves.

```bash
# ONE installer, TWO explicit roots — never one variable doing both jobs
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"                 # canonical installer lives at repo root (D-DEP1)
DEPLOY_DIR="$REPO_ROOT/setup/deploy"
```

**Delete the two duplicate installers.** Duplication is what let them drift apart in the first place; one copy cannot disagree with itself.

---

## 2. Validate every path BEFORE mutating anything

Today `set -euo pipefail` makes the script die at the *first* missing file — after it may already have copied others, leaving a half-applied profile, and telling you about only one of several problems.

```bash
require_paths() {
  local missing=()
  for p in "$REPO_ROOT/sops" "$REPO_ROOT/skills" "$REPO_ROOT/tools" \
           "$REPO_ROOT/OPERATING_MANUAL.md" \
           "$DEPLOY_DIR/profile.yaml" "$DEPLOY_DIR/SOUL.md" \
           "$DEPLOY_DIR/preflight.sh" "$DEPLOY_DIR/cron" "$DEPLOY_DIR/runs"; do
    [ -e "$p" ] || missing+=("$p")
  done
  (( ${#missing[@]} == 0 )) || { printf 'MISSING: %s\n' "${missing[@]}"; exit 1; }
}
```

**Fail before the first copy, and report every problem at once.** This turns "it died on line 85" into "these four paths are wrong."

---

## 3. ⭐ `verify.sh` — the actual feature

The path fix is ten minutes. **Verification is what prevents the next silent divergence**, and it's the reason this feature exists.

The rule: **check reachability, not presence.** Presence is what already looked fine while five options tools were unusable — the files were there; the tools were not exposed to the agent.

| # | Check | Failure mode it catches |
|---|---|---|
| 1 | MCP server **responds** in the deployed profile | server registered but not starting |
| 2 | **Expected tools reachable** — enumerate via the profile's MCP connection and diff against the expected set | 🔴 **the 34-session bug**: tools built, registered nowhere the agent can see |
| 3 | **Options tools specifically** reachable (`get_options_chain`, `get_options_market_data`, `calc_iv_rank`, `get_put_skew`, `calc_expected_move`) | the exact regression already suffered |
| 4 | **Skills present**, and each skill's `requires_tools` ⊆ reachable tools | a skill whose declared tools aren't exposed (`skill-tool-contract`) |
| 5 | **Crons registered** with resolvable script paths | the 06-23 "Script not found" class of failure |
| 6 | **Kanban boards** exist | dispatcher silently no-ops |
| 7 | `OPERATING_MANUAL.md` present in profile | agent runs without its constitution |
| 8 | **Provenance stamp** matches this install | runtime silently older than the repo |
| 9 | ⚠️ **Runtime-only skills** reported (present in profile, absent from repo) | **WARN, never fail** — surfaces `options-trader` divergence without destroying it (D-DEP2) |

Exit non-zero on 1–8; warn on 9.

```
install.sh  →  copy  →  register MCP  →  boards  →  crons  →  verify.sh  →  ✅ / ❌
                                                                  │
                                                    failure ⇒ install FAILS (non-zero)
```

Verification runs **automatically at the end of install** and is **independently invocable** (`./verify.sh hermes`) so you can answer "is the runtime current?" at any time.

---

## 4. Provenance stamp

```yaml
# written into the profile at install
deployed:
  git_sha: 9f3a1c4
  installed_at: 2026-07-25T14:02:11Z
  repo_root: /Users/…/trading-system
```

Makes "what is actually running?" a question with an answer. `verify.sh` reports it; a mismatch against the current repo SHA is a warning that the runtime is stale.

---

## 5. What this feature deliberately does NOT do

- **It does not reconcile the Hermes-only skills.** `options-trader` / `options-exit-manager` exist only in the runtime. Deleting them would remove the only running options logic; adopting them into the repo is a **strategy** decision. This feature makes the divergence **visible** (check 9) and leaves the call to the owner (D-DEP2).
- **It does not gate the trading cron yet** (D-DEP3) — wire `verify.sh` into the morning cycle only once it has proven stable, so a verification bug can't halt trading.

---

## 6. Verification of the verifier

The failure mode to guard against is **a verifier that passes vacuously.**

- **Negative tests are mandatory:** deliberately break each condition (remove a skill, drop a tool from its group, unregister a cron) and assert `verify.sh` **fails**. A verifier never seen to fail is not evidence.
- **Dry-run honesty:** `--dry-run` must perform real path resolution — a dry run that skips validation would have hidden this very bug.
- **Idempotency:** installing twice yields the same profile state.
- **Ordering:** verification runs *after* every mutation, never interleaved.
