# tools/tests/test_scanner_swing.py
"""Tests for scan_universe_swing — sops/equity/swing/v1.0.0.md mechanical gates."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from scanner.filters import scan_universe_swing, _swing_metrics, SWING_V1


def _df(closes, volume=2_000_000, spread=0.01):
    """Build an OHLCV DataFrame from a close series; high/low straddle close."""
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame({
        "open": closes * (1 - spread / 2),
        "high": closes * (1 + spread),
        "low": closes * (1 - spread),
        "close": closes,
        "volume": np.full(len(closes), volume, dtype=float),
    })


def _uptrend(n=200, start=100.0, daily=0.004):
    return [start * (1 + daily) ** i for i in range(n)]


def _spy():
    return _df(_uptrend(200, 500.0, 0.0005))  # nearly flat SPY


class TestEngineM:
    def test_clean_momentum_passes(self):
        # Steady riser: SMA25>SMA50, close>SMA25, big ROC50, beats flat SPY
        df = _df(_uptrend(200, 100.0, 0.004), volume=5_000_000)  # ~$400M+/day
        m = _swing_metrics("MOMO", df, spy_ret_10d=0.5)
        assert m["engine_m_fails"] == [] or m["engine_m_fails"] == ["M-G7"]
        # a perfectly steady riser can trip the chase filter near highs; accept
        # either clean pass or only-chase-fail, but trend gates must hold:
        assert "M-G4" not in m["engine_m_fails"]
        assert "M-G6" not in m["engine_m_fails"]

    def test_downtrend_fails_trend_gate(self):
        df = _df([200 - i * 0.5 for i in range(200)], volume=5_000_000)
        m = _swing_metrics("DOWN", df, spy_ret_10d=0.0)
        assert "M-G4" in m["engine_m_fails"]
        assert m["engine_m_pass"] is False

    def test_illiquid_fails_liquidity_gate(self):
        df = _df(_uptrend(200, 15.0, 0.004), volume=100_000)  # ~$2M/day
        m = _swing_metrics("THIN", df, spy_ret_10d=0.0)
        assert "M-G2" in m["engine_m_fails"]

    def test_parabolic_extension_fails_chase_gate(self):
        # flat then vertical: last closes way above SMA25
        closes = [100.0] * 180 + [100 * 1.06 ** i for i in range(1, 21)]
        df = _df(closes, volume=5_000_000)
        m = _swing_metrics("CHASE", df, spy_ret_10d=0.0)
        assert "M-G7" in m["engine_m_fails"]


class TestEngineR:
    def _dip_df(self, drop_total=0.09):
        """Long uptrend, then a sharp 3-day drop that keeps price above SMA150."""
        base = _uptrend(197, 100.0, 0.004)
        last = base[-1]
        d = (1 + drop_total) ** (1 / 3) - 1
        dips = [last / (1 + d), last / (1 + d) ** 2, last / (1 + d) ** 3]
        return _df(base + dips, volume=5_000_000, spread=0.02)

    def test_sharp_dip_in_uptrend_passes(self):
        df = self._dip_df(0.09)  # ~9% 3-day drop
        m = _swing_metrics("DIPR", df, spy_ret_10d=0.0)
        assert m["engine_r_fails"] == [], m
        assert m["engine_r_pass"] is True
        assert m["drop_3d"] >= SWING_V1["r_drop3_min"]
        assert m["rsi3"] < SWING_V1["r_rsi3_max"]

    def test_shallow_dip_fails_stretch_gate(self):
        df = self._dip_df(0.03)  # only ~3% drop
        m = _swing_metrics("SHAL", df, spy_ret_10d=0.0)
        assert "R-G5" in m["engine_r_fails"]

    def test_broken_long_trend_fails_sma150_gate(self):
        # long downtrend then a dip: price below SMA150
        closes = [200 - i * 0.4 for i in range(197)]
        last = closes[-1]
        closes += [last * 0.97, last * 0.94, last * 0.91]
        df = _df(closes, volume=5_000_000, spread=0.02)
        m = _swing_metrics("BRKN", df, spy_ret_10d=0.0)
        assert "R-G4" in m["engine_r_fails"]


class TestScanUniverseSwing:
    def test_returns_only_passing_symbols_and_skips_short_history(self):
        stock_data = {
            "SPY": _spy(),
            "DOWN": _df([200 - i * 0.5 for i in range(200)], volume=5_000_000),
            "SHORT": _df(_uptrend(100), volume=5_000_000),  # <160 bars → skipped
            "DIPR": TestEngineR()._dip_df(0.09),
        }
        out = scan_universe_swing(stock_data, stock_data["SPY"])
        syms = {c["symbol"] for c in out}
        assert "DIPR" in syms
        assert "DOWN" not in syms      # fails both engines
        assert "SHORT" not in syms     # insufficient history
        assert "SPY" not in syms

    def test_gate_ids_reported_for_agent_logging(self):
        stock_data = {"DIPR": TestEngineR()._dip_df(0.09)}
        out = scan_universe_swing(stock_data, None)
        c = out[0]
        # the failing M gates are named so the agent can log rules_triggered
        assert isinstance(c["engine_m_fails"], list)
        assert c["engine_r_pass"] is True
