#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")"
PREFLIGHT="./preflight.sh"
if "$PREFLIGHT"; then
    TODAY=$(date +%Y-%m-%d)
    BOARD="equity"
    SOP_PATH="sops/equity"
    SCANNER_PROFILE="equity"
    # Create risk task
    RISK_ID=$(hermes kanban --board "$BOARD" create \"$TODAY 1-risk-regime\" --assignee trading --json --body "Assess market regime and set mode per OPERATING_MANUAL. Output: mode, eligible engines per $SOP_PATH/_routing, kill-switch state, account equity. Comment the full assessment on this task, then complete." | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id"))')
    # Create research task
    RESEARCH_ID=$(hermes kanban --board "$BOARD" create \"$TODAY 2-research-scan\" --assignee trading --json --body "Read 1-risk-regime task comments first (mode + eligible engines). If HALTED: comment 'halted, no scan' and complete. Otherwise scan per skills/research, run DD on candidates, and comment a ranked list: symbol, engine, score, full/half size, entry/stop/target params per the current SOP version, and the DD reasoning per candidate. Then complete." | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id"))')
    # Create trade task
    TRADE_ID=$(hermes kanban --board "$BOARD" create \"$TODAY 3-trade-exec\" --assignee trading --json --body "Read 2-research-scan task comments (candidate list). Validate each against risk caps (heat, position cap, daily limits) per OPERATING_MANUAL, then place orders for the approved ones with full trade plans saved. NEVER exceed caps; check kill switch before every order. Comment every order id / skip reason. Then complete." | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id"))')
    # Link tasks
    hermes kanban --board "$BOARD" link "$RISK_ID" "$RESEARCH_ID"
    hermes kanban --board "$BOARD" link "$RESEARCH_ID" "$TRADE_ID"
else
    echo "Preflight failed; aborting cycle creation."
    exit 1
fi