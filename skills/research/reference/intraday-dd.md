# Intraday Trade Due Diligence

> **STATUS: PLACEHOLDER** — To be developed. This file will contain intraday-specific screening criteria, entry timing (opening range breakouts, VWAP reclaims, momentum scalps), and exit rules for sub-day holds.

---

## Planned Sections

- Pre-market gap scan criteria (> 3% gap, > 2x RVOL, identifiable catalyst)
- Opening range breakout (ORB) framework
- VWAP-based entries and exits
- Intraday momentum scoring (first 15-min candle, volume acceleration)
- Time-of-day filters (avoid 12:00-14:00 chop zone)
- Scalp vs. hold decision matrix
- PDT rule compliance (sub-$25K accounts)

---

## Reference

See `sops/day-trade-momentum/v1.0.0.md` for the existing intraday strategy SOP which covers much of this. This reference file will extract the reusable DD patterns for any intraday strategy.
