#!/usr/bin/env bash
# Pre-market daily refresh of the existing universe's adjusted daily bars (single writer).
# Light path: refreshes the ~400-symbol universe, does NOT re-derive it.
set -euo pipefail
cd "$(dirname "$0")/../tools"
exec uv run python -c "from server import refresh_market_data; print(refresh_market_data(''))"
