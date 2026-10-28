from __future__ import annotations

import asyncio
import logging
import os
import signal
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.emergency_alerts.core import open_store


def require_activation() -> None:
    required = (
        "EMERGENCY_ENABLED",
        "EMERGENCY_MAX_PERMISSION_CONFIRMED",
        "EMERGENCY_SOURCE_VERIFIED",
    )
    if any(os.environ.get(name) != "true" for name in required):
        raise PermissionError("Emergency service disabled: activation, MAX permission and live source verification required")


async def serve() -> None:
    require_activation()
    from app.emergency_alerts.max_source import AuthorizedMaxSession
    from app.emergency_alerts.pipeline import EmergencyPipeline
    from app.emergency_alerts.rewrite import OriginalRewriter
    from app.emergency_alerts.telegram import EmergencyTelegramSender
    from app.emergency_alerts.worker import run_forever

    interval = float(os.environ.get("EMERGENCY_POLL_SECONDS", "30"))
    if not 10 <= interval <= 300:
        raise ValueError("poll interval must be 10..300 seconds and comply with granted limits")
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    connection = open_store(os.environ["EMERGENCY_SQLITE_PATH"])
    sender = None
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    try:
        sender = EmergencyTelegramSender(os.environ["BOT_TOKEN"])
        await asyncio.wait_for(sender.verify_destination(), timeout=30)
        session = AuthorizedMaxSession(
            os.environ["MAX_SESSION_PATH"], int(os.environ["EMERGENCY_MAX_CHANNEL_ID"]), True,
        )
        async with asyncio.timeout(60):
            reader = await session.__aenter__()
        try:
            await run_forever(reader, EmergencyPipeline(connection, OriginalRewriter(), sender), stop, interval)
        finally:
            await session.__aexit__()
    finally:
        if sender is not None:
            await sender.close()
        connection.close()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(signum)


def check_health() -> None:
    path = Path(os.environ["EMERGENCY_SQLITE_PATH"])
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        row = connection.execute("SELECT checked_at, status FROM worker_health WHERE singleton=1").fetchone()
        unresolved = connection.execute(
            "SELECT COUNT(*) FROM deliveries AS delivery JOIN posts AS post USING (post_id) "
            "WHERE delivery.status='claimed' OR (delivery.status='pending' AND post.status='pending')"
        ).fetchone()[0]
        reviews = connection.execute("SELECT COUNT(*) FROM posts WHERE status LIKE 'review_%'").fetchone()[0]
        if not row or row[1] != "ok" or unresolved or reviews:
            raise RuntimeError("Emergency worker needs attention")
        age = (datetime.now(UTC) - datetime.fromisoformat(row[0])).total_seconds()
        interval = float(os.environ.get("EMERGENCY_POLL_SECONDS", "30"))
        if not 0 <= age <= max(120, interval * 2 + 60):
            raise RuntimeError("Emergency heartbeat is stale")
    finally:
        connection.close()
    print("Emergency worker healthy; no unresolved deliveries or review items.")
