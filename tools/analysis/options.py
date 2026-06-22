"""Options analysis — pure calculation functions (stdlib math only, no pandas/numpy).

All functions are stateless and have no side effects. They accept plain Python
types and return plain Python types (float, dict, or math.nan on failure).
"""

import math


# ---------------------------------------------------------------------------
# OCC Symbol Parsing
# ---------------------------------------------------------------------------


def parse_occ_symbol(symbol: str) -> dict:
    """Parse an OCC option symbol into its components.

    OCC format: <ROOT><YYMMDD><TYPE><8-digit-strike>
    The suffix is always exactly 15 characters: 6 date + 1 type + 8 strike.
    The root is everything before the suffix (variable length).

    Args:
        symbol: OCC option symbol string, e.g. "AAPL250620C00230000"

    Returns:
        dict with keys:
            underlying (str)  — ticker root, e.g. "AAPL"
            expiration (str)  — YYMMDD string, e.g. "250620"
            type       (str)  — "C" or "P"
            strike     (float) — dollar value, e.g. 230.0

    Example:
        >>> parse_occ_symbol("AAPL250620C00230000")
        {'underlying': 'AAPL', 'expiration': '250620', 'type': 'C', 'strike': 230.0}
    """
    # OCC suffix is always 15 chars (6 + 1 + 8)
    suffix = symbol[-15:]
    root = symbol[:-15]

    date_str = suffix[:6]       # YYMMDD
    option_type = suffix[6]     # C or P
    strike_str = suffix[7:15]   # 8-digit integer, divide by 1000 for dollars

    strike = int(strike_str) / 1000.0

    return {
        "underlying": root,
        "expiration": date_str,
        "type": option_type,
        "strike": strike,
    }


# ---------------------------------------------------------------------------
# ATM IV Extraction
# ---------------------------------------------------------------------------


def nearest_dte_contracts(chain: list[dict], target_dte: int = 30) -> list[dict]:
    """Return only the contracts of the single expiration whose DTE is closest to target_dte.

    Used to capture a consistent ~30-day ATM IV (IV30) rather than mixing tenors.
    Returns [] for an empty chain.
    """
    dtes = {c.get("dte") for c in chain if c.get("dte") is not None}
    if not dtes:
        return []
    best = min(dtes, key=lambda d: abs(d - target_dte))
    return [c for c in chain if c.get("dte") == best]


def atm_iv(chain: list[dict]) -> float | None:
    """Aggregate ATM IV: average of the call and put whose |delta| is nearest 0.50.

    Returns None if no suitable contract is found. (Relocated from server.py for
    reuse by the options data source.)
    """
    calls = [c for c in chain if c.get("type", "").upper() == "C" and c.get("iv", 0) > 0]
    puts = [c for c in chain if c.get("type", "").upper() == "P" and c.get("iv", 0) > 0]
    if not calls and not puts:
        return None
    ivs = []
    if calls:
        best_call = min(calls, key=lambda c: abs(abs(c.get("greeks", {}).get("delta", 0)) - 0.50))
        if abs(abs(best_call.get("greeks", {}).get("delta", 0)) - 0.50) < 0.15:
            ivs.append(best_call["iv"])
    if puts:
        best_put = min(puts, key=lambda c: abs(abs(c.get("greeks", {}).get("delta", 0)) - 0.50))
        if abs(abs(best_put.get("greeks", {}).get("delta", 0)) - 0.50) < 0.15:
            ivs.append(best_put["iv"])
    if not ivs:
        all_with_delta = [c for c in chain if c.get("iv", 0) > 0 and c.get("greeks", {}).get("delta")]
        if all_with_delta:
            best = min(all_with_delta, key=lambda c: abs(abs(c["greeks"]["delta"]) - 0.50))
            return best["iv"]
        return None
    return sum(ivs) / len(ivs)


# ---------------------------------------------------------------------------
# IV Rank
# ---------------------------------------------------------------------------


def calc_iv_rank(current_iv: float, iv_history: list) -> float:
    """Calculate IV Rank (IVR) as a 0–100 percentile of current IV vs history.

    Formula: IVR = (current - min) / (max - min) × 100
    Clamped to [0, 100]. Returns 50.0 if fewer than 2 distinct values in history.

    Args:
        current_iv:  Current implied volatility (e.g. 0.30 for 30%).
        iv_history:  List of historical IV values.

    Returns:
        Float in [0, 100], or 50.0 if history is insufficient to rank.

    Example:
        >>> calc_iv_rank(0.30, [0.10, 0.20, 0.30, 0.40, 0.50])
        50.0
    """
    distinct = set(iv_history)
    if len(distinct) < 2:
        return 50.0

    lo = min(iv_history)
    hi = max(iv_history)

    if hi == lo:
        return 50.0

    ivr = (current_iv - lo) / (hi - lo) * 100.0
    return max(0.0, min(100.0, ivr))


# ---------------------------------------------------------------------------
# Historical Volatility
# ---------------------------------------------------------------------------


def calc_hv(closes: list, window: int = 20) -> float:
    """Calculate annualized historical volatility from closing prices.

    Uses log returns, std of the last `window` returns, annualized by √252.
    Requires at least window+1 close prices.

    Args:
        closes: List of closing prices (floats), oldest first.
        window: Rolling window for std calculation (default 20).

    Returns:
        Annualized HV as a float, or math.nan if insufficient data.

    Example:
        >>> calc_hv([100.0] * 22, window=20)
        0.0
    """
    if len(closes) < window + 1:
        return math.nan

    # Compute log returns for all available bars
    log_returns = [
        math.log(closes[i] / closes[i - 1])
        for i in range(1, len(closes))
    ]

    # Use the last `window` log returns
    sample = log_returns[-window:]
    n = len(sample)

    if n < 1:
        return math.nan

    mean = sum(sample) / n
    if n > 1:
        variance = sum((r - mean) ** 2 for r in sample) / (n - 1)
    else:
        variance = 0.0

    daily_std = math.sqrt(variance)
    return daily_std * math.sqrt(252)


# ---------------------------------------------------------------------------
# Put Skew
# ---------------------------------------------------------------------------


def calc_put_skew(chain: list, target_delta: float = 0.25) -> float:
    """Calculate put skew in IV percentage points at the nearest target delta.

    Matches the SOP definition (options-vol-edge/v1.0.0 §Phase 1):
        put_skew = IV_OTM_put − IV_equidistant_OTM_call

    expressed in IV percentage points (e.g. put IV 0.35 vs call IV 0.28 → 7.0).
    Positive skew means puts carry richer IV than equidistant calls (the normal
    state); the SOP's bonus trigger is put_skew > 5 and its soft-gate warning is
    put_skew < 0.

    Searches for the put and call contracts whose absolute delta is closest to
    target_delta. A tolerance of ±0.10 is applied; if the nearest match for
    either side exceeds that tolerance the function returns NaN.

    Args:
        chain:         List of contract dicts with keys "type", "delta", "iv".
                       delta should be a positive float (absolute value).
        target_delta:  Target delta to find (default 0.25 for 25-delta).

    Returns:
        (put_iv − call_iv) × 100, in IV percentage points, or math.nan if
        matching contracts can't be found.

    Example:
        >>> chain = [{"type": "put", "delta": 0.25, "iv": 0.35},
        ...          {"type": "call", "delta": 0.25, "iv": 0.20}]
        >>> calc_put_skew(chain, target_delta=0.25)
        15.0
    """
    tolerance = 0.10

    puts = [c for c in chain if c.get("type", "").lower() == "put"]
    calls = [c for c in chain if c.get("type", "").lower() == "call"]

    if not puts or not calls:
        return math.nan

    best_put = min(puts, key=lambda c: abs(c["delta"] - target_delta))
    best_call = min(calls, key=lambda c: abs(c["delta"] - target_delta))

    if abs(best_put["delta"] - target_delta) > tolerance:
        return math.nan
    if abs(best_call["delta"] - target_delta) > tolerance:
        return math.nan

    return (best_put["iv"] - best_call["iv"]) * 100.0


# ---------------------------------------------------------------------------
# Expected Move
# ---------------------------------------------------------------------------


def calc_expected_move(stock_price: float, iv: float, dte: int) -> float:
    """Calculate the expected 1-sigma move over the remaining DTE.

    Formula: stock_price × iv × √(dte / 365)

    Args:
        stock_price: Current stock price.
        iv:          Implied volatility as a decimal (e.g. 0.20 for 20%).
        dte:         Days to expiration (integer).

    Returns:
        Expected move in dollars. Returns 0.0 if dte <= 0.

    Example:
        >>> calc_expected_move(100.0, 0.20, 30)
        5.724...
    """
    if dte <= 0:
        return 0.0
    return stock_price * iv * math.sqrt(dte / 365.0)


# ---------------------------------------------------------------------------
# Black-Scholes
# ---------------------------------------------------------------------------


def _norm_cdf(x: float) -> float:
    """Standard normal CDF using math.erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes_price(
    stock: float,
    strike: float,
    dte: int,
    rate: float,
    vol: float,
    option_type: str,
) -> float:
    """Price a European option using the Black-Scholes formula.

    Args:
        stock:       Current underlying price.
        strike:      Option strike price.
        dte:         Days to expiration.
        rate:        Risk-free interest rate as a decimal (e.g. 0.05).
        vol:         Implied volatility as a decimal (e.g. 0.20).
        option_type: "call" / "C" / "put" / "P" (case-insensitive).

    Returns:
        Option price (float). Returns intrinsic value when dte == 0.

    Example:
        >>> black_scholes_price(100.0, 100.0, 30, 0.05, 0.20, "call")
        2.99...
    """
    opt = option_type.lower()
    is_call = opt in ("call", "c")

    # At expiry return intrinsic value
    if dte <= 0:
        if is_call:
            return max(stock - strike, 0.0)
        else:
            return max(strike - stock, 0.0)

    T = dte / 365.0
    sqrt_T = math.sqrt(T)

    # Guard against zero or near-zero vol
    if vol <= 0.0:
        # Deterministic price: discounted intrinsic
        if is_call:
            return max(stock - strike * math.exp(-rate * T), 0.0)
        else:
            return max(strike * math.exp(-rate * T) - stock, 0.0)

    d1 = (math.log(stock / strike) + (rate + 0.5 * vol ** 2) * T) / (vol * sqrt_T)
    d2 = d1 - vol * sqrt_T

    if is_call:
        return stock * _norm_cdf(d1) - strike * math.exp(-rate * T) * _norm_cdf(d2)
    else:
        return strike * math.exp(-rate * T) * _norm_cdf(-d2) - stock * _norm_cdf(-d1)


# ---------------------------------------------------------------------------
# Implied Volatility (BSM inversion via bisection)
# ---------------------------------------------------------------------------


def implied_vol_from_price(
    option_price: float,
    stock: float,
    strike: float,
    dte: int,
    rate: float,
    option_type: str,
    *,
    max_iter: int = 200,
    tol: float = 1e-6,
) -> float:
    """Invert the Black-Scholes formula to find implied volatility.

    Uses bisection between vol=1e-6 and vol=10.0 (1000% IV). Returns math.nan
    if the option_price is outside the feasible range or bisection fails to
    converge.

    Args:
        option_price: Market price of the option.
        stock:        Current underlying price.
        strike:       Option strike price.
        dte:          Days to expiration.
        rate:         Risk-free rate as a decimal.
        option_type:  "call" / "C" / "put" / "P" (case-insensitive).
        max_iter:     Maximum bisection iterations (default 200).
        tol:          Convergence tolerance on volatility (default 1e-6).

    Returns:
        Implied volatility as a float, or math.nan on failure.

    Example:
        >>> price = black_scholes_price(100.0, 100.0, 30, 0.05, 0.25, "call")
        >>> implied_vol_from_price(price, 100.0, 100.0, 30, 0.05, "call")
        0.25...
    """
    if option_price < 0.0:
        return math.nan

    # Bracket the search
    lo_vol = 1e-6
    hi_vol = 10.0

    lo_price = black_scholes_price(stock, strike, dte, rate, lo_vol, option_type)
    hi_price = black_scholes_price(stock, strike, dte, rate, hi_vol, option_type)

    # Target must lie within [lo_price, hi_price]
    if option_price < lo_price - tol or option_price > hi_price + tol:
        return math.nan

    # Clamp to bracket for numerical safety
    option_price = max(lo_price, min(hi_price, option_price))

    for _ in range(max_iter):
        mid_vol = 0.5 * (lo_vol + hi_vol)
        mid_price = black_scholes_price(stock, strike, dte, rate, mid_vol, option_type)

        if abs(mid_price - option_price) < tol:
            return mid_vol

        if mid_price < option_price:
            lo_vol = mid_vol
        else:
            hi_vol = mid_vol

        if hi_vol - lo_vol < tol:
            return 0.5 * (lo_vol + hi_vol)

    return math.nan
