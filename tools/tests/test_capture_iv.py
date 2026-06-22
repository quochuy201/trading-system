import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.options_source import AlpacaOptionsSource
from persistence.repository import Repository


class _Broker:
    def get_option_chain(self, underlying):
        return [{"type": "C", "iv": 0.30, "greeks": {"delta": 0.5}, "dte": 40, "bid": 2, "ask": 2.1, "mid": 2.05},
                {"type": "P", "iv": 0.34, "greeks": {"delta": -0.5}, "dte": 40, "bid": 2, "ask": 2.1, "mid": 2.05}]
    def get_option_snapshot(self, s): return []


def test_capture_iv_writes_history():
    repo = Repository(":memory:")
    out = AlpacaOptionsSource(_Broker()).capture_iv(repo, ["AAA", "BBB"], today="2026-06-21")
    assert out["captured"] == 2
    assert repo.count_iv_history("AAA") == 1
    assert abs(repo.query_iv_history("AAA", min_days=1)[0] - 0.32) < 1e-6  # avg of 0.30/0.34
