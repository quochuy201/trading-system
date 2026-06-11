"""R-engine counterfactual replay — DIAGNOSIS ONLY (run-6 skipped washouts).

Mechanically replays SOP v1.4.0 Engine R rules over signals that were
skipped for slot/sequencing reasons. Rule PARAMETERS arrive in the signals
JSON (regime tier per signal date from the original scans); mechanics
mirror week_runner.py daily-bar conventions (no same-day target fills,
close-based stop -> next open, 4-session time stop -> next open).

Usage: uv run python scripts/replay_r_counterfactual.py signals.json

signals.json: [{"symbol": "FERG", "signal_date": "2025-12-10",
                "prev_close": 226.02, "atr10": 6.18, "rsi3": 3.0,
                "spy_tr_atr": 0.322}, ...]
"""
import json
import sqlite3
import sys
from pathlib import Path

DB = str(Path(__file__).parent.parent / "trading.db")
SLIPPAGE = 0.0005
STOP_ATR = 2.5
TIME_STOP = 4
ENTRY_LIMIT_ATR = 0.5  # limit 0.5*ATR10 below prev close (v1.1.0+)


def bars_from(symbol, start_date, n=15):
    rows = sqlite3.connect(DB).execute(
        "select timestamp, open, high, low, close from price_data "
        "where symbol=? and timeframe='1Day' and timestamp >= ? "
        "order by timestamp limit ?", (symbol, start_date, n)).fetchall()
    return [(r[0][:10], float(r[1]), float(r[2]), float(r[3]), float(r[4]))
            for r in rows]


def target_pct(spy_tr_atr, atr_pct):
    """v1.4.0 volatility-regime-adjusted R target (percent of fill)."""
    if spy_tr_atr < 0.8:
        return max(2.5, 0.5 * atr_pct)
    if spy_tr_atr <= 1.2:
        return max(4.0, 1.0 * atr_pct)
    return max(5.0, 1.5 * atr_pct)


def replay_one(sig):
    sym, d0 = sig["symbol"], sig["signal_date"]
    bars = bars_from(sym, d0)
    if not bars or bars[0][0] != d0:
        return {"symbol": sym, "signal_date": d0, "result": "no_data"}
    lim = sig["prev_close"] - ENTRY_LIMIT_ATR * sig["atr10"]
    date, o, h, l, c = bars[0]
    if o <= lim:
        fill = o
    elif l <= lim:
        fill = lim
    else:
        return {"symbol": sym, "signal_date": d0, "result": "no_fill",
                "limit": round(lim, 2), "day_low": l}
    atr = sig["atr10"]
    rps = STOP_ATR * atr
    stop = fill - rps
    tpct = target_pct(sig["spy_tr_atr"], atr / fill * 100)
    target = fill * (1 + tpct / 100)
    for i in range(1, len(bars)):
        dte, o, h, l, c = bars[i]
        prev_c = bars[i - 1][4]
        if prev_c < stop:                       # close-based stop -> this open
            px = o * (1 - SLIPPAGE)
            return _res(sig, fill, px, dte, "stop", rps)
        if h >= target:                          # resting intrabar limit
            return _res(sig, fill, target, dte, "target", rps)
        if i + 1 > TIME_STOP:                    # fill day = session 1
            px = o * (1 - SLIPPAGE)
            return _res(sig, fill, px, dte, "time_stop", rps)
    return _res(sig, fill, bars[-1][4], bars[-1][0], "data_end", rps)


def _res(sig, fill, px, dte, reason, rps):
    return {"symbol": sig["symbol"], "signal_date": sig["signal_date"],
            "result": "filled", "fill": round(fill, 2), "exit": round(px, 2),
            "exit_date": dte, "reason": reason,
            "r": round((px - fill) / rps, 2), "rsi3": sig["rsi3"]}


def main():
    signals = json.loads(Path(sys.argv[1]).read_text())
    out = [replay_one(s) for s in signals]
    filled = [r for r in out if r["result"] == "filled"]
    print(json.dumps({
        "trades": out,
        "summary": {
            "signals": len(signals),
            "filled": len(filled),
            "no_fill": sum(1 for r in out if r["result"] == "no_fill"),
            "total_r": round(sum(r["r"] for r in filled), 2),
            "avg_r": round(sum(r["r"] for r in filled) / len(filled), 3) if filled else None,
            "wr": round(sum(1 for r in filled if r["r"] > 0) / len(filled), 2) if filled else None,
        }}, indent=1))


if __name__ == "__main__":
    main()
