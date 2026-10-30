from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Protocol

from app.emergency_alerts.core import SourcePost
from app.emergency_alerts.pipeline import EmergencyPipeline


logger = logging.getLogger(__name__)


class Reader(Protocol):
    async def fetch_recent(self, count: int = 20) -> list[SourcePost]: ...


async def run_forever(reader: Reader, pipeline: EmergencyPipeline, stop: asyncio.Event, interval_seconds: float = 10) -> bool:
    if interval_seconds <= 0:
        raise ValueError("poll interval must be positive")
    failures = 0
    while not stop.is_set():
        poll_started = time.monotonic()
        post_count = 0
        error_type = ""
        try:
            posts = await asyncio.wait_for(reader.fetch_recent(), timeout=30)
            post_count = len(posts)
            for post in sorted(posts, key=lambda item: item.published_at):
                await asyncio.wait_for(pipeline.process(post), timeout=30)
            failures = 0
        except asyncio.CancelledError:
            raise
        except Exception as error:
            failures += 1
            error_type = type(error).__name__
            logger.error("Emergency polling failed: %s; retrying after delay", type(error).__name__)
        checked_at = datetime.now(UTC).isoformat()
        duration_ms = max(0, round((time.monotonic() - poll_started) * 1000))
        pipeline.connection.execute(
            "INSERT OR REPLACE INTO worker_health VALUES (1, ?, ?)",
            (checked_at, "error" if failures else "ok"),
        )
        metrics = {
            "last_poll_completed_at": checked_at,
            "last_poll_duration_ms": str(duration_ms),
            "last_poll_post_count": str(post_count),
            "consecutive_poll_failures": str(failures),
            "last_poll_error_type": error_type,
        }
        pipeline.connection.executemany(
            "INSERT OR REPLACE INTO service_state VALUES (?, ?)",
            metrics.items(),
        )
        if error_type and not _reader_is_connected(reader):
            logger.warning("Emergency MAX connection is closed; requesting a fresh session")
            return True
        delay = max(interval_seconds, min(300, interval_seconds * 2 ** min(failures, 8)))
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except TimeoutError:
            pass
    return False


def _reader_is_connected(reader: Reader) -> bool:
    client = getattr(reader, "client", None)
    return client is None or bool(getattr(client, "is_connected", True))
