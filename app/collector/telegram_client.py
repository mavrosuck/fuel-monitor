import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from telethon import TelegramClient

from app.collector.models import CollectedMessage
from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatDiagnostic:
    source: str
    chat_id: int | None
    title: str | None
    username: str | None
    messages: list[tuple[int, Any, str]]
    error: str | None = None


def create_telegram_client(settings: Settings) -> TelegramClient:
    return TelegramClient(settings.telethon_session_name, settings.telegram_api_id, settings.telegram_api_hash.get_secret_value())


async def inspect_source_chats(client: Any, source_chats: list[str], limit: int = 5) -> list[ChatDiagnostic]:
    diagnostics: list[ChatDiagnostic] = []
    for source in source_chats:
        try:
            entity = await client.get_entity(source)
            messages = [(message.id, message.date, (message.raw_text or "")[:300]) async for message in client.iter_messages(entity, limit=limit)]
            diagnostics.append(ChatDiagnostic(source, entity.id, getattr(entity, "title", None), getattr(entity, "username", None), messages))
        except Exception as exc:
            logger.exception("Cannot inspect Telegram source %s", source)
            diagnostics.append(ChatDiagnostic(source, None, None, None, [], str(exc)))
    return diagnostics


class TelegramCollector:
    """Collects the current time window; it never starts a long-running listener."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = create_telegram_client(settings)

    async def collect_since(self, start: datetime, end: datetime) -> list[CollectedMessage]:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("collection window must be timezone-aware")
        messages: list[CollectedMessage] = []
        await self.client.connect()
        try:
            if not await self.client.is_user_authorized():
                raise RuntimeError("Telethon session is not authorized")
            for source in self.settings.source_chats:
                entity = await self.client.get_entity(source)
                chat_id = int(entity.id)
                username = getattr(entity, "username", None)
                async for message in self.client.iter_messages(entity):
                    message_date = message.date.astimezone(UTC)
                    if message_date < start:
                        break
                    if message_date > end:
                        continue
                    if message.media:
                        continue
                    text = (message.raw_text or "").strip()
                    if not text:
                        continue
                    messages.append(
                        CollectedMessage(
                            platform="telegram",
                            source_chat_id=chat_id,
                            source_message_id=message.id,
                            message_date=message_date,
                            text=text,
                            source_name=source,
                        )
                    )
        finally:
            await self.client.disconnect()
        return messages
