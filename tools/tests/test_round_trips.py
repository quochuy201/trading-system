"""Tests for round-trip construction (go-live-metrics Task 5).

A round trip is what a person means by "a trade", and it is almost never one
fill: a 300-share entry filled in two executions and scaled out in two more is
four fills and one trip.

The most important test here is the rebuild invariant. `round_trips` is a
cache; `fills` is the truth. If a rebuild does not reproduce the cache exactly
— ids included — then every stored metric is unfixable, because recomputing
history would silently renumber it.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from audit.round_trips import build_round_trips, rebuild_round_trips
from models import Fill, Order, TradePlan
from persistence.repository import Repository

BASE = datetime(2026, 4, 30, 13, 30, tzinfo=timezone.utc)


def f(fid, side, qty, price, minutes=0, symbol="NVDA", mode="paper", order="brk-1"):
    """One fill. `minutes` orders the stream; ids stay explicit for the hashes."""
    return Fill(
        fill_id=fid, broker_order_id=order, symbol=symbol, side=side,
        qty=qty, price=price, fill_type="fill",
        filled_at=BASE + timedelta(minutes=minutes), mode=mode,
    )


def _store(repo, fills):
    for fill in fills:
        repo.insert_fill(fill)


# --- pairing ---


def test_simple_pair():
    trips = build_round_trips([
        f("e1", "buy", 100, 150.00, 0),
        f("x1", "sell", 100, 154.00, 10),
    ])
    assert len(trips) == 1
    t = trips[0]
    assert t["direction"] == "long"
    assert t["quantity"] == 100
    assert t["entry_price"] == 150.00 and t["exit_price"] == 154.00
    assert t["gross_pnl"] == pytest.approx(400.00)


def test_partial_entry_uses_quantity_weighted_average():
    """100 @150.10 + 200 @150.15 is NOT (150.10+150.15)/2."""
    trips = build_round_trips([
        f("e1", "buy", 100, 150.10, 0),
        f("e2", "buy", 200, 150.15, 1),
        f("x1", "sell", 300, 154.00, 10),
    ])
    assert len(trips) == 1
    expected = (100 * 150.10 + 200 * 150.15) / 300
    assert trips[0]["entry_price"] == pytest.approx(expected)
    assert trips[0]["entry_price"] != pytest.approx((150.10 + 150.15) / 2)
    assert trips[0]["quantity"] == 300


def test_scale_out_is_one_trip():
    trips = build_round_trips([
        f("e1", "buy", 300, 150.00, 0),
        f("x1", "sell", 150, 154.00, 10),
        f("x2", "sell", 150, 154.20, 11),
    ])
    assert len(trips) == 1
    assert trips[0]["exit_price"] == pytest.approx((150 * 154.00 + 150 * 154.20) / 300)
    assert len(trips[0]["exit_fill_ids"]) == 2


def test_short_trip_pnl_is_inverted():
    trips = build_round_trips([
        f("e1", "sell", 100, 154.00, 0),
        f("x1", "buy", 100, 150.00, 10),
    ])
    assert trips[0]["direction"] == "short"
    assert trips[0]["gross_pnl"] == pytest.approx(400.00)  # sold high, bought back low


def test_open_position_produces_no_trip():
    """No exit means no outcome. A row here would report a result we do not have."""
    assert build_round_trips([f("e1", "buy", 100, 150.00, 0)]) == []


def test_flr_sequence_yields_two_trips_long_then_short():
    """buy 311, sell 311, sell 267, buy 267 — one plan, unambiguously 2 trips.

    This is the ambiguity that `plan_id` grouping cannot resolve, and the
    reason pairing tracks the running position instead.
    """
    trips = build_round_trips([
        f("e1", "buy", 311, 10.00, 0),
        f("x1", "sell", 311, 11.00, 10),
        f("e2", "sell", 267, 12.00, 20),
        f("x2", "buy", 267, 11.50, 30),
    ])
    assert [t["direction"] for t in trips] == ["long", "short"]
    assert trips[0]["gross_pnl"] == pytest.approx(311.00)
    assert trips[1]["gross_pnl"] == pytest.approx(0.50 * 267)


def test_a_single_fill_that_flips_the_position_is_split():
    """Long 100, then one sell of 300: closes the long AND opens a short 200.

    The fill belongs to both trips, with different quantities in each.
    """
    trips = build_round_trips([
        f("e1", "buy", 100, 150.00, 0),
        f("flip", "sell", 300, 154.00, 10),
        f("x2", "buy", 200, 152.00, 20),
    ])
    assert [t["direction"] for t in trips] == ["long", "short"]
    assert trips[0]["quantity"] == 100 and trips[1]["quantity"] == 200
    assert "flip" in trips[0]["exit_fill_ids"]
    assert "flip" in trips[1]["entry_fill_ids"]
    assert trips[1]["gross_pnl"] == pytest.approx((154.00 - 152.00) * 200)


def test_symbols_and_modes_never_mix():
    """Paper and live are separate ledgers; two symbols are separate positions."""
    trips = build_round_trips([
        f("a1", "buy", 100, 150.00, 0, symbol="NVDA"),
        f("b1", "buy", 100, 50.00, 1, symbol="AAPL"),
        f("a2", "sell", 100, 154.00, 10, symbol="NVDA"),
        f("b2", "sell", 100, 52.00, 11, symbol="AAPL"),
        f("c1", "buy", 100, 150.00, 0, mode="live"),
        f("c2", "sell", 100, 160.00, 10, mode="live"),
    ])
    assert len(trips) == 3
    assert {t["symbol"] for t in trips} == {"NVDA", "AAPL"}
    assert sorted(t["mode"] for t in trips) == ["live", "paper", "paper"]


def test_same_timestamp_fills_are_ordered_stably():
    """Two executions can share a millisecond; the result must not depend on
    dict/insert order, or ids would flicker between rebuilds."""
    a = build_round_trips([f("e1", "buy", 100, 150.0, 0), f("x1", "sell", 100, 154.0, 0)])
    b = build_round_trips([f("x1", "sell", 100, 154.0, 0), f("e1", "buy", 100, 150.0, 0)])
    assert a[0]["round_trip_id"] == b[0]["round_trip_id"]


# --- the derived id ---


def test_id_is_derived_from_the_boundary_fills():
    from audit.ids import round_trip_id
    trips = build_round_trips([
        f("e1", "buy", 100, 150.00, 0),
        f("e2", "buy", 100, 150.50, 1),
        f("x1", "sell", 100, 154.00, 10),
        f("x2", "sell", 100, 154.50, 11),
    ])
    assert trips[0]["round_trip_id"] == round_trip_id("e1", "x2")


def test_fees_are_marked_unattributable_rather_than_zeroed():
    """Alpaca's fill activities carry no fee data, and account-level fees have
    no order_id. Reporting 0.0 without the flag would overstate net_pnl."""
    trips = build_round_trips([
        f("e1", "buy", 100, 150.00, 0), f("x1", "sell", 100, 154.00, 10)])
    assert trips[0]["fees_attributable"] == 0
    assert trips[0]["net_pnl"] == trips[0]["gross_pnl"]


# --- ⭐ the rebuild invariant ---


def _snapshot(repo):
    """Every column except rebuilt_at, which is metadata and not hashed."""
    rows = repo.conn.execute(
        "SELECT * FROM round_trips ORDER BY round_trip_id").fetchall()
    return [{k: r[k] for k in r.keys() if k != "rebuilt_at"} for r in rows]


def _links(repo):
    return repo.conn.execute(
        "SELECT * FROM round_trip_fills ORDER BY round_trip_id, fill_id"
    ).fetchall()


def test_rebuild_is_byte_identical_including_ids():
    """⭐ The single most important test in this feature.

    round_trips is a cache. If a rebuild does not reproduce it exactly, then a
    bug in the pairing or the R formula can never be fixed — recomputing would
    renumber history and dangle every reference.
    """
    repo = Repository(":memory:")
    _store(repo, [
        f("e1", "buy", 100, 150.00, 0),
        f("e2", "buy", 200, 150.15, 1),
        f("x1", "sell", 150, 154.00, 10),
        f("x2", "sell", 150, 154.20, 11),
    ])

    rebuild_round_trips(repo)
    before, before_links = _snapshot(repo), [tuple(r) for r in _links(repo)]

    # corrupt the cache the way a bad deploy would
    repo.conn.execute("UPDATE round_trips SET entry_price = 999, quantity = 1")
    repo.conn.execute("DELETE FROM round_trip_fills")
    repo.conn.commit()

    rebuild_round_trips(repo)

    assert _snapshot(repo) == before
    assert [tuple(r) for r in _links(repo)] == before_links
    repo.close()


def test_rebuild_is_idempotent():
    repo = Repository(":memory:")
    _store(repo, [f("e1", "buy", 100, 150.0, 0), f("x1", "sell", 100, 154.0, 10)])
    first = rebuild_round_trips(repo)
    snapshot = _snapshot(repo)
    assert rebuild_round_trips(repo) == first
    assert _snapshot(repo) == snapshot
    repo.close()


def test_rebuild_reflects_a_late_middle_fill_without_renumbering():
    """A fill discovered inside an existing trip must keep round_trip_id (so
    references survive) and change content_hash (so the amendment is visible).
    """
    repo = Repository(":memory:")
    _store(repo, [f("e1", "buy", 100, 150.00, 0), f("x1", "sell", 100, 154.00, 20)])
    rebuild_round_trips(repo)
    before = _snapshot(repo)[0]

    _store(repo, [f("e2", "buy", 100, 151.00, 5)])   # arrives late, in the middle
    _store(repo, [f("x2", "sell", 100, 154.00, 19)])  # keeps it closing at x1
    rebuild_round_trips(repo)
    after = _snapshot(repo)[0]

    assert after["round_trip_id"] == before["round_trip_id"]
    assert after["content_hash"] != before["content_hash"]
    assert after["quantity"] == 200
    repo.close()


def test_rebuild_truncates_trips_whose_fills_are_gone():
    repo = Repository(":memory:")
    _store(repo, [f("e1", "buy", 100, 150.0, 0), f("x1", "sell", 100, 154.0, 10)])
    rebuild_round_trips(repo)
    assert len(_snapshot(repo)) == 1

    repo.conn.execute("DELETE FROM fills")
    repo.conn.commit()
    rebuild_round_trips(repo)

    assert _snapshot(repo) == []
    assert _links(repo) == []
    repo.close()


# --- the link table ---


def test_every_composing_fill_is_linked_with_its_leg():
    repo = Repository(":memory:")
    _store(repo, [
        f("e1", "buy", 100, 150.00, 0),
        f("e2", "buy", 200, 150.15, 1),
        f("x1", "sell", 150, 154.00, 10),
        f("x2", "sell", 150, 154.20, 11),
    ])
    rebuild_round_trips(repo)

    legs = {r["fill_id"]: r["leg"] for r in _links(repo)}
    assert legs == {"e1": "entry", "e2": "entry", "x1": "exit", "x2": "exit"}
    repo.close()


def test_a_flip_fill_links_to_both_trips():
    repo = Repository(":memory:")
    _store(repo, [
        f("e1", "buy", 100, 150.00, 0),
        f("flip", "sell", 300, 154.00, 10),
        f("x2", "buy", 200, 152.00, 20),
    ])
    rebuild_round_trips(repo)

    rows = [r for r in _links(repo) if r["fill_id"] == "flip"]
    assert len(rows) == 2
    assert sorted(r["leg"] for r in rows) == ["entry", "exit"]
    repo.close()


def test_fills_table_is_never_stamped_with_a_trip_id():
    """Round trips are computed later, so stamping fills would need an UPDATE —
    breaking the append-only immutability the design rests on."""
    repo = Repository(":memory:")
    cols = {r["name"] for r in repo.conn.execute("PRAGMA table_info(fills)")}
    assert "round_trip_id" not in cols
    repo.close()


# --- plan context ---


def test_plan_context_is_carried_through_from_the_entry_order():
    repo = Repository(":memory:")
    repo.save_trade_plan(TradePlan(plan_id="p1", symbol="NVDA", side="buy",
                                   quantity=100, strategy="swing",
                                   sop_version="v1.3.0", regime="RISK_ON"))
    repo.save_order(Order(order_id="o1", plan_id="p1", broker_order_id="brk-1",
                          symbol="NVDA", side="buy", order_type="market",
                          qty_requested=100, mode="paper",
                          regime_at_entry="RISK_ON"))
    _store(repo, [f("e1", "buy", 100, 150.0, 0), f("x1", "sell", 100, 154.0, 10)])
    rebuild_round_trips(repo)

    t = _snapshot(repo)[0]
    assert t["plan_id"] == "p1"
    assert t["strategy"] == "swing" and t["sop_version"] == "v1.3.0"
    assert t["regime_at_entry"] == "RISK_ON"
    repo.close()


def test_orphan_fills_still_produce_a_trip_with_null_context():
    """250 real fills in the dev DB have no matching order row — backfilled
    history. They must still measure, with context NULL rather than invented."""
    repo = Repository(":memory:")
    _store(repo, [f("e1", "buy", 100, 150.0, 0), f("x1", "sell", 100, 154.0, 10)])
    rebuild_round_trips(repo)

    t = _snapshot(repo)[0]
    assert t["gross_pnl"] == pytest.approx(400.0)
    assert t["plan_id"] is None and t["strategy"] is None
    assert t["regime_at_entry"] is None
    repo.close()


def test_task_6_columns_are_left_null_not_zeroed():
    """A 0.0 here would later be indistinguishable from a real measurement."""
    repo = Repository(":memory:")
    _store(repo, [f("e1", "buy", 100, 150.0, 0), f("x1", "sell", 100, 154.0, 10)])
    rebuild_round_trips(repo)

    t = _snapshot(repo)[0]
    assert t["r_multiple"] is None
    assert t["initial_stop"] is None
    assert t["slippage"] is None
    repo.close()


# --- Task 6: R-multiple ---


class TestRMultiple:
    """R is *the* performance metric: outcome in units of the risk taken.

    Every uncomputable case must return a reason, never a number. A silent 0.0
    would be indistinguishable from a real break-even trade and would drag the
    expectancy D5 gates on toward zero.
    """

    def test_long_r_hand_computed(self):
        from audit.round_trips import r_multiple
        # entry 150.25, stop 147.10 -> risk 3.15; exit 158.40 -> gain 8.15
        r, reason = r_multiple("long", 150.25, 158.40, 147.10)
        assert reason is None
        assert round(r, 4) == round(8.15 / 3.15, 4) == 2.5873

    def test_short_r_hand_computed(self):
        from audit.round_trips import r_multiple
        # entry 50.71, stop 52.20 -> risk 1.49; exit 48.61 -> gain 2.10
        r, reason = r_multiple("short", 50.71, 48.61, 52.20)
        assert reason is None
        assert round(r, 4) == round(2.10 / 1.49, 4) == 1.4094

    def test_losing_long_is_negative_r(self):
        from audit.round_trips import r_multiple
        r, reason = r_multiple("long", 150.00, 147.00, 145.00)
        assert reason is None
        assert r == pytest.approx(-0.6)  # lost 3 of the 5 risked

    def test_a_full_stop_out_is_exactly_minus_one(self):
        from audit.round_trips import r_multiple
        r, _ = r_multiple("long", 150.00, 145.00, 145.00)
        assert r == pytest.approx(-1.0)

    def test_break_even_is_zero_and_not_a_missing_value(self):
        """0.0 here is a real outcome. It must be a number with no reason —
        that is exactly why uncomputable cases return None instead."""
        from audit.round_trips import r_multiple
        r, reason = r_multiple("long", 150.00, 150.00, 145.00)
        assert r == 0.0 and reason is None

    def test_missing_stop_is_null_with_a_reason(self):
        from audit.round_trips import r_multiple
        r, reason = r_multiple("long", 150.00, 160.00, None)
        assert r is None and reason == "no_stop_recorded"

    def test_zero_stop_placeholder_is_refused(self):
        """TradePlan.stop_loss defaults to 0.0. Treating that as a real stop
        gives risk == entry_price and a plausible-looking R that is fiction."""
        from audit.round_trips import r_multiple
        r, reason = r_multiple("long", 150.00, 160.00, 0.0)
        assert r is None and reason == "stop_is_zero_placeholder"

    def test_stop_on_the_wrong_side_is_refused(self):
        """A long whose stop sits above entry has non-positive risk. Estimating
        one would fabricate the denominator of the number D7 is judged on."""
        from audit.round_trips import r_multiple
        r, reason = r_multiple("long", 150.00, 160.00, 155.00)
        assert r is None and reason == "non_positive_risk"
        r, reason = r_multiple("short", 150.00, 140.00, 145.00)
        assert r is None and reason == "non_positive_risk"

    def test_stop_equal_to_entry_is_refused_not_infinite(self):
        from audit.round_trips import r_multiple
        r, reason = r_multiple("long", 150.00, 160.00, 150.00)
        assert r is None and reason == "non_positive_risk"

    def test_uncomputable_never_returns_zero(self):
        from audit.round_trips import r_multiple
        for stop in (None, 0.0, 155.00, 150.00):
            r, reason = r_multiple("long", 150.00, 160.00, stop)
            assert r is None and reason, f"stop={stop} produced {r!r}"


# --- Task 6: slippage ---


class TestSlippage:
    """Positive always means worse, whichever way the trade goes. This is the
    number that reveals whether paper fills are flattering us."""

    def test_long_paying_more_than_intended_is_positive(self):
        from audit.round_trips import slippage
        assert slippage("long", 150.25, 150.00) == pytest.approx(0.25)

    def test_long_getting_a_better_price_is_negative(self):
        from audit.round_trips import slippage
        assert slippage("long", 149.80, 150.00) == pytest.approx(-0.20)

    def test_short_selling_lower_than_intended_is_positive(self):
        from audit.round_trips import slippage
        assert slippage("short", 153.50, 154.00) == pytest.approx(0.50)

    def test_short_selling_higher_is_negative(self):
        from audit.round_trips import slippage
        assert slippage("short", 154.30, 154.00) == pytest.approx(-0.30)

    def test_no_reference_price_is_null_not_zero(self):
        """0.0 would read as 'filled exactly at intent' — a claim we cannot make."""
        from audit.round_trips import slippage
        assert slippage("long", 150.25, None) is None


# --- Task 6: end to end through the rebuild ---


def _trip_with_plan(repo, stop_loss, intended_price, side="buy",
                    entry=150.00, exit_=160.00):
    repo.save_trade_plan(TradePlan(plan_id="p1", symbol="NVDA", side=side,
                                   quantity=100, stop_loss=stop_loss))
    repo.save_order(Order(order_id="o1", plan_id="p1", broker_order_id="brk-1",
                          symbol="NVDA", side=side, order_type="limit",
                          qty_requested=100, intended_price=intended_price,
                          mode="paper"))
    other = "sell" if side == "buy" else "buy"
    _store(repo, [f("e1", side, 100, entry, 0), f("x1", other, 100, exit_, 10)])
    rebuild_round_trips(repo)
    return _snapshot(repo)[0]


def test_r_and_slippage_land_in_the_table():
    repo = Repository(":memory:")
    t = _trip_with_plan(repo, stop_loss=145.00, intended_price=149.50)
    assert t["initial_stop"] == 145.00
    assert round(t["r_multiple"], 4) == 2.0          # gained 10 on 5 risked
    assert t["r_uncomputable_reason"] is None
    assert t["slippage"] == pytest.approx(0.50)      # paid 150.00 vs 149.50
    repo.close()


def test_short_trip_r_and_slippage_end_to_end():
    repo = Repository(":memory:")
    t = _trip_with_plan(repo, stop_loss=155.00, intended_price=150.50,
                        side="sell", entry=150.00, exit_=145.00)
    assert t["direction"] == "short"
    assert round(t["r_multiple"], 4) == 1.0          # gained 5 on 5 risked
    assert t["slippage"] == pytest.approx(0.50)      # sold 150.00 vs 150.50
    repo.close()


def test_fill_with_no_order_row_reports_no_order_recorded():
    """All 250 real fills predate intent capture, so they have no order row.
    The reason must say that precisely — it is unrecoverable history, not a
    planning gap, and the scorecard's exclusions should distinguish them."""
    repo = Repository(":memory:")
    _store(repo, [f("e1", "buy", 100, 150.0, 0), f("x1", "sell", 100, 154.0, 10)])
    rebuild_round_trips(repo)

    t = _snapshot(repo)[0]
    assert t["r_multiple"] is None
    assert t["r_uncomputable_reason"] == "no_order_recorded"
    assert t["slippage"] is None
    repo.close()


def test_ad_hoc_order_without_a_plan_reports_no_plan_recorded():
    """An order we DID record but that carries no plan is a different case:
    a manual trade, not missing history."""
    repo = Repository(":memory:")
    repo.save_order(Order(order_id="o1", broker_order_id="brk-1", symbol="NVDA",
                          side="buy", order_type="market", qty_requested=100,
                          mode="paper"))
    _store(repo, [f("e1", "buy", 100, 150.0, 0), f("x1", "sell", 100, 154.0, 10)])
    rebuild_round_trips(repo)

    t = _snapshot(repo)[0]
    assert t["r_uncomputable_reason"] == "no_plan_recorded"
    repo.close()


def test_plan_without_a_stop_reports_the_placeholder():
    repo = Repository(":memory:")
    t = _trip_with_plan(repo, stop_loss=0.0, intended_price=None)
    assert t["r_multiple"] is None
    assert t["r_uncomputable_reason"] == "stop_is_zero_placeholder"
    repo.close()


def test_metrics_survive_the_rebuild_invariant():
    """R and slippage are derived too — a rebuild must reproduce them exactly."""
    repo = Repository(":memory:")
    _trip_with_plan(repo, stop_loss=145.00, intended_price=149.50)
    before = _snapshot(repo)

    repo.conn.execute("UPDATE round_trips SET r_multiple = 99, slippage = 99")
    repo.conn.commit()
    rebuild_round_trips(repo)

    assert _snapshot(repo) == before
    repo.close()
