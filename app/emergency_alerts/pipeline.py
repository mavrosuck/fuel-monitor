from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from typing import Awaitable, Callable, Protocol

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
    def __init__(
        self,
        connection: sqlite3.Connection,
        rewriter: Rewriter,
        sender: Sender,
        checkpoint: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.connection = connection
        self.rewriter = rewriter
        self.sender = sender
        self.checkpoint = checkpoint

    async def save_checkpoint(self) -> None:
        if self.checkpoint is not None:
            await self.checkpoint()

    async def process(self, post: SourcePost, now: datetime | None = None) -> bool:
        detected_at = now or datetime.now(UTC)
        if not register_post(self.connection, post, detected_at):
            return False
        try:
            rewritten = validate_rewrite(post.text, await self.rewriter.rewrite(post))
        except Exception as error:
            logger.warning("Emergency rewrite unavailable: %s; using original", type(error).__name__)
            rewritten = post.text
        try:
            message = render(post, rewritten)
            await self.sender.verify_destination()
        except Exception as error:
            logger.error("Emergency preparation failed: %s", type(error).__name__)
            return False
        claimed_revision = claim_delivery(self.connection, post, TARGET_CHANNEL, datetime.now(UTC) if now is None else now)
        if claimed_revision is None:
            return False
        await self.save_checkpoint()
        logger.info("Emergency transition=%s detected_at=%s", event_transition(post), detected_at.isoformat())
        try:
            remote_id = await self.sender.send(TARGET_CHANNEL, message)
        except Exception as error:
            logger.error("Emergency delivery uncertain: %s; manual reconciliation required", type(error).__name__)
            return False
        sent_at = datetime.now(UTC)
        confirm_delivery(self.connection, post, claimed_revision, remote_id, sent_at)
        await self.save_checkpoint()
        logger.info("Emergency sent_at=%s latency_seconds=%.1f", sent_at.isoformat(), (sent_at - post.published_at).total_seconds())
        return True
