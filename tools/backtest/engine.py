"""Backtest replay engine — sets up simulation environment.

This module provides run_replay() which loads historical data and creates
a SimulationBrokerAdapter. The actual bar-by-bar execution and decision-making
is handled by the BacktestHarness (harness.py).

DESIGN RULE: This module NEVER contains strategy logic or decision functions.
It only sets up the environment. The AI agent makes all decisions via MCP tools.
"""

from datetime import datetime
from persistence.repository import Repository
from broker.simulation import SimulationBrokerAdapter


def run_replay(
    repo: Repository,
    symbol: str,
    start_date: str,
    end_date: str,
    timeframe: str = "1Day",
    initial_capital: float = 100000.0,
) -> dict:
    """Set up a backtest replay environment.

    Loads bars from the price cache and creates a simulation broker.
    Does NOT step through bars or make decisions — that's the harness's job.

    Returns the simulation broker instance and the list of bars.
    """
    bars = repo.query_price_data(symbol, start_date, end_date, timeframe)
    if not bars:
        return {"error": f"No data for {symbol} from {start_date} to {end_date}"}

    sim = SimulationBrokerAdapter(
        repo=repo,
        initial_capital=initial_capital,
        slippage_pct=0.05,
        fee_per_trade=0.0,
        timeframe=timeframe,
    )

    return {
        "broker": sim,
        "bars": bars,
        "symbol": symbol,
        "total_bars": len(bars),
    }
