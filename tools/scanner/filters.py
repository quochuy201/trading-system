"""Stock universe scanner — 4-layer filter for finding tradeable candidates.

This module is used by BOTH live trading and backtesting. Same code path.
The agent calls this via MCP tools; it returns candidates for AI DD.

Filter 1: Liquidity + ATR + Relative Volume (tradeable and in play?)
Filter 2: Relative Strength vs SPY (leader or laggard?)
Filter 3: Trend + Levels via MAs (clear structure?)
Filter 4: Momentum indicators for timing (RSI, MACD, Bollinger)

Candidates that pass all 4 filters go to the AI agent for Due Diligence.

`scan_universe_swing` implements the MECHANICAL gates of
sops/equity/swing/v1.0.0.md (two-engine: momentum continuation M +
mean-reversion dip R). Thresholds here MUST mirror that SOP version —
the scanner measures and gates; the AI agent does DD, the thesis-break
veto (R-G7), earnings checks, and the final enter/skip decision.
"""

import pandas as pd
import ta


def scan_universe(stock_data: dict[str, pd.DataFrame], spy_data: pd.DataFrame | None = None) -> list[dict]:
    """Run the 4-layer scanner on a dict of DataFrames.

    Args:
        stock_data: {symbol: DataFrame} with columns [date, open, high, low, close, volume].
                    Must have >= 50 rows for indicator computation.
        spy_data: DataFrame for SPY (same columns). Used for relative strength.
                  If None, Filter 2 (relative strength) is skipped.

    Returns:
        List of candidate dicts sorted by relative strength (strongest first).
        Each candidate has: symbol, price, atr, atr_pct, rvol, rs_10d, rsi,
        macd_bullish, bb_pos, sma20, sma50.
    """
    # SPY returns for relative strength
    spy_ret_10d = 0.0
    if spy_data is not None and len(spy_data) >= 10:
        spy_ret_10d = (spy_data["close"].iloc[-1] / spy_data["close"].iloc[-10] - 1) * 100

    candidates = []

    for sym, df in stock_data.items():
        if sym == "SPY":
            continue
        if len(df) < 50:
            continue

        result = _evaluate_stock(sym, df, spy_ret_10d, spy_data is not None)
        if result is not None:
            candidates.append(result)

    return sorted(candidates, key=lambda x: x["rs_10d"], reverse=True)


def _evaluate_stock(sym: str, df: pd.DataFrame, spy_ret_10d: float, check_rs: bool) -> dict | None:
    """Evaluate a single stock through all 4 filters. Returns candidate dict or None."""

    price = float(df["close"].iloc[-1])
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)

    # === FILTER 1: Liquidity + ATR + Relative Volume ===
    avg_vol = volume.iloc[-20:].mean()
    latest_vol = volume.iloc[-1]
    rvol = latest_vol / avg_vol if avg_vol > 0 else 0

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = float(tr.iloc[-14:].mean())
    atr_pct = (atr / price) * 100

    if not (10 <= price <= 500):
        return None
    if avg_vol < 2_000_000:
        return None
    if not (atr >= 1.5 and 1.5 <= atr_pct <= 5):
        return None
    if rvol < 1.1:
        return None

    # === FILTER 2: Relative Strength vs SPY ===
    stock_ret_10d = (close.iloc[-1] / close.iloc[-10] - 1) * 100
    rs_10d = stock_ret_10d - spy_ret_10d

    if check_rs and rs_10d <= 2:
        return None

    # === FILTER 3: Trend + Structure ===
    sma20 = float(close.iloc[-20:].mean())
    sma50 = float(close.iloc[-50:].mean())
    above_sma20 = price > sma20
    sma_aligned = above_sma20 and sma20 > sma50

    if not (above_sma20 and sma_aligned):
        return None

    # === FILTER 4: Momentum / Timing ===
    rsi_series = ta.momentum.RSIIndicator(close, window=14).rsi()
    rsi = float(rsi_series.iloc[-1])

    macd_ind = ta.trend.MACD(close)
    macd_bullish = float(macd_ind.macd().iloc[-1]) > float(macd_ind.macd_signal().iloc[-1])

    bb = ta.volatility.BollingerBands(close, window=20)
    bb_upper = float(bb.bollinger_hband().iloc[-1])
    bb_lower = float(bb.bollinger_lband().iloc[-1])
    bb_pos = (price - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5

    if not (40 <= rsi <= 70 and macd_bullish and bb_pos < 0.95):
        return None

    # === CHASING FILTER: Reject entries at/near highs after a run ===
    # If price within 2% of 10-day high AND ran >5% in 5 days → chasing
    recent_high_10d = float(high.iloc[-10:].max())
    pct_from_high = (price - recent_high_10d) / recent_high_10d * 100
    momentum_5d = (price / float(close.iloc[-6]) - 1) * 100 if len(close) >= 6 else 0

    if pct_from_high > -2 and momentum_5d > 5:
        return None  # chasing an exhausted move

    # === PASSED ALL FILTERS ===
    return {
        "symbol": sym,
        "price": round(price, 2),
        "atr": round(atr, 2),
        "atr_pct": round(atr_pct, 2),
        "rvol": round(rvol, 2),
        "rs_10d": round(rs_10d, 2),
        "rsi": round(rsi, 1),
        "macd_bullish": macd_bullish,
        "bb_pos": round(bb_pos, 2),
        "sma20": round(sma20, 2),
        "sma50": round(sma50, 2),
    }


# ---------------------------------------------------------------------------
# Swing scanner — sops/equity/swing/v1.0.0.md mechanical gates
# ---------------------------------------------------------------------------

# Gate thresholds — MUST mirror sops/equity/swing/v1.1.0.md. Do not tune here
# without a new SOP version.
SWING_V1 = {
    "min_dollar_vol20": 50_000_000,   # M-G2 / R-G2
    "price_min": 10.0,                # M-G2 / R-G2
    "price_max": 500.0,               # M-G2 (M only)
    "m_atr_pct_min": 1.5,             # M-G3
    "m_atr_pct_max": 6.0,             # M-G3
    "m_rs10_min": 2.0,                # M-G5 (vs SPY, pct points)
    "m_roc50_min": 10.0,              # M-G6
    "m_chase_atr_mult": 2.5,          # M-G7: close ≤ SMA25 + 2.5*ATR10
    "m_pullback_rsi3_max": 50.0,      # M-G7b (v1.1.0): RSI3 < 50 OR ...
    "m_pullback_atr_dist": 1.0,       # M-G7b: ... close ≤ SMA25 + 1*ATR10
    "r_atr_pct_min": 2.5,             # R-G3
    "r_drop3_min": 6.0,               # R-G5 (pct)
    "r_rsi3_max": 15.0,               # R-G5 (v1.1.0: was 30)
}


def scan_universe_swing(stock_data: dict[str, pd.DataFrame],
                        spy_data: pd.DataFrame | None = None) -> list[dict]:
    """Evaluate the swing SOP's mechanical gates for every symbol.

    Returns one dict per symbol that passes EITHER engine's gates, with
    `engine_m_pass` / `engine_r_pass` flags, the measured metrics, and per-gate
    failure lists so the agent can log `rules_triggered` honestly.

    Needs >= 160 daily bars for SMA150/ROC50; shorter histories are skipped.
    Ranking (per SOP): engine M by roc50 desc, engine R by drop_3d desc —
    the agent ranks; this function just measures.
    """
    spy_ret_10d = 0.0
    if spy_data is not None and len(spy_data) >= 10:
        spy_ret_10d = (spy_data["close"].iloc[-1] / spy_data["close"].iloc[-10] - 1) * 100

    out = []
    for sym, df in stock_data.items():
        if sym == "SPY" or len(df) < 160:
            continue
        m = _swing_metrics(sym, df, spy_ret_10d)
        if m["engine_m_pass"] or m["engine_r_pass"]:
            out.append(m)
    return out


def _swing_metrics(sym: str, df: pd.DataFrame, spy_ret_10d: float) -> dict:
    c = SWING_V1
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)
    price = float(close.iloc[-1])

    dollar_vol20 = float((close.iloc[-20:] * volume.iloc[-20:]).mean())

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr10 = float(tr.iloc[-10:].mean())
    atr10_pct = (atr10 / price) * 100 if price > 0 else 0.0

    sma25 = float(close.iloc[-25:].mean())
    sma50 = float(close.iloc[-50:].mean())
    sma150 = float(close.iloc[-150:].mean())
    roc50 = (price / float(close.iloc[-51]) - 1) * 100
    rs_10d = (price / float(close.iloc[-10]) - 1) * 100 - spy_ret_10d
    drop_3d = (1 - price / float(close.iloc[-4])) * 100  # positive = dropped
    rsi3 = float(ta.momentum.RSIIndicator(close, window=3).rsi().iloc[-1])
    rsi14 = float(ta.momentum.RSIIndicator(close, window=14).rsi().iloc[-1])

    high_10d = float(high.iloc[-10:].max())
    pct_from_high = (price - high_10d) / high_10d * 100
    mom_5d = (price / float(close.iloc[-6]) - 1) * 100 if len(close) >= 6 else 0.0

    # --- Engine M gates (M-G2..M-G7; regime/earnings/portfolio are agent-side) ---
    m_fails = []
    if not (c["price_min"] <= price <= c["price_max"] and dollar_vol20 >= c["min_dollar_vol20"]):
        m_fails.append("M-G2")
    if not (c["m_atr_pct_min"] <= atr10_pct <= c["m_atr_pct_max"]):
        m_fails.append("M-G3")
    if not (sma25 > sma50 and price > sma25):
        m_fails.append("M-G4")
    if not (rs_10d >= c["m_rs10_min"]):
        m_fails.append("M-G5")
    if not (roc50 >= c["m_roc50_min"]):
        m_fails.append("M-G6")
    chasing = (pct_from_high > -2 and mom_5d > 5) or (price > sma25 + c["m_chase_atr_mult"] * atr10)
    if chasing:
        m_fails.append("M-G7")
    # M-G7b (v1.1.0): buy leaders on pullback, not at extension
    pullback = (rsi3 < c["m_pullback_rsi3_max"]) or (price <= sma25 + c["m_pullback_atr_dist"] * atr10)
    if not pullback:
        m_fails.append("M-G7b")

    # --- Engine R gates (R-G2..R-G5) ---
    r_fails = []
    if not (price >= c["price_min"] and dollar_vol20 >= c["min_dollar_vol20"]):
        r_fails.append("R-G2")
    if not (atr10_pct >= c["r_atr_pct_min"]):
        r_fails.append("R-G3")
    if not (price > sma150):
        r_fails.append("R-G4")
    if not (drop_3d >= c["r_drop3_min"] and rsi3 < c["r_rsi3_max"]):
        r_fails.append("R-G5")

    return {
        "symbol": sym,
        "price": round(price, 2),
        "dollar_vol20": round(dollar_vol20),
        "atr10": round(atr10, 2),
        "atr10_pct": round(atr10_pct, 2),
        "sma25": round(sma25, 2),
        "sma50": round(sma50, 2),
        "sma150": round(sma150, 2),
        "roc50": round(roc50, 2),
        "rs_10d": round(rs_10d, 2),
        "drop_3d": round(drop_3d, 2),
        "rsi3": round(rsi3, 1),
        "rsi14": round(rsi14, 1),
        "pct_from_10d_high": round(pct_from_high, 2),
        "mom_5d": round(mom_5d, 2),
        "engine_m_pass": not m_fails,
        "engine_m_fails": m_fails,
        "engine_r_pass": not r_fails,
        "engine_r_fails": r_fails,
    }
