"""Stock universe scanner — 4-layer filter for finding tradeable candidates.

This module is used by BOTH live trading and backtesting. Same code path.
The agent calls this via MCP tools; it returns candidates for AI DD.

Filter 1: Liquidity + ATR + Relative Volume (tradeable and in play?)
Filter 2: Relative Strength vs SPY (leader or laggard?)
Filter 3: Trend + Levels via MAs (clear structure?)
Filter 4: Momentum indicators for timing (RSI, MACD, Bollinger)

Candidates that pass all 4 filters go to the AI agent for Due Diligence.
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
    if not (atr >= 1.5 and 1.5 <= atr_pct <= 10):
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

    # === PASSED ALL 4 FILTERS ===
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
