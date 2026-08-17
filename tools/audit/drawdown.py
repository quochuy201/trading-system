"""Drawdown from peak, and the daily equity snapshot.

The governance gate's §4.4 circuit breakers fire on drawdown over 5 and 20
days. Without this they would be **dead controls that look alive** — present,
tested, logging OK, and unable to ever fire (review finding F4).

Source of truth is the BROKER (D3): equity history comes from
`get_portfolio_history`, so drawdown is computable today, with no warmup and
no dependence on us having recorded anything. `portfolio_snapshots` is written
alongside as a durable copy that survives a broker change — a cross-check, not
the authority.

⚠️ A failed fetch reports UNAVAILABLE. It must never report 0.0, which reads
as "no drawdown" and would silently disarm the breaker at exactly the moment
we cannot see the account.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

UNAVAILABLE = "UNAVAILABLE"


def drawdown_pct(equity: list[float], days: int) -> float | None:
    """Current drawdown from the peak of the last `days` points, in percent.

    Args:
        equity: Equity points, oldest first.
        days: Window length in points; must be >= 1. A window longer than the
            series uses everything available — an account younger than the
            window still has a real, measurable drawdown.

    Returns:
        Percent below the window's peak, >= 0. 0.0 means "at or above the
        peak", which is a genuine measurement. None when the series is empty
        or the peak is non-positive (no meaningful denominator) — the caller
        reports UNAVAILABLE rather than inventing a number.
    """
    if not equity or days < 1:
        return None
    window = equity[-days:]
    peak = max(window)
    if peak <= 0:
        return None
    return max(0.0, (peak - window[-1]) / peak * 100.0)


def drawdowns_from_broker(broker, windows=(5, 20), period: str = "1M",
                          timeframe: str = "1D") -> dict:
    """Drawdown over each window, straight from broker-served equity history.

    Args:
        broker: A BrokerAdapter.
        windows: Lookback lengths in points, e.g. (5, 20).
        period: Passed to the broker.
        timeframe: Passed to the broker.

    Returns:
        {"drawdown_5d_pct": float | "UNAVAILABLE", ..., "points": int}. Every
        window reports UNAVAILABLE — never 0.0 — when the fetch fails or the
        history is empty, because a breaker reading 0.0 is a disarmed breaker.
    """
    try:
        history = broker.get_portfolio_history(period=period, timeframe=timeframe)
        equity = list(history.get("equity") or [])
    except Exception:
        logger.exception(
            "portfolio history unavailable — drawdown breakers cannot evaluate")
        equity = []

    result: dict = {"points": len(equity)}
    for window in windows:
        value = drawdown_pct(equity, window)
        result[f"drawdown_{window}d_pct"] = UNAVAILABLE if value is None else value
    return result


def write_daily_snapshot(repo, account: dict, positions: list[dict],
                         as_of: datetime | None = None) -> str:
    """Record one equity snapshot per calendar day.

    A durable copy of what the broker said, for backtests and for cross-checking
    a future broker change. The broker stays authoritative.

    Args:
        repo: Repository.
        account: `get_account()` output — needs at least `equity` and `cash`.
        positions: `get_positions()` output; stored as JSON for context.
        as_of: Timestamp to record against; defaults to now (UTC).

    Returns:
        The date written, "YYYY-MM-DD". Re-running on the same day REPLACES
        that day's row rather than appending, so an EOD retry cannot produce
        two rows for one day and double-count the series.
    """
    import json

    when = as_of or datetime.now(timezone.utc).replace(tzinfo=None)
    date = when.strftime("%Y-%m-%d")
    repo.conn.execute(
        """INSERT OR REPLACE INTO portfolio_snapshots
        (date, timestamp, total_value, cash, daily_pnl, total_pnl, positions)
        VALUES (?,?,?,?,?,?,?)""",
        (
            date, when.isoformat(), account.get("equity"), account.get("cash"),
            account.get("daily_pnl"), account.get("total_pnl"),
            json.dumps(positions or []),
        ),
    )
    repo.conn.commit()
    logger.info("portfolio snapshot written date=%s equity=%s",
                date, account.get("equity"))
    return date
