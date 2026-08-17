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
    def get_account_activities(
        self,
        activity_type: str = "FILL",
        page_token: str | None = None,
        page_size: int = 100,
    ) -> list[dict]:
        """Discrete account activities, oldest first — THE fill source.

        Each row is one *execution*, so a partially filled order yields several
        rows. This is why fills come from here and not from `get_order()`:
        `get_order()` reports a *cumulative* filled quantity, so appending it
        across polls double-counts (poll at 50 filled, poll again at 100,
        append both ⇒ 150). Real evidence from the paper account: 64 of 250
        FILL activities have `qty != cum_qty`, and 31 orders filled in more
        than one execution.

        Args:
            activity_type: Broker activity type, e.g. "FILL".
            page_token: Cursor — the `id` of the last row already consumed.
                None starts from the oldest activity.
            page_size: Max rows per page; >= 1.

        Returns:
            List of dicts, oldest first, each with keys:
            `id` (stable unique execution id — becomes `fills.fill_id`),
            `order_id`, `symbol`, `side`, `qty` (THIS execution only),
            `cum_qty` (the broker's running total — exposed so the difference
            is checkable, never to be summed), `price`, `type`
            (fill | partial_fill), `transaction_time` (ISO-8601).
            Empty list when the cursor has reached the end.

        Raises:
            ValueError: the broker reported a fractional quantity, which would
                be silently truncated into a wrong position.
        """
        ...

    @abstractmethod
    def get_order(self, broker_order_id: str) -> dict:
        """Order status ONLY — never a fill source.

        Needed because cancelled/rejected/expired orders never appear in the
        FILL activity feed, so terminal status cannot be derived from fills
        alone. Deliberately exposes no quantity or price fields: the cumulative
        ones are exactly what would double-count if appended.

        Args:
            broker_order_id: The broker's order id.

        Returns:
            {"order_id", "status", "symbol", "qty_requested"}. `status` is
            "unknown" when the broker has no such order.
        """
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
