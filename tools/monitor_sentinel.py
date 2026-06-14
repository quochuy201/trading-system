#!/usr/bin/env python3
"""Every-minute mechanical monitor sentinel (NO LLM).

Runs cheaply once a minute during market hours. Reads positions, plans, and
account guards directly via the server tool functions, computes how close each
position is to an actionable level, and — only when a threshold trips — enqueues
a kanban monitor task so the LLM monitor agent reacts per skills/monitor.

On a quiet minute it prints nothing and exits 0 (cron --no-agent: empty stdout
= no delivery, no LLM call, negligible cost). This is the fast reaction layer;
the scheduled/EOD monitor tasks remain the thorough layer.

Design note: swing STOPS are close-based by SOP (act on hourly bar closes, not
intraday wicks). This sentinel does NOT exit positions itself and does NOT
fabricate stop exits on wicks — it only WAKES the LLM monitor, which applies the
close-based rule. What genuinely needs sub-hour reaction (kill switch, daily-loss
breach, target touches, large adverse moves, options gap-through-strike) is what
trips the wake.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import server  # loads ../.env, registers tool functions

# --- thresholds (tune here) ------------------------------------------------
NEAR_STOP_PCT = 1.0      # within 1% of stop -> wake (close-based rule applied by LLM)
NEAR_TARGET_PCT = 0.5    # within 0.5% of target / target touched -> wake
LARGE_MOVE_PCT = 3.0     # |unrealized move| since entry jump guard handled by LLM
BOARD = "trading"

# Per-condition cooldown: once we wake the LLM monitor for a given condition
# signature, suppress re-waking for the SAME signature within this window so a
# persistent state (e.g. a position parked near its stop all day) doesn't queue
# a monitor run every single minute. A genuinely NEW signature wakes at once.
COOLDOWN_SECONDS = 1800  # 30 min
_STATE_FILE = Path(__file__).parent / "monitor_sentinel_state.json"


def _reasons_to_wake() -> list[str]:
    reasons: list[str] = []

    # 1. Hard guards — always wake immediately.
    try:
        if json.loads(server.check_kill_switch()).get("active"):
            reasons.append("kill_switch_active")
    except Exception as e:
        reasons.append(f"kill_switch_check_error:{e}")
    try:
        dl = json.loads(server.check_daily_limits())
        # risk.checks returns {"passed": bool, ...}; passed=False => breached.
        if "passed" in dl and not dl["passed"]:
            reasons.append("daily_loss_breached")
    except Exception:
        pass  # never block on a guard read

    # 2. Per-position proximity to levels.
    try:
        positions = json.loads(server.get_positions())
    except Exception as e:
        reasons.append(f"positions_read_error:{e}")
        positions = []

    for p in positions:
        sym = p.get("symbol", "?")
        price = p.get("current_price")
        if price is None:
            continue

        # large adverse intraday move vs entry -> let LLM assess thesis
        mv = p.get("unrealized_pnl_pct")
        if mv is not None and mv <= -LARGE_MOVE_PCT:
            reasons.append(f"{sym}:large_drop_{mv:.1f}pct")

        # match to a saved plan for stop/target proximity
        try:
            plans = server.get_repo().list_trade_plans(symbol=sym)
        except Exception:
            plans = []
        if not plans:
            continue
        plan = plans[-1]  # most recent plan for this symbol
        stop = getattr(plan, "stop_loss", None)
        target = getattr(plan, "take_profit", None)

        if stop:
            dist = (price - stop) / price * 100
            if dist <= NEAR_STOP_PCT:
                reasons.append(f"{sym}:near_stop_{dist:.2f}pct")
        if target:
            dist = (target - price) / price * 100
            if dist <= NEAR_TARGET_PCT:
                reasons.append(f"{sym}:near/at_target_{dist:.2f}pct")

    return reasons


def _load_state() -> dict:
    try:
        return json.loads(_STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        _STATE_FILE.write_text(json.dumps(state))
    except Exception:
        pass  # cooldown is best-effort; never fail the sentinel on disk issues


def _signature(reason: str) -> str:
    """Collapse a reason to a stable key so the same condition dedupes across
    minutes even as the exact percentage drifts (e.g. near_stop_0.83pct vs 0.91)."""
    return reason.split("_")[0] if ":" not in reason else \
        reason.split(":")[0] + ":" + reason.split(":")[1].split("_")[0]


def _filter_by_cooldown(reasons: list[str]) -> list[str]:
    """Keep only reasons whose signature hasn't fired within COOLDOWN_SECONDS."""
    now = time.time()
    state = _load_state()
    fresh = []
    for r in reasons:
        sig = _signature(r)
        last = state.get(sig, 0)
        if now - last >= COOLDOWN_SECONDS:
            fresh.append(r)
            state[sig] = now
    # prune stale entries so the file doesn't grow unbounded
    state = {k: v for k, v in state.items() if now - v < COOLDOWN_SECONDS * 2}
    _save_state(state)
    return fresh


def _monitor_task_already_queued() -> bool:
    """Avoid piling up sentinel tasks: skip if one is still ready/running."""
    try:
        out = subprocess.run(
            ["hermes", "kanban", "--board", BOARD, "list"],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except Exception:
        return False
    for line in out.splitlines():
        if "SENTINEL-WAKE" in line and (" ready " in line or " running " in line):
            return True
    return False


def main() -> int:
    reasons = _reasons_to_wake()
    if not reasons:
        return 0  # quiet minute, no LLM, no output

    # suppress conditions we already woke for recently (avoids per-minute storms
    # on a persistent state like a position parked near a level all session)
    reasons = _filter_by_cooldown(reasons)
    if not reasons:
        return 0  # all current triggers are within their cooldown window

    if _monitor_task_already_queued():
        print("sentinel: trigger present but a monitor wake is already queued")
        return 0

    from datetime import datetime
    title = f"{datetime.now():%Y-%m-%d %H:%M} SENTINEL-WAKE monitor"
    body = (
        "Mechanical sentinel detected an actionable condition: "
        + "; ".join(reasons)
        + ". Check ALL open positions against their trade plans and execute any "
        "triggered exits per skills/monitor (apply the close-based stop rule — "
        "do NOT exit on intraday wicks). Report status and notify_sell on each "
        "exit. Then complete."
    )
    try:
        subprocess.run(
            ["hermes", "kanban", "--board", BOARD, "create", title,
             "--assignee", "trading-monitor", "--body", body],
            capture_output=True, text=True, timeout=30, check=True,
        )
        print(f"sentinel: queued monitor wake — {len(reasons)} trigger(s): {reasons}")
    except Exception as e:
        # last resort: surface to operator channels so a wake is never silently lost
        try:
            server.send_notification(
                f"Monitor sentinel could not queue a wake task ({e}). "
                f"Triggers: {reasons}", "critical")
        except Exception:
            pass
        print(f"sentinel: FAILED to queue wake: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
