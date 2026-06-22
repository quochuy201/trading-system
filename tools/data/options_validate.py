"""Options data validation — sanity-gate live quotes, flag IV anomalies.

Pure functions so corruption from the INDICATIVE feed (synthetic/one-sided
quotes) is rejected before it sizes a trade or poisons the IV series.
"""


def sanity_check_quote(contract: dict, max_rel_spread: float = 0.25) -> tuple[bool, str]:
    """Return (ok, reason). Rejects missing/one-sided/crossed/too-wide quotes and absurd IV."""
    bid = float(contract.get("bid") or 0.0)
    ask = float(contract.get("ask") or 0.0)
    iv = float(contract.get("iv") or 0.0)
    if bid <= 0 or ask <= 0:
        return False, "missing/one-sided bid or ask"
    if ask < bid:
        return False, "crossed quote (ask < bid)"
    mid = (bid + ask) / 2
    if (ask - bid) / mid > max_rel_spread:
        return False, f"spread too wide ({(ask - bid) / mid:.0%} > {max_rel_spread:.0%})"
    if not (0 < iv < 5):
        return False, f"implausible IV ({iv})"
    return True, ""


def iv_anomaly(prev_iv: float | None, new_iv: float, max_jump_pct: float = 50.0) -> bool:
    """True if new_iv jumps more than max_jump_pct vs the prior captured point."""
    if prev_iv is None or prev_iv <= 0:
        return False
    return abs(new_iv / prev_iv - 1) * 100 > max_jump_pct
