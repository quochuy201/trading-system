"""End-to-end smoke test: hit Alpaca paper with the options MCP tool functions.

Run from tools/: uv run python scripts/smoke_test_options.py SYMBOL
Default symbol: AAPL.
"""

import json
import sys
import os
from pathlib import Path

# Load .env (same way server.py does)
_env_file = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def _section(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def _truncate(s: str, n: int = 400) -> str:
    return s if len(s) <= n else s[:n] + f"\n... [truncated, {len(s)} chars total]"


def main() -> int:
    symbol = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(f"Smoke testing options MCP tools against Alpaca paper for {symbol}")

    # Import inside main so .env loads first
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from server import (
        get_account,
        get_market_data,
        get_options_chain,
        get_options_market_data,
        get_options_positions,
        calc_iv_rank,
        calc_hv,
        get_put_skew,
        calc_expected_move,
    )

    _section("0. Account check")
    print(get_account())

    _section(f"1. get_market_data({symbol})")
    md = get_market_data(symbol)
    print(md)
    md_data = json.loads(md)
    if "error" in md_data:
        print("ABORT: cannot get underlying quote")
        return 1
    stock_price = md_data.get("mid", 0)

    _section(f"2. calc_hv({symbol}, window=20)")
    print(calc_hv(symbol, 20))

    _section(f"3. get_options_chain({symbol}) — limited to ATM ± $20, 21–60 DTE")
    from datetime import date, timedelta
    today = date.today()
    chain_json = get_options_chain(
        underlying=symbol,
        expiration_gte=(today + timedelta(days=21)).isoformat(),
        expiration_lte=(today + timedelta(days=60)).isoformat(),
        strike_gte=stock_price - 20,
        strike_lte=stock_price + 20,
        option_type=None,
    )
    print(_truncate(chain_json, 1200))
    chain = json.loads(chain_json) if not chain_json.startswith('{"error"') else []
    if not chain:
        print("ABORT: no chain data")
        return 1
    print(f"  → got {len(chain)} contracts")

    # Pick a single near-ATM call to snapshot
    calls = [c for c in chain if c.get("type") == "call"]
    calls.sort(key=lambda c: abs(c.get("strike", 0) - stock_price))
    if calls:
        atm_sym = calls[0]["symbol"]
        _section(f"4. get_options_market_data('{atm_sym}')")
        print(get_options_market_data(atm_sym))

    _section(f"5. calc_iv_rank({symbol})")
    print(calc_iv_rank(symbol))

    # Pick a single expiration for skew test (chain has YYMMDD; convert to ISO)
    expirations = sorted({c["expiration"] for c in chain if "expiration" in c})
    if expirations:
        yymmdd = expirations[len(expirations) // 2]  # e.g. "260710"
        target_exp = f"20{yymmdd[:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}"  # → "2026-07-10"
        _section(f"6. get_put_skew({symbol}, {target_exp}, 0.25)")
        print(get_put_skew(symbol, target_exp, 0.25))

    _section(f"7. calc_expected_move({symbol}, 30)")
    print(calc_expected_move(symbol, 30))

    _section("8. get_options_positions()")
    print(get_options_positions())

    print("\n✅ Smoke test complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
