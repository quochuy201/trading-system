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
        self._fill_price_bar: dict | None = None  # set by harness for correct fill pricing
        # Executions this simulation modelled, oldest first — the backtest's
        # equivalent of the broker's activity feed, so reconciliation runs the
        # same code path live and in backtest.
        self._activities: list[dict] = []
        self._order_status: dict[str, dict] = {}
        self._equity_curve: list[tuple[int, float]] = []

    def set_time(self, t: datetime) -> None:
        """Advance simulation clock. Data queries respect this.

        Also records an equity point, so the backtest builds the same equity
        curve shape the live broker serves and drawdown is computed by
        identical code in both.
        """
        self.current_time = t
        self._equity_curve.append((int(t.timestamp()), self.get_account()["equity"]))

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
        # Use the fill price bar (current bar set by harness) if available.
        # This ensures market orders fill at the current bar's OPEN — the first
        # available price after the agent makes its decision.
        if self._fill_price_bar and self._fill_price_bar.get("symbol") == symbol:
            bar = self._fill_price_bar
        else:
            bar = self._get_current_bar(symbol)
        order_id = self._next_order_id()

        if bar is None:
            self._record_status(order_id, symbol, quantity, "rejected")
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
            self._record_status(order_id, symbol, quantity, "pending")
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

        self._record_status(order_id, symbol, quantity, "filled")
        self._record_activity(order_id, symbol, side, quantity, fill_price)

        return TradeTransaction(
            transaction_id=order_id, symbol=symbol, side=side,
            order_type=order_type, quantity=quantity, price=fill_price,
            broker_order_id=order_id, status="filled",
        )

    def _record_status(self, order_id, symbol, quantity, status) -> None:
        self._order_status[order_id] = {
            "order_id": order_id, "status": status,
            "symbol": symbol, "qty_requested": quantity,
        }

    def _record_activity(
        self, order_id: str, symbol: str, side: str, qty: int, price: float
    ) -> None:
        """Append the execution just modelled.

        The activity id is derived from the sequence, never random: backtests
        must be reproducible, and Task 5 hashes fill ids into round-trip ids.
        The simulation fills in one shot, so `cum_qty == qty` — but the field
        is present so both adapters carry the same shape.
        """
        self._activities.append({
            "id": f"SIM-ACT-{len(self._activities) + 1:06d}",
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "cum_qty": qty,
            "price": price,
            "type": "fill",
            "transaction_time": (
                self.current_time.isoformat() if self.current_time else ""
            ),
        })

    def get_account_activities(
        self,
        activity_type: str = "FILL",
        page_token: str | None = None,
        page_size: int = 100,
    ) -> list[dict]:
        """See BrokerAdapter.get_account_activities.

        Only FILL is modelled — the simulation charges no regulatory fees, so
        inventing FEE rows would fabricate costs the backtest never paid.
        """
        if activity_type != "FILL":
            return []
        start = 0
        if page_token:
            ids = [a["id"] for a in self._activities]
            # Unknown cursor ⇒ nothing left, rather than silently replaying
            # from the beginning and duplicating every fill.
            start = ids.index(page_token) + 1 if page_token in ids else len(ids)
        return [dict(a) for a in self._activities[start:start + page_size]]

    def get_order(self, broker_order_id: str) -> dict:
        """See BrokerAdapter.get_order — status only, never a fill source."""
        return self._order_status.get(broker_order_id, {
            "order_id": broker_order_id, "status": "unknown",
            "symbol": "", "qty_requested": 0,
        })

    def cancel_order(self, order_id: str) -> bool:
        if order_id in self._order_status:
            self._order_status[order_id]["status"] = "canceled"
        return True  # Simulation: all cancels succeed

    def get_portfolio_history(
        self, period: str = "1M", timeframe: str = "1D"
    ) -> dict:
        """See BrokerAdapter.get_portfolio_history.

        Served from the simulated equity curve. `period`/`timeframe` are
        accepted for shape compatibility but not resampled — the harness
        already advances one point per bar.
        """
        return {
            "timestamps": [t for t, _ in self._equity_curve],
            "equity": [e for _, e in self._equity_curve],
        }

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
        """Return the last known price.

        During backtest: this returns the PREVIOUS completed bar's close
        (since current_time is set to just before the current bar).
        This is equivalent to "last trade price" at market open — you know
        yesterday's close but not today's close.

        If _fill_price_bar is set (harness mode), return its open as the
        "current" price — this is the opening print.
        """
        if self._fill_price_bar and self._fill_price_bar.get("symbol") == symbol:
            # In harness mode: the "current price" is the bar's open
            price = self._fill_price_bar["open"]
            return {
                "symbol": symbol,
                "bid": price * 0.999,
                "ask": price * 1.001,
                "mid": price,
                "timestamp": self._fill_price_bar["timestamp"],
            }

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

    def get_tradeable_universe(self) -> list[str]:
        """Return all symbols that have daily data in the DB."""
        rows = self.repo.conn.execute(
            "SELECT DISTINCT symbol FROM price_data WHERE timeframe = '1Day'"
        ).fetchall()
        return [r["symbol"] for r in rows]

    def get_option_chain(self, underlying, **kwargs) -> list[dict]:
        raise NotImplementedError("Options simulation requires Phase 4 implementation")

    def get_option_snapshot(self, option_symbols) -> list[dict]:
        raise NotImplementedError("Options simulation requires Phase 4 implementation")

    def get_option_historical_iv(self, underlying, lookback_days=252) -> list[dict]:
        raise NotImplementedError("Options simulation requires Phase 4 implementation")

    def get_options_positions(self) -> list[dict]:
        raise NotImplementedError("Options simulation requires Phase 4 implementation")

    def place_multileg_order(self, legs, order_type, **kwargs):
        raise NotImplementedError("Options simulation requires Phase 4 implementation")
