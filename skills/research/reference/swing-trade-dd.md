# Swing Trade Due Diligence — engine-aware rubric

**Pairs with `sops/equity/swing/v1.1.0.md`** (two-engine: M momentum / R
mean-reversion). The scanner (`scan_swing_candidates`) has already applied the
mechanical gates before you see a candidate. This rubric scores what the
scanner CANNOT measure plus trade geometry. Score each candidate 0–100 under
its routed engine. Bensdorp's frame: a system is 12 ingredients; the scanner
covered universe/filter/setup — you cover ranking context, catalyst, risk
geometry, and the decision.

**Score → conviction/SIZE (it does NOT gate entry).** The mechanical scanner has
already qualified the setup; this score only sets size: **≥ 70 → full size · 50–69 →
half size · < 50 → quarter / minimum size.** A mechanically-valid, regime-eligible
candidate ENTERS at the corresponding size — a low score (e.g. no fresh catalyst, so
the 25-pt catalyst block is ~0) **reduces size, it does not SKIP.** The catalyst &
narrative block is a conviction modifier, consistent with `skills/research/SKILL.md`
Layer 3.

**Hard SKIP only via the engine kill list** (gap rules violated · confirmed earnings in
the hold window · R:R < 2:1 · Engine-R structural break / R-G7 · Engine-M LATE-HYPE
chase). A low composite score alone never skips.

---

## Engine M rubric (momentum continuation)

| Block | Max | What earns points |
|---|---|---|
| Setup quality | 30 | Clean trend structure (10): higher highs/lows visible, no overlapping chop. Gate margins (10): roc50 and rs_10d comfortably above minimums, not borderline. Volume character (10): advance on expanding volume, pullbacks on contracting volume. |
| Catalyst & narrative | 25 | Fresh driver behind the strength (15): earnings raise, product cycle, sector leadership — apply the Catalyst Decay Model below. Hype state (10): EARLY/CONFIRMED = 6–10; NO HYPE = 5; LATE HYPE = 0 **and overall veto if price ran >5% on aged buzz**. |
| Market/sector context | 20 | Regime row solidly ON, not borderline (10). Sector ETF outperforming SPY over 10 days (10). |
| Risk geometry | 25 | R:R to next resistance ≥ 2:1 with 2.5×ATR10 stop (15; below 2:1 = 0 and SKIP). Stop below a real structural level, not floating in air (10). |

Engine M kill list (any → SKIP regardless of score): gap rules violated at
entry · earnings within 5 sessions (confirmed) · LATE HYPE state · R:R < 2:1.

### Catalyst Decay Model (Engine M)

| Days Since Catalyst | Strength | Action |
|---|---|---|
| Day 0 | FULL | Full catalyst points |
| Day 1 | HIGH | Most points; prefer pullback entry |
| Day 2 | MEDIUM | Half points — half size ceiling |
| Day 3+ | STALE | 0 points — strength must stand on technicals alone |

**Exception:** multi-week sector rotations (rate cycles, AI capex waves) decay
slowly — treat the SECTOR move as the catalyst and check the sector ETF's RS
instead.

## Engine R rubric (mean-reversion dip)

| Block | Max | What earns points |
|---|---|---|
| Drop diagnosis (R-G7) | 35 | THE block that matters. Why did it drop? Index/sector-wide selloff or sympathy (30–35) · stock-specific but transient: analyst cut, headline overreaction, sympathy with a competitor's bad print (20–29) · unclear cause (10–19) · structural break: fraud, guidance cut, regulatory, key-customer loss, secular demand break (0 → **VETO, log R-G7-FAIL**). |
| Stretch quality | 25 | drop_3d well above the 6% minimum (10). RSI3 in single digits (8). Long-term trend comfortably intact — price above SMA150 by margin, SMA150 still rising (7). |
| Crowd state | 15 | Retail PANIC (bearish buzz, no structural news) = contrarian positive (10–15). Quiet tape = 8. Heavy day-1 "buy the dip" cheerleading = 0–5 (the sellers aren't done). |
| Risk geometry | 25 | 2.5×ATR10 stop clears the recent panic low (10). +4% target < 1.5× average daily range — realistically reachable inside 4 sessions (10). Heat: adding this keeps portfolio ≤ 6% (5). |

Engine R kill list: R-G7 structural break · earnings before expected exit
(confirmed) · limit-entry already gapped past (never market-chase an R entry).

---

## Scoring discipline

1. Score conservatively — borderline evidence earns the bottom of each band.
2. Cite a number or quote for every block; "looks strong" earns nothing.
3. The two engines are judged differently ON PURPOSE: M tolerates a sub-50%
   win rate because winners run; R needs its 55–65% hit rate because winners
   are small. Never apply M's R:R demand to R's target/time-stop exit — and
   never let an R trade "become a swing hold" after the time stop.
4. Output per candidate: engine, score, block subtotals, the one-sentence
   thesis, and the gate IDs that passed/failed (`rules_triggered`).
