"""Performance calculator — trading metrics from the transaction ledger."""

from persistence.repository import Repository


def calc_performance(repo: Repository, start_date: str = "", end_date: str = "",
                     sop_version: str = "") -> dict:
    """Calculate trading performance metrics from closed trades in the ledger.

    Returns: {win_rate, profit_factor, expectancy, total_pnl, total_trades,
              avg_winner, avg_loser, max_drawdown, by_symbol, by_sop_version}
    """
    sells = repo.query_ledger(
        action="sell", start_date=start_date, end_date=end_date,
        sop_version=sop_version, limit=10000,
    )
    # Only count fills with P&L data
    closed = [s for s in sells if s.get("pnl") is not None and s["status"] == "filled"]

    if not closed:
        return _empty_metrics()

    pnls = [t["pnl"] for t in closed]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p <= 0]

    total_trades = len(closed)
    win_rate = len(winners) / total_trades if total_trades else 0
    total_pnl = sum(pnls)
    avg_winner = sum(winners) / len(winners) if winners else 0
    avg_loser = sum(losers) / len(losers) if losers else 0
    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    profit_factor = gross_profit / gross_loss if gross_loss else float("inf")
    expectancy = total_pnl / total_trades if total_trades else 0

    # Max drawdown from cumulative P&L curve
    max_drawdown = _calc_max_drawdown(pnls)

    # Group by symbol
    by_symbol = _group_by(closed, "symbol")
    by_sop = _group_by(closed, "sop_version")

    return {
        "total_trades": total_trades,
        "win_rate": round(win_rate, 3),
        "profit_factor": round(profit_factor, 2),
        "expectancy": round(expectancy, 2),
        "total_pnl": round(total_pnl, 2),
        "avg_winner": round(avg_winner, 2),
        "avg_loser": round(avg_loser, 2),
        "max_drawdown": round(max_drawdown, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "by_symbol": by_symbol,
        "by_sop_version": by_sop,
    }


def _calc_max_drawdown(pnls: list[float]) -> float:
    """Max drawdown from a sequence of trade P&Ls."""
    if not pnls:
        return 0
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        cumulative += pnl
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _group_by(trades: list[dict], key: str) -> dict:
    """Group trades by a field and compute per-group metrics."""
    groups: dict[str, list[float]] = {}
    for t in trades:
        g = t.get(key, "unknown") or "unknown"
        groups.setdefault(g, []).append(t["pnl"])
    result = {}
    for g, pnls in groups.items():
        winners = [p for p in pnls if p > 0]
        result[g] = {
            "trades": len(pnls),
            "win_rate": round(len(winners) / len(pnls), 3) if pnls else 0,
            "total_pnl": round(sum(pnls), 2),
        }
    return result


def _empty_metrics() -> dict:
    return {
        "total_trades": 0, "win_rate": 0, "profit_factor": 0,
        "expectancy": 0, "total_pnl": 0, "avg_winner": 0,
        "avg_loser": 0, "max_drawdown": 0, "gross_profit": 0,
        "gross_loss": 0, "by_symbol": {}, "by_sop_version": {},
    }
