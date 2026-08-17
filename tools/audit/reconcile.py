"""Reconciliation: pull what the broker actually did into our own tables.

Two routines with different jobs, because the broker reports the two facts
through different endpoints:

- `sync_fills()` copies EXECUTIONS from the account activity feed into `fills`.
- `sync_orders_terminal()` copies STATUS from the orders endpoint, because
  cancelled / rejected / expired orders never appear in the activity feed at
  all — an order that dies without executing leaves no trace there.

Sits between the broker adapter and the repository; the round-trip builder
(Task 5) reads `fills` afterwards and never talks to the broker itself.

Why cursor-based and not per-order polling: `get_order()` reports a CUMULATIVE
filled quantity, so appending it across polls double-counts (poll at 50 filled,
poll again at 100, append both ⇒ 150). The activity feed reports discrete
executions with stable ids, so one pass covers every order at once and a replay
is a primary-key conflict rather than a duplicate row. Measured on the live
paper account: 250 activities across 186 orders, 31 of which filled in more than
one execution, 64 rows where qty != cum_qty.
"""

import logging
from datetime import datetime

from models import Fill

logger = logging.getLogger(__name__)

FILL_CURSOR_KEY = "fills:FILL"

# Broker status -> our terminal_status vocabulary. Alpaca spells it "canceled";
# the schema uses "cancelled". One mapping, one home.
_TERMINAL_STATUS = {
    "filled": "filled",
    "partially_filled": "partially_filled",
    "canceled": "cancelled",
    "cancelled": "cancelled",
    "expired": "expired",
    "rejected": "rejected",
    "done_for_day": "expired",
}


def _parse_broker_time(raw: str) -> datetime:
    """Parse a broker timestamp into a datetime.

    Args:
        raw: ISO-8601 as the broker sends it, e.g.
            "2026-04-30T13:30:34.923781Z". Alpaca uses a trailing Z.

    Returns:
        A timezone-aware datetime.

    Raises:
        ValueError: unparseable. Caught per-record by sync_fills so one bad
            timestamp cannot abort the batch — never silently replaced with
            "now", which would put the execution at the wrong point in the
            round-trip sequence.
    """
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def sync_fills(
    broker,
    repo,
    mode: str,
    page_size: int = 100,
    max_pages: int = 200,
) -> dict:
    """Import every broker execution recorded since the stored cursor.

    Walks the activity feed oldest-first from the persisted cursor, inserting
    one `fills` row per execution. Idempotent by construction: `fill_id` is the
    broker's own activity id, so re-running inserts nothing new.

    Args:
        broker: A BrokerAdapter. Only `get_account_activities` is used — never
            `get_order`, whose cumulative quantities would double-count.
        repo: Repository for `insert_fill` and the cursor.
        mode: "paper" | "live" | "simulation" — stamped on each fill so paper
            and live results are never summed.
        page_size: Activities per request; >= 1.
        max_pages: Safety stop, so a broker that never returns an empty page
            cannot spin forever.

    Returns:
        {"inserted": int, "skipped": int, "failed": int, "pages": int,
         "cursor": str | None} — `skipped` counts executions already stored
        (the normal case on a re-run), `failed` counts records that could not
        be stored at all. A non-zero `failed` means those executions are
        missing from the metrics; rewind the cursor to re-import them.

    Raises:
        Nothing from a single bad record — each is caught, logged and counted so
        one malformed activity cannot abort the batch. Broker/transport errors
        from the page fetch itself propagate to the caller.
    """
    cursor = repo.get_sync_cursor(FILL_CURSOR_KEY)
    logger.info("sync_fills start mode=%s cursor=%s", mode, cursor)

    inserted = skipped = failed = pages = 0
    while pages < max_pages:
        batch = broker.get_account_activities(
            "FILL", page_token=cursor, page_size=page_size
        )
        if not batch:
            break
        pages += 1

        for act in batch:
            try:
                is_new = repo.insert_fill(Fill(
                    fill_id=act["id"],
                    broker_order_id=act["order_id"],
                    symbol=act["symbol"],
                    side=act["side"],
                    qty=act["qty"],  # THIS execution — never cum_qty
                    price=act["price"],
                    fill_type=act["type"],
                    filled_at=_parse_broker_time(act["transaction_time"]),
                    mode=mode,
                ))
                inserted += int(is_new)
                skipped += int(not is_new)
            except Exception:
                failed += 1
                logger.exception(
                    "sync_fills could not store activity id=%s order=%s — "
                    "this execution is missing from the metrics",
                    act.get("id"), act.get("order_id"),
                )

        # Advance past the whole page, including any record that failed: not
        # advancing would wedge the sync on it forever. Failures are counted and
        # logged instead, and rewinding the cursor re-imports them.
        cursor = batch[-1]["id"]
        repo.set_sync_cursor(FILL_CURSOR_KEY, cursor)

    if pages >= max_pages:
        logger.warning(
            "sync_fills stopped at the %d-page safety limit; run again to continue",
            max_pages,
        )
    logger.info(
        "sync_fills done inserted=%d skipped=%d failed=%d pages=%d cursor=%s",
        inserted, skipped, failed, pages, cursor,
    )
    return {"inserted": inserted, "skipped": skipped, "failed": failed,
            "pages": pages, "cursor": cursor}


def sync_orders_terminal(broker, repo) -> dict:
    """Close out orders that reached a terminal state at the broker.

    Needed because a cancelled, rejected or expired order produces no execution
    and therefore never appears in the activity feed — without this, it stays
    "open" in our tables forever.

    Only the STATUS field is read. `get_order()` deliberately exposes no
    quantity or price, so no fill can be derived from it.

    Args:
        broker: A BrokerAdapter.
        repo: Repository for `get_open_orders` and `set_order_terminal`.

    Returns:
        {"checked": int, "closed": int, "failed": int} — `closed` counts orders
        moved to a terminal status this run.

    Raises:
        Nothing per order: a lookup failure is logged and the batch continues,
        so one unknown order cannot block the rest.
    """
    checked = closed = failed = 0
    for order in repo.get_open_orders():
        if not order.broker_order_id:
            continue  # never reached the broker; nothing to ask about
        checked += 1
        try:
            status = str(broker.get_order(order.broker_order_id).get("status", ""))
        except Exception:
            failed += 1
            logger.exception(
                "sync_orders_terminal lookup failed order=%s broker_order=%s",
                order.order_id, order.broker_order_id,
            )
            continue

        terminal = _TERMINAL_STATUS.get(status.lower())
        if terminal:
            repo.set_order_terminal(order.order_id, terminal)
            closed += 1
            logger.info(
                "order terminal order=%s broker_order=%s status=%s",
                order.order_id, order.broker_order_id, terminal,
            )

    logger.info(
        "sync_orders_terminal done checked=%d closed=%d failed=%d",
        checked, closed, failed,
    )
    return {"checked": checked, "closed": closed, "failed": failed}
