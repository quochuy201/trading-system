"""Simulation broker adapter for backtesting — replays historical data."""

from datetime import datetime

from broker.adapter import BrokerAdapter
from models import TradeTransaction
from persistence.repository import Repository


class SimulationBrokerAdapter(BrokerAdapter):
    """Simulates broker execution against historical data.

    - Market orders fill at next bar's open + slippage
    - Limit orders fill when price crosses limit level
    - Stop orders trigger when price crosses stop level
    - Tracks simulated account state (cash, positions)
    """

    def __init__(
        self,
        repo: Repository,
        initial_capital: float = 100000.0,
        slippage_pct: float = 0.05,
        fee_per_trade: float = 0.0,
        timeframe: str = "1Day",
    ):
        self.repo = repo
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: dict[str, dict] = {}  # symbol → {quantity, avg_price, side}
        self.slippage_pct = slippage_pct
        self.fee_per_trade = fee_per_trade
        self.timeframe = timeframe
        self.current_time: datetime | None = None
        self._order_counter = 0

    def set_time(self, t: datetime) -> None:
        """Advance simulation clock. Data queries respect this."""
        self.current_time = t

    def _next_order_id(self) -> str:
        self._order_counter += 1
        return f"SIM-{self._order_counter:06d}"

    def _get_current_bar(self, symbol: str) -> dict | None:
        """Get the most recent bar at or before current simulation time."""
        if not self.current_time:
            return None
        ts = self.current_time.isoformat()
        bars = self.repo.query_price_data(symbol, "1900-01-01", ts, self.timeframe)
        return bars[-1] if bars else None

    def _apply_slippage(self, price: float, side: str) -> float:
        slip = price * (self.slippage_pct / 100)
        return price + slip if side == "buy" else price - slip

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: int,
        limit_price: float | None = None,
        stop_price: float | None = None,
    ) -> TradeTransaction:
        bar = self._get_current_bar(symbol)
        order_id = self._next_order_id()

        if bar is None:
            return TradeTransaction(
                transaction_id=order_id, symbol=symbol, side=side,
                order_type=order_type, quantity=quantity, price=0.0,
                broker_order_id=order_id, status="rejected",
            )

        # Determine fill price
        fill_price = 0.0
        filled = False

        if order_type == "market":
            fill_price = self._apply_slippage(bar["open"], side)
            filled = True
        elif order_type == "limit" and limit_price:
            if side == "buy" and bar["low"] <= limit_price:
                fill_price = min(limit_price, bar["open"])
                filled = True
            elif side == "sell" and bar["high"] >= limit_price:
                fill_price = max(limit_price, bar["open"])
                filled = True
        elif order_type == "stop" and stop_price:
            if side == "sell" and bar["low"] <= stop_price:
                fill_price = self._apply_slippage(stop_price, side)
                filled = True
            elif side == "buy" and bar["high"] >= stop_price:
                fill_price = self._apply_slippage(stop_price, side)
                filled = True

        if not filled:
            return TradeTransaction(
                transaction_id=order_id, symbol=symbol, side=side,
                order_type=order_type, quantity=quantity, price=0.0,
                broker_order_id=order_id, status="pending",
            )

        # Update account
        cost = fill_price * quantity + self.fee_per_trade
        if side == "buy":
            self.cash -= cost
            pos = self.positions.get(symbol, {"quantity": 0, "avg_price": 0.0})
            total_qty = pos["quantity"] + quantity
            if total_qty > 0:
                pos["avg_price"] = (
                    (pos["avg_price"] * pos["quantity"] + fill_price * quantity) / total_qty
                )
            pos["quantity"] = total_qty
            self.positions[symbol] = pos
        else:  # sell
            self.cash += fill_price * quantity - self.fee_per_trade
            pos = self.positions.get(symbol, {"quantity": 0, "avg_price": 0.0})
            pos["quantity"] -= quantity
            if pos["quantity"] <= 0:
                del self.positions[symbol]
            else:
                self.positions[symbol] = pos

        return TradeTransaction(
            transaction_id=order_id, symbol=symbol, side=side,
            order_type=order_type, quantity=quantity, price=fill_price,
            broker_order_id=order_id, status="filled",
        )

    def cancel_order(self, order_id: str) -> bool:
        return True  # Simulation: all cancels succeed

    def get_positions(self) -> list[dict]:
        result = []
        for symbol, pos in self.positions.items():
            bar = self._get_current_bar(symbol)
            current_price = bar["close"] if bar else pos["avg_price"]
            unrealized = (current_price - pos["avg_price"]) * pos["quantity"]
            result.append({
                "symbol": symbol,
                "quantity": pos["quantity"],
                "side": "long",
                "entry_price": pos["avg_price"],
                "current_price": current_price,
                "unrealized_pnl": unrealized,
                "unrealized_pnl_pct": (unrealized / (pos["avg_price"] * pos["quantity"])) * 100 if pos["quantity"] > 0 else 0,
            })
        return result

    def get_account(self) -> dict:
        positions_value = sum(
            p["quantity"] * (self._get_current_bar(s) or {"close": p["avg_price"]}).get("close", p["avg_price"])
            for s, p in self.positions.items()
        )
        equity = self.cash + positions_value
        return {
            "equity": equity,
            "cash": self.cash,
            "buying_power": self.cash * 2,
            "portfolio_value": equity,
            "daily_pnl": equity - self.initial_capital,
        }

    def get_market_data(self, symbol: str) -> dict:
        bar = self._get_current_bar(symbol)
        if not bar:
            return {"symbol": symbol, "bid": 0, "ask": 0, "mid": 0}
        price = bar["close"]
        return {
            "symbol": symbol,
            "bid": price * 0.999,
            "ask": price * 1.001,
            "mid": price,
            "timestamp": bar["timestamp"],
        }

    def get_historical_data(
        self, symbol: str, start: datetime, end: datetime, timeframe: str = "1Day"
    ) -> list[dict]:
        # Only return data up to current simulation time (no look-ahead)
        effective_end = min(end, self.current_time) if self.current_time else end
        return self.repo.query_price_data(
            symbol,
            start.strftime("%Y-%m-%dT%H:%M:%S"),
            effective_end.strftime("%Y-%m-%dT%H:%M:%S"),
            timeframe,
        )
