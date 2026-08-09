"""Market data source adapter — the SINGLE writer of price bars.

Default = yfinance (consolidated, split/dividend-adjusted, no API key).
Selected via env `TRADING_DATA_SOURCE` (default "yfinance"). Alpaca remains the
execution broker; only price *data* flows through here. Swap to a paid source
(Alpaca SIP / Polygon) by adding a subclass and a factory branch — no scanner
change.
"""

import os
from abc import ABC, abstractmethod

import pandas as pd


class MarketDataSource(ABC):
    """Abstract source of historical bars and last price."""

    @abstractmethod
    def get_daily_bars(self, symbols: list[str], start: str, end: str) -> dict[str, list[dict]]:
        """Return {symbol: [bar dict, ...]} of adjusted 1Day bars in [start, end)."""

    @abstractmethod
    def get_last_price(self, symbol: str) -> float | None:
        """Return the latest available adjusted close, or None."""


class YFinanceSource(MarketDataSource):
    """yfinance-backed source. Network calls are isolated to the public methods;
    `_normalize_bars` is pure and unit-tested offline."""

    def _normalize_bars(self, df: pd.DataFrame, symbol: str, timeframe: str = "1Day") -> list[dict]:
        rows: list[dict] = []
        for ts, r in df.iterrows():
            if pd.isna(r["Close"]):
                continue
            rows.append({
                "symbol": symbol,
                "timestamp": ts.strftime("%Y-%m-%dT00:00:00+00:00"),
                "open": float(r["Open"]), "high": float(r["High"]),
                "low": float(r["Low"]), "close": float(r["Close"]),
                "volume": float(r["Volume"]), "timeframe": timeframe,
            })
        return rows

    def get_daily_bars(self, symbols: list[str], start: str, end: str) -> dict[str, list[dict]]:
        import time
        import yfinance as yf
        out: dict[str, list[dict]] = {}
        if not symbols:
            return out

        # yfinance yf.download() with 400+ symbols hits internal SQLite
        # cache contention (OperationalError + false "delisted" reports).
        # Chunk into batches of 25 with retries.
        chunk_size = 25
        for i in range(0, len(symbols), chunk_size):
            chunk = symbols[i:i + chunk_size]
            for attempt in range(3):
                try:
                    df = yf.download(chunk, start=start, end=end,
                                     auto_adjust=True, progress=False,
                                     group_by="ticker", threads=False)
                    for s in chunk:
                        try:
                            sub = df[s]
                        except KeyError:
                            continue
                        sub = sub.dropna(how="all")
                        if not sub.empty:
                            out[s] = self._normalize_bars(sub, s)
                    break  # chunk succeeded
                except Exception:
                    time.sleep(2 ** attempt)
            else:
                # All retries exhausted — skip chunk, continue with next
                continue
        return out

    def get_last_price(self, symbol: str) -> float | None:
        import yfinance as yf
        df = yf.download(symbol, period="5d", auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None
        # Handle both flat and MultiIndex columns from yfinance robustly.
        # Keying on ("Close", symbol) breaks for tickers with normalised names
        # (e.g. BRK.B → BRK-B), so select the Close level then take first column.
        closes = df["Close"]
        if hasattr(closes, "columns"):
            closes = closes.iloc[:, 0]
        closes = closes.dropna()
        return float(closes.iloc[-1]) if len(closes) else None


def get_data_source(name: str | None = None) -> MarketDataSource:
    """Return the configured data source (env `TRADING_DATA_SOURCE`, default yfinance)."""
    name = (name or os.environ.get("TRADING_DATA_SOURCE", "yfinance")).lower()
    if name == "yfinance":
        return YFinanceSource()
    raise ValueError(f"unknown data source: {name!r}")
