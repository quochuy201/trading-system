"""Price-data validation: anomaly detection + freshness/alignment report.

Pure functions over bar lists and a repository, so corruption (splits, IEX
volume, patchwork freshness) is caught loudly instead of silently skewing the
scanner.
"""

from datetime import date


def find_price_anomalies(bars: list[dict], threshold_pct: float = 35.0) -> list[dict]:
    """Flag day-over-day close moves exceeding threshold_pct (split/decimal hints)."""
    out: list[dict] = []
    prev: float | None = None
    for b in bars:
        c = float(b["close"])
        if prev is not None and prev > 0:
            chg = abs(c / prev - 1) * 100
            if chg > threshold_pct:
                out.append({"symbol": b.get("symbol"), "timestamp": b.get("timestamp"),
                            "pct": round(chg, 1), "prev": prev, "close": c})
        prev = c
    return out


def is_stale(freshest_date: str | None, scan_date: str, max_age_days: int = 5) -> bool:
    """True if data is missing or older than max_age_days vs scan_date (YYYY-MM-DD prefixes).

    Default tolerance is 5 calendar days so a normal market gap (weekend, or a
    holiday + weekend, e.g. Thu close -> Mon scan across Juneteenth) does NOT
    false-flag as stale; a genuinely broken refresh (6+ days) still trips it.
    """
    if not freshest_date:
        return True
    f = date.fromisoformat(freshest_date[:10])
    s = date.fromisoformat(scan_date[:10])
    return (s - f).days > max_age_days


def freshness_report(repo, symbols: list[str], timeframe: str = "1Day") -> dict:
    """Per-symbol latest-bar dates → {freshest, n_fresh, stale, missing, aligned}."""
    dates = {s: repo.latest_price_date(s, timeframe) for s in symbols}
    present = {s: d[:10] for s, d in dates.items() if d}
    freshest = max(present.values()) if present else None
    stale = sorted(s for s, d in present.items() if d != freshest)
    missing = sorted(s for s, d in dates.items() if not d)
    return {
        "freshest": freshest,
        "n_fresh": sum(1 for d in present.values() if d == freshest),
        "stale": stale,
        "missing": missing,
        "aligned": (not stale) and (not missing),
    }
