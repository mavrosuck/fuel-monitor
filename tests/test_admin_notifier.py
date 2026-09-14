import asyncio
import logging
from datetime import UTC, datetime
from types import SimpleNamespace

from app import runner
from app.services.admin_notifier import AdminNotifier


class FakeBot:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []
        self.session = SimpleNamespace(close=self._close)

    async def send_message(self, chat_id: int, text: str) -> None:
        self.calls.append((chat_id, text))

    async def _close(self) -> None:
        return None


def test_notifier_is_disabled_without_admin_chat_id(caplog) -> None:
    settings = SimpleNamespace(bot_token=None, timezone="Asia/Yekaterinburg")

    with caplog.at_level(logging.INFO):
        notifier = runner._admin_notifier(settings)

    assert not notifier.enabled
    assert "Admin notifications: disabled" in caplog.text


def test_notifier_sends_only_to_configured_admin_chat() -> None:
    bot = FakeBot()
    notifier = AdminNotifier("unused", 123456, "Asia/Yekaterinburg", bot_factory=lambda _token: bot)

    asyncio.run(notifier.notify_error("MAX collection failed", datetime(2026, 9, 15, 5, tzinfo=UTC), TimeoutError()))

    assert [chat_id for chat_id, _text in bot.calls] == [123456]
    assert "MAX collection failed" in bot.calls[0][1]
    assert "TimeoutError" in bot.calls[0][1]


def test_notifier_failure_is_best_effort_and_does_not_raise() -> None:
    class FailingBot(FakeBot):
        async def send_message(self, _chat_id: int, _text: str) -> None:
            raise ConnectionError("unavailable")

    notifier = AdminNotifier("unused", 123456, "Asia/Yekaterinburg", bot_factory=lambda _token: FailingBot())

    asyncio.run(notifier.notify_error("Gemini request failed after retries", datetime(2026, 9, 15, 5, tzinfo=UTC)))
