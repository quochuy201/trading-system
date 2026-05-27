"""Backtest harness v3 — daily cycle + mechanical monitoring.

DESIGN:
  The backtest simulates live trading using the same skills and tools.
  The harness provides the infrastructure (time management, data, mechanical checks).
  The LLM agent makes all entry/exit DECISIONS via skills.

DAILY CYCLE:
  1. advance_to_next_day() → sets clock to first bar of new trading day
  2. LLM runs scanner / does DD / enters positions
  3. step_bar() loop → advances intraday bars with mechanical checks
  4. LLM invoked only on EVENTS (stop hit, large drop, approaching stop)
  5. End of day → roll to next day

MECHANICAL MONITORING (no LLM needed):
  - Stop loss: previous bar close below stop → exit at next bar open
  - Take profit: bar high touches target → exit at target price
  - Trailing stop: update when price makes new high; exit when broken
  - Time stop: exceeded max hold bars → exit at bar open

EVENT TRIGGERS (LLM called):
  - Large drop (> 3% in one bar)
  - Approaching stop (within 0.5%)
  - Dead money (5+ days, never reached +0.5R)
  - Volume spike (> 3x average of recent bars)
"""

from datetime import datetime, timedelta
from collections import defaultdict

from broker.simulation import SimulationBrokerAdapter
from backtest.validator import WorkflowValidator
from backtest.logger import BacktestLogger
from persistence.repository import Repository


class Position:
    """Tracks a simulated position with stop/target/trail state."""

    def __init__(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: int,
        stop_loss: float,
        take_profit: float,
        atr: float,
        entry_bar_idx: int,
        entry_timestamp: str,
        reasoning: str,
        time_stop_bars: int = 105,
    ):
        self.symbol = symbol
        self.side = side
        self.entry_price = entry_price
        self.quantity = quantity
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.atr = atr
        self.entry_bar_idx = entry_bar_idx
        self.entry_timestamp = entry_timestamp
        self.reasoning = reasoning
        self.time_stop_bars = time_stop_bars

        self.trailing_stop = stop_loss
        self.highest_close = entry_price
        self.prev_close = entry_price
        self.bars_held = 0
        self.max_favorable = 0.0
        self.max_adverse = 0.0

        self.status = "open"
        self.exit_price: float | None = None
        self.exit_reason: str | None = None
        self.exit_timestamp: str | None = None
        self.exit_bar_idx: int | None = None
        self.pnl: float = 0.0
        self.pnl_pct: float = 0.0
        self.r_multiple: float = 0.0


class BacktestHarness:
    """Orchestrates bar-by-bar backtest with daily cycle and mechanical monitoring."""

    def __init__(self, repo: Repository):
        self.repo = repo
        self.logger = BacktestLogger(repo)
        self.validator = WorkflowValidator()
        self.broker: SimulationBrokerAdapter | None = None
        self.run_id: str | None = None

        # Config
        self.monitor_timeframe: str = "1Hour"
        self.scanner_mode: bool = False
        self.initial_capital: float = 100000.0

        # State
        self.positions: list[Position] = []
        self.closed_trades: list[Position] = []
        self.trade_log: list[dict] = []
        self.daily_log: list[dict] = []

        # Time management
        self._trading_days: list[str] = []
        self._current_day_idx: int = -1
        self._current_day: str | None = None
        self._day_bars: dict[str, list[dict]] = {}
        self._day_bar_idx: int = 0
        self._global_bar_idx: int = 0

    def start(
        self,
        start_date: str,
        end_date: str,
        monitor_timeframe: str = "1Hour",
        initial_capital: float = 100000.0,
        scanner_mode: bool = False,
        symbols: list[str] | None = None,
        sop_version: str = "",
    ) -> str:
        """Initialize backtest. Daily data for scanner should already be loaded."""
        self.monitor_timeframe = monitor_timeframe
        self.scanner_mode = scanner_mode
        self.initial_capital = initial_capital

        self.broker = SimulationBrokerAdapter(
            repo=self.repo,
            initial_capital=initial_capital,
            slippage_pct=0.05,
            timeframe=monitor_timeframe,
        )

        # Discover trading days from daily bar data (SPY as reference)
        daily_bars = self.repo.query_price_data("SPY", start_date, end_date, "1Day")
        self._trading_days = sorted(set(b["timestamp"][:10] for b in daily_bars))

        if not self._trading_days:
            raise ValueError(f"No trading days found between {start_date} and {end_date}")

        self._current_day_idx = -1

        self.run_id = self.logger.create_run(
            symbols=symbols or [],
            start_date=start_date,
            end_date=end_date,
            timeframe=monitor_timeframe,
            initial_capital=initial_capital,
            sop_version=sop_version,
        )
        return self.run_id

    def advance_to_next_day(self) -> dict | None:
        """Move to the next trading day. Returns day info or None if backtest complete."""
        self._current_day_idx += 1
        if self._current_day_idx >= len(self._trading_days):
            return None

        self._current_day = self._trading_days[self._current_day_idx]
        self._day_bars = {}
        self._day_bar_idx = 0

        # Set sim clock to start of this trading day
        day_dt = datetime.fromisoformat(self._current_day)
        self.broker.set_time(day_dt + timedelta(hours=9, minutes=30))

        # Summary of open positions
        open_positions = [
            {
                "symbol": p.symbol,
                "entry_price": p.entry_price,
                "quantity": p.quantity,
                "stop_loss": p.stop_loss,
                "take_profit": p.take_profit,
                "bars_held": p.bars_held,
                "unrealized_pct": round(
                    ((p.prev_close - p.entry_price) / p.entry_price) * 100, 2
                ),
            }
            for p in self.positions if p.status == "open"
        ]

        return {
            "date": self._current_day,
            "day_number": self._current_day_idx + 1,
            "total_days": len(self._trading_days),
            "open_positions": open_positions,
            "open_count": len(open_positions),
            "account": self.broker.get_account(),
        }

    def load_day_bars(self, symbols: list[str]) -> dict:
        """Load intraday bars for given symbols for the current day.

        Called after scanner identifies candidates (+ any open position symbols).
        Only loads what's needed for today's monitoring.
        """
        if not self._current_day:
            return {"error": "No active day. Call advance_to_next_day first."}

        day = self._current_day
        loaded = {}

        for sym in symbols:
            day_end = day + "T23:59:59"
            bars = self.repo.query_price_data(sym, day, day_end, self.monitor_timeframe)
            # Filter to market hours only (14:00-21:00 UTC = 9:30-4:00 ET)
            market_bars = []
            for b in bars:
                ts = b["timestamp"]
                try:
                    dt = datetime.fromisoformat(ts)
                    if 14 <= dt.hour < 21:
                        market_bars.append(b)
                except (ValueError, TypeError):
                    if ts.startswith(day):
                        market_bars.append(b)

            if market_bars:
                self._day_bars[sym] = market_bars
                loaded[sym] = len(market_bars)

        self._day_bar_idx = 0
        return {
            "day": day,
            "symbols_loaded": loaded,
            "total_bars_per_symbol": max(loaded.values()) if loaded else 0,
        }

    def step_bar(self) -> dict:
        """Advance one intraday bar. Run mechanical checks on all positions.

        Returns:
          - {"status": "nothing"} if no action needed
          - {"status": "events", "events": [...]} if LLM attention needed
          - {"status": "day_complete"} if all bars for today are done
        """
        if not self._day_bars:
            return {"status": "day_complete", "day": self._current_day}

        # Find max bars available today
        max_bars = max(len(bars) for bars in self._day_bars.values()) if self._day_bars else 0

        if self._day_bar_idx >= max_bars:
            # End of day: update prev_close for all positions
            for pos in self.positions:
                if pos.status == "open" and pos.symbol in self._day_bars:
                    bars = self._day_bars[pos.symbol]
                    if bars:
                        pos.prev_close = float(bars[-1]["close"])
            return {"status": "day_complete", "day": self._current_day}

        self._global_bar_idx += 1
        bar_idx = self._day_bar_idx
        self._day_bar_idx += 1

        # Get current timestamp from any available symbol
        current_ts = None
        for sym, bars in self._day_bars.items():
            if bar_idx < len(bars):
                current_ts = bars[bar_idx]["timestamp"]
                break

        if current_ts:
            try:
                bar_time = datetime.fromisoformat(current_ts)
                self.broker.set_time(bar_time)
            except (ValueError, TypeError):
                pass

        # Run mechanical checks on all open positions
        events = []
        auto_exits = []

        for pos in self.positions:
            if pos.status != "open":
                continue
            if pos.symbol not in self._day_bars:
                continue

            bars = self._day_bars[pos.symbol]
            if bar_idx >= len(bars):
                continue

            bar = bars[bar_idx]
            bar_open = float(bar["open"])
            bar_high = float(bar["high"])
            bar_low = float(bar["low"])
            bar_close = float(bar["close"])
            bar_volume = float(bar.get("volume", 0))

            pos.bars_held += 1

            # Track excursions
            unrealized_pct = ((bar_high - pos.entry_price) / pos.entry_price) * 100
            adverse_pct = ((bar_low - pos.entry_price) / pos.entry_price) * 100
            pos.max_favorable = max(pos.max_favorable, unrealized_pct)
            pos.max_adverse = min(pos.max_adverse, adverse_pct)

            # --- MECHANICAL CHECKS ---

            # 1. Stop loss (close-based): PREVIOUS bar closed below stop
            if pos.prev_close < pos.stop_loss and pos.bars_held > 1:
                exit_price = bar_open * (1 - self.broker.slippage_pct / 100)
                auto_exits.append((pos, exit_price, "stop_loss", current_ts))
                continue

            # 2. Take profit: bar high reaches target
            if bar_high >= pos.take_profit:
                exit_price = pos.take_profit
                auto_exits.append((pos, exit_price, "take_profit", current_ts))
                continue

            # 3. Trailing stop broken: prev close below trailing stop
            if pos.trailing_stop > pos.stop_loss and pos.prev_close < pos.trailing_stop:
                exit_price = bar_open * (1 - self.broker.slippage_pct / 100)
                auto_exits.append((pos, exit_price, "trailing_stop", current_ts))
                continue

            # 4. Time stop
            if pos.bars_held >= pos.time_stop_bars:
                exit_price = bar_open * (1 - self.broker.slippage_pct / 100)
                auto_exits.append((pos, exit_price, "time_stop", current_ts))
                continue

            # --- TRAILING STOP UPDATE ---
            if bar_close > pos.highest_close:
                pos.highest_close = bar_close
                # After 1R profit, start trailing below highest close
                # Use 2×ATR for volatile stocks (ATR% > 3%), 1.5×ATR otherwise
                risk = pos.entry_price - pos.stop_loss
                if risk > 0 and (bar_close - pos.entry_price) >= risk:
                    atr_pct = (pos.atr / pos.entry_price) * 100
                    trail_multiplier = 2.0 if atr_pct > 3 else 1.5
                    new_trail = bar_close - (trail_multiplier * pos.atr)
                    if new_trail > pos.trailing_stop:
                        pos.trailing_stop = new_trail

            # --- EVENT DETECTION (for LLM) ---
            pct_change = ((bar_close - bar_open) / bar_open) * 100 if bar_open > 0 else 0

            # Large drop
            if pct_change < -3:
                events.append({
                    "type": "large_drop",
                    "symbol": pos.symbol,
                    "pct_change": round(pct_change, 2),
                    "bar_close": bar_close,
                    "stop_loss": pos.stop_loss,
                    "timestamp": current_ts,
                })

            # Approaching stop (within 0.5%)
            stop_distance_pct = ((bar_close - pos.stop_loss) / bar_close) * 100 if bar_close > 0 else 99
            if 0 < stop_distance_pct < 0.5:
                events.append({
                    "type": "approaching_stop",
                    "symbol": pos.symbol,
                    "price": bar_close,
                    "stop_loss": pos.stop_loss,
                    "distance_pct": round(stop_distance_pct, 2),
                    "timestamp": current_ts,
                })

            # Dead money: 5+ days (35+ hourly bars), never reached +0.5R
            risk = pos.entry_price - pos.stop_loss
            if risk > 0 and pos.bars_held >= 35:
                best_r = pos.max_favorable / ((risk / pos.entry_price) * 100)
                if best_r < 0.5:
                    events.append({
                        "type": "dead_money",
                        "symbol": pos.symbol,
                        "bars_held": pos.bars_held,
                        "best_r": round(best_r, 2),
                        "current_price": bar_close,
                        "timestamp": current_ts,
                    })

            # Update prev_close for next bar's check
            pos.prev_close = bar_close

        # Process auto-exits
        for pos, exit_price, reason, ts in auto_exits:
            self._close_position(pos, exit_price, reason, ts)

        # Build response
        result = {
            "bar_index": self._day_bar_idx,
            "timestamp": current_ts,
            "bars_remaining_today": max_bars - self._day_bar_idx,
        }

        if auto_exits:
            result["exits"] = [
                {
                    "symbol": pos.symbol,
                    "exit_price": round(pos.exit_price, 2),
                    "reason": pos.exit_reason,
                    "pnl": round(pos.pnl, 2),
                    "pnl_pct": round(pos.pnl_pct, 2),
                    "r_multiple": round(pos.r_multiple, 2),
                    "bars_held": pos.bars_held,
                }
                for pos, _, _, _ in auto_exits
            ]

        if events:
            result["status"] = "events"
            result["events"] = events
        elif auto_exits:
            result["status"] = "exits"
        else:
            result["status"] = "nothing"

        return result

    def enter_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: int,
        stop_loss: float,
        take_profit: float,
        atr: float,
        reasoning: str,
        time_stop_bars: int = 105,
    ) -> dict:
        """Log a simulated entry. Called by LLM after DD and risk checks pass."""
        # Prevent duplicate positions in same symbol
        for p in self.positions:
            if p.symbol == symbol and p.status == "open":
                return {"error": f"Already have open position in {symbol}"}

        pos = Position(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            atr=atr,
            entry_bar_idx=self._global_bar_idx,
            entry_timestamp=self._day_bars.get(symbol, [{}])[min(self._day_bar_idx, len(self._day_bars.get(symbol, [])) - 1)].get("timestamp", self._current_day),
            reasoning=reasoning,
            time_stop_bars=time_stop_bars,
        )
        self.positions.append(pos)

        # Update broker state
        cost = entry_price * quantity
        self.broker.cash -= cost
        self.broker.positions[symbol] = {
            "quantity": quantity,
            "avg_price": entry_price,
        }

        entry_log = {
            "action": "entry",
            "symbol": symbol,
            "side": side,
            "price": round(entry_price, 2),
            "quantity": quantity,
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "atr": round(atr, 2),
            "reasoning": reasoning,
            "timestamp": pos.entry_timestamp,
            "day": self._current_day,
        }
        self.trade_log.append(entry_log)

        return entry_log

    def exit_position(self, symbol: str, exit_price: float, reason: str) -> dict | None:
        """Manually exit a position (LLM decision, not mechanical)."""
        for pos in self.positions:
            if pos.symbol == symbol and pos.status == "open":
                self._close_position(
                    pos, exit_price, reason,
                    self._day_bars.get(symbol, [{}])[min(self._day_bar_idx - 1, len(self._day_bars.get(symbol, [])) - 1)].get("timestamp", self._current_day)
                )
                return {
                    "symbol": symbol,
                    "exit_price": round(pos.exit_price, 2),
                    "reason": reason,
                    "pnl": round(pos.pnl, 2),
                    "pnl_pct": round(pos.pnl_pct, 2),
                    "r_multiple": round(pos.r_multiple, 2),
                }
        return None

    def _close_position(self, pos: Position, exit_price: float, reason: str, timestamp: str) -> None:
        """Close a position and record results."""
        pos.status = "closed"
        pos.exit_price = exit_price
        pos.exit_reason = reason
        pos.exit_timestamp = timestamp
        pos.exit_bar_idx = self._global_bar_idx

        pos.pnl = (exit_price - pos.entry_price) * pos.quantity
        pos.pnl_pct = ((exit_price - pos.entry_price) / pos.entry_price) * 100

        risk = pos.entry_price - pos.stop_loss
        if risk > 0:
            pos.r_multiple = (exit_price - pos.entry_price) / risk
        else:
            pos.r_multiple = 0.0

        self.closed_trades.append(pos)

        # Update broker state
        self.broker.cash += exit_price * pos.quantity
        if pos.symbol in self.broker.positions:
            del self.broker.positions[pos.symbol]

        exit_log = {
            "action": "exit",
            "symbol": pos.symbol,
            "price": round(exit_price, 2),
            "reason": reason,
            "pnl": round(pos.pnl, 2),
            "pnl_pct": round(pos.pnl_pct, 2),
            "r_multiple": round(pos.r_multiple, 2),
            "bars_held": pos.bars_held,
            "timestamp": timestamp,
            "day": self._current_day,
        }
        self.trade_log.append(exit_log)

    def force_close_all(self) -> list[dict]:
        """Close all open positions at last known price (end of backtest)."""
        results = []
        for pos in self.positions:
            if pos.status != "open":
                continue
            # Use last known close
            last_price = pos.prev_close
            self._close_position(pos, last_price, "end_of_backtest", self._current_day or "")
            results.append({
                "symbol": pos.symbol,
                "exit_price": round(pos.exit_price, 2),
                "pnl": round(pos.pnl, 2),
                "pnl_pct": round(pos.pnl_pct, 2),
            })
        return results

    def get_open_positions(self) -> list[dict]:
        """Return current open positions with monitoring state."""
        return [
            {
                "symbol": p.symbol,
                "entry_price": round(p.entry_price, 2),
                "quantity": p.quantity,
                "stop_loss": round(p.stop_loss, 2),
                "take_profit": round(p.take_profit, 2),
                "trailing_stop": round(p.trailing_stop, 2),
                "prev_close": round(p.prev_close, 2),
                "bars_held": p.bars_held,
                "unrealized_pct": round(((p.prev_close - p.entry_price) / p.entry_price) * 100, 2),
                "max_favorable_pct": round(p.max_favorable, 2),
                "max_adverse_pct": round(p.max_adverse, 2),
            }
            for p in self.positions if p.status == "open"
        ]

    def get_results(self) -> dict:
        """Compute final backtest results."""
        total_trades = len(self.closed_trades)
        if total_trades == 0:
            return {
                "total_trades": 0,
                "message": "No trades taken during backtest period.",
            }

        winners = [t for t in self.closed_trades if t.pnl > 0]
        losers = [t for t in self.closed_trades if t.pnl <= 0]
        total_pnl = sum(t.pnl for t in self.closed_trades)
        win_rate = len(winners) / total_trades * 100

        avg_winner = sum(t.pnl for t in winners) / len(winners) if winners else 0
        avg_loser = sum(t.pnl for t in losers) / len(losers) if losers else 0

        gross_profit = sum(t.pnl for t in winners)
        gross_loss = abs(sum(t.pnl for t in losers))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Max drawdown
        equity_curve = [self.initial_capital]
        for t in sorted(self.closed_trades, key=lambda x: x.exit_bar_idx or 0):
            equity_curve.append(equity_curve[-1] + t.pnl)
        peak = self.initial_capital
        max_dd = 0
        for eq in equity_curve:
            peak = max(peak, eq)
            max_dd = max(max_dd, peak - eq)

        final_equity = self.initial_capital + total_pnl

        return {
            "initial_capital": self.initial_capital,
            "final_equity": round(final_equity, 2),
            "total_pnl": round(total_pnl, 2),
            "return_pct": round(total_pnl / self.initial_capital * 100, 2),
            "total_trades": total_trades,
            "winners": len(winners),
            "losers": len(losers),
            "win_rate": round(win_rate, 1),
            "avg_winner": round(avg_winner, 2),
            "avg_loser": round(avg_loser, 2),
            "profit_factor": round(profit_factor, 2),
            "expectancy": round(total_pnl / total_trades, 2),
            "max_drawdown": round(max_dd, 2),
            "max_drawdown_pct": round(max_dd / self.initial_capital * 100, 2),
            "trades": [
                {
                    "symbol": t.symbol,
                    "side": t.side,
                    "entry_price": round(t.entry_price, 2),
                    "exit_price": round(t.exit_price, 2),
                    "quantity": t.quantity,
                    "pnl": round(t.pnl, 2),
                    "pnl_pct": round(t.pnl_pct, 2),
                    "r_multiple": round(t.r_multiple, 2),
                    "bars_held": t.bars_held,
                    "exit_reason": t.exit_reason,
                    "entry_date": t.entry_timestamp[:10] if t.entry_timestamp else "",
                    "exit_date": t.exit_timestamp[:10] if t.exit_timestamp else "",
                    "reasoning": t.reasoning,
                }
                for t in self.closed_trades
            ],
            "trade_log": self.trade_log,
        }

    def get_current_day(self) -> str | None:
        return self._current_day

    def get_day_bar_data(self, symbol: str, bar_idx: int | None = None) -> dict | None:
        """Get a specific bar for a symbol on the current day."""
        if symbol not in self._day_bars:
            return None
        bars = self._day_bars[symbol]
        idx = bar_idx if bar_idx is not None else max(0, self._day_bar_idx - 1)
        if idx < len(bars):
            return bars[idx]
        return None

    def is_done(self) -> bool:
        return self._current_day_idx >= len(self._trading_days)
