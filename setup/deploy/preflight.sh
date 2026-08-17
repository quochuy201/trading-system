#!/usr/bin/env bash
# preflight.sh - Mechanical health gate that runs before each trading cycle
# Exits with code 0 if all checks pass, non-zero if any check fails
# On failure, prints actionable remediation and exits without creating kanban graph
#
# Checks are real, not imagined:
#   1. Model auth   -> `hermes -z` round-trip; the agent must actually answer
#   2. Alpaca       -> keys present + get_account() round-trip via tools layer
#   3. Data fresh   -> MAX(timestamp) in price_data within 4 days (Fri->Mon + holiday)
#   4. Kill switch  -> check_kill_switch() from server.py, must be inactive
#
# NO CHECK MAY NAME A VENDOR'S CREDENTIAL. Provider and delivery channel both
# change -- this file once asserted DEEPSEEK_API_KEY while the profiles ran
# provider xai (whose credential is an OAuth token in auth.json, not a key in
# .env at all), and asserted DISCORD_BOT_TOKEN after delivery had moved to
# Telegram. A key-name grep is also a dead control: it passes while the token
# is revoked or the account is out of credits.
#
# So check 1 asks the runtime that OWNS the credential instead of guessing
# where it lives: `hermes -z` exits non-zero both when the agent raises and
# when no final response is produced (hermes_cli/oneshot.py). It stays correct
# across a provider change because it never names one.
#
# Delivery credentials are deliberately NOT checked: a missing notifier is a
# quiet cycle, not a wrong one, and there is no vendor-neutral way to ask.
#
# Tools layer lives INSIDE the profile (~/.hermes/profiles/<profile>/tools/),
# and server.py auto-loads <profile>/.env itself (parent.parent of tools/), so
# no manual key exporting is needed.
#
# The profile is resolved from HERMES_PROFILE if set (per-profile cron/gateway
# runs set it), else from the parent directory of this script when installed
# into a profile's scripts/ dir, else defaults to "trading".

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Determine the owning profile: env wins, then script location, then default.
if [ -n "${HERMES_PROFILE:-}" ]; then
    PROFILE_NAME="$HERMES_PROFILE"
elif [[ "$SCRIPT_DIR" == *"/profiles/"*"/scripts" ]]; then
    PROFILE_NAME="$(basename "$(dirname "$SCRIPT_DIR")")"
else
    PROFILE_NAME="trading"
fi

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PROFILE_DIR="$HERMES_HOME/profiles/$PROFILE_NAME"
TOOLS_DIR="$PROFILE_DIR/tools"
ENV_FILE="$PROFILE_DIR/.env"
LOG_FILE="$SCRIPT_DIR/preflight.log"
UV_BIN="${UV_BIN:-uv}"

# Prefer the venv interpreter the tools layer already ships. `uv run` can
# re-resolve dependencies, which needs the network and adds latency to a gate
# that runs before the market opens; run_mcp.sh avoids it for the same reason.
# Falls back to uv when the profile has no venv.
if [ -x "$TOOLS_DIR/.venv/bin/python" ]; then
    PY_RUN=("$TOOLS_DIR/.venv/bin/python")
else
    PY_RUN=("$UV_BIN" run python)
fi

# Logging
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }
fail() { log "❌ PREFLIGHT FAILED: $1"; echo "🔧 REMEDIATION: $2"; exit 1; }
success() { log "✅ PREFLIGHT PASSED: $1"; }

# Assert an env var is present AND non-empty in the profile .env.
# One definition rather than the same regex written out per key — and the
# key name stays a parameter, so nothing here looks like a literal secret.
require_env_key() {
    grep -qE "^$1=.+" "$ENV_FILE" || \
        fail "$1 missing or empty in $ENV_FILE" "Add $1 to $ENV_FILE"
}

: > "$LOG_FILE"
log "Starting preflight health check (profile: $PROFILE_NAME)..."

# 0. Prerequisites: tools layer + .env exist inside the profile
log "0. Checking profile prerequisites..."
[ -d "$TOOLS_DIR" ] || fail "Tools layer missing at $TOOLS_DIR" \
    "Run the installer from the repo: ./install.sh hermes (it owns that path, not this script)"
[ -f "$ENV_FILE" ] || fail "Profile .env missing" \
    "Create $ENV_FILE with ALPACA_API_KEY and ALPACA_SECRET_KEY (plus whatever the model provider and notifier need)"
[ -f "$TOOLS_DIR/trading.db" ] || fail "trading.db missing in tools layer" \
    "Re-copy tools layer from the repo (includes trading.db)"
success "Prerequisites present (tools layer + .env)"

# 1. Model auth -- ask the runtime that owns the credential.
#    Called directly, not through an indirection variable: there is exactly
#    one hermes on PATH and naming it twice invites drift.
log "1. Checking model authentication..."
if ! PROBE_OUT="$(hermes -p "$PROFILE_NAME" -z 'Reply with exactly: ok' 2>&1)"; then
    fail "Model auth failed: $(printf '%s' "$PROBE_OUT" | tr '\n' ' ' | tail -c 200)" \
        "Re-authenticate the provider, or check the account has credits and is under its spending limit"
fi
success "Model authentication valid (live round-trip)"

# 2. Alpaca keys present and account reachable
log "2. Checking Alpaca connectivity..."
require_env_key ALPACA_API_KEY
require_env_key ALPACA_SECRET_KEY

ACCT_OUT="$(cd "$TOOLS_DIR" && "${PY_RUN[@]}" -c "from server import get_account; print(get_account())" 2>&1)" || \
    fail "Alpaca connection failed" "Check ALPACA keys / network. Raw: $(echo "$ACCT_OUT" | tail -c 300)"
echo "$ACCT_OUT" | grep -q '"equity"' || \
    fail "Alpaca account response malformed" "Raw: $(echo "$ACCT_OUT" | tail -c 300)"
ACCT_EQUITY="$(printf '%s' "$ACCT_OUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('equity') or '?')" 2>/dev/null)"
success "Alpaca connection successful (equity: ${ACCT_EQUITY:-?})"

# 3. Data freshness within tolerance.
#    Last completed daily bar is Fri on Mon mornings (and up to +1 holiday),
#    so tolerate 4 days: 3-day weekend + holiday. The pre-market refresh at
#    06:15 keeps this well under in normal operation; this check only fires
#    when the refresh itself has been broken for multiple days.
log "3. Checking data freshness..."
MAX_TS="$(sqlite3 "$TOOLS_DIR/trading.db" "SELECT MAX(timestamp) FROM price_data WHERE timeframe='1Day';" 2>/dev/null || true)"
if [ -z "$MAX_TS" ] || [ "$MAX_TS" = "NULL" ]; then
    fail "Market data is stale (price_data empty)" \
        "Run: $SCRIPT_DIR/trading-data-refresh.sh"
fi
DATE_PART="${MAX_TS%%T*}"
DATE_PART="${DATE_PART%% *}"
if ! EPOCH="$(date -j -f "%Y-%m-%d" "$DATE_PART" +%s 2>/dev/null)"; then
    fail "Cannot parse last bar date '$MAX_TS'" "Inspect price_data.timestamp format"
fi
AGE_DAYS=$(( ( $(date +%s) - EPOCH ) / 86400 ))
if [ "$AGE_DAYS" -gt 4 ]; then
    fail "Market data is stale (last bar $DATE_PART, ${AGE_DAYS}d old)" \
        "Run: $SCRIPT_DIR/trading-data-refresh.sh"
fi
success "Market data is fresh (last bar $DATE_PART)"

# 4. Kill-switch state
log "4. Checking kill-switch state..."
KS_OUT="$(cd "$TOOLS_DIR" && "${PY_RUN[@]}" -c "from server import check_kill_switch; print(check_kill_switch())" 2>&1)" || \
    fail "Kill-switch check errored" "Raw: $(echo "$KS_OUT" | tail -c 300)"
echo "$KS_OUT" | grep -qE '"active": *true' && \
    fail "Kill switch is ACTIVE" "Review emergency, then clear the KILL_SWITCH file / state before resuming"
success "Kill switch is inactive (trading allowed)"

# All checks passed
log "🎉 All preflight checks passed - proceeding with cycle creation"
exit 0
