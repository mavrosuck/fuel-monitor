import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from pymax import ExtraConfig, WebClient

from app.collector.models import CollectedMessage
from app.config import Settings

logger = logging.getLogger(__name__)


class MaxCollectionError(RuntimeError):
    """Raised when a configured MAX source cannot be read completely."""


class ExistingSessionOnly:
    """Refuses to start an interactive login if the saved session is invalid."""

    async def authenticate(self, _app):
        raise MaxCollectionError("MAX session is invalid or expired")


@dataclass(frozen=True)
class MaxCollection:
    messages: list[CollectedMessage]
    message_counts: dict[int, int]
    chat_titles: dict[int, str]


def _message_date(value: int) -> datetime:
    timestamp = value // 1000 if value > 10_000_000_000 else value
    return datetime.fromtimestamp(timestamp, UTC)


class MaxCollector:
    """One-shot read-only collector for explicitly configured MAX chats."""

    HISTORY_PAGE_SIZE = 100
    HISTORY_REQUEST_TIMEOUT_SECONDS = 30
    START_TIMEOUT_SECONDS = 30

    def __init__(
        self,
        settings: Settings,
        client_factory: Callable[..., WebClient] = WebClient,
    ) -> None:
        self.settings = settings
        self.client_factory = client_factory

    async def collect_since(self, start: datetime, end: datetime) -> MaxCollection:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("MAX collection window must be timezone-aware")
        session_path = Path(self.settings.max_session_path).expanduser().resolve()
        if not session_path.is_file():
            raise MaxCollectionError("MAX session file is unavailable")
        logger.info("MAX: opening saved session")
        client = self.client_factory(
            work_dir=str(session_path.parent),
            session_name=session_path.name,
            auth_flow=ExistingSessionOnly(),
            extra_config=ExtraConfig(log_level="WARNING", reconnect=False, telemetry=False),
        )
        collected: list[CollectedMessage] = []
        counts = {chat_id: 0 for chat_id in self.settings.max_source_chat_ids}
        titles: dict[int, str] = {}
        closed = False

        try:
            logger.info("MAX: starting client")
            await asyncio.wait_for(client.connect(), timeout=self.START_TIMEOUT_SECONDS)
            if not client.is_connected:
                raise MaxCollectionError("MAX session is invalid or unavailable")
            logger.info("MAX: client started")
            logger.info("MAX: fetching chats")
            chats = await client.fetch_chats()
            chats_by_id = {int(chat.id): chat for chat in chats}
            missing = set(self.settings.max_source_chat_ids) - set(chats_by_id)
            if missing:
                raise MaxCollectionError("one or more required MAX chats are unavailable")
            for chat_id in self.settings.max_source_chat_ids:
                chat = chats_by_id[chat_id]
                titles[chat_id] = str(chat.title or "(без названия)")
                logger.info("MAX: fetching chat %s", chat_id)
                history = await self._fetch_hour(client, chat_id, start, end)
                for message in history:
                    collected.append(
                        CollectedMessage(
                            platform="max",
                            source_chat_id=chat_id,
                            source_message_id=int(message.id),
                            message_date=_message_date(int(message.time)),
                            text=str(message.text).strip(),
                            source_name=titles[chat_id],
                        )
                    )
                counts[chat_id] = len(history)
        except TimeoutError as exc:
            raise MaxCollectionError("MAX client start timed out; saved session or network is unavailable") from exc
        except MaxCollectionError:
            raise
        except Exception as exc:
            raise MaxCollectionError("MAX connection or history retrieval failed") from exc
        finally:
            if not closed:
                logger.info("MAX: closing client")
                await client.close()
                closed = True
        logger.info("MAX read-only collection completed for %d chats", len(counts))
        return MaxCollection(collected, counts, titles)

    async def _fetch_hour(
        self,
        client: WebClient,
        chat_id: int,
        start: datetime,
        end: datetime,
    ) -> list[object]:
        start_ms = int(start.timestamp() * 1000)
        cursor_ms = int(end.timestamp() * 1000)
        seen_message_ids: set[int] = set()
        messages_in_window: list[object] = []

        while True:
            try:
                page = await asyncio.wait_for(
                    client.fetch_history(
                        chat_id=chat_id,
                        backward=self.HISTORY_PAGE_SIZE,
                        from_time=cursor_ms,
                    ),
                    timeout=self.HISTORY_REQUEST_TIMEOUT_SECONDS,
                )
            except TimeoutError as exc:
                raise MaxCollectionError("MAX history request timed out") from exc
            if not page:
                return messages_in_window
            timestamps_ms = [
                value if value > 10_000_000_000 else value * 1000
                for value in (int(message.time) for message in page)
            ]
            oldest_ms = min(timestamps_ms)
            for message in page:
                message_id = int(message.id)
                message_ms = int(message.time)
                if message_ms <= 10_000_000_000:
                    message_ms *= 1000
                if message_id in seen_message_ids or not start_ms <= message_ms <= cursor_ms:
                    continue
                text = str(message.text or "").strip()
                if text:
                    messages_in_window.append(message)
                    seen_message_ids.add(message_id)
            if oldest_ms <= start_ms:
                return messages_in_window
            next_cursor_ms = oldest_ms - 1
            if next_cursor_ms >= cursor_ms:
                raise MaxCollectionError("MAX history pagination did not advance")
            cursor_ms = next_cursor_ms
