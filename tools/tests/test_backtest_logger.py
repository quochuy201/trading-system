import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.logger import BacktestLogger
from persistence.repository import Repository


class TestBacktestLogger:
    def setup_method(self):
        self.repo = Repository(":memory:")
        self.logger = BacktestLogger(self.repo)

    def teardown_method(self):
        self.repo.close()

    def test_create_run(self):
        run_id = self.logger.create_run(
            symbols=["NVDA", "AAPL"],
            start_date="2026-01-01",
            end_date="2026-05-01",
            timeframe="1Day",
            initial_capital=100000.0,
            sop_version="v1.0.0",
        )
        assert run_id is not None
        run = self.repo.get_backtest_run(run_id)
        assert run["symbols"] == '["NVDA", "AAPL"]'
        assert run["status"] == "running"

    def test_log_decision(self):
        run_id = self.logger.create_run(
            symbols=["NVDA"], start_date="2026-01-01",
            end_date="2026-05-01", timeframe="1Day",
            initial_capital=100000.0,
        )
        decision_id = self.logger.log_decision(
            run_id=run_id,
            bar_index=10,
            timestamp="2026-01-15",
            symbol="NVDA",
            phase="research",
            input_state={"price": 220.5, "rsi": 65.2, "atr": 4.5},
            tools_called=["calc_technical_indicators", "get_market_data"],
            rules_evaluated=[{"rule": "RSI_RANGE", "passed": True, "value": "65.2 in [50,75]"}],
            score=82.0,
            decision="enter",
            reasoning="Breakout on volume",
            trade_plan={"entry": 220.5, "stop": 215.0, "target": 232.0},
            workflow_valid=True,
        )
        assert decision_id is not None
        decisions = self.repo.get_backtest_decisions(run_id)
        assert len(decisions) == 1
        assert decisions[0]["decision"] == "enter"
        assert decisions[0]["workflow_valid"] == 1

    def test_complete_run(self):
        run_id = self.logger.create_run(
            symbols=["NVDA"], start_date="2026-01-01",
            end_date="2026-05-01", timeframe="1Day",
            initial_capital=100000.0,
        )
        self.logger.complete_run(
            run_id=run_id,
            final_equity=105000.0,
            total_pnl=5000.0,
            total_trades=8,
            win_rate=0.625,
            expectancy=106.0,
            max_drawdown=420.0,
        )
        run = self.repo.get_backtest_run(run_id)
        assert run["status"] == "completed"
        assert run["final_equity"] == 105000.0

    def test_export_jsonl(self):
        run_id = self.logger.create_run(
            symbols=["NVDA"], start_date="2026-01-01",
            end_date="2026-05-01", timeframe="1Day",
            initial_capital=100000.0,
        )
        self.logger.log_decision(
            run_id=run_id, bar_index=1, timestamp="2026-01-02",
            symbol="NVDA", phase="research",
            input_state={"price": 200.0}, tools_called=["get_market_data"],
            rules_evaluated=[], score=None, decision="skip",
            reasoning="No setup", trade_plan=None, workflow_valid=True,
        )
        lines = self.logger.export_jsonl(run_id)
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["decision"] == "skip"
        assert record["symbol"] == "NVDA"
