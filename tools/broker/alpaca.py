"""Alpaca broker adapter implementation."""

import os
from datetime import datetime

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    StopOrderRequest,
    StopLimitOrderRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderType
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import (
    StockLatestQuoteRequest,
    StockBarsRequest,
)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from broker.adapter import BrokerAdapter
from models import TradeTransaction


_TIMEFRAME_MAP = {
    "1Min": TimeFrame(1, TimeFrameUnit.Minute),
    "5Min": TimeFrame(5, TimeFrameUnit.Minute),
    "15Min": TimeFrame(15, TimeFrameUnit.Minute),
    "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
    "1Day": TimeFrame(1, TimeFrameUnit.Day),
}


class AlpacaBrokerAdapter(BrokerAdapter):
    """Alpaca paper/live trading adapter."""

    def __init__(
        self,
        api_key: str | None = None,
        secret_key: str | None = None,
        paper: bool = True,
    ):
        self.api_key = api_key or os.environ["ALPACA_API_KEY"]
        self.secret_key = secret_key or os.environ["ALPACA_SECRET_KEY"]
        self.paper = paper
        self.trading_client = TradingClient(
            self.api_key, self.secret_key, paper=paper
        )
        self.data_client = StockHistoricalDataClient(
            self.api_key, self.secret_key
        )

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: int,
        limit_price: float | None = None,
        stop_price: float | None = None,
    ) -> TradeTransaction:
        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL

        if order_type == "market":
            req = MarketOrderRequest(
                symbol=symbol, qty=quantity, side=order_side,
                time_in_force=TimeInForce.DAY,
            )
        elif order_type == "limit":
            req = LimitOrderRequest(
                symbol=symbol, qty=quantity, side=order_side,
                time_in_force=TimeInForce.DAY, limit_price=limit_price,
            )
        elif order_type == "stop":
            req = StopOrderRequest(
                symbol=symbol, qty=quantity, side=order_side,
                time_in_force=TimeInForce.DAY, stop_price=stop_price,
            )
        elif order_type == "stop_limit":
            req = StopLimitOrderRequest(
                symbol=symbol, qty=quantity, side=order_side,
                time_in_force=TimeInForce.DAY,
                limit_price=limit_price, stop_price=stop_price,
            )
        else:
            raise ValueError(f"Unsupported order type: {order_type}")

        order = self.trading_client.submit_order(req)

        return TradeTransaction(
            transaction_id=str(order.id),
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=int(order.qty),
            price=float(order.filled_avg_price) if order.filled_avg_price else 0.0,
            broker_order_id=str(order.id),
            status=str(order.status.value) if order.status else "submitted",
        )

    def cancel_order(self, order_id: str) -> bool:
        try:
            self.trading_client.cancel_order_by_id(order_id)
            return True
        except Exception:
            return False

    def get_positions(self) -> list[dict]:
        positions = self.trading_client.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "quantity": int(p.qty),
                "side": p.side.value,
                "entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "unrealized_pnl": float(p.unrealized_pl),
                "unrealized_pnl_pct": float(p.unrealized_plpc) * 100,
            }
            for p in positions
        ]

    def get_account(self) -> dict:
        acct = self.trading_client.get_account()
        return {
            "equity": float(acct.equity),
            "cash": float(acct.cash),
            "buying_power": float(acct.buying_power),
            "portfolio_value": float(acct.portfolio_value or acct.equity),
            "daily_pnl": float(acct.equity) - float(acct.last_equity),
        }

    def get_market_data(self, symbol: str) -> dict:
        req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
        quotes = self.data_client.get_stock_latest_quote(req)
        quote = quotes[symbol]
        return {
            "symbol": symbol,
            "bid": float(quote.bid_price),
            "ask": float(quote.ask_price),
            "mid": (float(quote.bid_price) + float(quote.ask_price)) / 2,
            "bid_size": int(quote.bid_size),
            "ask_size": int(quote.ask_size),
            "timestamp": quote.timestamp.isoformat(),
        }

    def get_historical_data(
        self, symbol: str, start: datetime, end: datetime, timeframe: str = "1Day"
    ) -> list[dict]:
        tf = _TIMEFRAME_MAP.get(timeframe, TimeFrame(1, TimeFrameUnit.Day))
        req = StockBarsRequest(
            symbol_or_symbols=symbol, start=start, end=end, timeframe=tf
        )
        bars = self.data_client.get_stock_bars(req)
        return [
            {
                "symbol": symbol,
                "timestamp": bar.timestamp.isoformat(),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": int(bar.volume),
                "timeframe": timeframe,
            }
            for bar in bars[symbol]
        ]
