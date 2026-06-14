"""Discord notification tools.

Discord incoming webhooks accept a JSON POST with a `content` field (max 2000
chars). Same fire-and-forget contract as the Slack module: never raise, never
block trading. Markdown (`**bold**`, bullets) renders natively in Discord.
"""

import json
import logging
import os
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)

_MAX_LEN = 2000  # Discord hard limit on message content


def send_discord_message(text: str) -> dict:
    """Send a message to Discord via webhook. Fire-and-forget (never blocks trading)."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        logger.debug("DISCORD_WEBHOOK_URL not set, skipping notification")
        return {"sent": False, "reason": "no webhook configured"}

    payload = {"content": text[:_MAX_LEN]}

    try:
        req = Request(
            webhook_url,
            data=json.dumps(payload).encode(),
            # Discord rejects urllib's default User-Agent (Python-urllib/x.y)
            # with HTTP 403; a custom UA is required.
            headers={
                "Content-Type": "application/json",
                "User-Agent": "trading-system-bot/1.0 (+https://github.com)",
            },
        )
        with urlopen(req, timeout=5) as resp:
            return {"sent": True, "status": resp.status}
    except (URLError, TimeoutError) as e:
        logger.warning("Discord notification failed: %s", e)
        return {"sent": False, "reason": str(e)}
