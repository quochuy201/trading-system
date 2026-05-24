"""Slack notification tools."""

import json
import logging
import os
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)


def send_slack_message(text: str, blocks: list[dict] | None = None) -> dict:
    """Send a message to Slack via webhook. Fire-and-forget (never blocks trading)."""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        logger.debug("SLACK_WEBHOOK_URL not set, skipping notification")
        return {"sent": False, "reason": "no webhook configured"}

    payload = {"text": text}
    if blocks:
        payload["blocks"] = blocks

    try:
        req = Request(
            webhook_url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=5) as resp:
            return {"sent": True, "status": resp.status}
    except (URLError, TimeoutError) as e:
        logger.warning("Slack notification failed: %s", e)
        return {"sent": False, "reason": str(e)}


def format_trade_executed(symbol: str, side: str, quantity: int, price: float, plan_id: str) -> str:
    emoji = "🟢" if side == "buy" else "🔴"
    return f"{emoji} *Trade Executed*: {side.upper()} {quantity} {symbol} @ ${price:.2f} (plan: {plan_id})"


def format_position_exited(symbol: str, pnl: float, pnl_pct: float, reason: str) -> str:
    emoji = "✅" if pnl >= 0 else "❌"
    return f"{emoji} *Position Closed*: {symbol} | P&L: ${pnl:.2f} ({pnl_pct:.1f}%) | Reason: {reason}"


def format_daily_summary(trades: int, wins: int, pnl: float, equity: float) -> str:
    win_rate = (wins / trades * 100) if trades > 0 else 0
    emoji = "📈" if pnl >= 0 else "📉"
    return (
        f"{emoji} *Daily Summary*\n"
        f"• Trades: {trades} ({wins}W / {trades - wins}L) — {win_rate:.0f}% win rate\n"
        f"• P&L: ${pnl:.2f}\n"
        f"• Equity: ${equity:.2f}"
    )


def format_alert(message: str, severity: str = "warning") -> str:
    emoji = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(severity, "⚠️")
    return f"{emoji} *Alert*: {message}"
