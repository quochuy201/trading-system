"""Tests for options sanity/anomaly validation (pure, offline)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.options_validate import sanity_check_quote, iv_anomaly


def _q(bid=2.0, ask=2.1, iv=0.30):
    return {"bid": bid, "ask": ask, "mid": (bid + ask) / 2, "iv": iv,
            "greeks": {"delta": 0.5}}


def test_sanity_ok():
    ok, reason = sanity_check_quote(_q())
    assert ok and reason == ""


def test_sanity_rejects_one_sided():
    ok, reason = sanity_check_quote(_q(bid=0.0))
    assert not ok and "bid" in reason.lower()


def test_sanity_rejects_crossed():
    ok, _ = sanity_check_quote(_q(bid=2.5, ask=2.0))
    assert not ok


def test_sanity_rejects_wide_spread():
    ok, _ = sanity_check_quote(_q(bid=1.0, ask=2.0))  # 67% rel spread
    assert not ok


def test_sanity_rejects_absurd_iv():
    ok, _ = sanity_check_quote(_q(iv=7.0))
    assert not ok


def test_iv_anomaly():
    assert iv_anomaly(0.30, 0.60) is True       # +100% jump
    assert iv_anomaly(0.30, 0.33) is False       # +10%
    assert iv_anomaly(None, 0.30) is False       # no prior → not anomalous
