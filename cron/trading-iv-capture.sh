#!/usr/bin/env bash
# Daily after-close ATM IV30 capture for the universe → iv_history (per-name IVR accrual).
# Heavy (one chain fetch per name); the watchlist may be narrowed later for cost.
set -euo pipefail
cd "$(dirname "$0")/../tools"
exec uv run python -c "from server import capture_iv_universe; print(capture_iv_universe(''))"
