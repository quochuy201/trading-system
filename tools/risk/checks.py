"""Risk management tools — portfolio risk checks and daily limits."""

from broker.adapter import BrokerAdapter


# Default risk limits (overridable via config)
DEFAULT_MAX_CONCENTRATION_PCT = 20.0
DEFAULT_MAX_OPEN_POSITIONS = 5
DEFAULT_DAILY_LOSS_LIMIT_PCT = 3.0


def check_portfolio_risk(
    broker: BrokerAdapter,
    symbol: str,
    quantity: int,
    entry_price: float,
    max_concentration_pct: float = DEFAULT_MAX_CONCENTRATION_PCT,
    max_open_positions: int = DEFAULT_MAX_OPEN_POSITIONS,
) -> dict:
    """Check if a proposed trade passes portfolio risk limits.

    Returns dict with pass/fail and details.
    """
    account = broker.get_account()
    positions = broker.get_positions()
    portfolio_value = account["portfolio_value"]

    # Position value as % of portfolio
    position_value = quantity * entry_price
    concentration_pct = (position_value / portfolio_value * 100) if portfolio_value > 0 else 100

    # Current number of open positions
    num_positions = len(positions)

    # Check existing exposure to same symbol
    existing_exposure = sum(
        p["quantity"] * p["current_price"]
        for p in positions if p["symbol"] == symbol
    )
    total_symbol_exposure = existing_exposure + position_value
    total_symbol_pct = (total_symbol_exposure / portfolio_value * 100) if portfolio_value > 0 else 100

    # Evaluate limits
    checks = {
        "concentration": {
            "limit": max_concentration_pct,
            "actual": round(concentration_pct, 2),
            "passed": concentration_pct <= max_concentration_pct,
        },
        "total_symbol_exposure": {
            "limit": max_concentration_pct,
            "actual": round(total_symbol_pct, 2),
            "passed": total_symbol_pct <= max_concentration_pct,
        },
        "max_positions": {
            "limit": max_open_positions,
            "actual": num_positions,
            "passed": num_positions < max_open_positions,
        },
    }

    all_passed = all(c["passed"] for c in checks.values())

    return {
        "passed": all_passed,
        "portfolio_value": round(portfolio_value, 2),
        "proposed_value": round(position_value, 2),
        "checks": checks,
    }


def check_daily_limits(
    broker: BrokerAdapter,
    daily_loss_limit_pct: float = DEFAULT_DAILY_LOSS_LIMIT_PCT,
) -> dict:
    """Check if daily loss limit has been breached.

    Returns dict with pass/fail and current daily P&L.
    """
    account = broker.get_account()
    portfolio_value = account["portfolio_value"]
    daily_pnl = account["daily_pnl"]

    daily_pnl_pct = (daily_pnl / portfolio_value * 100) if portfolio_value > 0 else 0
    limit_amount = portfolio_value * (daily_loss_limit_pct / 100)

    breached = daily_pnl < -limit_amount

    return {
        "passed": not breached,
        "daily_pnl": round(daily_pnl, 2),
        "daily_pnl_pct": round(daily_pnl_pct, 2),
        "limit_pct": daily_loss_limit_pct,
        "limit_amount": round(limit_amount, 2),
        "remaining_budget": round(limit_amount + daily_pnl, 2),
    }
