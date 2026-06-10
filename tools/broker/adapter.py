"""Abstract broker interface."""

from abc import ABC, abstractmethod
from datetime import datetime

from models import TradeTransaction


class BrokerAdapter(ABC):
    """Abstract broker interface. Implement per broker."""

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: int,
        limit_price: float | None = None,
        stop_price: float | None = None,
    ) -> TradeTransaction:
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        ...

    @abstractmethod
    def get_positions(self) -> list[dict]:
        ...

    @abstractmethod
    def get_account(self) -> dict:
        ...

    @abstractmethod
    def get_market_data(self, symbol: str) -> dict:
        ...

    @abstractmethod
    def get_historical_data(
        self, symbol: str, start: datetime, end: datetime, timeframe: str = "1Day"
    ) -> list[dict]:
        ...

    def get_tradeable_universe(self) -> list[str]:
        """Return all tradeable symbols. Override per broker.

        Default returns empty — subclasses that can enumerate the full market
        should return active, tradeable US equities (no OTC, no warrants).
        """
        return []

    @abstractmethod
    def get_option_chain(
        self,
        underlying: str,
        expiration_date_gte: str | None = None,
        expiration_date_lte: str | None = None,
        strike_price_gte: float | None = None,
        strike_price_lte: float | None = None,
        option_type: str | None = None,
    ) -> list[dict]:
        """Fetch option chain with greeks+IV for an underlying symbol."""
        ...

    @abstractmethod
    def get_option_snapshot(self, option_symbols: list[str]) -> list[dict]:
        """Fetch real-time snapshot (quote + greeks + IV) for specific option contracts."""
        ...

    @abstractmethod
    def get_option_historical_iv(
        self, underlying: str, lookback_days: int = 252
    ) -> list[dict]:
        """Fetch historical IV data points for IV Rank calculation.
        Returns list of {"date": "YYYY-MM-DD", "iv": float} sorted ascending."""
        ...

    @abstractmethod
    def get_options_positions(self) -> list[dict]:
        """Get all open option positions (filtered by asset class)."""
        ...

    @abstractmethod
    def place_multileg_order(
        self,
        legs: list[dict],
        order_type: str,
        limit_price: float | None = None,
        time_in_force: str = "day",
        qty: int = 1,
    ) -> "TradeTransaction":
        """Place a multi-leg option order (spreads). Each leg: {symbol, side, ratio_qty}.
        side values: buy_to_open, buy_to_close, sell_to_open, sell_to_close.
        qty = number of spread contracts (multiplies each leg's ratio_qty)."""
        ...
