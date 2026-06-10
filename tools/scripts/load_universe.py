"""Criteria-based universe loader for swing backtests (NO fixed ticker list).

RUN LOCALLY (needs Alpaca keys in .env and internet):
    cd tools && uv run python scripts/load_universe.py
    # options:
    #   --max-symbols 400        cap (top by dollar volume)
    #   --daily-start 2025-01-02 --daily-end 2025-12-05

Selection criteria (mirrors sops/equity/swing v1.1.0 M-G2/R-G2):
  1. All ACTIVE, TRADABLE US equities on NYSE/NASDAQ/AMEX (Alpaca assets API)
     - excludes obvious funds (name contains ETF/Trust/Fund/Index) and SPY-like
       index products; SPY itself is loaded separately as the regime reference
  2. Liquidity gate measured on JUNE 2025 daily bars (predates every test
     window -> no look-ahead in the filter): avg close $10-500 AND
     20-day avg dollar volume >= $50M
  3. Cap at --max-symbols ranked by June dollar volume

KNOWN LIMITATION (documented, acceptable for now): the asset list is
"active today", so names delisted during 2025 are missing -> mild
survivorship bias. Revisit if results look too good.

Output:
  - daily bars for all selected symbols + SPY into trading.db
  - the selected universe written to tools/universe_backtest.json
    (committed, so backtests are reproducible)
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env from project root (same convention as server.py)
_env_file = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

PREFILTER_START = "2025-06-01"   # liquidity measured here — predates test windows
PREFILTER_END = "2025-06-30"
FUND_WORDS = ("ETF", "TRUST", "FUND", "INDEX", "SHARES OUTSTANDING", "ISHARES",
              "PROSHARES", "VANGUARD", "SPDR", "DIREXION")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-symbols", type=int, default=400)
    ap.add_argument("--daily-start", default="2025-01-02")
    ap.add_argument("--daily-end", default="2025-12-05")
    ap.add_argument("--batch", type=int, default=300)
    args = ap.parse_args()

    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import GetAssetsRequest
    from alpaca.trading.enums import AssetClass, AssetStatus
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from persistence.repository import Repository

    api_key = os.environ["ALPACA_API_KEY"]
    secret = os.environ["ALPACA_SECRET_KEY"]
    trading = TradingClient(api_key, secret, paper=True)
    data = StockHistoricalDataClient(api_key, secret)
    repo = Repository(str(Path(__file__).parent.parent / "trading.db"))

    # ---- Stage 1: candidate symbols from the assets API -------------------
    assets = trading.get_all_assets(GetAssetsRequest(
        status=AssetStatus.ACTIVE, asset_class=AssetClass.US_EQUITY))
    syms = []
    for a in assets:
        if not a.tradable:
            continue
        ex = str(a.exchange.value if hasattr(a.exchange, "value") else a.exchange)
        if ex not in ("NYSE", "NASDAQ", "AMEX", "ARCA"):
            continue
        name = (a.name or "").upper()
        if any(w in name for w in FUND_WORDS):
            continue
        s = a.symbol
        if not s.isalpha() or len(s) > 5 or s == "SPY":
            continue
        syms.append(s)
    print(f"Stage 1: {len(syms)} tradable US equities after fund/exchange filters")

    # ---- Stage 2: June-2025 liquidity prefilter (batched bars) ------------
    survivors = {}
    for i in range(0, len(syms), args.batch):
        chunk = syms[i:i + args.batch]
        try:
            bars = data.get_stock_bars(StockBarsRequest(
                symbol_or_symbols=chunk, timeframe=TimeFrame.Day,
                start=datetime.fromisoformat(PREFILTER_START),
                end=datetime.fromisoformat(PREFILTER_END)))
        except Exception as e:
            print(f"  batch {i//args.batch}: FAILED {e} — skipping")
            continue
        for sym in chunk:
            blist = bars.data.get(sym, [])
            if len(blist) < 15:
                continue
            closes = [b.close for b in blist]
            dvols = [b.close * b.volume for b in blist]
            avg_close = sum(closes) / len(closes)
            adv = sum(dvols) / len(dvols)
            if 10 <= avg_close <= 500 and adv >= 50_000_000:
                survivors[sym] = adv
        print(f"  batch {i//args.batch + 1}/{(len(syms)-1)//args.batch + 1}: "
              f"{len(survivors)} survivors so far")

    universe = sorted(survivors, key=survivors.get, reverse=True)[:args.max_symbols]
    print(f"Stage 2: {len(survivors)} pass liquidity gates; keeping top {len(universe)}")

    out = Path(__file__).parent.parent / "universe_backtest.json"
    out.write_text(json.dumps({
        "criteria": "price $10-500, ADV20 >= $50M, measured 2025-06 (pre-window)",
        "generated": datetime.utcnow().isoformat(),
        "count": len(universe), "symbols": universe,
    }, indent=1))
    print(f"Universe written to {out.name}")

    # ---- Stage 3: full daily history for universe + SPY -------------------
    to_load = universe + ["SPY"]
    total = 0
    for i in range(0, len(to_load), args.batch):
        chunk = to_load[i:i + args.batch]
        try:
            bars = data.get_stock_bars(StockBarsRequest(
                symbol_or_symbols=chunk, timeframe=TimeFrame.Day,
                start=datetime.fromisoformat(args.daily_start),
                end=datetime.fromisoformat(args.daily_end)))
        except Exception as e:
            print(f"  history batch {i//args.batch}: FAILED {e}")
            continue
        rows = []
        for sym, blist in bars.data.items():
            for b in blist:
                rows.append({
                    "symbol": sym, "timestamp": b.timestamp.isoformat(),
                    "open": float(b.open), "high": float(b.high),
                    "low": float(b.low), "close": float(b.close),
                    "volume": float(b.volume), "timeframe": "1Day",
                })
        if rows:
            repo.save_price_bars(rows)
            total += len(rows)
        print(f"  history batch {i//args.batch + 1}: {total} bars cumulative")

    # ---- Stage 4: verify ---------------------------------------------------
    ok = 0
    for sym in universe:
        if len(repo.query_price_data(sym, "2025-03-01", "2025-08-25", "1Day")) >= 100:
            ok += 1
    print("\n=== SUMMARY ===")
    print(f"universe size: {len(universe)} | full-history coverage: {ok}/{len(universe)}")
    print(f"total bars loaded: {total}")
    print("Done. Backtest-ready." if ok >= len(universe) * 0.9 else
          "WARNING: thin coverage — rerun or check API limits.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
