import asyncio
import logging
from types import SimpleNamespace

from app.publisher.telegram_publisher import TelegramPublisher


def test_log_identity_logs_only_bot_username_and_target_channel(caplog) -> None:
    publisher = object.__new__(TelegramPublisher)
    publisher.bot = SimpleNamespace(get_me=lambda: _get_bot())
    publisher.channel = "@benzinoren"

    with caplog.at_level(logging.INFO):
        asyncio.run(publisher.log_identity())

    assert "Telegram publisher bot: @fuel_monitor_bot" in caplog.text
    assert "Telegram target channel: @benzinoren" in caplog.text
    assert "token" not in caplog.text.casefold()


async def _get_bot():
    return SimpleNamespace(username="fuel_monitor_bot")
