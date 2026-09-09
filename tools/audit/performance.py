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


# --- Go-live metrics: the round-trip view + its path-dependent companions ---
#
# `v_performance_current` answers everything that is a pure aggregate of
# round_trips, on read, with no job to run and no staleness possible. Two
# metrics cannot live there because they depend on the ORDER of trades, which
# a GROUP BY discards: max drawdown and Sharpe. Those are computed here.
#
# Nothing in this section reads `trade_transactions` or the ledger — the
# legacy path above is untouched (design §6).

import logging
import math
from datetime import datetime, timezone

_log = logging.getLogger(__name__)


def current_performance(repo: Repository, mode: str | None = None) -> list[dict]:
    """Read `v_performance_current`, one row per (mode, strategy).

    Args:
        repo: Repository.
        mode: Restrict to "paper" | "live" | "simulation". None returns every
            group — but they are never merged, because summing paper and live
            would be meaningless.

    Returns:
        List of dicts with the view's columns. Empty list when there are no
        round trips. Values may be None ("unknown"); they are never coerced to
        0.0, which would read as a measured zero.
    """
    sql = "SELECT * FROM v_performance_current"
    params: tuple = ()
    if mode:
        sql += " WHERE mode = ?"
        params = (mode,)
    sql += " ORDER BY mode, strategy"
    return [dict(r) for r in repo.conn.execute(sql, params).fetchall()]


def max_drawdown_r(pnls: list[float]) -> float | None:
    """Largest peak-to-trough decline of the cumulative P&L curve.

    Path-dependent, so it cannot be a column in the view: a GROUP BY has no
    notion of trade order.

    Args:
        pnls: Realised P&L per trade, in exit order.

    Returns:
        The drawdown as a positive number, 0.0 for a curve that never declines,
        None for an empty series ("unknown", not "no drawdown").
    """
    if not pnls:
        return None
    cumulative = peak = 0.0
    worst = 0.0
    for pnl in pnls:
        cumulative += pnl
        peak = max(peak, cumulative)
        worst = max(worst, peak - cumulative)
    return worst


def sharpe(values: list[float]) -> float | None:
    """Mean over standard deviation of a per-trade series.

    Args:
        values: Per-trade returns — R-multiples where available, since a
            Sharpe over raw dollars is dominated by position size.

    Returns:
        None for fewer than two points, or when every value is identical
        (zero dispersion ⇒ undefined, not "infinitely good").
    """
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    if variance <= 0:
        return None
    return mean / math.sqrt(variance)


def path_metrics(repo: Repository, mode: str) -> dict:
    """Max drawdown and Sharpe for one mode, in exit order.

    Args:
        repo: Repository.
        mode: "paper" | "live" | "simulation".

    Returns:
        {"max_drawdown": float | None, "sharpe_r": float | None,
         "trades": int} — None means "not computable from what we have",
        never a stand-in zero.
    """
    rows = repo.conn.execute(
        "SELECT net_pnl, r_multiple FROM round_trips WHERE mode = ? ORDER BY exit_at",
        (mode,),
    ).fetchall()
    pnls = [r["net_pnl"] for r in rows if r["net_pnl"] is not None]
    rs = [r["r_multiple"] for r in rows if r["r_multiple"] is not None]
    return {
        "max_drawdown": max_drawdown_r(pnls),
        "sharpe_r": sharpe(rs),
        "trades": len(rows),
    }


def write_performance_snapshot(repo: Repository, mode: str,
                               as_of: datetime | None = None) -> int:
    """Append one dated row per (mode, strategy) to the EOD snapshot log.

    `performance_metrics` is repurposed as a LOG of what the numbers were on a
    given day. The view remains the source of truth — this exists so a later
    question like "what did expectancy look like in July" is answerable without
    replaying history.

    Args:
        repo: Repository.
        mode: Which mode to snapshot.
        as_of: Timestamp to stamp; defaults to now (UTC).

    Returns:
        Number of rows written — one per strategy group. 0 when there are no
        round trips yet, which is not an error.
    """
    when = as_of or datetime.now(timezone.utc).replace(tzinfo=None)
    path = path_metrics(repo, mode)
    written = 0
    for row in current_performance(repo, mode=mode):
        repo.conn.execute(
            """INSERT INTO performance_metrics
            (period, mode, strategy, total_trades, win_rate, expectancy_r,
             r_excluded, profit_factor, max_drawdown, sharpe_ratio, snapshot_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                "eod", mode, row["strategy"], row["total_trades"],
                row["win_rate"], row["expectancy_r"], row["r_excluded"],
                row["profit_factor"], path["max_drawdown"], path["sharpe_r"],
                when.isoformat(),
            ),
        )
        written += 1
    repo.conn.commit()
    _log.info("performance snapshot mode=%s rows=%d", mode, written)
    return written


# --- Go-live D5 ladder (BUILD-PLAN D5) -------------------------------------
# One home for the ladder thresholds. D5: >=100 closed R-computable trades with
# positive expectancy-in-R, spanning >1 regime, paper within ~15-20% of
# backtest, gate live, D7 passed. The last three are not yet measurable and are
# reported UNAVAILABLE — never a pass (honest-data rule 5: unknown != pass).
GO_LIVE_TRADES_FLOOR = 100
GO_LIVE_TRADES_CONVINCING = 200
GO_LIVE_MIN_REGIMES = 2  # ">1 regime"


def _unavailable(reason: str) -> dict:
    """A criterion we cannot measure yet — carried as unknown, never a pass."""
    return {"value": None, "pass": None, "status": "UNAVAILABLE", "reason": reason}


def go_live_scorecard(repo: Repository, mode: str = "paper") -> dict:
    """Assemble the D5 go-live readiness ladder for one trading mode.

    Reads audit records only (`round_trips` + `v_performance_current`); writes
    nothing and changes no trading behaviour.

    Args:
        repo: Repository.
        mode: "paper" | "live" | "simulation". The ladder is a mode-level
            question, so metrics are aggregated across strategies here (the
            view groups by strategy; a per-strategy breakdown is returned under
            "strategies").

    Returns:
        dict with:
          - "mode": the mode scored.
          - "verdict": "READY" only if every criterion's ``pass`` is True; an
            unknown criterion (``pass`` is None) is never a pass, so today's
            verdict is "NOT READY".
          - "criteria": {trades, expectancy_r, regimes, paper_vs_backtest,
            gate_live, d7_edge}, each a dict carrying at least ``value`` and
            ``pass`` (None = unknown). ``expectancy_r.value`` is None when no
            trade is R-computable — never coerced to 0.0.
          - "r_excluded": count of closed round trips excluded from R (a
            shrinking denominator kept visible).
          - "strategies": per-(mode, strategy) rows from `current_performance`.

    Never raises for empty data — an empty mode yields trades 0 and a NOT READY
    verdict, which is the honest current state, not an error.
    """
    row = repo.conn.execute(
        """SELECT
             COUNT(r_multiple)                            AS r_trades,
             COUNT(*) - COUNT(r_multiple)                 AS r_excluded,
             AVG(r_multiple)                              AS expectancy_r,
             COUNT(DISTINCT CASE WHEN r_multiple IS NOT NULL
                                 THEN regime_at_entry END) AS regimes
           FROM round_trips WHERE mode = ?""",
        (mode,),
    ).fetchone()
    r_trades = row["r_trades"] or 0
    r_excluded = row["r_excluded"] or 0
    expectancy_r = row["expectancy_r"]  # None when nothing is R-computable
    regimes = row["regimes"] or 0

    criteria = {
        "trades": {
            "value": r_trades,
            "floor": GO_LIVE_TRADES_FLOOR,
            "convincing": GO_LIVE_TRADES_CONVINCING,
            "pass": r_trades >= GO_LIVE_TRADES_FLOOR,
        },
        "expectancy_r": {
            "value": expectancy_r,
            "pass": (expectancy_r > 0) if expectancy_r is not None else None,
        },
        "regimes": {
            "value": regimes,
            "required": GO_LIVE_MIN_REGIMES,
            "pass": regimes >= GO_LIVE_MIN_REGIMES,
        },
        "paper_vs_backtest": _unavailable(
            "backtest baseline not wired (backtest-engine not built)"),
        "gate_live": _unavailable("governance-gate not shipped"),
        "d7_edge": _unavailable("edge validation not built (D7)"),
    }
    verdict = "READY" if all(
        c["pass"] is True for c in criteria.values()) else "NOT READY"
    _log.info("go_live_scorecard mode=%s trades=%d verdict=%s",
              mode, r_trades, verdict)
    return {
        "mode": mode,
        "verdict": verdict,
        "criteria": criteria,
        "r_excluded": r_excluded,
        "strategies": current_performance(repo, mode=mode),
    }
