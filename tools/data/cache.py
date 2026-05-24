"""Data tools — price cache loading and querying."""

from datetime import datetime

from broker.adapter import BrokerAdapter
from persistence.repository import Repository


def load_price_cache(
    broker: BrokerAdapter,
    repo: Repository,
    symbols: list[str],
    start: str,
    end: str,
    timeframe: str = "1Day",
) -> dict:
    """Bulk load historical data from broker into SQLite cache. Returns summary."""
    total = 0
    for symbol in symbols:
        bars = broker.get_historical_data(
            symbol,
            datetime.fromisoformat(start),
            datetime.fromisoformat(end),
            timeframe,
        )
        if bars:
            repo.save_price_bars(bars)
            total += len(bars)
    return {"symbols": symbols, "bars_loaded": total, "timeframe": timeframe}


def query_price_cache(
    repo: Repository,
    symbol: str,
    start: str,
    end: str,
    timeframe: str = "1Day",
) -> list[dict]:
    """Query cached price data from SQLite."""
    return repo.query_price_data(symbol, start, end, timeframe)
