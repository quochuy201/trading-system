#!/usr/bin/env bash
# Verify a deployed Hermes profile actually works.
#
# The installer fix was ten minutes; this is the feature. Five options MCP tools
# sat present-but-unreachable for 34 sessions because every check anyone ran
# asked "is the file there?" instead of "can the agent call it?". So the rule
# here is: CHECK REACHABILITY, NOT PRESENCE.
#
# Checks 1-8 fail the run (exit 1). Check 9 only warns: runtime-only skills are
# the sole running options logic and deleting them would be worse than the
# divergence (D-DEP2).
#
# Usage:
#   ./verify.sh hermes [--profile trading] [--hermes-home DIR] [--repo-root DIR]
set -uo pipefail

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$DEPLOY_DIR/../.." && pwd)"
PLATFORM="${1:-}"
PROFILE="trading"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
MCP_SERVER="trading-tools"

# The five tools whose silent unreachability is the reason this script exists
# (deployment-design.md §3, check 3).
OPTIONS_TOOLS="get_options_chain get_options_market_data calc_iv_rank get_put_skew calc_expected_move"

usage() {
    echo "Usage: ./verify.sh hermes [--profile NAME] [--hermes-home DIR] [--repo-root DIR]"
    exit 2
}

shift || true
while [ $# -gt 0 ]; do
    case "$1" in
        --profile)     PROFILE="$2"; shift 2 ;;
        --hermes-home) HERMES_HOME="$2"; shift 2 ;;
        --repo-root)   REPO_ROOT="$(cd "$2" && pwd)"; shift 2 ;;
        --server)      MCP_SERVER="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done
[ "$PLATFORM" = "hermes" ] || usage

PROFILE_DIR="${HERMES_HOME}/profiles/${PROFILE}"
PY="${REPO_ROOT}/tools/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
PROBE="${DEPLOY_DIR}/mcp_probe.py"

FAILURES=0
pass() { printf '  ok   %s\n' "$*"; }
fail() { printf '  FAIL %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
warn() { printf '  warn %s\n' "$*"; }

echo "Verifying profile '${PROFILE}' at ${PROFILE_DIR}"
echo "  repo: ${REPO_ROOT}"

# ── 1. MCP server responds ──────────────────────────────────────────────────
# Spawns the command the profile registered and completes a real handshake, so
# the launcher, the venv and any TRADING_TOOL_GROUPS gating are all exercised.
echo "[1] MCP server responds"
REACHABLE=""
PROBE_OUT="$("$PY" "$PROBE" --config "${PROFILE_DIR}/config.yaml" --server "$MCP_SERVER" 2>/dev/null)"
if [ -z "$PROBE_OUT" ]; then
    fail "probe produced no output (is ${PY} usable?)"
elif ! printf '%s' "$PROBE_OUT" | "$PY" -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("ok") else 1)'; then
    fail "$(printf '%s' "$PROBE_OUT" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("error","unknown error"))')"
else
    REACHABLE="$(printf '%s' "$PROBE_OUT" | "$PY" -c 'import json,sys; print(" ".join(json.load(sys.stdin)["tools"]))')"
    pass "handshake completed, $(printf '%s' "$REACHABLE" | wc -w | tr -d ' ') tools reachable"
fi

# ── 2. Expected tools reachable ─────────────────────────────────────────────
# Expected = what the REPO's server exposes under the same registration env.
# The runtime runs its own copy of tools/, so this is a repo-vs-runtime diff:
# it answers "is the deployed profile running current code?". Never a
# hardcoded tool count (RULE 3).
echo "[2] Expected tools reachable"
if [ -z "$REACHABLE" ]; then
    fail "skipped — no MCP connection"
else
    REG_ENV="$("$PY" -c '
import sys, yaml
cfg = yaml.safe_load(open(sys.argv[1])) or {}
entry = (cfg.get("mcp_servers") or {}).get(sys.argv[2]) or {}
for k, v in (entry.get("env") or {}).items():
    print(f"{k}={v}")
' "${PROFILE_DIR}/config.yaml" "$MCP_SERVER" 2>/dev/null)"

    ENV_ARGS=()
    while IFS= read -r pair; do
        [ -n "$pair" ] && ENV_ARGS+=(--env "$pair")
    done <<< "$REG_ENV"

    EXPECTED_OUT="$("$PY" "$PROBE" --command "${REPO_ROOT}/tools/run_mcp.sh" ${ENV_ARGS[@]+"${ENV_ARGS[@]}"} 2>/dev/null)"
    if ! printf '%s' "$EXPECTED_OUT" | "$PY" -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("ok") else 1)' 2>/dev/null; then
        fail "could not enumerate the repo's own tools to compare against"
    else
        MISSING="$(printf '%s\n%s' "$EXPECTED_OUT" "$PROBE_OUT" | "$PY" -c '
import json, sys
expected, actual = (json.loads(line) for line in sys.stdin.read().splitlines() if line.strip())
print(" ".join(sorted(set(expected["tools"]) - set(actual["tools"]))))')"
        EXTRA="$(printf '%s\n%s' "$EXPECTED_OUT" "$PROBE_OUT" | "$PY" -c '
import json, sys
expected, actual = (json.loads(line) for line in sys.stdin.read().splitlines() if line.strip())
print(" ".join(sorted(set(actual["tools"]) - set(expected["tools"]))))')"
        if [ -n "$MISSING" ]; then
            fail "defined in the repo but NOT reachable: ${MISSING}"
        else
            pass "every tool the repo defines is reachable"
        fi
        [ -n "$EXTRA" ] && warn "runtime exposes tools absent from the repo: ${EXTRA}"
    fi
fi

# ── 3. Options tools specifically ───────────────────────────────────────────
echo "[3] Options tools reachable"
if [ -z "$REACHABLE" ]; then
    fail "skipped — no MCP connection"
else
    missing_opts=""
    for tool in $OPTIONS_TOOLS; do
        case " $REACHABLE " in *" $tool "*) ;; *) missing_opts="$missing_opts $tool" ;; esac
    done
    if [ -n "$missing_opts" ]; then
        fail "options tools unreachable:${missing_opts}"
    else
        pass "all 5 options tools reachable"
    fi
fi

# ── 4. Skills present, and their declared tools reachable ───────────────────
# A skill promising a tool the agent cannot call is the skill-tool-contract bug.
echo "[4] Skill contracts satisfied"
if [ -z "$REACHABLE" ]; then
    fail "skipped — no MCP connection"
else
    if ! SKILL_REPORT="$("$PY" -c '
import re, sys
from pathlib import Path

profile_skills, repo_skills, reachable = Path(sys.argv[1]), Path(sys.argv[2]), set(sys.argv[3].split())
problems = []
for skill_md in sorted(repo_skills.glob("*/SKILL.md")):
    name = skill_md.parent.name
    if not (profile_skills / name / "SKILL.md").exists():
        problems.append("skill missing from profile: " + name)
        continue
    match = re.search(r"requires_tools:\s*\[(.*?)\]", skill_md.read_text(), re.S)
    if not match:
        continue
    declared = {t.strip() for t in match.group(1).split(",") if t.strip()}
    unreachable = sorted(declared - reachable)
    if unreachable:
        problems.append(name + " declares unreachable tools: " + ", ".join(unreachable))
print("\n".join(problems))
' "${PROFILE_DIR}/skills" "${REPO_ROOT}/skills" "$REACHABLE")"; then
        # A check that cannot run must never report ok — that is the vacuous
        # pass this whole script exists to make impossible.
        fail "skill-contract check could not run"
    elif [ -n "$SKILL_REPORT" ]; then
        while IFS= read -r line; do [ -n "$line" ] && fail "$line"; done <<< "$SKILL_REPORT"
    else
        pass "every skill's requires_tools is reachable"
    fi
fi

# ── 5. Crons registered with resolvable script paths ────────────────────────
# Hermes resolves a bare `--script NAME.sh` against the profile's scripts dir.
# Getting that wrong is what made the data refresh silently never run (06-23).
echo "[5] Crons registered and their scripts resolvable"
JOBS_FILE="${PROFILE_DIR}/cron/jobs.json"
if [ ! -f "$JOBS_FILE" ]; then
    fail "no cron job store at ${JOBS_FILE} — nothing is scheduled"
else
    if ! CRON_REPORT="$("$PY" -c '
import json, sys
from pathlib import Path

jobs_file, scripts_dir = Path(sys.argv[1]), Path(sys.argv[2])
jobs = (json.loads(jobs_file.read_text()) or {}).get("jobs") or []
if not jobs:
    print("cron job store is empty - nothing is scheduled")
for job in jobs:
    script = job.get("script")
    if script and not (scripts_dir / script).exists():
        name = job.get("name")
        print("cron " + repr(name) + " -> script not found: " + str(scripts_dir / script))
' "$JOBS_FILE" "${PROFILE_DIR}/scripts")"; then
        fail "cron check could not run"
    elif [ -n "$CRON_REPORT" ]; then
        while IFS= read -r line; do [ -n "$line" ] && fail "$line"; done <<< "$CRON_REPORT"
    else
        pass "all registered cron scripts resolve"
    fi
fi

# ── 6. Kanban boards exist ──────────────────────────────────────────────────
# Board names come from setup/deploy/runs/*.yaml, their one home (RULE 3).
echo "[6] Kanban boards exist"
BOARDS="$("$PY" -c '
import sys, yaml
from pathlib import Path
for run in sorted(Path(sys.argv[1]).glob("*.yaml")):
    if run.name.startswith("_"):
        continue
    board = (yaml.safe_load(run.read_text()) or {}).get("board")
    if board:
        print(board)
' "${DEPLOY_DIR}/runs" 2>/dev/null)"
if [ -z "$BOARDS" ]; then
    fail "no boards declared in ${DEPLOY_DIR}/runs/*.yaml"
else
    for board in $BOARDS; do
        board_db="${HERMES_HOME}/kanban/boards/${board}/kanban.db"
        if [ ! -f "$board_db" ]; then
            fail "board '${board}' missing (${board_db})"
        elif ! sqlite3 "$board_db" "select 1 from tasks limit 1" >/dev/null 2>&1; then
            fail "board '${board}' has no tasks table — the dispatcher would no-op"
        else
            pass "board '${board}' present"
        fi
    done
fi

# ── 7. OPERATING_MANUAL.md present ──────────────────────────────────────────
# The risk constitution. An agent running without it has no limits.
echo "[7] OPERATING_MANUAL.md deployed"
if [ -f "${PROFILE_DIR}/OPERATING_MANUAL.md" ]; then
    pass "present"
else
    fail "missing from ${PROFILE_DIR} — the agent has no risk constitution"
fi

# ── 8. Provenance stamp current ─────────────────────────────────────────────
echo "[8] Provenance stamp matches the repo"
STAMP="${PROFILE_DIR}/PROVENANCE.md"
if [ ! -f "$STAMP" ]; then
    fail "no provenance stamp — cannot tell which commit the runtime came from"
else
    HEAD_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null)"
    STAMP_SHA="$(sed -n 's/.*\*\*Git SHA:\*\* *\([0-9a-f]*\).*/\1/p' "$STAMP" | head -1)"
    if [ -z "$STAMP_SHA" ]; then
        fail "provenance stamp has no Git SHA"
    elif [ "$STAMP_SHA" != "$HEAD_SHA" ]; then
        fail "runtime is stale: deployed ${STAMP_SHA:0:8}, repo is at ${HEAD_SHA:0:8}"
    else
        pass "runtime matches ${HEAD_SHA:0:8}"
    fi
fi

# ── 9. Runtime-only skills (WARN — never fail, never delete) ────────────────
# options-trader / options-exit-manager exist only in the runtime and are the
# only running options logic. Surface the divergence; the call is the owner's.
echo "[9] Runtime-only skills (warn only)"
if [ -d "${PROFILE_DIR}/skills" ]; then
    found_divergence=0
    for skill_dir in "${PROFILE_DIR}/skills"/*/; do
        [ -d "$skill_dir" ] || continue
        name="$(basename "$skill_dir")"
        if [ ! -d "${REPO_ROOT}/skills/${name}" ]; then
            found_divergence=1
            tools_ref="$(sed -n 's/.*requires_tools:\s*\[\(.*\)\].*/\1/p' "${skill_dir}SKILL.md" 2>/dev/null | head -1)"
            warn "runtime-only skill '${name}' has no repo counterpart (declares: ${tools_ref:-none})"
        fi
    done
    [ "$found_divergence" -eq 0 ] && pass "no runtime-only skills"
else
    warn "no skills directory in the profile"
fi

echo
if [ "$FAILURES" -gt 0 ]; then
    echo "❌ verification FAILED — ${FAILURES} check(s) failed"
    exit 1
fi
echo "✅ verification passed"
