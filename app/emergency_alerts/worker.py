from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Protocol

from app.emergency_alerts.core import SourcePost
from app.emergency_alerts.pipeline import EmergencyPipeline


logger = logging.getLogger(__name__)


class Reader(Protocol):
    async def fetch_recent(self, count: int = 20) -> list[SourcePost]: ...


async def run_forever(reader: Reader, pipeline: EmergencyPipeline, stop: asyncio.Event, interval_seconds: float = 10) -> None:
    if interval_seconds <= 0:
        raise ValueError("poll interval must be positive")
    failures = 0
    while not stop.is_set():
        try:
            posts = await asyncio.wait_for(reader.fetch_recent(), timeout=30)
            for post in sorted(posts, key=lambda item: item.published_at):
                await asyncio.wait_for(pipeline.process(post), timeout=30)
            failures = 0
        except asyncio.CancelledError:
            raise
        except Exception as error:
            failures += 1
            logger.error("Emergency polling failed: %s; retrying after delay", type(error).__name__)
        pipeline.connection.execute(
            "INSERT OR REPLACE INTO worker_health VALUES (1, ?, ?)",
            (datetime.now(UTC).isoformat(), "error" if failures else "ok"),
        )
        delay = max(interval_seconds, min(300, interval_seconds * 2 ** min(failures, 8)))
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except TimeoutError:
            pass
