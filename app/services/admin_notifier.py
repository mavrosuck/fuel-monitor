"""Private, best-effort operational notifications for the monitor owner."""

import logging
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

from aiogram import Bot

logger = logging.getLogger(__name__)


def _local_timestamp(now: datetime, timezone: str) -> str:
    return now.astimezone(ZoneInfo(timezone)).strftime("%Y-%m-%d %H:%M")


def build_admin_error_alert(title: str, now: datetime, timezone: str, error: BaseException | None = None) -> str:
    lines = ["⚠️ Fuel Monitor", title, f"{_local_timestamp(now, timezone)} Orenburg"]
    if error is not None:
        lines.append(f"Причина: {type(error).__name__}")
    return "\n".join(lines)


class AdminNotifier:
    def __init__(
        self,
        token: str | None,
        chat_id: int | None,
        timezone: str,
        bot_factory: Callable[[str], Bot] = Bot,
    ) -> None:
        self.chat_id = chat_id
        self.timezone = timezone
        self._bot = bot_factory(token) if token and chat_id is not None else None

    @property
    def enabled(self) -> bool:
        return self._bot is not None

    async def notify_error(self, title: str, now: datetime, error: BaseException | None = None) -> None:
        if self._bot is None or self.chat_id is None:
            return
        try:
            await self._bot.send_message(self.chat_id, build_admin_error_alert(title, now, self.timezone, error))
        except Exception as notifier_error:
            logger.warning("Admin notification failed: %s", type(notifier_error).__name__)

    async def close(self) -> None:
        if self._bot is None:
            return
        try:
            await self._bot.session.close()
        except Exception as notifier_error:
            logger.warning("Admin notifier close failed: %s", type(notifier_error).__name__)
