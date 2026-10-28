from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from pymax import ExtraConfig, WebClient

from app.emergency_alerts.core import SOURCE_CHANNEL, SourcePost
from app.collector.max_collector import ExistingSessionOnly


class AuthorizedMaxSession:
    """Open the existing personal session for one verified public channel."""

    def __init__(self, session_path: str, chat_id: int, permission_confirmed: bool, client_factory=WebClient) -> None:
        if not permission_confirmed:
            raise PermissionError("MAX automated collection requires platform permission")
        if not chat_id:
            raise ValueError("verified MChS channel ID required")
        path = Path(session_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError("existing MAX session is unavailable")
        self.chat_id = chat_id
        self.client = client_factory(
            work_dir=str(path.parent),
            session_name=path.name,
            auth_flow=ExistingSessionOnly(),
            extra_config=ExtraConfig(log_level="WARNING", reconnect=False, telemetry=False),
        )

    async def __aenter__(self) -> PreparedMaxReader:
        try:
            await self.client.connect()
            if not self.client.is_connected:
                raise ConnectionError("MAX session did not connect")
            chat = await self.client.get_chat(self.chat_id)
            chat_type = getattr(chat, "type", "")
            if getattr(chat_type, "value", chat_type) != "CHANNEL" or getattr(chat, "link", None) != SOURCE_CHANNEL:
                raise ValueError("MAX channel identity does not match official MChS link")
            return PreparedMaxReader(self.client, self.chat_id, lambda post_id: f"{SOURCE_CHANNEL}/{post_id}")
        except BaseException:
            await self.client.close()
            raise

    async def __aexit__(self, *_exc: object) -> None:
        await self.client.close()


class PreparedMaxReader:
    """Read only a verified chat through an already connected, authorized client."""

    def __init__(self, client: object, verified_chat_id: int, post_url_for_id: Callable[[str], str]) -> None:
        if not verified_chat_id:
            raise ValueError("verified channel ID required")
        self.client = client
        self.verified_chat_id = verified_chat_id
        self.post_url_for_id = post_url_for_id

    async def fetch_recent(self, count: int = 20) -> list[SourcePost]:
        if not 1 <= count <= 100:
            raise ValueError("MAX page size must be 1..100")
        messages = await self.client.fetch_history(
            chat_id=self.verified_chat_id,
            backward=count,
            get_chat=False,
            interactive=False,
        )
        return [from_verified_message(message, self.verified_chat_id, self.post_url_for_id(str(message.id))) for message in messages]


def from_verified_message(message: object, verified_chat_id: int, post_url: str) -> SourcePost:
    """Convert one message supplied by an independently authorized, connected reader."""
    if not verified_chat_id or getattr(message, "chat_id", None) != verified_chat_id:
        raise ValueError("message is not from the verified MChS channel")
    timestamp = int(getattr(message, "time"))
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    post_id = str(getattr(message, "id"))
    if post_url != f"{SOURCE_CHANNEL}/{post_id}":
        raise ValueError("unverified MAX post link")
    return SourcePost(
        post_id=post_id,
        channel_url=SOURCE_CHANNEL,
        post_url=post_url,
        published_at=datetime.fromtimestamp(timestamp, UTC),
        text=str(getattr(message, "text") or ""),
    )
