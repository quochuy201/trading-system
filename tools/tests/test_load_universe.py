"""Tests for load_universe helpers (network-free)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import load_universe


def test_exclusive_end_includes_daily_end_bar():
    # Half-open [start, end): to load daily_end's own bar the exclusive end is +1 day.
    assert load_universe._exclusive_end("2026-06-22") == "2026-06-23"
    assert load_universe._exclusive_end("2025-12-31") == "2026-01-01"  # year rollover
