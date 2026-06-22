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
