# Scanner Tuning Config — 2026-07-16 (Thursday)

## 6a. Exclusion List
| Symbol | Days Rejected | Reason |
|--------|--------------|--------|
| AON | 1 | Sector overlap with IBKR (Finance), ranked below HWM/DXCM by ROC50 |
| AJG | 1 | Sector overlap with IBKR (Finance), ranked below by ROC50 |
| HPQ | 1 | Tech-adjacent sector (overlap with OKTA/PANW) |
| EAT | 1 | Insufficient R:R (1.26:1 vs 2:1 min) with Keybanc PT204 |
| NTAP | 1 | Sector overlap concern (Tech/Cloud adjacent to OKTA+PANW). ROC50 strongest at 45 but sector diversity vetoed |

**Note:** None yet at 2+ consecutive days — these are single-day skips from solid reasoning (sector diversity). Only track if same symbols appear tomorrow.

## 6b. Threshold Overrides (Regime-Adaptive)
- **SPY trend**: UP (+1.71% above SMA50)
- **SPY ATR**: 0.58 (low — low volatility regime)
- **SPY IVR**: 35.3 (moderate)
- **Engine M candidates**: 7 passed (normal for low-ATR bull regime — momentum works well here)
- **Engine R candidates**: 0 passed (expected: low ATR suppresses mean-reversion)
- No threshold overrides needed. Current settings are correctly filtering for regime.

**Recommendation**: Consider lowering Engine R ATR-gate threshold if low-volatility persists (>3 sessions), but no action today.

## 6c. Risk Limit Overrides
- Account equity: $105,447.91
- Daily loss: -$145.64 (-0.14%) — well within 3% limit
- 5 positions held simultaneously (max 5, at limit)
- No overrides needed. Standard 1-2% risk-per-trade maintained.

**Note**: Portfolio was at max position count (5). With today's exits queued, slots free for tomorrow.

## 6d. Notes
- 3 new entries today (DXCM, HWM, IBKR on Jul14)
- 2 legacy entries (OKTA Jul13, PANW Jul8)
- DXCM (Engine M, catalyst score 10/10): current +3.35% — strong start
- HWM (Engine M, catalyst score 7/10): current -2.82% — underwater on entry day
- IBKR (Engine M, catalyst score 7/10): current -2.39% — underwater since Jul14
- OKTA (Engine M, catalyst score 7/10): current +8.62% — best performer
- PANW (Engine M, catalyst score 10/10 v1.0.0): current +6.04% — solid after 8 days

**Auto-revert condition**: If SPY closes below SMA50 (> 0%), revert to DEFENSIVE (half size on all entries).

## 6e. Friday Full Review
- [ ] Not Friday — full review skipped. Next: 2026-07-17 (Friday)
