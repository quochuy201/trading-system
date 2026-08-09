"""Telegram notification tools.

Telegram Bot API sendMessage endpoint. Fire-and-forget (never raise, never
block trading). MarkdownV2 parse mode for native formatting.

Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in environment.
"""

import json
import logging
import os
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)

_MAX_LEN = 4096  # Telegram hard limit on message text


def send_telegram_message(text: str) -> dict:
    """Send a message to Telegram via Bot API. Fire-and-forget."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.debug("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set, skipping notification")
        return {"sent": False, "reason": "telegram not configured"}

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text[:_MAX_LEN],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        req = Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read())
            if body.get("ok"):
                return {"sent": True, "status": resp.status}
            else:
                logger.warning("Telegram API error: %s", body.get("description"))
                return {"sent": False, "reason": body.get("description", "unknown")}
    except (URLError, TimeoutError, json.JSONDecodeError) as e:
        logger.warning("Telegram notification failed: %s", e)
        return {"sent": False, "reason": str(e)}
