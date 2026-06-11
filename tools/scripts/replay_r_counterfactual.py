"""R-engine counterfactual replay — DIAGNOSIS ONLY (run-6 skipped washouts).

Mechanically replays SOP v1.4.0 Engine R rules over signals that were
skipped for slot/sequencing reasons. Rule PARAMETERS arrive in the signals
JSON (regime tier per signal date from the original scans); mechanics
mirror week_runner.py daily-bar conventions (no same-day target fills,
close-based stop -> next open, 4-session time stop -> next open).

Usage: uv run python scripts/replay_r_counterfactual.py signals.json [stop_atr]

signals.json: [{"symbol": "FERG", "signal_date": "2025-12-10",
                "prev_close": 226.02, "atr10": 6.18, "rsi3": 3.0,
                "spy_tr_atr": 0.322, "cohort": "DEC"}, ...]
prev_close/atr10/spy_tr_atr are derived from price_data (data strictly
before signal_date) when omitted. stop_atr defaults to 2.5 (v1.4.0).
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


def _trs(symbol, before, n):
    """Last n true ranges strictly before `before` (needs n+1 bars)."""
    rows = sqlite3.connect(DB).execute(
        "select high, low, close from price_data where symbol=? and "
        "timeframe='1Day' and timestamp < ? order by timestamp",
        (symbol, before)).fetchall()[-(n + 1):]
    out = []
    for i in range(1, len(rows)):
        h, l, pc = float(rows[i][0]), float(rows[i][1]), float(rows[i - 1][2])
        out.append(max(h - l, abs(h - pc), abs(l - pc)))
    return out


def derive(sig):
    """Fill in prev_close / atr10 / spy_tr_atr from the DB (no look-ahead)."""
    sym, d0 = sig["symbol"], sig["signal_date"]
    if "prev_close" not in sig:
        row = sqlite3.connect(DB).execute(
            "select close from price_data where symbol=? and timeframe='1Day' "
            "and timestamp < ? order by timestamp desc limit 1", (sym, d0)).fetchone()
        sig["prev_close"] = float(row[0])
    if "atr10" not in sig:
        trs = _trs(sym, d0, 10)
        sig["atr10"] = sum(trs) / len(trs)
    if "spy_tr_atr" not in sig:
        trs = _trs("SPY", d0, 21)
        sig["spy_tr_atr"] = trs[-1] / (sum(trs[:-1]) / len(trs[:-1]))
    sig.setdefault("rsi3", None)
    sig.setdefault("cohort", "ALL")
    return sig


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


def replay_one(sig, stop_atr=STOP_ATR):
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
    rps = stop_atr * atr
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
            "exit_date": dte, "reason": reason, "cohort": sig["cohort"],
            "r": round((px - fill) / rps, 2), "rsi3": sig["rsi3"]}


def _summ(filled):
    if not filled:
        return None
    return {"n": len(filled), "total_r": round(sum(r["r"] for r in filled), 2),
            "avg_r": round(sum(r["r"] for r in filled) / len(filled), 3),
            "wr": round(sum(1 for r in filled if r["r"] > 0) / len(filled), 2)}


def main():
    signals = [derive(s) for s in json.loads(Path(sys.argv[1]).read_text())]
    widths = [float(sys.argv[2])] if len(sys.argv) > 2 else [2.5, 2.0, 1.5]
    out = {"trades": {}, "summary": {}}
    for w in widths:
        res = [replay_one(s, w) for s in signals]
        filled = [r for r in res if r["result"] == "filled"]
        out["trades"][str(w)] = res
        out["summary"][str(w)] = {"ALL": _summ(filled)}
        for cohort in sorted({r["cohort"] for r in filled}):
            out["summary"][str(w)][cohort] = _summ(
                [r for r in filled if r["cohort"] == cohort])
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
