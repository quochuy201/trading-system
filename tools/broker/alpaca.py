"""Alpaca broker adapter implementation."""

import math
import os
from datetime import datetime, timedelta

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    StopOrderRequest,
    StopLimitOrderRequest,
    GetAssetsRequest,
    GetOptionContractsRequest,
    OptionLegRequest,
    OrderRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderType, AssetClass, AssetStatus, OrderClass, PositionIntent, ContractType
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import (
    StockLatestQuoteRequest,
    StockBarsRequest,
    OptionChainRequest,
    OptionSnapshotRequest,
    OptionBarsRequest,
)
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.data.enums import DataFeed, OptionsFeed

from analysis.options import parse_occ_symbol, implied_vol_from_price
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
        self.option_data_client = OptionHistoricalDataClient(
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
        req = StockLatestQuoteRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX)
        quotes = self.data_client.get_stock_latest_quote(req)
        quote = quotes[symbol]
        bid = float(quote.bid_price)
        ask = float(quote.ask_price)
        # Outside market hours IEX may return 0 for one side — use the other as mid
        if bid > 0 and ask > 0:
            mid = (bid + ask) / 2
        elif bid > 0:
            mid = bid
        elif ask > 0:
            mid = ask
        else:
            mid = 0.0
        return {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "bid_size": int(quote.bid_size),
            "ask_size": int(quote.ask_size),
            "timestamp": quote.timestamp.isoformat(),
        }

    def get_historical_data(
        self, symbol: str, start: datetime, end: datetime, timeframe: str = "1Day"
    ) -> list[dict]:
        tf = _TIMEFRAME_MAP.get(timeframe, TimeFrame(1, TimeFrameUnit.Day))
        req = StockBarsRequest(
            symbol_or_symbols=symbol, start=start, end=end, timeframe=tf,
            feed=DataFeed.IEX,
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

    def get_tradeable_universe(self) -> list[str]:
        """Return all active, tradeable US equities from Alpaca (excludes OTC)."""
        req = GetAssetsRequest(
            asset_class=AssetClass.US_EQUITY,
            status=AssetStatus.ACTIVE,
        )
        assets = self.trading_client.get_all_assets(req)
        return [
            a.symbol for a in assets
            if a.tradable and a.exchange in ("NYSE", "NASDAQ", "ARCA", "BATS")
            and not a.symbol.endswith("W")  # skip warrants
            and "." not in a.symbol  # skip preferred shares (BRK.B etc.)
        ]

    def get_option_chain(
        self,
        underlying: str,
        expiration_date_gte: str | None = None,
        expiration_date_lte: str | None = None,
        strike_price_gte: float | None = None,
        strike_price_lte: float | None = None,
        option_type: str | None = None,
    ) -> list[dict]:
        """Fetch option chain with greeks+IV for an underlying symbol.

        Uses Alpaca OptionHistoricalDataClient to fetch chain snapshots. Parses
        OCC symbols for metadata (strike, expiration, type). Returns a list of
        contract dicts with quote, IV, and greeks fields.

        Sample input:
            get_option_chain("AAPL", expiration_date_gte="2025-06-01",
                             expiration_date_lte="2025-06-30")

        Expected output:
            [{"symbol": "AAPL250620C00230000", "underlying": "AAPL",
              "strike": 230.0, "type": "C", "expiration": "250620",
              "dte": 18, "bid": 2.50, "ask": 2.60, "mid": 2.55,
              "volume": 1200, "open_interest": 5400, "iv": 0.28,
              "greeks": {"delta": 0.45, "gamma": 0.03, "theta": -0.05,
                         "vega": 0.12, "rho": 0.01}}, ...]
        """
        contract_type = None
        if option_type:
            ot = option_type.upper()
            if ot in ("C", "CALL"):
                contract_type = ContractType.CALL
            elif ot in ("P", "PUT"):
                contract_type = ContractType.PUT

        req_kwargs = {
            "underlying_symbol": underlying,
            "feed": OptionsFeed.INDICATIVE,  # Required for greeks+IV on paper accounts
        }
        if contract_type is not None:
            req_kwargs["type"] = contract_type
        if expiration_date_gte:
            req_kwargs["expiration_date_gte"] = expiration_date_gte
        if expiration_date_lte:
            req_kwargs["expiration_date_lte"] = expiration_date_lte
        if strike_price_gte is not None:
            req_kwargs["strike_price_gte"] = strike_price_gte
        if strike_price_lte is not None:
            req_kwargs["strike_price_lte"] = strike_price_lte

        req = OptionChainRequest(**req_kwargs)
        chain_data = self.option_data_client.get_option_chain(req)

        today = datetime.now().date()
        results = []
        for symbol, snapshot in chain_data.items():
            try:
                meta = parse_occ_symbol(symbol)
            except Exception:
                continue

            exp_str = meta["expiration"]  # YYMMDD
            try:
                exp_date = datetime.strptime("20" + exp_str, "%Y%m%d").date()
                dte = max(0, (exp_date - today).days)
            except ValueError:
                dte = 0

            quote = snapshot.latest_quote
            bid = float(quote.bid_price) if quote and quote.bid_price else 0.0
            ask = float(quote.ask_price) if quote and quote.ask_price else 0.0
            mid = (bid + ask) / 2

            trade = snapshot.latest_trade
            volume = int(trade.size) if trade and trade.size else 0

            iv = float(snapshot.implied_volatility) if snapshot.implied_volatility else 0.0

            greeks_obj = snapshot.greeks
            greeks = {}
            if greeks_obj:
                greeks = {
                    "delta": float(greeks_obj.delta) if greeks_obj.delta is not None else 0.0,
                    "gamma": float(greeks_obj.gamma) if greeks_obj.gamma is not None else 0.0,
                    "theta": float(greeks_obj.theta) if greeks_obj.theta is not None else 0.0,
                    "vega": float(greeks_obj.vega) if greeks_obj.vega is not None else 0.0,
                    "rho": float(greeks_obj.rho) if greeks_obj.rho is not None else 0.0,
                }

            results.append({
                "symbol": symbol,
                "underlying": meta["underlying"],
                "strike": meta["strike"],
                "type": meta["type"],
                "expiration": meta["expiration"],
                "dte": dte,
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "volume": volume,
                "open_interest": 0,  # not provided in chain snapshot
                "iv": iv,
                "greeks": greeks,
            })

        return results

    def get_option_snapshot(self, option_symbols: list[str]) -> list[dict]:
        """Fetch real-time snapshot (quote + greeks + IV) for specific option contracts.

        Sample input:
            get_option_snapshot(["AAPL250620C00230000", "AAPL250620P00220000"])

        Expected output:
            [{"symbol": "AAPL250620C00230000", "underlying": "AAPL",
              "strike": 230.0, "type": "C", "expiration": "250620",
              "dte": 18, "bid": 2.50, "ask": 2.60, "mid": 2.55,
              "volume": 1200, "open_interest": 0, "iv": 0.28,
              "greeks": {"delta": 0.45, ...}}, ...]
        """
        if not option_symbols:
            return []

        req = OptionSnapshotRequest(
            symbol_or_symbols=option_symbols, feed=OptionsFeed.INDICATIVE
        )
        snap_data = self.option_data_client.get_option_snapshot(req)

        today = datetime.now().date()
        results = []
        for symbol, snapshot in snap_data.items():
            try:
                meta = parse_occ_symbol(symbol)
            except Exception:
                continue

            exp_str = meta["expiration"]
            try:
                exp_date = datetime.strptime("20" + exp_str, "%Y%m%d").date()
                dte = max(0, (exp_date - today).days)
            except ValueError:
                dte = 0

            quote = snapshot.latest_quote
            bid = float(quote.bid_price) if quote and quote.bid_price else 0.0
            ask = float(quote.ask_price) if quote and quote.ask_price else 0.0
            mid = (bid + ask) / 2

            trade = snapshot.latest_trade
            volume = int(trade.size) if trade and trade.size else 0

            iv = float(snapshot.implied_volatility) if snapshot.implied_volatility else 0.0

            greeks_obj = snapshot.greeks
            greeks = {}
            if greeks_obj:
                greeks = {
                    "delta": float(greeks_obj.delta) if greeks_obj.delta is not None else 0.0,
                    "gamma": float(greeks_obj.gamma) if greeks_obj.gamma is not None else 0.0,
                    "theta": float(greeks_obj.theta) if greeks_obj.theta is not None else 0.0,
                    "vega": float(greeks_obj.vega) if greeks_obj.vega is not None else 0.0,
                    "rho": float(greeks_obj.rho) if greeks_obj.rho is not None else 0.0,
                }

            results.append({
                "symbol": symbol,
                "underlying": meta["underlying"],
                "strike": meta["strike"],
                "type": meta["type"],
                "expiration": meta["expiration"],
                "dte": dte,
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "volume": volume,
                "open_interest": 0,
                "iv": iv,
                "greeks": greeks,
            })

        return results

    def get_option_historical_iv(
        self, underlying: str, lookback_days: int = 252
    ) -> list[dict]:
        """Fetch historical IV data points for IV Rank calculation.

        Finds the longest-DTE ATM contract, fetches daily option bars to get
        implied vol proxied via mid-price and Black-Scholes inversion. Falls back
        to empty list if no contracts are found.

        Sample input:
            get_option_historical_iv("AAPL", lookback_days=252)

        Expected output:
            [{"date": "2024-06-01", "iv": 0.28}, {"date": "2024-06-02", "iv": 0.29}, ...]
        """
        today = datetime.now().date()
        start_date = today - timedelta(days=lookback_days)

        # Get current stock price to filter to near-ATM contracts only
        try:
            quote = self.get_market_data(underlying)
            stock_price = quote.get("mid", 0) or quote.get("bid", 0)
        except Exception:
            stock_price = 0
        if stock_price <= 0:
            return []

        # Find a suitable ATM contract within the strategy's DTE window.
        # SOP uses 30-120 DTE across all engines. Going further is wasteful and
        # gives newer (= less history) contracts. Filter to ATM ± 10% to keep
        # the result set small (API caps at 1000 per page).
        exp_gte = (today + timedelta(days=30)).strftime("%Y-%m-%d")
        exp_lte = (today + timedelta(days=120)).strftime("%Y-%m-%d")

        contracts_req = GetOptionContractsRequest(
            underlying_symbols=[underlying],
            expiration_date_gte=exp_gte,
            expiration_date_lte=exp_lte,
            status="active",
            type=ContractType.CALL,
            strike_price_gte=str(round(stock_price * 0.9, 2)),
            strike_price_lte=str(round(stock_price * 1.1, 2)),
            limit=1000,
        )
        try:
            contracts_resp = self.trading_client.get_option_contracts(contracts_req)
            # Response is OptionContractsResponse with .option_contracts field
            contracts = contracts_resp.option_contracts or []
        except Exception:
            return []

        if not contracts:
            return []

        # Pick the contract with the longest DTE (furthest expiration)
        def _dte(c):
            try:
                return (datetime.strptime(str(c.expiration_date), "%Y-%m-%d").date() - today).days
            except Exception:
                return 0

        target_contract = max(contracts, key=_dte)
        option_symbol = target_contract.symbol

        # Fetch daily option bars for the lookback period
        bar_start = datetime.combine(start_date, datetime.min.time())
        bar_end = datetime.combine(today, datetime.min.time())

        try:
            bar_req = OptionBarsRequest(
                symbol_or_symbols=option_symbol,
                start=bar_start,
                end=bar_end,
                timeframe=TimeFrame(1, TimeFrameUnit.Day),
            )
            bars_resp = self.option_data_client.get_option_bars(bar_req)
            # BarSet supports __getitem__; use .data dict for safety
            bars = bars_resp.data.get(option_symbol, []) if hasattr(bars_resp, "data") else []
        except Exception:
            return []

        if not bars:
            return []

        # Fetch underlying stock bars for the same period (needed for BS inversion)
        try:
            stock_req = StockBarsRequest(
                symbol_or_symbols=underlying,
                start=bar_start,
                end=bar_end,
                timeframe=TimeFrame(1, TimeFrameUnit.Day),
                feed=DataFeed.IEX,
            )
            stock_resp = self.data_client.get_stock_bars(stock_req)
            stock_bars = stock_resp.data.get(underlying, []) if hasattr(stock_resp, "data") else []
            stock_price_by_date = {
                bar.timestamp.date().isoformat(): float(bar.close)
                for bar in stock_bars
            }
        except Exception:
            stock_price_by_date = {}

        # Parse contract metadata for BS inputs
        try:
            meta = parse_occ_symbol(option_symbol)
            strike = meta["strike"]
            opt_type = "call" if meta["type"] == "C" else "put"
            exp_date = datetime.strptime("20" + meta["expiration"], "%Y%m%d").date()
        except Exception:
            return []

        results = []
        for bar in bars:
            bar_date = bar.timestamp.date()
            date_str = bar_date.isoformat()
            dte = max(1, (exp_date - bar_date).days)
            mid = (float(bar.open) + float(bar.close)) / 2
            stock_price = stock_price_by_date.get(date_str)
            if not stock_price or stock_price <= 0 or mid <= 0:
                continue
            iv = implied_vol_from_price(mid, stock_price, strike, dte, 0.05, opt_type)
            if not math.isnan(iv) and iv > 0:
                results.append({"date": date_str, "iv": iv})

        # Sort ascending by date
        results.sort(key=lambda x: x["date"])
        return results

    def get_options_positions(self) -> list[dict]:
        """Get all open option positions (filtered by asset class).

        Fetches all positions from the account, filters for options (asset_class
        == "us_option"), enriches each with greeks via a secondary snapshot call,
        and parses the OCC symbol for metadata.

        Sample input: (no parameters)

        Expected output:
            [{"symbol": "AAPL250620C00230000", "underlying": "AAPL",
              "strike": 230.0, "type": "C", "expiration": "250620",
              "quantity": 2, "side": "long", "entry_price": 2.50,
              "current_price": 3.10, "unrealized_pnl": 120.0,
              "unrealized_pnl_pct": 24.0,
              "greeks": {"delta": 0.45, "gamma": 0.03, ...}}, ...]
        """
        all_positions = self.trading_client.get_all_positions()
        option_positions = [
            p for p in all_positions
            if hasattr(p, "asset_class") and str(p.asset_class).lower() in ("us_option", "usoptionable")
            or (hasattr(p, "asset_class") and "option" in str(p.asset_class).lower())
        ]

        if not option_positions:
            return []

        # Enrich with greeks via snapshot
        symbols = [p.symbol for p in option_positions]
        snapshot_map: dict[str, dict] = {}
        try:
            snapshots = self.get_option_snapshot(symbols)
            snapshot_map = {s["symbol"]: s for s in snapshots}
        except Exception:
            pass

        results = []
        for p in option_positions:
            try:
                meta = parse_occ_symbol(p.symbol)
            except Exception:
                meta = {"underlying": p.symbol, "expiration": "", "type": "C", "strike": 0.0}

            snap = snapshot_map.get(p.symbol, {})
            greeks = snap.get("greeks", {})

            results.append({
                "symbol": p.symbol,
                "underlying": meta["underlying"],
                "strike": meta["strike"],
                "type": meta["type"],
                "expiration": meta["expiration"],
                "quantity": int(p.qty),
                "side": p.side.value if hasattr(p.side, "value") else str(p.side),
                "entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "unrealized_pnl": float(p.unrealized_pl),
                "unrealized_pnl_pct": float(p.unrealized_plpc) * 100,
                "greeks": greeks,
            })

        return results

    def place_multileg_order(
        self,
        legs: list[dict],
        order_type: str,
        limit_price: float | None = None,
        time_in_force: str = "day",
    ) -> TradeTransaction:
        """Place a multi-leg option order (spreads).

        Each leg dict must include: symbol, side (buy_to_open/buy_to_close/
        sell_to_open/sell_to_close), ratio_qty.

        Sample input:
            place_multileg_order(
                legs=[
                    {"symbol": "AAPL250620C00230000", "side": "buy_to_open", "ratio_qty": 1},
                    {"symbol": "AAPL250620C00240000", "side": "sell_to_open", "ratio_qty": 1},
                ],
                order_type="limit",
                limit_price=1.50,
                time_in_force="day",
            )

        Expected output:
            TradeTransaction with broker_order_id, status="submitted"
        """
        _tif_map = {
            "day": TimeInForce.DAY,
            "gtc": TimeInForce.GTC,
        }
        tif = _tif_map.get(time_in_force.lower(), TimeInForce.DAY)

        _intent_map = {
            "buy_to_open": PositionIntent.BUY_TO_OPEN,
            "buy_to_close": PositionIntent.BUY_TO_CLOSE,
            "sell_to_open": PositionIntent.SELL_TO_OPEN,
            "sell_to_close": PositionIntent.SELL_TO_CLOSE,
        }

        option_legs = []
        for leg in legs:
            intent = _intent_map.get(leg["side"].lower())
            if intent is None:
                raise ValueError(f"Invalid leg side: {leg['side']}")
            option_legs.append(
                OptionLegRequest(
                    symbol=leg["symbol"],
                    ratio_qty=int(leg["ratio_qty"]),
                    position_intent=intent,
                )
            )

        # Shared kwargs for all multi-leg order types
        shared_kwargs = {
            "order_class": OrderClass.MLEG,
            "time_in_force": tif,
            "legs": option_legs,
            "qty": 1,  # required for mleg; number of spread contracts to trade
            "side": OrderSide.BUY,  # required by base validator; direction is in position_intent
        }

        if order_type.lower() == "market":
            order_req = MarketOrderRequest(**shared_kwargs)
        else:
            # Default to limit
            if limit_price is None:
                raise ValueError("limit_price is required for limit multi-leg orders")
            order_req = LimitOrderRequest(**shared_kwargs, limit_price=limit_price)
        order = self.trading_client.submit_order(order_req)

        return TradeTransaction(
            transaction_id=str(order.id),
            symbol=legs[0]["symbol"] if legs else "MULTILEG",
            side=legs[0]["side"] if legs else "buy",
            order_type=order_type,
            quantity=sum(int(leg["ratio_qty"]) for leg in legs),
            price=float(order.filled_avg_price) if order.filled_avg_price else 0.0,
            broker_order_id=str(order.id),
            status=str(order.status.value) if order.status else "submitted",
        )
