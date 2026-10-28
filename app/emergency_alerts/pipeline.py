from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from typing import Protocol

from app.emergency_alerts.core import (
    TARGET_CHANNEL,
    SourcePost,
    claim_delivery,
    confirm_delivery,
    event_transition,
    register_post,
    render,
)
from app.emergency_alerts.rewrite import validate_rewrite


logger = logging.getLogger(__name__)


class Rewriter(Protocol):
    async def rewrite(self, post: SourcePost) -> str: ...


class Sender(Protocol):
    async def verify_destination(self) -> None: ...

    async def send(self, destination: str, text: str) -> str: ...


class EmergencyPipeline:
    def __init__(self, connection: sqlite3.Connection, rewriter: Rewriter, sender: Sender) -> None:
        self.connection = connection
        self.rewriter = rewriter
        self.sender = sender

    async def process(self, post: SourcePost, now: datetime | None = None) -> bool:
        detected_at = now or datetime.now(UTC)
        if not register_post(self.connection, post, detected_at):
            return False
        try:
            rewritten = validate_rewrite(post.text, await self.rewriter.rewrite(post))
        except Exception as error:
            logger.warning("Emergency rewrite unavailable for post %s: %s; using original", post.post_id, type(error).__name__)
            rewritten = post.text
        try:
            message = render(post, rewritten)
            await self.sender.verify_destination()
        except Exception as error:
            logger.error("Emergency preparation failed for post %s: %s", post.post_id, type(error).__name__)
            return False
        claimed_revision = claim_delivery(self.connection, post, TARGET_CHANNEL, datetime.now(UTC) if now is None else now)
        if claimed_revision is None:
            return False
        logger.info("Emergency post %s transition=%s detected_at=%s", post.post_id, event_transition(post), detected_at.isoformat())
        try:
            remote_id = await self.sender.send(TARGET_CHANNEL, message)
        except Exception as error:
            logger.error("Emergency delivery uncertain for post %s: %s; manual reconciliation required", post.post_id, type(error).__name__)
            return False
        sent_at = datetime.now(UTC)
        confirm_delivery(self.connection, post, claimed_revision, remote_id, sent_at)
        logger.info("Emergency post %s sent_at=%s latency_seconds=%.1f", post.post_id, sent_at.isoformat(), (sent_at - post.published_at).total_seconds())
        return True
