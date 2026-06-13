"""Notification channels (Slack + Discord) and structured report formatters."""
import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent))

from notifications.discord import send_discord_message
from notifications.slack import (
    format_analysis_pick,
    format_position_exited,
    format_trade_executed,
)


def test_discord_skips_when_no_webhook(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    result = send_discord_message("hello")
    assert result == {"sent": False, "reason": "no webhook configured"}


def test_discord_posts_content_field(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/webhook")
    captured = {}

    class FakeResp:
        status = 204
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=5):
        captured["url"] = req.full_url
        captured["payload"] = json.loads(req.data.decode())
        return FakeResp()

    with mock.patch("notifications.discord.urlopen", fake_urlopen):
        result = send_discord_message("BUY 10 NVDA")
    assert result == {"sent": True, "status": 204}
    assert captured["payload"] == {"content": "BUY 10 NVDA"}


def test_discord_truncates_to_2000_chars(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/webhook")

    class FakeResp:
        status = 204
        def __enter__(self): return self
        def __exit__(self, *a): return False

    captured = {}

    def fake_urlopen(req, timeout=5):
        captured["payload"] = json.loads(req.data.decode())
        return FakeResp()

    with mock.patch("notifications.discord.urlopen", fake_urlopen):
        send_discord_message("x" * 5000)
    assert len(captured["payload"]["content"]) == 2000


def test_analysis_pick_includes_symbol_thesis_and_rr():
    text = format_analysis_pick(
        "NVDA", "M", 8, "Quantum catalyst", 220.0, 210.0, 250.0, "full")
    assert "NVDA" in text and "Quantum catalyst" in text
    assert "$220.00" in text and "$210.00" in text and "$250.00" in text
    assert "3.0:1" in text  # (250-220)/(220-210)


def test_buy_and_sell_formatters():
    buy = format_trade_executed("NVDA", "buy", 10, 220.5, "plan_x")
    assert "BUY" in buy and "NVDA" in buy and "220.50" in buy
    sell = format_position_exited("NVDA", 300.0, 11.1, "take_profit")
    assert "NVDA" in sell and "300.00" in sell and "take_profit" in sell
