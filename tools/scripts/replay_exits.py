"""Mechanical exit-variant replay over closed M trades — DIAGNOSIS ONLY.

CLAUDE.md compliance: this is replay arithmetic for hypothesis testing
(in-sample, never a forecast). Exit-rule PARAMETERS arrive as JSON variant
definitions; the engine below is generic mechanics (close-based confirm,
exit next open, slippage), mirroring week_runner.py conventions.

Usage:
  uv run python scripts/replay_exits.py trades.json variants.json

trades.json:   [{"symbol": "CAT", "fill_date": "2025-08-26",
                 "fill_price": 431.2155|null, "sample": "CAL"}, ...]
               fill_price null -> next-open fill with slippage (runner rule).
variants.json: [{"name": "B0", "stop_atr": 2.5, "time_stop": 20,
                 "arm_r": 1.0, "arm_atr": null, "width_atr": 2.0,
                 "breakeven_r": null, "giveback_frac": null,
                 "swing_low": false, "scaleout_r": null}, ...]
"""
import json
import sqlite3
import sys
from pathlib import Path

DB = str(Path(__file__).parent.parent / "trading.db")
SLIPPAGE = 0.0005


def bars_from(symbol, start_date, n=80):
    rows = sqlite3.connect(DB).execute(
        "select timestamp, open, high, low, close from price_data "
        "where symbol=? and timeframe='1Day' and timestamp >= ? "
        "order by timestamp limit ?", (symbol, start_date, n)).fetchall()
    return [(r[0][:10], float(r[1]), float(r[2]), float(r[3]), float(r[4]))
            for r in rows]


def atr10_at(symbol, fill_date):
    """ATR10 from the 10 sessions strictly before fill_date (no look-ahead)."""
    rows = sqlite3.connect(DB).execute(
        "select high, low, close from price_data where symbol=? and "
        "timeframe='1Day' and timestamp < ? order by timestamp",
        (symbol, fill_date)).fetchall()[-11:]
    trs = []
    for i in range(1, len(rows)):
        h, l, pc = float(rows[i][0]), float(rows[i][1]), float(rows[i - 1][2])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs) if trs else None


def swing_lows(bars, upto):
    """Confirmed 2-bar-fractal lows among bars[0..upto] (inclusive)."""
    lows = []
    for i in range(2, upto - 1):
        l = bars[i][3]
        if (l < bars[i - 1][3] and l < bars[i - 2][3]
                and l < bars[i + 1][3] and l < bars[i + 2][3]):
            lows.append(l)
    return lows


def replay(trade, variant):
    """Returns dict with exit info + R multiple (weighted if scaled out)."""
    sym, fd = trade["symbol"], trade["fill_date"]
    bars = bars_from(sym, fd)
    if not bars or bars[0][0] != fd:
        return {"symbol": sym, "error": f"no bar on {fd}"}
    atr = atr10_at(sym, fd)
    fill = trade.get("fill_price") or bars[0][1] * (1 + SLIPPAGE)
    rps = variant["stop_atr"] * atr
    stop = fill - rps
    peak = bars[0][4]
    armed = False
    scaled_out_r = None
    frac_open = 1.0
    realized = 0.0  # R units already banked by scale-out

    def exit_at_open(i, reason):
        px = (bars[i][1] * (1 - SLIPPAGE)) if i < len(bars) else bars[-1][4]
        date = bars[i][0] if i < len(bars) else bars[-1][0]
        r = realized + frac_open * (px - fill) / rps
        return {"symbol": sym, "variant": variant["name"], "exit": round(px, 4),
                "date": date, "reason": reason, "r": round(r, 2)}

    for i, (date, o, h, l, c) in enumerate(bars):
        if i == 0:
            continue
        # queued scale-out executes at this open
        if scaled_out_r == "pending":
            realized += 0.5 * (o * (1 - SLIPPAGE) - fill) / rps
            frac_open = 0.5
            scaled_out_r = "done"
        sess = i + 1  # fill day = session 1
        prev_c = bars[i - 1][4]
        # close-based stop / trail / structure / giveback -> exit this open
        lvl = stop
        if armed:
            lvl = max(lvl, peak - variant["width_atr"] * atr)
            if variant.get("swing_low"):
                sl = swing_lows(bars, i - 1)
                if sl:
                    lvl = max(lvl, sl[-1])
        if variant.get("breakeven_r") is not None and \
                (peak - fill) >= variant["breakeven_r"] * rps:
            lvl = max(lvl, fill)
        if prev_c < lvl:
            return exit_at_open(i, "trail" if lvl > stop else "stop")
        gb = variant.get("giveback_frac")
        if gb and armed and (prev_c - fill) < gb * (peak - fill):
            return exit_at_open(i, "giveback")
        # state updates on today's close
        peak = max(peak, c)
        gain = c - fill
        thr = (variant["arm_r"] * rps if variant.get("arm_r") is not None
               else variant["arm_atr"] * atr)
        if gain >= thr:
            armed = True
        so = variant.get("scaleout_r")
        if so and scaled_out_r is None and gain >= so * rps:
            scaled_out_r = "pending"
        if sess >= variant["time_stop"]:
            return exit_at_open(i + 1, "time_stop")
    return exit_at_open(len(bars) - 1, "data_end")


def main():
    trades = json.loads(Path(sys.argv[1]).read_text())
    variants = json.loads(Path(sys.argv[2]).read_text())
    out = {"per_trade": [], "summary": {}}
    for v in variants:
        for samp in ("CAL", "CHECK"):
            rs = []
            for t in [t for t in trades if t["sample"] == samp]:
                res = replay(t, v)
                res["sample"] = samp
                out["per_trade"].append(res)
                if "r" in res:
                    rs.append(res["r"])
            if rs:
                out["summary"][f"{v['name']}/{samp}"] = {
                    "n": len(rs), "total_r": round(sum(rs), 2),
                    "avg_r": round(sum(rs) / len(rs), 3),
                    "wr": round(sum(1 for r in rs if r > 0) / len(rs), 2)}
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
