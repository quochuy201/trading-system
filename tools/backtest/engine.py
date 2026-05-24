"""Backtest replay engine — steps through historical data bar-by-bar.

The agent cannot see future data. At each bar, it can only access
data up to that point. Orders fill at the current bar's close price.
Everything is logged through the standard audit system.
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
    """Run a backtest replay and return results.

    This does NOT invoke the agent — it sets up the environment.
    The agent is invoked externally (by the orchestrator or test harness)
    at each bar via the MCP tools, which are wired to the simulation broker.

    Returns the simulation broker instance and the list of bars for stepping.
    """
    # Load all bars for the period
    bars = repo.query_price_data(symbol, start_date, end_date, timeframe)
    if not bars:
        return {"error": f"No data for {symbol} from {start_date} to {end_date}"}

    sim = SimulationBrokerAdapter(
        repo=repo,
        initial_capital=initial_capital,
        slippage_pct=0.0,  # simple: fill at market price exactly
        fee_per_trade=0.0,
        timeframe=timeframe,
    )

    return {
        "broker": sim,
        "bars": bars,
        "symbol": symbol,
        "total_bars": len(bars),
    }


def step_through(
    sim: SimulationBrokerAdapter,
    bars: list[dict],
    decision_fn=None,
) -> dict:
    """Step through bars one at a time. At each bar, call decision_fn if provided.

    decision_fn(bar_index, bar, sim) -> None
        Called at each bar so the caller can invoke agent logic.
        If None, just steps through (useful for testing the engine itself).

    Returns final performance summary.
    """
    for i, bar in enumerate(bars):
        # Advance simulation clock to this bar
        ts = bar["timestamp"]
        if isinstance(ts, str):
            # Handle various timestamp formats
            try:
                sim.set_time(datetime.fromisoformat(ts))
            except ValueError:
                sim.set_time(datetime.strptime(ts, "%Y-%m-%d"))
        else:
            sim.set_time(ts)

        # Let the caller make decisions at this bar
        if decision_fn:
            decision_fn(i, bar, sim)

    # Final account state
    account = sim.get_account()
    pnl = account["equity"] - sim.initial_capital
    pnl_pct = (pnl / sim.initial_capital) * 100

    return {
        "initial_capital": sim.initial_capital,
        "final_equity": round(account["equity"], 2),
        "total_pnl": round(pnl, 2),
        "total_pnl_pct": round(pnl_pct, 2),
        "total_bars": len(bars),
        "open_positions": len(sim.positions),
        "positions": sim.get_positions(),
    }


def run_simple_backtest(
    repo: Repository,
    symbol: str,
    start_date: str,
    end_date: str,
    strategy_fn,
    timeframe: str = "1Day",
    initial_capital: float = 100000.0,
) -> dict:
    """Convenience: load data + step through with a strategy function.

    strategy_fn(bar_index, bar, sim, repo) -> None
        The strategy logic. Can call sim.place_order(), sim.get_positions(), etc.
        Only has access to data up to current bar (enforced by sim.current_time).
    """
    setup = run_replay(repo, symbol, start_date, end_date, timeframe, initial_capital)
    if "error" in setup:
        return setup

    sim = setup["broker"]
    bars = setup["bars"]

    def _wrapped(i, bar, s):
        strategy_fn(i, bar, s, repo)

    result = step_through(sim, bars, _wrapped)
    result["symbol"] = symbol
    result["start_date"] = start_date
    result["end_date"] = end_date
    result["timeframe"] = timeframe
    return result
