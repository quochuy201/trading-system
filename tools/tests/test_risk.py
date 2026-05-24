"""Tests for risk management tools."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from risk.checks import check_portfolio_risk, check_daily_limits


def _mock_broker(equity=100000, daily_pnl=0, positions=None):
    broker = MagicMock()
    broker.get_account.return_value = {
        "equity": equity,
        "cash": equity,
        "buying_power": equity * 2,
        "portfolio_value": equity,
        "daily_pnl": daily_pnl,
    }
    broker.get_positions.return_value = positions or []
    return broker


class TestCheckPortfolioRisk:
    def test_passes_within_limits(self):
        broker = _mock_broker(equity=100000)
        result = check_portfolio_risk(broker, "AAPL", 50, 150.0)  # $7500 = 7.5%
        assert result["passed"] is True
        assert result["checks"]["concentration"]["passed"] is True
        assert result["checks"]["max_positions"]["passed"] is True

    def test_fails_concentration_limit(self):
        broker = _mock_broker(equity=100000)
        # $25,000 = 25% > 20% limit
        result = check_portfolio_risk(broker, "AAPL", 500, 50.0)
        assert result["passed"] is False
        assert result["checks"]["concentration"]["passed"] is False

    def test_fails_max_positions(self):
        positions = [
            {"symbol": f"SYM{i}", "quantity": 10, "current_price": 100.0}
            for i in range(5)
        ]
        broker = _mock_broker(equity=100000, positions=positions)
        result = check_portfolio_risk(broker, "NEW", 10, 100.0)
        assert result["passed"] is False
        assert result["checks"]["max_positions"]["passed"] is False

    def test_fails_total_symbol_exposure(self):
        # Already have $15K in AAPL, adding $10K more = $25K = 25% > 20%
        positions = [{"symbol": "AAPL", "quantity": 100, "current_price": 150.0}]
        broker = _mock_broker(equity=100000, positions=positions)
        result = check_portfolio_risk(broker, "AAPL", 67, 150.0)  # +$10,050
        assert result["passed"] is False
        assert result["checks"]["total_symbol_exposure"]["passed"] is False

    def test_custom_limits(self):
        broker = _mock_broker(equity=100000)
        # $30K = 30%, passes with 40% limit
        result = check_portfolio_risk(
            broker, "AAPL", 200, 150.0, max_concentration_pct=40.0
        )
        assert result["passed"] is True

    def test_returns_portfolio_value(self):
        broker = _mock_broker(equity=50000)
        result = check_portfolio_risk(broker, "AAPL", 10, 150.0)
        assert result["portfolio_value"] == 50000.0
        assert result["proposed_value"] == 1500.0


class TestCheckDailyLimits:
    def test_passes_no_loss(self):
        broker = _mock_broker(equity=100000, daily_pnl=500)
        result = check_daily_limits(broker)
        assert result["passed"] is True
        assert result["daily_pnl"] == 500.0

    def test_passes_small_loss(self):
        broker = _mock_broker(equity=100000, daily_pnl=-1000)  # -1% < 3% limit
        result = check_daily_limits(broker)
        assert result["passed"] is True

    def test_fails_exceeds_limit(self):
        broker = _mock_broker(equity=100000, daily_pnl=-3500)  # -3.5% > 3% limit
        result = check_daily_limits(broker)
        assert result["passed"] is False

    def test_exactly_at_limit(self):
        broker = _mock_broker(equity=100000, daily_pnl=-3000)  # exactly -3%
        result = check_daily_limits(broker)
        # At exactly the limit, not breached (need to exceed)
        assert result["passed"] is True

    def test_custom_limit(self):
        broker = _mock_broker(equity=100000, daily_pnl=-1500)  # -1.5%
        result = check_daily_limits(broker, daily_loss_limit_pct=1.0)  # 1% limit
        assert result["passed"] is False

    def test_remaining_budget(self):
        broker = _mock_broker(equity=100000, daily_pnl=-1000)
        result = check_daily_limits(broker)  # 3% limit = $3000
        assert result["remaining_budget"] == 2000.0  # $3000 - $1000 lost
