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
