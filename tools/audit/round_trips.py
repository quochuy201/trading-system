"""Round-trip construction: turn a stream of fills into completed trades.

`fills` records what the broker executed. A *round trip* is the thing a person
means by "a trade" — get into a position, get out of it — and it is not any
single row: a 300-share entry filled in two executions and scaled out in two
more is four fills and one trip.

Why this is procedural code and not a view: it depends on the running position,
which SQL cannot express without a window function per symbol per mode and a
lot of hope. Tracking the position also resolves the pairing ambiguity that
`plan_id` grouping cannot — the FLR sequence (buy 311, sell 311, sell 267, buy
267) is one plan but unambiguously **two** trips, long then short.

⭐ This table is a CACHE. `fills` is the truth, and `rebuild_round_trips()`
must reproduce the cache exactly, ids included. That is what buys the right to
be wrong later: if the pairing or the R formula turns out to have a bug, fix it
and recompute all history. Had we stored only a final number, the bug would be
permanent.
"""

import logging
from datetime import datetime, timezone

from audit.ids import content_hash, round_trip_id

logger = logging.getLogger(__name__)

LONG = "long"
SHORT = "short"


def _signed(fill) -> int:
    """Position delta of a fill. Buy adds, sell subtracts."""
    return fill.qty if fill.side == "buy" else -fill.qty


def _weighted(legs) -> tuple[float, int]:
    """Quantity-weighted average price and total quantity of one leg.

    Args:
        legs: [(fill, qty_used)] — qty_used, not fill.qty, because a fill split
            by a position flip contributes different amounts to two trips.

    Returns:
        (average_price, total_qty). (0.0, 0) for an empty leg.
    """
    total = sum(q for _, q in legs)
    if not total:
        return 0.0, 0
    return sum(f.price * q for f, q in legs) / total, total


class _OpenTrip:
    """A position being accumulated; becomes a round trip when it returns flat."""

    def __init__(self, direction: str, symbol: str, mode: str):
        self.direction = direction
        self.symbol = symbol
        self.mode = mode
        self.entry: list = []
        self.exit: list = []

    def close(self) -> dict:
        """Emit the finished trip.

        Returns:
            A dict of the columns this task owns. `initial_stop`, `r_multiple`,
            `r_uncomputable_reason` and `slippage` are deliberately absent —
            Task 6 computes those, and a placeholder 0.0 here would be a lie
            that later looks like a real measurement.
        """
        entry_price, qty = _weighted(self.entry)
        exit_price, _ = _weighted(self.exit)

        if self.direction == LONG:
            gross = (exit_price - entry_price) * qty
        else:
            gross = (entry_price - exit_price) * qty

        entry_ids = [f.fill_id for f, _ in self.entry]
        exit_ids = [f.fill_id for f, _ in self.exit]

        return {
            "round_trip_id": round_trip_id(entry_ids[0], exit_ids[-1]),
            "content_hash": content_hash(entry_ids + exit_ids),
            "symbol": self.symbol,
            "direction": self.direction,
            "quantity": qty,
            "entry_price": entry_price,
            "entry_at": self.entry[0][0].filled_at.isoformat(),
            "exit_price": exit_price,
            "exit_at": self.exit[-1][0].filled_at.isoformat(),
            "gross_pnl": gross,
            # Alpaca's TradeActivity carries no fee data, and regulatory fees
            # arrive as separate non-trade activities with no order_id — so per
            # trade they are NOT attributable. The flag says so rather than
            # letting a 0.0 quietly overstate net_pnl. D7's "net of costs" is
            # evaluated at the portfolio level; see design §3b-bis.
            "total_fees": 0.0,
            "fees_attributable": 0,
            "net_pnl": gross,
            "mode": self.mode,
            "entry_fill_ids": entry_ids,
            "exit_fill_ids": exit_ids,
        }


def build_round_trips(fills) -> list[dict]:
    """Pair a stream of fills into completed round trips.

    Args:
        fills: Fill objects. Grouped internally by (symbol, mode) and ordered
            by (filled_at, fill_id) — paper and live are never mixed, and the
            tie-break keeps the result stable when two executions share a
            timestamp.

    Returns:
        One dict per COMPLETED trip, ordered by exit time then id. A position
        still open produces no row: it has no exit, so no outcome to measure.
    """
    by_market: dict[tuple[str, str], list] = {}
    for fill in fills:
        by_market.setdefault((fill.symbol, fill.mode), []).append(fill)

    trips: list[dict] = []
    for (symbol, mode), group in by_market.items():
        group.sort(key=lambda f: (f.filled_at, f.fill_id))
        position = 0
        trip: _OpenTrip | None = None

        for fill in group:
            remaining = _signed(fill)
            while remaining:
                if position == 0:
                    # Opening from flat. When this is the tail of a fill that
                    # just closed a position, the same fill legitimately opens
                    # the next trip — that is the flip split.
                    trip = _OpenTrip(LONG if remaining > 0 else SHORT, symbol, mode)
                    trip.entry.append((fill, abs(remaining)))
                    position, remaining = remaining, 0
                elif (position > 0) == (remaining > 0):
                    trip.entry.append((fill, abs(remaining)))  # adding to the position
                    position, remaining = position + remaining, 0
                else:
                    closing = min(abs(remaining), abs(position))
                    trip.exit.append((fill, closing))
                    step = closing if remaining > 0 else -closing
                    position += step
                    remaining -= step
                    if position == 0:
                        trips.append(trip.close())
                        trip = None

        if position:
            logger.debug("position still open symbol=%s mode=%s qty=%d",
                         symbol, mode, position)

    trips.sort(key=lambda t: (t["exit_at"], t["round_trip_id"]))
    return trips


def r_multiple(direction: str, entry_price: float, exit_price: float,
               initial_stop: float | None) -> tuple[float | None, str | None]:
    """Trade outcome in units of the risk taken — *the* performance metric.

        long:   r = (exit  - entry) / (entry - stop)
        short:  r = (entry - exit)  / (stop  - entry)

    Args:
        direction: "long" | "short".
        entry_price: Quantity-weighted entry.
        exit_price: Quantity-weighted exit.
        initial_stop: `trade_plans.stop_loss` **as planned at entry**. None
            when there is no plan or no stop.

    Returns:
        (r, None) when computable, else (None, reason). NEVER (0.0, ...) —
        a zero R is a real outcome (exited at entry) and must not be
        confused with "we could not work it out".

    Raises:
        Nothing. Every failure is a reason string, because an exception here
        would abort a whole rebuild over one incomplete trade.
    """
    if initial_stop is None:
        return None, "no_stop_recorded"
    # A stop of exactly 0.0 is the dataclass default, not a price anyone
    # planned. Treating it as real gives risk == entry_price and a
    # plausible-looking R that is pure fiction.
    if initial_stop == 0:
        return None, "stop_is_zero_placeholder"

    risk = (entry_price - initial_stop) if direction == LONG else (initial_stop - entry_price)
    if risk <= 0:
        # Stop on the wrong side of entry: the plan was amended after entry, or
        # recorded wrong. Estimating a stop here would fabricate the denominator
        # of the number D5 and D7 are judged on.
        return None, "non_positive_risk"

    gain = (exit_price - entry_price) if direction == LONG else (entry_price - exit_price)
    return gain / risk, None


def slippage(direction: str, entry_price: float,
             intended_price: float | None) -> float | None:
    """How much worse than intended we actually got in, per share.

    Sign is normalised so **positive always means worse**, whichever way the
    trade goes: a long that paid above its intended price and a short that
    sold below it both report positive slippage.

    Args:
        direction: "long" | "short".
        entry_price: Quantity-weighted entry actually achieved.
        intended_price: `orders.intended_price` — the limit or signal price.
            None when the order carried no reference (e.g. a market order with
            no plan).

    Returns:
        Per-share slippage, or None when there is nothing to compare against.
        This number is what reveals whether paper trading is flattering us,
        and it exists only because intent and reality are separate rows.
    """
    if intended_price is None:
        return None
    return (entry_price - intended_price) if direction == LONG else (intended_price - entry_price)


def _enrich_from_orders(repo, trip: dict) -> dict:
    """Attach plan context and the derived metrics, from the first entry fill.

    The join is `fills.broker_order_id = orders.broker_order_id` — the broker's
    id on both sides. `orders.order_id` is ours and matches nothing here.

    Args:
        repo: Repository.
        trip: A trip dict from build_round_trips.

    Returns:
        The trip with plan_id / strategy / sop_version / regime_at_entry /
        initial_stop / r_multiple / r_uncomputable_reason / slippage filled in
        where they are knowable. All stay None for a fill whose order we never
        recorded — backfilled history, or a position opened outside this
        system. Never fabricated.

    Note:
        An entry spanning several orders takes its intent from the FIRST entry
        fill's order, the same source as the plan context. Distinct intended
        prices across one entry are not blended.
    """
    row = repo.conn.execute(
        """SELECT o.plan_id, o.regime_at_entry, o.intended_price,
                  p.strategy, p.sop_version, p.stop_loss
           FROM fills f
           JOIN orders o ON f.broker_order_id = o.broker_order_id
           LEFT JOIN trade_plans p ON o.plan_id = p.plan_id
           WHERE f.fill_id = ?""",
        (trip["entry_fill_ids"][0],),
    ).fetchone()

    stop = row["stop_loss"] if row else None
    r, reason = r_multiple(trip["direction"], trip["entry_price"],
                           trip["exit_price"], stop)
    # Say precisely WHY, because the three cases have different fixes: an
    # order predating intent capture is unrecoverable history; an order with
    # no plan is an ad-hoc trade; a plan with no stop is a planning gap.
    if reason == "no_stop_recorded":
        if row is None:
            reason = "no_order_recorded"
        elif row["plan_id"] is None:
            reason = "no_plan_recorded"

    trip.update({
        "plan_id": row["plan_id"] if row else None,
        "regime_at_entry": row["regime_at_entry"] if row else None,
        "strategy": row["strategy"] if row else None,
        "sop_version": row["sop_version"] if row else None,
        "initial_stop": stop,
        "r_multiple": r,
        "r_uncomputable_reason": reason,
        "slippage": slippage(trip["direction"], trip["entry_price"],
                             row["intended_price"] if row else None),
    })
    return trip


def rebuild_round_trips(repo) -> dict:
    """Truncate and recompute `round_trips` and `round_trip_fills` from `fills`.

    ⭐ The rebuild invariant: running this twice over unchanged fills must
    produce byte-identical rows, `round_trip_id` and `content_hash` included.
    Only `rebuilt_at` may differ, and it is deliberately not hashed.

    Args:
        repo: Repository holding `fills`, `orders` and `trade_plans`.

    Returns:
        {"trips": int, "links": int} — rows written to each table.

    Raises:
        Nothing is caught here: a failure to rebuild a derived cache must be
        loud, and the previous contents are already gone. Callers running this
        on a schedule wrap it so one bad rebuild cannot abort the EOD pass.
    """
    trips = [_enrich_from_orders(repo, t)
             for t in build_round_trips(repo.get_all_fills())]
    rebuilt_at = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()

    links = 0
    repo.conn.execute("DELETE FROM round_trip_fills")
    repo.conn.execute("DELETE FROM round_trips")
    for trip in trips:
        repo.conn.execute(
            """INSERT INTO round_trips
            (round_trip_id, content_hash, plan_id, symbol, strategy, sop_version,
             direction, quantity, entry_price, entry_at, exit_price, exit_at,
             initial_stop, gross_pnl, total_fees, fees_attributable, net_pnl,
             r_multiple, r_uncomputable_reason, slippage, regime_at_entry,
             mode, rebuilt_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                trip["round_trip_id"], trip["content_hash"], trip["plan_id"],
                trip["symbol"], trip["strategy"], trip["sop_version"],
                trip["direction"], trip["quantity"], trip["entry_price"],
                trip["entry_at"], trip["exit_price"], trip["exit_at"],
                trip["initial_stop"], trip["gross_pnl"], trip["total_fees"],
                trip["fees_attributable"], trip["net_pnl"], trip["r_multiple"],
                trip["r_uncomputable_reason"], trip["slippage"],
                trip["regime_at_entry"], trip["mode"], rebuilt_at,
            ),
        )
        for leg, ids in (("entry", trip["entry_fill_ids"]),
                         ("exit", trip["exit_fill_ids"])):
            for fill_id in ids:
                # A flip-split fill is both the exit of one trip and the entry
                # of the next; within ONE trip a fill cannot be both legs, so
                # OR IGNORE only absorbs a repeated id inside the same leg.
                cur = repo.conn.execute(
                    """INSERT OR IGNORE INTO round_trip_fills
                    (round_trip_id, fill_id, leg) VALUES (?,?,?)""",
                    (trip["round_trip_id"], fill_id, leg),
                )
                links += cur.rowcount
    repo.conn.commit()

    logger.info("rebuild_round_trips trips=%d", len(trips))
    return {"trips": len(trips), "links": links}
