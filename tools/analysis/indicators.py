"""Technical analysis tools — RSI, MACD, SMA, ATR, volume profile."""

import pandas as pd
import ta

from persistence.repository import Repository


def calc_technical_indicators(
    repo: Repository,
    symbol: str,
    start: str,
    end: str,
    timeframe: str = "1Day",
) -> dict:
    """Calculate technical indicators from cached price data.

    Returns dict with RSI, MACD, SMA(20/50/200), ATR, and volume stats.
    """
    bars = repo.query_price_data(symbol, start, end, timeframe)
    if len(bars) < 20:
        return {"error": f"Insufficient data: {len(bars)} bars (need >= 20)"}

    df = pd.DataFrame(bars)
    df["close"] = df["close"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["volume"] = df["volume"].astype(int)

    # RSI
    rsi = ta.momentum.RSIIndicator(df["close"], window=14)
    latest_rsi = rsi.rsi().iloc[-1]

    # MACD
    macd = ta.trend.MACD(df["close"])
    latest_macd = macd.macd().iloc[-1]
    latest_signal = macd.macd_signal().iloc[-1]
    macd_histogram = latest_macd - latest_signal

    # SMAs
    sma20 = df["close"].rolling(20).mean().iloc[-1]
    sma50 = df["close"].rolling(50).mean().iloc[-1] if len(df) >= 50 else None
    sma200 = df["close"].rolling(200).mean().iloc[-1] if len(df) >= 200 else None

    # ATR
    atr = ta.volatility.AverageTrueRange(df["high"], df["low"], df["close"], window=14)
    latest_atr = atr.average_true_range().iloc[-1]

    # Volume
    avg_volume = df["volume"].mean()
    latest_volume = df["volume"].iloc[-1]
    volume_ratio = latest_volume / avg_volume if avg_volume > 0 else 0

    latest_close = df["close"].iloc[-1]

    return {
        "symbol": symbol,
        "close": round(float(latest_close), 2),
        "rsi": round(float(latest_rsi), 2),
        "macd": round(float(latest_macd), 4),
        "macd_signal": round(float(latest_signal), 4),
        "macd_histogram": round(float(macd_histogram), 4),
        "sma_20": round(float(sma20), 2),
        "sma_50": round(float(sma50), 2) if sma50 is not None else None,
        "sma_200": round(float(sma200), 2) if sma200 is not None else None,
        "atr": round(float(latest_atr), 2),
        "volume": int(latest_volume),
        "avg_volume": int(avg_volume),
        "volume_ratio": round(float(volume_ratio), 2),
        "above_sma20": float(latest_close) > float(sma20),
        "above_sma50": float(latest_close) > float(sma50) if sma50 else None,
    }
