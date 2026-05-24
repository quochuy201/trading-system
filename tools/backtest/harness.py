"""Backtest harness — orchestrates bar-by-bar execution with workflow enforcement."""

from datetime import datetime

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
        if self._bar_index >= len(self._bars):
            return None

        bar = self._bars[self._bar_index]
        self._current_bar = bar
        self._bar_index += 1

        ts = bar["timestamp"]
        try:
            self.broker.set_time(datetime.fromisoformat(ts))
        except (ValueError, TypeError):
            self.broker.set_time(datetime.strptime(str(ts), "%Y-%m-%d"))

        self.validator.reset()

        return {
            "bar_index": self._bar_index - 1,
            "timestamp": bar["timestamp"],
            "symbol": bar["symbol"],
            "open": bar["open"],
            "high": bar["high"],
            "low": bar["low"],
            "close": bar["close"],
            "volume": bar.get("volume", 0),
            "remaining": len(self._bars) - self._bar_index,
        }

    def record_tool_call(self, tool_name: str) -> None:
        self.validator.record_tool_call(tool_name)

    def record_decision(
        self,
        symbol: str,
        phase: str,
        decision: str,
        reasoning: str,
        input_state: dict,
        tools_called: list[str],
        rules_evaluated: list[dict],
        score: float | None = None,
        trade_plan: dict | None = None,
    ) -> str:
        for tool in tools_called:
            self.validator.record_tool_call(tool)

        validation = self.validator.validate(phase, decision)

        return self.logger.log_decision(
            run_id=self.run_id,
            bar_index=self._bar_index - 1,
            timestamp=self._current_bar["timestamp"] if self._current_bar else "",
            symbol=symbol,
            phase=phase,
            input_state=input_state,
            tools_called=tools_called,
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
