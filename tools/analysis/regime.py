# tools/analysis/regime.py
"""Pure market-regime signal computation.

Returns RAW measured signals only — never a classified regime and never an
eligibility decision. The routing SOP (sops/_routing/) maps these signals to
strategy ON/OFF, and the agent applies it. Keeping the decision out of Python
is required by CLAUDE.md (no strategy logic in code).

vix and iv_rank_spy are INJECTED by the caller (the MCP tool wrapper fetches
them) so this function stays pure and unit-testable. A missing signal is left
as None; the SOP treats None as fail-safe restrictive.
"""

from datetime import datetime, timezone

from persistence.repository import Repository


def _true_range(bar: dict, prev_close: float) -> float:
    hi, lo = float(bar["high"]), float(bar["low"])
    return max(hi - lo, abs(hi - prev_close), abs(lo - prev_close))


def compute_market_regime(
    repo: Repository,
    symbol: str = "SPY",
    start: str = "2000-01-01",
    end: str = "2100-01-01",
    timeframe: str = "1Day",
    vix: float | None = None,
    iv_rank_spy: float | None = None,
) -> dict:
    """Compute raw regime signals from cached index bars.

    Args:
        repo: price-data repository.
        symbol: index proxy (default "SPY").
        start, end: clock bounds; pass current_time as `end` for no-look-ahead.
        vix: injected VIX level (None if unavailable).
        iv_rank_spy: injected SPY IV-rank 0-100 (None if unavailable).

    Returns:
        dict: {vix, spy_tr_atr, spy_vs_sma50_pct, spy_trend, iv_rank_spy, as_of}
        Price-derived fields are None (with a "warning") when data is insufficient.
    """
    as_of = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "vix": vix,
        "spy_tr_atr": None,
        "spy_vs_sma50_pct": None,
        "spy_trend": None,
        "iv_rank_spy": iv_rank_spy,
        "as_of": as_of,
    }

    bars = repo.query_price_data(symbol, start, end, timeframe)
    # Need >= 22 bars: 20 prior true ranges + today's TR. With 21 bars the
    # prior-20 ATR window would be short one element and silently understate
    # ATR; fail-safe to null instead (the SOP treats null as restrictive).
    if len(bars) < 22:
        snapshot["warning"] = f"insufficient data: {len(bars)} bars (need >= 22)"
        return snapshot

    closes = [float(b["close"]) for b in bars]

    # spy_tr_atr: today's true range / mean true range of the prior 20 bars.
    # trs has len(bars)-1 elements (>= 21 here), so trs[-21:-1] is exactly the
    # 20 bars before today, and trs[-1] is today.
    trs = [_true_range(bars[i], closes[i - 1]) for i in range(1, len(bars))]
    atr20 = sum(trs[-21:-1]) / 20.0           # 20 bars before today
    tr_today = trs[-1]
    snapshot["spy_tr_atr"] = round(tr_today / atr20, 3) if atr20 > 0 else None

    # spy_vs_sma50_pct: % of latest close above/below SMA50 (None if <50 bars)
    if len(closes) >= 50:
        sma50 = sum(closes[-50:]) / 50.0
        snapshot["spy_vs_sma50_pct"] = round((closes[-1] - sma50) / sma50 * 100, 2)

    # spy_trend: position vs SMA20 + SMA20 slope (up | down | flat)
    sma20_now = sum(closes[-20:]) / 20.0
    sma20_prev = sum(closes[-21:-1]) / 20.0
    rising = sma20_now > sma20_prev
    above = closes[-1] > sma20_now
    if above and rising:
        snapshot["spy_trend"] = "up"
    elif (not above) and (not rising):
        snapshot["spy_trend"] = "down"
    else:
        snapshot["spy_trend"] = "flat"

    return snapshot
