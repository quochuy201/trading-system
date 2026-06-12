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

install_hermes() {
    # Kanban multi-profile layout (v2): one lean orchestrator + five worker
    # profiles. Each worker loads ONLY its skill and a role-scoped MCP tool
    # set (TRADING_TOOL_GROUPS gates registration in tools/server.py) — this
    # replaces the monolithic profile whose all-skills/all-tools startup was
    # slow and which never had its MCP server registered (mcp.json is not
    # read by Hermes; servers must be added via `hermes mcp add`).
    local HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
    local ROLES="orchestrator research trader monitor risk eod"

    for role in $ROLES; do
        local PROFILE="trading-$role"
        local PROFILE_DIR="$HERMES_HOME/profiles/$PROFILE"
        log "Installing profile $PROFILE"
        run mkdir -p "$PROFILE_DIR"
        run cp "$REPO_DIR/hermes/profiles/$role/SOUL.md" "$PROFILE_DIR/SOUL.md"
        run cp "$REPO_DIR/OPERATING_MANUAL.md" "$PROFILE_DIR/OPERATING_MANUAL.md"

        if [ "$role" != "orchestrator" ]; then
            # one skill per worker (merge-copy: trailing /. avoids nesting)
            local SKILL_SRC_NAME="$role"
            [ "$role" = "risk" ] && SKILL_SRC_NAME="risk-manager"
            [ "$role" = "eod" ] && SKILL_SRC_NAME="eod-review"
            run mkdir -p "$PROFILE_DIR/skills/$SKILL_SRC_NAME"
            run cp -R "$REPO_DIR/skills/$SKILL_SRC_NAME/." "$PROFILE_DIR/skills/$SKILL_SRC_NAME/"
            # research/trader/monitor/risk consult SOPs; eod does not
            if [ "$role" != "eod" ]; then
                run mkdir -p "$PROFILE_DIR/sops"
                run cp -R "$REPO_DIR/sops/." "$PROFILE_DIR/sops/"
            fi
            # role-scoped MCP registration (idempotent: remove then add).
            # HERMES_PROFILE targets the profile; the launcher script avoids
            # `--args` (argparse rejects dash-prefixed values like --directory).
            local GROUP="$role"
            if [ "$DRY_RUN" = true ]; then
                echo "[dry-run] HERMES_PROFILE=$PROFILE hermes mcp add trading-tools (TRADING_TOOL_GROUPS=$GROUP)"
            else
                hermes -p "$PROFILE" mcp remove trading-tools >/dev/null 2>&1 || true
                # `mcp add` interactively asks "Enable all N tools?" — answer yes
                printf 'y\n' | hermes -p "$PROFILE" mcp add trading-tools \
                    --command "$REPO_DIR/tools/run_mcp.sh" \
                    --env "TRADING_TOOL_GROUPS=$GROUP"
            fi
        fi
    done

    # Shared kanban board + dispatcher ticker script
    if [ "$DRY_RUN" = true ]; then
        echo "[dry-run] hermes kanban init && boards create trading"
        echo "[dry-run] install ~/.hermes/scripts/trading-kanban-tick.sh"
    else
        hermes kanban init >/dev/null 2>&1 || true
        hermes kanban boards create trading >/dev/null 2>&1 || true
        mkdir -p "$HERMES_HOME/scripts"
        cat > "$HERMES_HOME/scripts/trading-kanban-tick.sh" <<'TICK'
#!/usr/bin/env bash
# Dispatch ready trading tasks (scheduled monitor/eod tasks + retries).
# Silent when nothing to do (cron --no-agent: empty stdout = no delivery).
out=$(hermes kanban dispatch --board trading --max 3 --json 2>/dev/null)
spawned=$(printf '%s' "$out" | python3 -c 'import json,sys
try: print(len(json.load(sys.stdin).get("spawned", [])))
except Exception: print(0)' 2>/dev/null)
[ "${spawned:-0}" -gt 0 ] && echo "dispatched $spawned trading task(s)"
exit 0
TICK
        chmod +x "$HERMES_HOME/scripts/trading-kanban-tick.sh"
    fi

    log "Done. Next steps:"
    log "  1. Ensure .env at repo root has ALPACA keys (server.py loads it)"
    log "  2. Register cron jobs (see cron/README-kanban.md):"
    log "       hermes cron create '35 9 * * 1-5' --name trading-morning ..."
    log "  3. Smoke test a worker: hermes -p trading-research -z 'list your tools'"
    log "  4. Morning cycle manually: hermes -p trading-orchestrator chat"
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
