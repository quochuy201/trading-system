"""Bounded loader for adaptive confirmation parameters.

The confirmation LOGIC lives in the SOP; only these PARAMETER VALUES adapt, and
every value is clamped to a hard rail the LLM/EOD review can never exceed. This
keeps adaptation safe (no reckless rule can be written) and backtests pinnable.
"""

import json
from pathlib import Path

_DEFAULT_PATH = Path(__file__).parent / "confirmation_params.json"

# (min, max) hard rails — adaptation may move within these, never beyond.
RAILS = {
    "confirmation_window_min": (15, 90),
    "rvol_multiple": (1.1, 2.0),
    "slippage_buffer_pct": (0.25, 2.0),
}

_DEFAULTS = {
    "version": "default",
    "confirmation_window_min": 30,
    "rvol_multiple": 1.2,
    "entry_cutoff_et": "11:00",
    "slippage_buffer_pct": 0.75,
    "regime": "default",
}


def _clamp(name: str, value):
    lo, hi = RAILS[name]
    return max(lo, min(hi, value))


def load_params(path: Path | None = None) -> dict:
    """Load params, falling back to defaults, with every railed key clamped."""
    path = path or _DEFAULT_PATH
    params = dict(_DEFAULTS)
    try:
        params.update(json.loads(Path(path).read_text()))
    except Exception:
        pass  # missing/corrupt -> safe defaults
    for name in RAILS:
        if name in params:
            try:
                params[name] = _clamp(name, float(params[name]))
            except (TypeError, ValueError):
                params[name] = _DEFAULTS[name]
    # window is an int count of minutes
    params["confirmation_window_min"] = int(params["confirmation_window_min"])
    return params
