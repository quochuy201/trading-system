import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.validator import WorkflowValidator


class TestWorkflowValidator:
    def setup_method(self):
        self.validator = WorkflowValidator()

    def test_research_valid_when_all_tools_called(self):
        self.validator.record_tool_call("calc_technical_indicators")
        self.validator.record_tool_call("get_market_data")
        result = self.validator.validate("research", "skip")
        assert result["valid"] is True
        assert result["missing"] == []

    def test_research_invalid_when_missing_indicators(self):
        self.validator.record_tool_call("get_market_data")
        result = self.validator.validate("research", "enter")
        assert result["valid"] is False
        assert "calc_technical_indicators" in result["missing"]

    def test_trader_valid_when_all_risk_checks_called(self):
        self.validator.record_tool_call("check_kill_switch")
        self.validator.record_tool_call("check_daily_limits")
        self.validator.record_tool_call("check_portfolio_risk")
        self.validator.record_tool_call("calc_position_size")
        result = self.validator.validate("trader", "enter")
        assert result["valid"] is True

    def test_trader_invalid_missing_kill_switch(self):
        self.validator.record_tool_call("check_daily_limits")
        self.validator.record_tool_call("check_portfolio_risk")
        self.validator.record_tool_call("calc_position_size")
        result = self.validator.validate("trader", "enter")
        assert result["valid"] is False
        assert "check_kill_switch" in result["missing"]

    def test_monitor_hold_valid(self):
        self.validator.record_tool_call("get_positions")
        self.validator.record_tool_call("get_market_data")
        result = self.validator.validate("monitor", "hold")
        assert result["valid"] is True

    def test_reset_clears_state(self):
        self.validator.record_tool_call("get_market_data")
        self.validator.reset()
        result = self.validator.validate("research", "skip")
        assert result["valid"] is False

    def test_get_calls_returns_recorded_tools(self):
        self.validator.record_tool_call("get_market_data")
        self.validator.record_tool_call("calc_technical_indicators")
        assert set(self.validator.get_calls()) == {"get_market_data", "calc_technical_indicators"}
