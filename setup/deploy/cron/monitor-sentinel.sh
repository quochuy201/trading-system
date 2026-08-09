#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")"
# Monitor sentinel: lightweight check that wakes LLM monitor only on triggers.
# We run the monitor skill via hermes -z; it will perform its internal two‑tier
# logic (tool‑only first, LLM only if needed).
hermes -p trading -z "Monitor open positions and execute any exits per your monitoring skill."