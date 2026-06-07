# tools/tests/test_regime.py
"""Tests for the pure market-regime signal function."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from persistence.repository import Repository
from analysis.regime import compute_market_regime


def _bars(symbol: str, closes: list[float]) -> list[dict]:
    """Build daily bars from a list of closes; high/low straddle close by ±1."""
    out = []
    for i, c in enumerate(closes):
        out.append({
            "symbol": symbol,
            "timestamp": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}T00:00:00",
            "open": round(c, 2), "high": round(c + 1, 2),
            "low": round(c - 1, 2), "close": round(c, 2),
            "volume": 1_000_000, "timeframe": "1Day",
        })
    return out


class TestRegime:
    def setup_method(self):
        self.repo = Repository(":memory:")

    def teardown_method(self):
        self.repo.close()

    def test_uptrend_above_sma50(self):
        # 60 strictly rising closes -> price above SMA50, trend up
        self.repo.save_price_bars(_bars("SPY", [100 + i for i in range(60)]))
        r = compute_market_regime(self.repo, "SPY", "2026-01-01", "2026-12-31")
        assert r["spy_vs_sma50_pct"] > 0
        assert r["spy_trend"] == "up"
        assert r["spy_tr_atr"] is not None and r["spy_tr_atr"] > 0
        assert r["vix"] is None and r["iv_rank_spy"] is None  # not injected
        assert r["as_of"] is not None

    def test_downtrend_below_sma50(self):
        self.repo.save_price_bars(_bars("SPY", [160 - i for i in range(60)]))
        r = compute_market_regime(self.repo, "SPY", "2026-01-01", "2026-12-31")
        assert r["spy_vs_sma50_pct"] < 0
        assert r["spy_trend"] == "down"

    def test_injected_vix_and_ivrank_passthrough(self):
        self.repo.save_price_bars(_bars("SPY", [100 + i for i in range(60)]))
        r = compute_market_regime(
            self.repo, "SPY", "2026-01-01", "2026-12-31",
            vix=27.5, iv_rank_spy=82.0,
        )
        assert r["vix"] == 27.5
        assert r["iv_rank_spy"] == 82.0

    def test_insufficient_data_is_failsafe_null(self):
        self.repo.save_price_bars(_bars("SPY", [100 + i for i in range(10)]))  # <22 bars
        r = compute_market_regime(self.repo, "SPY", "2026-01-01", "2026-12-31")
        assert r["spy_tr_atr"] is None
        assert r["spy_vs_sma50_pct"] is None
        assert r["spy_trend"] is None
        assert "warning" in r

    def test_atr_window_boundary_needs_22_bars(self):
        # Constant true range (every bar high-low spans exactly 2) -> the
        # today/prior-20 ATR ratio must be exactly 1.0 once computable.
        # 21 bars cannot form a correct prior-20 window -> fail-safe null.
        # 22 bars is the minimum that yields the correct 1.0 ratio.
        self.repo.save_price_bars(_bars("R21", [100 + i for i in range(21)]))
        r21 = compute_market_regime(self.repo, "R21", "2026-01-01", "2026-12-31")
        assert r21["spy_tr_atr"] is None
        assert "warning" in r21

        self.repo.save_price_bars(_bars("R22", [100 + i for i in range(22)]))
        r22 = compute_market_regime(self.repo, "R22", "2026-01-01", "2026-12-31")
        assert r22["spy_tr_atr"] == 1.0
