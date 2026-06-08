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
    local HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
    local PROFILE_DIR="$HERMES_HOME/profiles/trading-system"

    log "Installing as Hermes profile at $PROFILE_DIR"

    run mkdir -p "$PROFILE_DIR"
    run cp "$REPO_DIR/SOUL.md" "$PROFILE_DIR/SOUL.md"
    # OPERATING_MANUAL.md is the constitution SOUL.md says to READ FIRST — the
    # agent is non-functional without it. Must be installed alongside SOUL.md.
    run cp "$REPO_DIR/OPERATING_MANUAL.md" "$PROFILE_DIR/OPERATING_MANUAL.md"
    run cp "$REPO_DIR/config.yaml" "$PROFILE_DIR/config.yaml"
    run cp "$REPO_DIR/mcp.json" "$PROFILE_DIR/mcp.json"
    run cp "$REPO_DIR/distribution.yaml" "$PROFILE_DIR/distribution.yaml"
    run cp "$REPO_DIR/.env.EXAMPLE" "$PROFILE_DIR/.env.EXAMPLE"
    # Copy directory *contents* (trailing /.) so our skills/sops/cron overwrite
    # in place when the profile already exists. A plain `cp -r src dst` nests as
    # dst/src when dst pre-exists (e.g. a live Curator-managed profile), leaving
    # the files Hermes actually loads stale. Merge-copy preserves other skills.
    run mkdir -p "$PROFILE_DIR/skills" "$PROFILE_DIR/sops" "$PROFILE_DIR/cron"
    run cp -R "$REPO_DIR/skills/." "$PROFILE_DIR/skills/"
    run cp -R "$REPO_DIR/sops/." "$PROFILE_DIR/sops/"
    run cp -R "$REPO_DIR/cron/." "$PROFILE_DIR/cron/"

    log "Done. Next steps:"
    log "  1. cp $PROFILE_DIR/.env.EXAMPLE $PROFILE_DIR/.env && edit .env"
    log "  2. Start tools: cd $REPO_DIR/tools && uv run server.py"
    log "  3. Run: hermes -p trading-system chat"
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
