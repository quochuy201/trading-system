"""Hyperparameter sweep harness — CALIBRATION TOOL (mechanical, no LLM layer).

CLAUDE.md compliance:
- Metrics come from the SHARED scanner module (`scanner.filters._swing_metrics`)
  — the same code path live trading uses. This file contains MECHANICS only;
  every strategy parameter arrives in a config dict (params-as-data).
- Results are calibration arithmetic. Winning configs must be expressed as an
  SOP version and validated agent-driven before being trusted.
- The sim has NO DD layer (no news veto, no conviction scoring) — it measures
  the mechanical baseline the agent layer then filters.

Protocol: sweep ranks configs on TRAIN ONLY; evaluate survivors ONCE on the
HOLDOUT. Train Aug 25 - Nov 28 2025 · Holdout Dec 1 2025 - Feb 27 2026.

Usage:
  uv run python scripts/param_sweep.py precompute            # build metric cache
  uv run python scripts/param_sweep.py sweep configs.json [--window train|holdout]
  uv run python scripts/param_sweep.py run config.json --window holdout
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import pandas as pd  # noqa: E402
from scanner.filters import _swing_metrics  # noqa: E402  (shared live path)

DB = str(Path(__file__).parent.parent / "trading.db")
CACHE = Path(__file__).parent.parent / "sweep_metric_cache.json"
SLIPPAGE = 0.0005
TRAIN = ("2025-08-25", "2025-11-28")
HOLDOUT = ("2025-12-01", "2026-02-27")
CAPITAL = 100_000.0


# ------------------------------------------------------------------ data load
def load_bars():
    """{sym: DataFrame(date-indexed o/h/l/c/v)} for the whole DB range."""
    uni = json.loads((Path(__file__).parent.parent / "universe_backtest.json").read_text())
    syms = set(uni["symbols"]) | {"SPY"}
    conn = sqlite3.connect(DB)
    df = pd.read_sql_query(
        "select symbol, timestamp, open, high, low, close, volume from price_data "
        "where timeframe='1Day' order by timestamp", conn)
    df["date"] = df["timestamp"].str[:10]
    out = {}
    for sym, g in df.groupby("symbol"):
        if sym in syms:
            out[sym] = g.set_index("date")[["open", "high", "low", "close", "volume"]].astype(float)
    return out


def trading_days(bars, start, end):
    return [d for d in bars["SPY"].index if start <= d <= end]


def spy_regime(spy, day):
    """Mirror analysis/regime.py: tr_atr, vs_sma50, trend — data strictly < day."""
    h = spy[spy.index < day]
    if len(h) < 51:
        return None
    c, hi, lo = h["close"], h["high"], h["low"]
    tr = pd.concat([hi - lo, (hi - c.shift(1)).abs(), (lo - c.shift(1)).abs()], axis=1).max(axis=1)
    tr_atr = float(tr.iloc[-1] / tr.iloc[-21:-1].mean())
    vs50 = float((c.iloc[-1] - c.iloc[-50:].mean()) / c.iloc[-50:].mean() * 100)
    s20n, s20p = c.iloc[-20:].mean(), c.iloc[-21:-1].mean()
    above, rising = c.iloc[-1] > s20n, s20n > s20p
    trend = "up" if (above and rising) else ("down" if (not above and not rising) else "flat")
    return {"tr_atr": round(tr_atr, 3), "vs_sma50": round(vs50, 2), "trend": trend}


# ---------------------------------------------------------------- precompute
def cmd_precompute():
    bars = load_bars()
    days = trading_days(bars, TRAIN[0], HOLDOUT[1])
    cache = {}
    for i, day in enumerate(days):
        reg = spy_regime(bars["SPY"], day)
        spy_h = bars["SPY"][bars["SPY"].index < day]
        spy_ret = (spy_h["close"].iloc[-1] / spy_h["close"].iloc[-10] - 1) * 100
        rows = []
        for sym, df in bars.items():
            if sym == "SPY":
                continue
            h = df[df.index < day]
            if len(h) < 160:
                continue
            m = _swing_metrics(sym, h, float(spy_ret))
            rows.append({k: m[k] for k in (
                "symbol", "price", "dollar_vol20", "atr10", "atr10_pct", "sma25",
                "sma50", "sma150", "roc50", "rs_10d", "drop_3d", "rsi3",
                "pct_from_10d_high", "mom_5d")})
        cache[day] = {"regime": reg, "metrics": rows}
        if i % 10 == 0:
            print(f"{day} done ({i+1}/{len(days)})", file=sys.stderr)
    CACHE.write_text(json.dumps(cache))
    print(json.dumps({"days": len(cache), "cache": str(CACHE)}))


# ---------------------------------------------------------------- simulation
def gates(m, cfg, reg):
    """Parameterized gate evaluation on shared metrics. Returns set of engines."""
    out = set()
    liquid = 10 <= m["price"] <= 500 and m["dollar_vol20"] >= 50e6
    if cfg["m_on"] and liquid and reg["trend"] != "down" and reg["vs_sma50"] <= cfg["m_ext_spy_max"]:
        chasing = ((m["pct_from_10d_high"] > -2 and m["mom_5d"] > 5)
                   or m["price"] > m["sma25"] + cfg["m_chase_atr_mult"] * m["atr10"])
        pullback = (m["rsi3"] < cfg["m_pullback_rsi3_max"]
                    or m["price"] <= m["sma25"] + cfg["m_pullback_atr_dist"] * m["atr10"])
        if (cfg["m_atr_pct_min"] <= m["atr10_pct"] <= cfg["m_atr_pct_max"]
                and m["sma25"] > m["sma50"] and m["price"] > m["sma25"]
                and m["rs_10d"] >= cfg["m_rs10_min"] and m["roc50"] >= cfg["m_roc50_min"]
                and not chasing and pullback):
            out.add("M")
    if cfg["r_on"] and liquid and m["atr10_pct"] >= cfg["r_atr_pct_min"] \
            and m["price"] > m["sma150"] \
            and m["drop_3d"] >= cfg["r_drop3_min"] and m["rsi3"] < cfg["r_rsi3_max"]:
        out.add("R")
    return out


def r_target_pct(tr_atr, atr_pct, cfg):
    if tr_atr < 0.8:
        return max(cfg["r_target_low_floor"], cfg["r_target_low_atr"] * atr_pct)
    if tr_atr <= 1.2:
        return max(cfg["r_target_med_floor"], cfg["r_target_med_atr"] * atr_pct)
    return max(cfg["r_target_high_floor"], cfg["r_target_high_atr"] * atr_pct)


def simulate(cache, bars, days, cfg):
    cash, open_pos, closed = CAPITAL, [], []
    equity_curve = []
    for day in days:
        snap = cache.get(day)
        if snap is None or snap["regime"] is None:
            continue
        reg = snap["regime"]

        # ---- exits first (mirror week_runner order: queued exits at open)
        still = []
        for p in open_pos:
            b = bars[p["sym"]]
            if day not in b.index:
                still.append(p)
                continue
            o, h, l, c = b.loc[day, ["open", "high", "low", "close"]]
            done = False
            if p.get("exit_at_open"):
                px = o * (1 - SLIPPAGE)
                if p["exit_at_open"] == "scaleout":
                    part = int(p["shares"] * cfg["m_scaleout_frac"])
                    if 0 < part < p["shares"]:
                        cash += part * px
                        closed.append({**p, "shares": part, "exit": px, "partial": True,
                                       "reason": "scaleout", "exit_date": day})
                        p["shares"] -= part
                    p["exit_at_open"] = None
                else:
                    cash += p["shares"] * px
                    closed.append({**p, "exit": px, "reason": p["exit_at_open"], "exit_date": day})
                    done = True
            if not done:
                # close-based stop / trail breach checked on PRIOR close
                lvl = p["stop"]
                if p["eng"] == "M" and p.get("armed"):
                    lvl = max(lvl, p["peak"] - cfg["m_trail_width_atr"] * p["atr"])
                if p["prev_close"] < lvl:
                    px = o * (1 - SLIPPAGE)
                    cash += p["shares"] * px
                    closed.append({**p, "exit": px, "reason": "stop", "exit_date": day})
                    done = True
            if not done and p["eng"] == "R" and h >= p["target"]:
                cash += p["shares"] * p["target"]
                closed.append({**p, "exit": p["target"], "reason": "target", "exit_date": day})
                done = True
            if not done:
                p["sessions"] += 1
                p["peak"] = max(p["peak"], c)
                gain = c - p["fill"]
                if p["eng"] == "M":
                    if gain >= cfg["m_trail_arm_r"] * p["rps"]:
                        p["armed"] = True
                    if (cfg.get("m_scaleout_r") and not p.get("scaled")
                            and gain >= cfg["m_scaleout_r"] * p["rps"]):
                        p["scaled"], p["exit_at_open"] = True, "scaleout"
                ts = cfg["m_time_stop"] if p["eng"] == "M" else cfg["r_time_stop"]
                if p["sessions"] >= ts and not p.get("exit_at_open"):
                    p["exit_at_open"] = "time_stop"
                p["prev_close"] = c
                still.append(p)
        open_pos = still

        # ---- entries (signals from data < day, fills today)
        if reg["tr_atr"] <= cfg["stress_tr_atr_max"]:
            cands = {"M": [], "R": []}
            held = {p["sym"] for p in open_pos}
            for m in snap["metrics"]:
                if m["symbol"] in held:
                    continue
                for eng in gates(m, cfg, reg):
                    cands[eng].append(m)
            cands["M"].sort(key=lambda x: -x["roc50"])
            cands["R"].sort(key=lambda x: -x["drop_3d"])
            heat = sum(p["risk_pct"] for p in open_pos)
            for eng, lim_n in (("M", cfg["max_new_m"]), ("R", cfg["max_new_r"])):
                taken = 0
                for m in cands[eng]:
                    if taken >= lim_n or len(open_pos) >= cfg["cap"] or \
                            heat + cfg["risk_pct"] > cfg["heat_max"]:
                        break
                    sym = m["symbol"]
                    if sym not in bars or day not in bars[sym].index:
                        continue
                    o, h, l, c = bars[sym].loc[day, ["open", "high", "low", "close"]]
                    prev_c = m["price"]  # last close before today
                    if eng == "M":
                        gap = (o / prev_c - 1) * 100
                        if gap > cfg["gap_up_max"] or gap < -cfg["gap_down_max"]:
                            continue
                        fill = o * (1 + SLIPPAGE)
                        rps = cfg["m_stop_atr"] * m["atr10"]
                        target = None
                    else:
                        lim = prev_c - cfg["r_limit_atr"] * m["atr10"]
                        if o <= lim:
                            fill = o
                        elif l <= lim:
                            fill = lim
                        else:
                            continue
                        rps = cfg["r_stop_atr"] * m["atr10"]
                        target = fill * (1 + r_target_pct(reg["tr_atr"], m["atr10_pct"], cfg) / 100)
                    equity = cash + sum(p["shares"] * p["prev_close"] for p in open_pos)
                    shares = int(min(equity * cfg["risk_pct"] / 100 / rps,
                                     equity * cfg["notional_cap_pct"] / 100 / fill))
                    if shares < 1:
                        continue
                    cash -= shares * fill
                    open_pos.append({"sym": sym, "eng": eng, "fill": fill, "shares": shares,
                                     "rps": rps, "stop": fill - rps, "target": target,
                                     "atr": m["atr10"], "peak": c, "prev_close": c,
                                     "sessions": 1, "risk_pct": cfg["risk_pct"],
                                     "fill_date": day})
                    heat += cfg["risk_pct"]
                    taken += 1
        equity_curve.append(cash + sum(p["shares"] * p["prev_close"] for p in open_pos))

    # mark remaining at last close (truncation)
    for p in open_pos:
        closed.append({**p, "exit": p["prev_close"], "reason": "open_at_end",
                       "exit_date": days[-1]})
    return closed, equity_curve


def stats(closed, equity_curve, days):
    full = [t for t in closed if not t.get("partial")]
    rs = [(t["exit"] - t["fill"]) / t["rps"] for t in closed]
    pnl = sum((t["exit"] - t["fill"]) * t["shares"] for t in closed)
    peak, dd = -1e18, 0.0
    for e in equity_curve:
        peak = max(peak, e)
        dd = max(dd, peak - e)
    weeks = max(1e-9, len(days) / 5)
    per_eng = {}
    for eng in ("M", "R"):
        sub = [(t["exit"] - t["fill"]) / t["rps"] for t in full if t["eng"] == eng]
        if sub:
            per_eng[eng] = {"n": len(sub), "avg_r": round(sum(sub) / len(sub), 3),
                            "wr": round(sum(1 for r in sub if r > 0) / len(sub), 2)}
    return {"trades": len(full), "wr": round(sum(1 for r in rs if r > 0) / len(rs), 2) if rs else None,
            "total_r": round(sum(rs), 2), "avg_r": round(sum(rs) / len(rs), 3) if rs else None,
            "pnl": round(pnl), "pnl_wk": round(pnl / weeks), "max_dd": round(dd),
            "per_engine": per_eng}


def main():
    cmd = sys.argv[1]
    if cmd == "precompute":
        cmd_precompute()
        return
    window = HOLDOUT if "--window" in sys.argv and \
        sys.argv[sys.argv.index("--window") + 1] == "holdout" else TRAIN
    cache = json.loads(CACHE.read_text())
    bars = load_bars()
    days = trading_days(bars, *window)
    cfgs = json.loads(Path(sys.argv[2]).read_text())
    if isinstance(cfgs, dict):
        cfgs = [cfgs]
    results = []
    for cfg in cfgs:
        closed, eq = simulate(cache, bars, days, cfg)
        results.append({"name": cfg["name"], **stats(closed, eq, days)})
        print(json.dumps(results[-1]), file=sys.stderr)
    results.sort(key=lambda r: -(r["pnl"] - 2 * max(0, r["max_dd"] - 0.06 * CAPITAL)))
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
