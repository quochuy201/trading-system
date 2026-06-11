"""Agent-driven 1-week backtest runner — MECHANICS ONLY.

CLAUDE.md compliance:
- NO strategy thresholds in this file. Entry criteria live in the scanner
  (shared module mirroring sops/equity/swing/v1.0.0.md); exit/sizing/gap
  parameters arrive per-trade in the PLAN the agent submits (like live trade
  plans read by the Monitor agent).
- The AI agent calls `scan` (same scanner as live), decides, submits `plan`,
  then `run-day` executes mechanically: fills, close-based stops, intrabar
  targets, trailing, session time stops, event detection.
- Entries fill at NEXT-AVAILABLE price (day's bars), never the signal price.
- All clock-bounded queries: scan date D uses daily bars strictly < D.

State persists in JSON between invocations (each bash call is independent).

Usage:
  python3 scripts/week_runner.py init --capital 100000
  python3 scripts/week_runner.py scan 2025-11-17
  python3 scripts/week_runner.py plan --date 2025-11-17 --symbol NVDA --engine R \
      --entry-type limit --limit-price 178.50 --stop-price 170.10 \
      --target-close-pct 4.0 --time-stop-sessions 4 --risk-pct 1.0 \
      --reason "R-G5 drop 7.2% rsi3 9; sector sympathy"
  python3 scripts/week_runner.py run-day 2025-11-17
  python3 scripts/week_runner.py report
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DB = str(Path(__file__).parent.parent / "trading.db")
STATE = Path(__file__).parent.parent / "backtest_week_state.json"
SLIPPAGE = 0.0005  # 0.05% on market fills (config broker.slippage_pct)


# ---------------------------------------------------------------- data access
def _conn():
    return sqlite3.connect(DB)


def daily_bars(symbol, end_exclusive, limit=400):
    """Daily bars strictly BEFORE end_exclusive (no look-ahead)."""
    rows = _conn().execute(
        "select timestamp, open, high, low, close, volume from price_data "
        "where symbol=? and timeframe='1Day' and timestamp < ? order by timestamp",
        (symbol, end_exclusive),
    ).fetchall()
    return rows[-limit:]


def hour_bars(symbol, date):
    """Market-hours hourly bars for one date (14:00-20:00 UTC)."""
    rows = _conn().execute(
        "select timestamp, open, high, low, close, volume from price_data "
        "where symbol=? and timeframe='1Hour' and timestamp like ? order by timestamp",
        (symbol, f"{date}T%"),
    ).fetchall()
    return [r for r in rows if 14 <= int(r[0][11:13]) <= 20]


def day_session_bars(symbol, date, mode):
    """Bars used to simulate one session: hourly list, or the single daily bar."""
    if mode == "hourly":
        return hour_bars(symbol, date)
    rows = _conn().execute(
        "select timestamp, open, high, low, close, volume from price_data "
        "where symbol=? and timeframe='1Day' and timestamp like ?",
        (symbol, f"{date}T%"),
    ).fetchall()
    return rows


def prev_daily_close(symbol, date):
    bars = daily_bars(symbol, date)
    return float(bars[-1][4]) if bars else None


# ---------------------------------------------------------------- state
def load_state():
    return json.loads(STATE.read_text())


def save_state(s):
    STATE.write_text(json.dumps(s, indent=1))


# ---------------------------------------------------------------- commands
def cmd_init(args):
    save_state({
        "capital": args.capital, "cash": args.capital, "bar_mode": args.bar_mode,
        "open": [], "closed": [], "pending_plans": [], "pending_exits": [],
        "log": [],
    })
    print(json.dumps({"initialized": True, "capital": args.capital, "bar_mode": args.bar_mode}))


def cmd_scan(args):
    """Regime snapshot + swing scan as of pre-open of DATE (data < DATE)."""
    import pandas as pd
    from scanner.filters import scan_universe_swing
    from analysis.regime import compute_market_regime
    from persistence.repository import Repository

    repo = Repository(DB)
    regime = compute_market_regime(repo, "SPY", "2000-01-01", args.date, "1Day")

    syms = [r[0] for r in _conn().execute(
        "select distinct symbol from price_data where timeframe='1Day'").fetchall()]
    stock_data = {}
    for sym in syms:
        rows = daily_bars(sym, args.date)
        if len(rows) >= 160 or sym == "SPY":
            stock_data[sym] = pd.DataFrame(
                rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    cands = scan_universe_swing(stock_data, stock_data.get("SPY"))

    s = load_state()
    open_syms = [p["symbol"] for p in s["open"]]
    print(json.dumps({
        "date": args.date, "regime": regime,
        "open_positions": open_syms, "cash": round(s["cash"], 2),
        "candidates": cands, "scanned": len(stock_data) - 1,
    }, indent=1))


def cmd_plan(args):
    """Agent submits a trade plan (all parameters decided by the agent per SOP)."""
    if not (args.reason or "").strip():
        # Run-5 regression guard: a degraded session entered un-vetted
        # positions (empty DD reason). The agent's thesis is mandatory.
        print(json.dumps({"error": "plan rejected: --reason is required "
                          "(log the DD thesis per SOP; no un-vetted entries)"}))
        return
    s = load_state()
    plan = {
        "date": args.date, "symbol": args.symbol, "engine": args.engine,
        "entry_type": args.entry_type, "limit_price": args.limit_price,
        "stop_price": args.stop_price, "atr10": args.atr10,
        "stop_atr_mult": args.stop_atr_mult, "target_fill_pct": args.target_fill_pct,
        "target_price": args.target_price,           # intrabar target (M optional)
        "target_close_pct": args.target_close_pct,   # R: close >= fill*(1+pct) -> exit next open
        "time_stop_sessions": args.time_stop_sessions,
        "trail": bool(args.trail),                   # M: breakeven@1R, trail 2xATR@1.5R
        "risk_pct": args.risk_pct, "notional_cap_pct": args.notional_cap_pct,
        "gap_up_max_pct": args.gap_up_max_pct, "gap_down_max_pct": args.gap_down_max_pct,
        "reason": args.reason,
    }
    s["pending_plans"].append(plan)
    save_state(s)
    print(json.dumps({"planned": plan["symbol"], "engine": plan["engine"]}))


def _try_fill(plan, bars, prev_close):
    """Mechanical fill. Returns (fill_price, fill_ts, skip_reason)."""
    if not bars:
        return None, None, "no_bars"
    o = float(bars[0][1])
    if plan["entry_type"] == "market_open":
        if prev_close and plan.get("gap_up_max_pct") is not None:
            gap = (o / prev_close - 1) * 100
            if gap > plan["gap_up_max_pct"]:
                return None, None, f"gap_up {gap:.1f}%>{plan['gap_up_max_pct']}%"
            if gap < -plan["gap_down_max_pct"]:
                return None, None, f"gap_down {gap:.1f}%"
        return o * (1 + SLIPPAGE), bars[0][0], None
    # limit buy
    lim = plan["limit_price"]
    if o <= lim:
        return o, bars[0][0], None
    for b in bars:
        if float(b[3]) <= lim:
            return lim, b[0], None
    return None, None, "limit_not_reached"


def cmd_run_day(args):
    s = load_state()
    date = args.date
    report = {"date": date, "fills": [], "exits": [], "events": [], "skipped": []}

    # ---- 1. queued exits from prior session (R target/time stops exit at open)
    unexecuted = []
    for ex in s["pending_exits"]:
        pos = next((p for p in s["open"] if p["id"] == ex["id"]), None)
        if not pos:
            continue
        bars = day_session_bars(pos["symbol"], date, s.get("bar_mode", "hourly"))
        if not bars:
            unexecuted.append(ex)  # no data this date — KEEP the exit queued
            continue
        px = float(bars[0][1]) * (1 - SLIPPAGE)
        _close(s, pos, px, ex["reason"], bars[0][0], report)
    s["pending_exits"] = unexecuted

    # ---- 2. fill pending entry plans
    still_pending = []
    for plan in s["pending_plans"]:
        bars = day_session_bars(plan["symbol"], date, s.get("bar_mode", "hourly"))
        prev_c = prev_daily_close(plan["symbol"], date)
        px, ts, skip = _try_fill(plan, bars, prev_c)
        if skip:
            report["skipped"].append({"symbol": plan["symbol"], "reason": skip})
            continue
        equity = _equity(s, date)
        risk_dollars = equity * plan["risk_pct"] / 100
        stop_px = plan["stop_price"]
        if plan.get("stop_atr_mult"):
            stop_px = px - plan["stop_atr_mult"] * plan["atr10"]
        target_px = plan["target_price"]
        if plan.get("target_fill_pct"):
            target_px = px * (1 + plan["target_fill_pct"] / 100)
        rps = px - stop_px
        if rps <= 0:
            report["skipped"].append({"symbol": plan["symbol"], "reason": "stop>=fill"})
            continue
        shares = int(min(risk_dollars / rps, equity * plan["notional_cap_pct"] / 100 / px))
        if shares < 1:
            report["skipped"].append({"symbol": plan["symbol"], "reason": "size<1"})
            continue
        pos = {
            "id": f"{plan['symbol']}-{date}", "symbol": plan["symbol"],
            "engine": plan["engine"], "shares": shares,
            "fill_price": round(px, 4), "fill_ts": ts, "fill_date": date,
            "stop_price": round(stop_px, 4), "atr10": plan["atr10"],
            "target_price": round(target_px, 4) if target_px else None,
            "target_close_pct": plan["target_close_pct"],
            "time_stop_sessions": plan["time_stop_sessions"],
            "trail": plan["trail"], "trailing_stop": round(stop_px, 4),
            "highest_close": px, "prev_close": px, "sessions_held": 0,
            "risk_per_share": round(rps, 4), "reason": plan["reason"],
        }
        s["cash"] -= shares * px
        s["open"].append(pos)
        report["fills"].append({"symbol": pos["symbol"], "engine": pos["engine"],
                                "shares": shares, "fill": round(px, 2), "ts": ts})
    s["pending_plans"] = still_pending

    # ---- 3. hourly mechanical loop
    day_bars = {p["symbol"]: day_session_bars(p["symbol"], date, s.get("bar_mode", "hourly")) for p in s["open"]}
    max_n = max((len(b) for b in day_bars.values()), default=0)
    for i in range(max_n):
        for pos in list(s["open"]):
            bars = day_bars.get(pos["symbol"], [])
            if i >= len(bars):
                continue
            ts, o, h, l, c, v = bars[i]
            o, h, l, c = map(float, (o, h, l, c))
            if ts <= pos["fill_ts"]:
                pos["prev_close"] = c
                continue
            # close-based stop -> exit this bar open
            stop_lvl = max(pos["stop_price"], pos["trailing_stop"]) if pos["trail"] else pos["stop_price"]
            if pos["prev_close"] < stop_lvl:
                _close(s, pos, o * (1 - SLIPPAGE),
                       "trailing_stop" if pos["trail"] and stop_lvl > pos["stop_price"] else "stop_loss",
                       ts, report)
                continue
            # intrabar target
            if pos["target_price"] and h >= pos["target_price"]:
                _close(s, pos, pos["target_price"], "take_profit", ts, report)
                continue
            # trailing update (M profile: BE @1R, trail 2xATR @1.5R)
            if pos["trail"]:
                gain = c - pos["fill_price"]
                if c > pos["highest_close"]:
                    pos["highest_close"] = c
                if gain >= pos["risk_per_share"] and pos["trailing_stop"] < pos["fill_price"]:
                    pos["trailing_stop"] = pos["fill_price"]  # breakeven
                if gain >= 1.5 * pos["risk_per_share"]:
                    t = pos["highest_close"] - 2.0 * pos["atr10"]
                    if t > pos["trailing_stop"]:
                        pos["trailing_stop"] = t
            # event detection for LLM review
            chg = (c - o) / o * 100 if o else 0
            if chg < -3:
                report["events"].append({"type": "large_drop", "symbol": pos["symbol"],
                                         "pct": round(chg, 2), "ts": ts})
            pos["prev_close"] = c

    # ---- 4. end of session: session counters, R close-target, time stops
    for pos in s["open"]:
        bars = day_session_bars(pos["symbol"], date, s.get("bar_mode", "hourly"))
        if not bars:
            continue
        day_close = float(bars[-1][4])
        pos["sessions_held"] += 1
        if pos["target_close_pct"] and day_close >= pos["fill_price"] * (1 + pos["target_close_pct"] / 100):
            s["pending_exits"].append({"id": pos["id"], "reason": "target_close_next_open"})
        elif pos["sessions_held"] >= pos["time_stop_sessions"]:
            s["pending_exits"].append({"id": pos["id"], "reason": "time_stop_next_open"})

    report["eod_open"] = [
        {"symbol": p["symbol"], "engine": p["engine"], "shares": p["shares"],
         "fill": p["fill_price"], "last": p["prev_close"],
         "unreal_pct": round((p["prev_close"] / p["fill_price"] - 1) * 100, 2),
         "sessions": p["sessions_held"]}
        for p in s["open"]
    ]
    report["cash"] = round(s["cash"], 2)
    report["equity"] = round(_equity(s, date, eod=True), 2)
    s["log"].append(report)
    save_state(s)
    print(json.dumps(report, indent=1))


def _close(s, pos, px, reason, ts, report):
    pnl = (px - pos["fill_price"]) * pos["shares"]
    r_mult = (px - pos["fill_price"]) / pos["risk_per_share"]
    s["cash"] += pos["shares"] * px
    s["open"] = [p for p in s["open"] if p["id"] != pos["id"]]
    rec = {"symbol": pos["symbol"], "engine": pos["engine"], "shares": pos["shares"],
           "fill": pos["fill_price"], "exit": round(px, 4), "reason": reason,
           "pnl": round(pnl, 2), "r": round(r_mult, 2), "ts": ts,
           "entry_reason": pos["reason"], "fill_date": pos["fill_date"]}
    s["closed"].append(rec)
    report["exits"].append(rec)


def _equity(s, date, eod=False):
    eq = s["cash"]
    for p in s["open"]:
        eq += p["shares"] * p["prev_close"]
    return eq


def cmd_mark(args):
    """Mark open positions to a date's close (end-of-test valuation)."""
    s = load_state()
    marks = []
    for p in s["open"]:
        bars = hour_bars(p["symbol"], args.date)
        last = float(bars[-1][4]) if bars else p["prev_close"]
        marks.append({"symbol": p["symbol"], "engine": p["engine"],
                      "fill": p["fill_price"], "mark": last,
                      "unreal_pnl": round((last - p["fill_price"]) * p["shares"], 2),
                      "unreal_r": round((last - p["fill_price"]) / p["risk_per_share"], 2)})
    print(json.dumps(marks, indent=1))


def cmd_report(args):
    s = load_state()
    closed = s["closed"]
    out = {"capital": s["capital"], "cash": round(s["cash"], 2),
           "closed_trades": len(closed), "open_positions": len(s["open"])}
    for label, trades in [("ALL", closed),
                          ("M", [t for t in closed if t["engine"] == "M"]),
                          ("R", [t for t in closed if t["engine"] == "R"])]:
        if not trades:
            out[label] = {"trades": 0}
            continue
        wins = [t for t in trades if t["pnl"] > 0]
        pnl = sum(t["pnl"] for t in trades)
        out[label] = {
            "trades": len(trades), "wins": len(wins),
            "win_rate": round(len(wins) / len(trades) * 100, 1),
            "pnl": round(pnl, 2),
            "avg_r": round(sum(t["r"] for t in trades) / len(trades), 3),
            "expectancy_$": round(pnl / len(trades), 2),
            "avg_win": round(sum(t["pnl"] for t in wins) / len(wins), 2) if wins else 0,
            "avg_loss": round(sum(t["pnl"] for t in trades if t["pnl"] <= 0) /
                              max(1, len(trades) - len(wins)), 2),
        }
    out["trades"] = closed
    print(json.dumps(out, indent=1))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--capital", type=float, default=100000); p.add_argument("--bar-mode", default="hourly", choices=["hourly", "daily"])
    p = sub.add_parser("scan"); p.add_argument("date")
    p = sub.add_parser("plan")
    p.add_argument("--date", required=True); p.add_argument("--symbol", required=True)
    p.add_argument("--engine", required=True, choices=["M", "R"])
    p.add_argument("--entry-type", required=True, choices=["market_open", "limit"])
    p.add_argument("--limit-price", type=float)
    p.add_argument("--stop-price", type=float)
    p.add_argument("--stop-atr-mult", type=float)
    p.add_argument("--target-fill-pct", type=float)
    p.add_argument("--atr10", type=float, required=True)
    p.add_argument("--target-price", type=float)
    p.add_argument("--target-close-pct", type=float)
    p.add_argument("--time-stop-sessions", type=int, required=True)
    p.add_argument("--trail", type=int, default=0)
    p.add_argument("--risk-pct", type=float, required=True)
    p.add_argument("--notional-cap-pct", type=float, default=10.0)
    p.add_argument("--gap-up-max-pct", type=float)
    p.add_argument("--gap-down-max-pct", type=float)
    p.add_argument("--reason", default="")
    p = sub.add_parser("run-day"); p.add_argument("date")
    p = sub.add_parser("mark"); p.add_argument("date")
    sub.add_parser("report")
    args = ap.parse_args()
    {"init": cmd_init, "scan": cmd_scan, "plan": cmd_plan,
     "run-day": cmd_run_day, "mark": cmd_mark, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    main()
