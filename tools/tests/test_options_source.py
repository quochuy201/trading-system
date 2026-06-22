"""OptionsDataSource: live fetch is sanity-gated (offline, fake broker)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.options_source import AlpacaOptionsSource, get_options_source, OptionsDataSource


class _FakeBroker:
    def get_option_chain(self, underlying):
        return [
            {"type": "C", "iv": 0.3, "greeks": {"delta": 0.5}, "dte": 40, "bid": 2.0, "ask": 2.1, "mid": 2.05},
            {"type": "C", "iv": 0.3, "greeks": {"delta": 0.4}, "dte": 40, "bid": 0.0, "ask": 2.0, "mid": 1.0},  # one-sided → dropped
            {"type": "C", "iv": 0.3, "greeks": {"delta": 0.3}, "dte": 200, "bid": 1.0, "ask": 1.1, "mid": 1.05}, # out of DTE → dropped
        ]
    def get_option_snapshot(self, syms):
        return [{"symbol": syms[0], "bid": 1.0, "ask": 1.05, "mid": 1.025, "iv": 0.3, "greeks": {"delta": 0.5}}]


def test_get_chain_filters_dte_and_sanity():
    src = AlpacaOptionsSource(_FakeBroker())
    out = src.get_chain("AAPL", dte_min=30, dte_max=45)
    assert len(out) == 1            # one-sided dropped, out-of-DTE dropped
    assert out[0]["greeks"]["delta"] == 0.5


def test_factory_returns_adapter():
    assert isinstance(get_options_source(_FakeBroker()), OptionsDataSource)


def test_iv_rank_reads_history_only():
    from persistence.repository import Repository
    repo = Repository(":memory:")
    rows = [{"symbol": "AAA", "date": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
             "iv": 0.20 + (i % 40) * 0.005, "source": "snapshot"} for i in range(70)]
    repo.save_iv_data_batch(rows)
    src = AlpacaOptionsSource(_FakeBroker())
    out = src.iv_rank(repo, "AAA")
    assert out["data_points"] >= 60
    assert 0 <= out["iv_rank"] <= 100


def test_iv_rank_insufficient_history():
    from persistence.repository import Repository
    repo = Repository(":memory:")
    repo.save_iv_data("AAA", "2026-06-01", 0.3, "snapshot")
    out = AlpacaOptionsSource(_FakeBroker()).iv_rank(repo, "AAA")
    assert "error" in out
