import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from confirmation_params import load_params, RAILS


def test_defaults_load_and_are_within_rails():
    p = load_params()
    for name, (lo, hi) in RAILS.items():
        assert lo <= p[name] <= hi, f"{name}={p[name]} outside rail ({lo}, {hi})"
    # railed numeric keys are always present after load
    assert set(RAILS) <= set(p)


def test_out_of_range_values_are_clamped(tmp_path):
    bad = tmp_path / "p.json"
    bad.write_text('{"confirmation_window_min": 999, "rvol_multiple": 0.1, '
                   '"slippage_buffer_pct": 50}')
    p = load_params(path=bad)
    assert p["confirmation_window_min"] == RAILS["confirmation_window_min"][1]  # max 90
    assert p["rvol_multiple"] == RAILS["rvol_multiple"][0]                      # min 1.1
    assert p["slippage_buffer_pct"] == RAILS["slippage_buffer_pct"][1]          # max 2.0


def test_missing_file_returns_safe_defaults(tmp_path):
    p = load_params(path=tmp_path / "does_not_exist.json")
    assert p["confirmation_window_min"] == 30
    assert p["rvol_multiple"] == 1.2
