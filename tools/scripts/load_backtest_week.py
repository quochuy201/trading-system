"""Load historical data for the Nov 17-21, 2025 swing-strategy backtest week.

RUN LOCALLY (needs Alpaca keys in .env and internet):
    cd tools && uv run python scripts/load_backtest_week.py

Loads into trading.db:
  - DAILY bars 2025-01-02 → 2025-11-28 for the config universe + SPY
    (>= 160 trading days before Nov 17, required by SMA150/ROC50 gates)
  - HOURLY bars 2025-11-17 → 2025-11-26 for the same symbols
    (backtest week + 3 sessions so open trades can resolve)
  - Re-fetches any cached bar that fails sanity checks (e.g. the corrupted
    SPY 2026-02-02 daily bar with low=69.005, a decimal-shifted tick)

Idempotent: save_price_bars upserts on (symbol, timestamp, timeframe).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yaml

# Load .env from project root (same convention as server.py)
_env_file = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

DAILY_START = "2025-01-02"
DAILY_END = "2025-11-28"
HOURLY_START = "2025-11-17"
HOURLY_END = "2025-11-26"


def main() -> int:
    from broker.alpaca import AlpacaBrokerAdapter
    from persistence.repository import Repository
    from data.cache import load_price_cache

    root = Path(__file__).parent.parent.parent
    cfg = yaml.safe_load((root / "config.yaml").read_text())
    symbols = list(cfg["scanner"]["universe"])
    if "SPY" not in symbols:
        symbols.append("SPY")

    broker = AlpacaBrokerAdapter(paper=True)
    repo = Repository(str(Path(__file__).parent.parent / "trading.db"))

    print(f"Universe: {len(symbols)} symbols")

    # --- sanitize known-bad cached bars (low/high wildly off vs close) ---
    bad = repo.conn.execute(
        "select symbol, timestamp, timeframe, low, close from price_data "
        "where low < close * 0.5 or high > close * 2"
    ).fetchall()
    if bad:
        print(f"Removing {len(bad)} corrupted bars: {[(b[0], b[1][:10]) for b in bad]}")
        repo.conn.execute("delete from price_data where low < close * 0.5 or high > close * 2")
        repo.conn.commit()

    # --- daily bars (chunked so one failure doesn't kill the run) ---
    failed = []
    for i, sym in enumerate(symbols, 1):
        try:
            r = load_price_cache(broker, repo, [sym], DAILY_START, DAILY_END, "1Day")
            print(f"[{i}/{len(symbols)}] {sym}: {r['bars_loaded']} daily bars")
        except Exception as e:
            failed.append((sym, "1Day", str(e)))
            print(f"[{i}/{len(symbols)}] {sym}: DAILY FAILED — {e}")

    # --- hourly bars for the backtest window ---
    for i, sym in enumerate(symbols, 1):
        try:
            r = load_price_cache(broker, repo, [sym], HOURLY_START, HOURLY_END, "1Hour")
            print(f"[{i}/{len(symbols)}] {sym}: {r['bars_loaded']} hourly bars")
        except Exception as e:
            failed.append((sym, "1Hour", str(e)))
            print(f"[{i}/{len(symbols)}] {sym}: HOURLY FAILED — {e}")

    # --- verification summary ---
    daily_ok = hourly_ok = 0
    for sym in symbols:
        d = repo.query_price_data(sym, "2025-03-01", "2025-11-17", "1Day")
        h = repo.query_price_data(sym, HOURLY_START, HOURLY_END + "T23:59:59", "1Hour")
        if len(d) >= 160:
            daily_ok += 1
        if len(h) >= 30:
            hourly_ok += 1

    print("\n=== SUMMARY ===")
    print(f"daily history >=160 bars before Nov 17: {daily_ok}/{len(symbols)} symbols")
    print(f"hourly coverage for backtest window:    {hourly_ok}/{len(symbols)} symbols")
    if failed:
        print(f"FAILURES ({len(failed)}): {failed}")
    print("Done. Backtest-ready." if daily_ok >= 50 and hourly_ok >= 50 else
          "WARNING: coverage looks thin — rerun or check API limits.")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
