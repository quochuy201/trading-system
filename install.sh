#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
PLATFORM="${1:-}"

usage() {
    echo "Usage: ./install.sh <platform> [--dry-run]"
    echo ""
    echo "Platforms:"
    echo "  hermes   - Install as Hermes profile distribution"
    echo "  kermes   - Install skills + MCP config for Kermes"
    echo "  meshclaw - Generate MeshClaw agent specs"
    echo ""
    echo "Options:"
    echo "  --dry-run  Show what would be done without making changes"
    exit 1
}

DRY_RUN=false
for arg in "$@"; do
    [ "$arg" = "--dry-run" ] && DRY_RUN=true
done

log() { echo "[install] $*"; }
run() { if [ "$DRY_RUN" = true ]; then echo "[dry-run] $*"; else "$@"; fi; }

# Deploy the no-agent cron helper scripts into $1 with ABSOLUTE repo paths.
# Hermes resolves a bare `--script NAME.sh` relative to the owning profile's
# scripts/ dir, so these must live in each profile dir (not just the shared
# $HERMES_HOME/scripts) or every cron run fails "Script not found" and the
# daily data refresh silently never executes.
write_cron_scripts() {
    local dest="$1"
    if [ "$DRY_RUN" = true ]; then
        echo "[dry-run] write cron scripts to $dest/ (kanban-tick, data-refresh, iv-capture)"
        return
    fi
    mkdir -p "$dest"
    cat > "$dest/trading-kanban-tick.sh" <<'TICK'
#!/usr/bin/env bash
# Dispatch ready trading tasks (scheduled monitor/eod tasks + retries).
# Silent when nothing to do (cron --no-agent: empty stdout = no delivery).
# Cron runs with a minimal PATH that omits ~/.local/bin and homebrew, so
# `uv`/`hermes` resolve to "command not found" (exit 127) unless we add them.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
out=$(hermes kanban dispatch --board trading --max 3 --json 2>/dev/null)
spawned=$(printf '%s' "$out" | python3 -c 'import json,sys
try: print(len(json.load(sys.stdin).get("spawned", [])))
except Exception: print(0)' 2>/dev/null)
[ "${spawned:-0}" -gt 0 ] && echo "dispatched $spand trading task(s)"
exit 0
TICK
    cat > "$dest/trading-data-refresh.sh" <<REFRESH
#!/usr/bin/env bash
# Pre-market daily refresh of the universe's adjusted daily bars (single writer).
# Cron's minimal PATH omits ~/.local/bin, so a bare \`uv\` exits 127; prepend it.
set -euo pipefail
export PATH="\$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:\$PATH"
cd "$REPO_DIR/tools"
exec uv run python -c "from server import refresh_market_data; print(refresh_market_data(''))"
REFRESH
    cat > "$dest/trading-iv-capture.sh" <<IVCAP
#!/usr/bin/env bash
# Daily IV-rank accrual capture across the universe.
# Cron's minimal PATH omits ~/.local/bin, so a bare \`uv\` exits 127; prepend it.
set -euo pipefail
export PATH="\$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:\$PATH"
cd "$REPO_DIR/tools"
exec uv run python -c "from server import capture_iv_universe; print(capture_iv_universe(''))"
IVCAP
    chmod +x "$dest"/trading-kanban-tick.sh "$dest"/trading-data-refresh.sh "$dest"/trading-iv-capture.sh
}

install_hermes() {
    # Single profile design with asset‑asset‑class separation.
    local HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

    # 1. Create the single trading profile directory.
    local PROFILE_DIR="${HERMES_HOME}/profiles/trading"
    log "Creating profile trading at ${PROFILE_DIR}"
    run mkdir -p "${PROFILE_DIR}"

    # 2. Populate profile from deploy/.
    run cp "${REPO_DIR}/deploy/profile.yaml" "${PROFILE_DIR}/config.yaml"
    run cp "${REPO_DIR}/deploy/SOUL.md" "${PROFILE_DIR}/SOUL.md"
    run cp "${REPO_DIR}/OPERATING_MANUAL.md" "${PROFILE_DIR}/OPERATING_MANUAL.md"
    run hermes profile default trading >/dev/null 2>&1 || true

    # 3. Copy all scripts (workers load only what their task specifies).
    run mkdir -p "${PROFILE_DIR}/scripts"
    # Copy cron scripts from deploy/cron/
    for script in launch-equity.sh launch-options.sh trading-data-refresh.sh trading-iv-capture.sh monitor-sentinel.sh eod.sh; do
        run cp "${REPO_DIR}/deploy/cron/$script" "${PROFILE_DIR}/scripts/$script"
        run chmod +x "${PROFILE_DIR}/scripts/$script"
    done
    # Copy preflight.sh from deploy/
    run cp "${REPO_DIR}/deploy/preflight.sh" "${PROFILE_DIR}/scripts/preflight.sh"
    run chmod +x "${PROFILE_DIR}/scripts/preflight.sh"

    # 4. Copy all SOPs.
    run mkdir -p "${PROFILE_DIR}/sops"
    run cp -R "${REPO_DIR}/sops/." "${PROFILE_DIR}/sops/"

    # 5. Deploy cron scripts to shared scripts/.
    run mkdir -p "${HERMES_HOME}/scripts"
    # Copy cron scripts from deploy/cron/
    for script in launch-equity.sh launch-options.sh trading-data-refresh.sh trading-iv-capture.sh monitor-sentinel.sh eod.sh; do
        run cp "${REPO_DIR}/deploy/cron/$script" "${HERMES_HOME}/scripts/$script"
        run chmod +x "${HERMES_HOME}/scripts/$script"
    done
    # Copy preflight.sh from deploy/
    run cp "${REPO_DIR}/deploy/preflight.sh" "${HERMES_HOME}/scripts/preflight.sh"
    run chmod +x "${HERMES_HOME}/scripts/preflight.sh"

    # 6. Register MCP server (all tools exposed).
    log "Registering MCP server (all tools) for profile trading"
    run hermes -p trading mcp remove trading-tools >/dev/null 2>&1 || true
    # No TRADING_TOOL_GROUPS env var -> every tool exposed.
    printf 'y\n' | run hermes -p trading mcp add trading-tools \
        --command "${REPO_DIR}/tools/run_mcp.sh"

    # 7. Ensure kanban boards exist.
    log "Ensuring kanban boards equity and options exist"
    run hermes kanban boards create equity >/dev/null 2>&1 || true
    run hermes kanban boards create options >/dev/null 2>&1 || true

    # 8. Install cron jobs from deploy/runs/*.yaml.
    #    Helper: install a cron job.
    #    Usage: install_cron <name> <schedule> <script_name>
    #    where script_name is the bare script name (without path) that exists in ~/.hermes/scripts/
    install_cron() {
        local name="$1"
        local schedule="$2"
        local script="$3"
        if [ "${DRY_RUN}" = true ]; then
            echo "[dry-run] hermes cron create '${schedule}' --name '${name}' --script '${script}' --no-agent"
        else
            # Remove existing job with same name (idempotent)
            hermes cron delete "${name}" >/dev/null 2>&1 || true
            hermes cron create "${schedule}" --name "${name}" --script "${script}" --no-agent
        fi
    }

    # 9. Asset‑specific morning crons (run preflight then launch).
    #    Equity: 6:35 AM PT
    install_cron "trading-equity-morning" "35 6 * * 1-5" "launch-equity.sh"
    #    Options: 6:40 AM PT
    install_cron "trading-options-morning" "40 6 * * 1-5" "launch-options.sh"

    # 10. Shared‑service crons.
    #    Data refresh: 6:15 AM PT
    install_cron "trading-data-refresh" "15 6 * * 1-5" "trading-data-refresh.sh"
    #    IV capture: 1:05 PM PT
    install_cron "trading-iv-capture" "5 13 * * 1-5" "trading-iv-capture.sh"
    #    Monitor sentinel: every minute during market hours
    install_cron "trading-monitor-sentinel" "* 6-13 * * 1-5" "monitor-sentinel.sh"
    #    EOD review: 1:15 PM PT
    install_cron "trading-eod" "15 13 * * 1-5" "eod.sh"

    # 11. (Optional) Start/restart the gateway so the dispatcher is active.
    if [ "${DRY_RUN}" = true ]; then
        echo "[dry-run] hermes gateway start"
    else
        hermes gateway start >/dev/null 2>&1 || true
    fi

    # 12. Run preflight and show status.
    log "Running preflight check..."
    if run "${PROFILE_DIR}/scripts/preflight.sh"; then
        log "✅ Passed – system ready."
    else
        log "❌ Failed – see above for remediation."
    fi

    # 13. Remove legacy profiles (after new profile is fully configured).
    log "Removing legacy profiles..."
    for legacy in system orchestrator researcher trader monitor risk eod backtest; do
        local PROFILE="trading-${legacy}"
        log "Removing legacy profile $PROFILE"
        run hermes profile delete "$PROFILE" || true
    done
}

install_kermes() {
    local KERMES_HOME="${KERMES_HOME:-$HOME/.kermes}"
    local SKILLS_DIR="$KERMES_HOME/skills"

    log "Installing skills into Kermes at $SKILLS_DIR"

    # Link each skill directory (includes reference/ subdirs)
    for skill_dir in "$REPO_DIR/skills"/*/; do
        local name
        name=$(basename "$skill_dir")
        log "  Linking skill: $name"
        run ln -sfn "$skill_dir" "$SKILLS_DIR/$name"
    done

    # Link SOPs into kermes home for agent access
    run mkdir -p "$KERMES_HOME/trading-sops"
    run ln -sfn "$REPO_DIR/sops" "$KERMES_HOME/trading-sops/sops"

    log ""
    log "Done. Next steps:"
    log "  1. Start tools: cd $REPO_DIR/tools && uv run server.py"
    log "  2. Or add MCP to ~/.kermes config (see mcp.json)"
    log "  3. Run: kermes"
    log ""
    log "Skills installed: $(ls -1 "$REPO_DIR/skills" | wc -l)"
}

install_meshclaw() {
    local MC_HOME="${HOME}/.meshclaw/agents/trading-system"
    local KIRO_AGENTS="${HOME}/.kiro/agents"

    log "Installing for MeshClaw at $MC_HOME"

    run mkdir -p "$MC_HOME/skills"
    run cp "$REPO_DIR/SOUL.md" "$MC_HOME/SKILL.md"
    run cp -r "$REPO_DIR/skills"/* "$MC_HOME/skills/"
    run cp -r "$REPO_DIR/sops" "$MC_HOME/sops"

    # Generate agent spec
    local SPEC="$KIRO_AGENTS/trading-system.json"
    if [ "$DRY_RUN" = true ]; then
        echo "[dry-run] Would create $SPEC"
    else
        cat > "$SPEC" << EOF
{
  "name": "trading-system",
  "description": "Multi-agent autonomous trading system",
  "prompt": "file://$MC_HOME/SKILL.md",
  "model": "claude-sonnet-4-20250514",
  "mcpServers": {
    "trading-tools": {
      "command": "uv",
      "args": ["run", "--directory", "$REPO_DIR/tools", "server.py"]
    }
  },
  "resources": [
    "file://$MC_HOME/skills/research/SKILL.md",
    "file://$MC_HOME/skills/trader/SKILL.md",
    "file://$MC_HOME/skills/monitor/SKILL.md"
  ]
}
EOF
        log "  Created agent spec: $SPEC"
    fi

    log "Done. Run: kiro-cli chat --agent trading-system"
}

# --- Main ---
[ -z "$PLATFORM" ] || [ "$PLATFORM" = "--help" ] || [ "$PLATFORM" = "-h" ] && usage

case "$PLATFORM" in
    hermes)   install_hermes ;;
    kermes)   install_kermes ;;
    meshclaw) install_meshclaw ;;
    --dry-run) usage ;;
    *) echo "Unknown platform: $PLATFORM"; usage ;;
esac