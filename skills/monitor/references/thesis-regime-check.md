# Engine M Thesis–Regime Check (SPY vs SMA20/SMA50)

**Trigger:** An Engine M (momentum) swing position is open AND SPY closes below
BOTH SMA20 AND SMA50 after entry.

**Meaning:** The momentum thesis the entry was built on (broad-market uptrend
participation) is invalidated at the regime level. This is NOT dead money — the
position may still bounce — but the macro tailwind is gone.

**Action (flag only — NO auto-exit):**
1. Log `action="adjust"`, `rules_triggered=["THESIS_REGIME_BREAK"]` with the SPY
   levels in market_context.
2. Flag for operator review in the monitor report and EOD summary.
3. Do NOT exit. Normal mechanical exits (stop / target / scale-out / time stop)
   continue to govern the position.
4. Re-check daily. If SPY reclaims SMA20 (and ideally SMA50), note the flag
   clears and the regime tailwind is restored.

**Rationale:** A momentum entry validated on an uptrend regime should not be
silently held through a confirmed regime break; but exiting at a bad price
without a stop hit is also wrong. The operator decides; the machine keeps the
position managed by the original plan.

## Worked example (2026-07-31)
PANW Engine M swing (entry 334.35, plan PANW-20260722-swing, day 8/20).
SPY 743.6 below SMA20 (745.6) and SMA50 (743.9), VIX 17.
→ Flag THESIS_REGIME_BREAK for operator review. Position held per plan;
   no auto-exit.
