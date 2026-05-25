"""Backtest harness — orchestrates bar-by-bar execution with workflow enforcement.

TEMPORAL MODEL (critical for correctness):
  When advance_bar() moves to bar N:
  - The agent sees: all completed bars (0 to N-1) + bar N's open price
  - The agent CANNOT see: bar N's high, low, close, volume (hasn't happened yet)
  - Orders placed at bar N fill at bar N's open + slippage
  - After the agent decides, the bar "completes" internally (for position P&L tracking)

  This matches real trading: you see the open, you decide, the day plays out.
  You never know the close before it happens.

DESIGN RULES:
  - The harness NEVER makes trading decisions — only the agent does
  - The validator tracks ACTUAL tool calls (server-side), not agent self-reports
  - A decision MUST be logged before the next bar can be advanced
"""

from datetime import datetime, timedelta

from broker.simulation import SimulationBrokerAdapter
from backtest.validator import WorkflowValidator
from backtest.logger import BacktestLogger
from persistence.repository import Repository


class BacktestHarness:
    def __init__(self, repo: Repository):
        self.repo = repo
        self.logger = BacktestLogger(repo)
        self.validator = WorkflowValidator()
        self.broker: SimulationBrokerAdapter | None = None
        self.run_id: str | None = None
        self._bars: list[dict] = []
        self._bar_index: int = 0
        self._symbols: list[str] = []
        self._current_bar: dict | None = None
        self._previous_bar: dict | None = None
        self._decision_logged: bool = True  # starts True (no bar to decide on yet)

    def start(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
        timeframe: str = "1Day",
        initial_capital: float = 100000.0,
        sop_version: str = "",
    ) -> str:
        self._symbols = symbols
        all_bars = []
        for sym in symbols:
            bars = self.repo.query_price_data(sym, start_date, end_date, timeframe)
            all_bars.extend(bars)
        all_bars.sort(key=lambda b: b["timestamp"])
        seen = set()
        self._bars = []
        for bar in all_bars:
            key = (bar["symbol"], bar["timestamp"])
            if key not in seen:
                seen.add(key)
                self._bars.append(bar)

        self._bar_index = 0
        self._decision_logged = True

        self.broker = SimulationBrokerAdapter(
            repo=self.repo,
            initial_capital=initial_capital,
            slippage_pct=0.05,
            timeframe=timeframe,
        )

        self.run_id = self.logger.create_run(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            timeframe=timeframe,
            initial_capital=initial_capital,
            sop_version=sop_version,
        )
        return self.run_id

    def advance_bar(self) -> dict | None:
        """Advance to the next bar. Returns bar open + previous bar's data.

        ENFORCEMENT: Refuses to advance if no decision was logged for the current bar.
        This prevents the agent from skipping bars without recording reasoning.
        """
        if not self._decision_logged and self._current_bar is not None:
            return {"error": "Must log a decision for the current bar before advancing. Call log_backtest_decision first."}

        if self._bar_index >= len(self._bars):
            return None

        # The previous bar is now "completed" — agent had its chance to act
        self._previous_bar = self._current_bar

        bar = self._bars[self._bar_index]
        self._current_bar = bar
        self._bar_index += 1

        # Set simulation clock to JUST BEFORE this bar's close.
        # This means:
        #   - query_price_data will return bars UP TO (but not including) this bar's close
        #   - The broker's _get_current_bar uses data <= current_time
        #   - We set time to bar's timestamp which includes this bar in queries
        #
        # CRITICAL: We set a "previous bar" time so that indicators are computed
        # using only completed bars (not including current bar's close).
        # The simulation broker will see up to the PREVIOUS bar for data queries,
        # but fills orders at the CURRENT bar's open.
        ts = bar["timestamp"]
        try:
            bar_time = datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            bar_time = datetime.strptime(str(ts), "%Y-%m-%d")

        # Set broker time to 1 second before this bar's timestamp.
        # This ensures query_price_data returns bars BEFORE this one,
        # so indicators use only completed bars.
        self.broker.set_time(bar_time - timedelta(seconds=1))

        # Store the actual bar time for fill price
        self.broker._fill_price_bar = bar  # the bar whose open is the fill price

        # Reset state for new bar
        self.validator.reset()
        self._decision_logged = False

        # Return ONLY what the agent would know at market open:
        # - The current bar's open price (market just opened)
        # - The previous bar's full data (yesterday completed)
        # - Account state based on previous close (not current)
        result = {
            "bar_index": self._bar_index - 1,
            "timestamp": bar["timestamp"],
            "symbol": bar["symbol"],
            "open": bar["open"],  # current bar's open — the only "now" data
            "remaining": len(self._bars) - self._bar_index,
        }

        # Include previous bar for context (completed bar — full data OK)
        if self._previous_bar and self._previous_bar["symbol"] == bar["symbol"]:
            result["previous_bar"] = {
                "timestamp": self._previous_bar["timestamp"],
                "open": self._previous_bar["open"],
                "high": self._previous_bar["high"],
                "low": self._previous_bar["low"],
                "close": self._previous_bar["close"],
                "volume": self._previous_bar.get("volume", 0),
            }

        return result

    def record_tool_call(self, tool_name: str) -> None:
        """Record that an MCP tool was actually called (server-side tracking)."""
        self.validator.record_tool_call(tool_name)

    def record_decision(
        self,
        symbol: str,
        phase: str,
        decision: str,
        reasoning: str,
        input_state: dict,
        rules_evaluated: list[dict],
        score: float | None = None,
        trade_plan: dict | None = None,
    ) -> str:
        """Log the agent's decision for the current bar.

        IMPORTANT: tools_called is NOT a parameter — it's taken from the validator's
        server-side tracking. The agent cannot self-report which tools it called.
        """
        # Use server-tracked tool calls, not agent self-report
        actual_tools_called = self.validator.get_calls()

        validation = self.validator.validate(phase, decision)

        self._decision_logged = True

        return self.logger.log_decision(
            run_id=self.run_id,
            bar_index=self._bar_index - 1,
            timestamp=self._current_bar["timestamp"] if self._current_bar else "",
            symbol=symbol,
            phase=phase,
            input_state=input_state,
            tools_called=actual_tools_called,
            rules_evaluated=rules_evaluated,
            score=score,
            decision=decision,
            reasoning=reasoning,
            trade_plan=trade_plan,
            workflow_valid=validation["valid"],
            violation_details=", ".join(validation["missing"]) if not validation["valid"] else "",
        )

    def get_broker(self) -> SimulationBrokerAdapter:
        return self.broker

    def get_run_id(self) -> str:
        return self.run_id

    def is_done(self) -> bool:
        return self._bar_index >= len(self._bars)

    def get_current_bar_full(self) -> dict | None:
        """INTERNAL ONLY: Returns current bar's full OHLCV for position monitoring.
        This should NOT be exposed to the agent — only used by the mechanical
        stop/target checker after the agent has made its decision.
        """
        return self._current_bar
