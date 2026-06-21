"""Data tools — price cache loading and querying.

1Day bars are written by the single MarketDataSource (consolidated, adjusted).
Intraday timeframes still use the broker until the source supports them.
"""

from datetime import datetime

from broker.adapter import BrokerAdapter
from data.source import get_data_source
from persistence.repository import Repository


def load_price_cache(
    broker: BrokerAdapter,
    repo: Repository,
    symbols: list[str],
    start: str,
    end: str,
    timeframe: str = "1Day",
) -> dict:
    """Load historical bars into the SQLite cache via the single data source.

    1Day → MarketDataSource (adjusted, consolidated). Other timeframes → broker.
    """
    total = 0
    if timeframe == "1Day":
        data = get_data_source().get_daily_bars(symbols, start, end)
        for _sym, bars in data.items():
            if bars:
                repo.save_price_bars(bars)
                total += len(bars)
    else:
        for symbol in symbols:
            bars = broker.get_historical_data(
                symbol, datetime.fromisoformat(start), datetime.fromisoformat(end), timeframe)
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
