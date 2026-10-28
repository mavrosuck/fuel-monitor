from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable

from app.emergency_alerts.core import SOURCE_CHANNEL, SourcePost


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
