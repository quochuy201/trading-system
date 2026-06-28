#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")"
# End‑of‑day review: run the eod‑review skill.
hermes -p trading -z "Run end‑of‑day review, generate compliance score and journal."