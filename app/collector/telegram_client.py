import logging
from dataclasses import dataclass
from typing import Any

from telethon import TelegramClient, events

from app.collector.message_handler import MessageHandler
from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChatDiagnostic:
    """Безопасное для вывода описание доступного Telegram-источника."""

    source: str
    chat_id: int | None
    title: str | None
    username: str | None
    messages: list[tuple[int, Any, str]]
    error: str | None = None


def create_telegram_client(settings: Settings) -> TelegramClient:
    """Создаёт клиент с тем же persistent session для app и diagnostic CLI."""
    return TelegramClient(
        settings.telethon_session_name,
        settings.telegram_api_id,
        settings.telegram_api_hash.get_secret_value(),
    )


async def inspect_source_chats(client: Any, source_chats: list[str], limit: int = 5) -> list[ChatDiagnostic]:
    """Проверяет доступ к чатам и читает последние сообщения, ничего не отправляя."""
    diagnostics: list[ChatDiagnostic] = []
    for source in source_chats:
        try:
            entity = await client.get_entity(source)
            messages = [
                (message.id, message.date, (message.raw_text or "")[:300])
                async for message in client.iter_messages(entity, limit=limit)
            ]
            diagnostics.append(
                ChatDiagnostic(
                    source=source,
                    chat_id=entity.id,
                    title=getattr(entity, "title", None),
                    username=getattr(entity, "username", None),
                    messages=messages,
                )
            )
        except Exception as exc:
            logger.exception("Cannot inspect Telegram source %s", source)
            diagnostics.append(ChatDiagnostic(source=source, chat_id=None, title=None, username=None, messages=[], error=str(exc)))
    return diagnostics


class TelegramCollector:
    def __init__(self, settings: Settings, handler: MessageHandler) -> None:
        self.settings, self.handler = settings, handler
        self.client = create_telegram_client(settings)

    async def start(self) -> None:
        await self.client.start(phone=self.settings.telegram_phone)
        source_chats = self.settings.source_chats

        @self.client.on(events.NewMessage(chats=source_chats))
        async def on_message(event):
            try:
                chat = await event.get_chat()
                # Captions/media are retained by Telegram but intentionally never
                # enter the hourly OpenAI text batch.
                text = event.raw_text or ""
                if event.message.media:
                    await self.handler.store_backfill(event.chat_id, getattr(chat, "username", None), event.message.id, text, event.message.date)
                    return
                await self.handler.process(event.chat_id, getattr(chat, "username", None), event.message.id, text, event.message.date)
            except Exception:
                logger.exception("Error processing Telegram message")

        diagnostics = await inspect_source_chats(self.client, source_chats)
        for diagnostic in diagnostics:
            if diagnostic.error:
                logger.error("Telegram source unavailable: source=%s error=%s", diagnostic.source, diagnostic.error)
                continue
            assert diagnostic.chat_id is not None
            stored = 0
            for message_id, message_date, text in diagnostic.messages:
                if await self.handler.store_backfill(
                    diagnostic.chat_id,
                    diagnostic.username,
                    message_id,
                    text,
                    message_date,
                ):
                    stored += 1
            logger.info(
                "Telegram source verified: source=%s chat_id=%s username=%s title=%s recent=%d backfill_saved=%d",
                diagnostic.source,
                diagnostic.chat_id,
                diagnostic.username,
                diagnostic.title,
                len(diagnostic.messages),
                stored,
            )

        logger.info("Telegram collector connected to %s", ", ".join(source_chats))

    async def run(self) -> None:
        await self.client.run_until_disconnected()

    async def stop(self) -> None:
        await self.client.disconnect()
