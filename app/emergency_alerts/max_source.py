from __future__ import annotations

import stat
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from pymax import ExtraConfig, WebClient

from app.emergency_alerts.core import MAX_AGE, SOURCE_CHANNEL, SOURCE_CHAT_ID, SourcePost
from app.collector.max_collector import ExistingSessionOnly


class AuthorizedMaxSession:
    """Open the existing personal session for one verified public channel."""

    def __init__(self, session_path: str, chat_id: int, permission_confirmed: bool, client_factory=WebClient) -> None:
        if not permission_confirmed:
            raise PermissionError("MAX automated collection requires platform permission")
        if chat_id != SOURCE_CHAT_ID:
            raise ValueError("verified MChS channel ID does not match the pinned source")
        requested_path = Path(session_path).expanduser()
        if requested_path.is_symlink():
            raise ValueError("MAX session must be a private regular file, not a symlink")
        path = requested_path.resolve()
        if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
            raise FileNotFoundError("existing MAX session is unavailable")
        if path.stat().st_mode & 0o077:
            raise ValueError("MAX session must not be readable or writable by other users")
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
            return PreparedMaxReader(self.client, self.chat_id)
        except BaseException:
            await self.client.close()
            raise

    async def __aexit__(self, *_exc: object) -> None:
        await self.client.close()


class PreparedMaxReader:
    """Read only a verified chat through an already connected, authorized client."""

    def __init__(self, client: object, verified_chat_id: int) -> None:
        if verified_chat_id != SOURCE_CHAT_ID:
            raise ValueError("verified channel ID does not match the pinned source")
        self.client = client
        self.verified_chat_id = verified_chat_id

    async def fetch_recent(self, count: int = 20) -> list[SourcePost]:
        if not 1 <= count <= 100:
            raise ValueError("MAX page size must be 1..100")
        posts = {}
        cursor = None
        cutoff = datetime.now(UTC) - MAX_AGE
        for page in range(10):
            options = {} if cursor is None else {"from_time": cursor}
            messages = await self.client.fetch_history(
                chat_id=self.verified_chat_id, backward=count,
                get_chat=False, interactive=False, **options,
            )
            if not messages:
                return list(posts.values())
            batch = []
            for message in messages:
                scoped = SimpleNamespace(
                    id=message.id, time=message.time, text=message.text,
                    chat_id=getattr(message, "chat_id", None),
                )
                if scoped.chat_id is None:
                    scoped.chat_id = self.verified_chat_id
                post = from_verified_message(scoped, self.verified_chat_id)
                batch.append(post)
                posts[post.post_id] = post
            oldest = min(post.published_at for post in batch)
            if len(messages) < count or oldest < cutoff:
                return list(posts.values())
            next_cursor = int(oldest.timestamp() * 1000) - 1
            if cursor is not None and next_cursor >= cursor:
                raise RuntimeError("MAX history cursor stalled; coverage cannot be verified")
            cursor = next_cursor
        raise RuntimeError("MAX history page limit reached; coverage cannot be verified")


def from_verified_message(message: object, verified_chat_id: int) -> SourcePost:
    """Convert one message supplied by an independently authorized, connected reader."""
    if verified_chat_id != SOURCE_CHAT_ID or getattr(message, "chat_id", None) != verified_chat_id:
        raise ValueError("message is not from the verified MChS channel")
    timestamp = int(getattr(message, "time"))
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    post_id = str(getattr(message, "id"))
    return SourcePost(
        post_id=post_id,
        channel_url=SOURCE_CHANNEL,
        post_url=SOURCE_CHANNEL,
        published_at=datetime.fromtimestamp(timestamp, UTC),
        text=str(getattr(message, "text") or ""),
    )
