#!/usr/bin/env bash
# preflight.sh - Mechanical health gate that runs before each trading cycle
# Exits with code 0 if all checks pass, non-zero if any check fails
# On failure, prints actionable remediation and exits without creating kanban graph

set -euo pipefail

# Configuration
CONFIG_FILE="${0%/*}/../profile.yaml"
TIMEOUT=10
LOG_FILE="${0%/*}/preflight.log"

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# Error handling
fail() {
    log "❌ PREFLIGHT FAILED: $1"
    echo "🔧 REMEDIATION: $2"
    exit 1
}

success() {
    log "✅ PREFLIGHT PASSED: $1"
}

# Clear log file at start
: > "$LOG_FILE"

log "Starting preflight health check..."

# 1. Check model auth resolves
log "1. Checking model authentication..."
if ! hermes model check 2>/dev/null; then
    fail "Model authentication failed" "Run: hermes model login"
fi
success "Model authentication valid"

# 2. Check Alpaca keys load and account reachable
log "2. Checking Alpaca connectivity..."
if ! hermes broker ping 2>/dev/null; then
    fail "Alpaca connection failed" "Check ALPACA_API_KEY and ALPACA_SECRET_KEY in .env"
fi
success "Alpaca connection successful"

# 3. Check data freshness within tolerance
log "3. Checking data freshness..."
# Check if we have recent daily bar data (within last 2 trading days)
if ! hermes data check-freshness --max-age-hours 48 2>/dev/null; then
    fail "Market data is stale" "Run: ./tools/trading-data-refresh.sh to refresh universe data"
fi
success "Market data is fresh"

# 4. Check kill-switch state
log "4. Checking kill-switch state..."
if hermes kill-switch status | grep -q "ACTIVE"; then
    fail "Kill switch is ACTIVE" "Review emergency situation, then run: hermes kill-switch disable"
fi
success "Kill switch is inactive (trading allowed)"

# 5. Check delivery channel reachable
log "5. Checking delivery channel..."
if ! hermes notification test --discord 2>/dev/null; then
    fail "Discord notification failed" "Check DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID in .env"
fi
success "Delivery channel reachable"

# All checks passed
log "🎉 All preflight checks passed - proceeding with cycle creation"
exit 0