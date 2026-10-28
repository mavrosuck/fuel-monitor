from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from app.emergency_alerts.core import SourcePost
from app.emergency_alerts.pipeline import EmergencyPipeline


logger = logging.getLogger(__name__)


class Reader(Protocol):
    async def fetch_recent(self, count: int = 20) -> list[SourcePost]: ...


async def run_forever(reader: Reader, pipeline: EmergencyPipeline, stop: asyncio.Event, interval_seconds: float = 10) -> None:
    if interval_seconds <= 0:
        raise ValueError("poll interval must be positive")
    while not stop.is_set():
        try:
            posts = await reader.fetch_recent()
            for post in sorted(posts, key=lambda item: item.published_at):
                await pipeline.process(post)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.error("Emergency polling failed: %s; retrying after delay", type(error).__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass
