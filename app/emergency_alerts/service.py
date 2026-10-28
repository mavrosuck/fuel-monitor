from __future__ import annotations

import asyncio
import logging
import os
import signal
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from app.emergency_alerts.core import SOURCE_CHAT_ID, initialize_without_backfill, open_store


def require_activation() -> None:
    required = (
        "EMERGENCY_ENABLED",
        "EMERGENCY_MAX_PERMISSION_CONFIRMED",
        "EMERGENCY_SOURCE_VERIFIED",
    )
    if any(os.environ.get(name) != "true" for name in required):
        raise PermissionError("Emergency service disabled: activation, MAX permission and live source verification required")


def load_configuration() -> tuple[float, int, str, str, str]:
    required = ("BOT_TOKEN", "MAX_SESSION_PATH", "EMERGENCY_SQLITE_PATH", "EMERGENCY_MAX_CHANNEL_ID")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise ValueError("Emergency service configuration is incomplete")
    interval = float(os.environ.get("EMERGENCY_POLL_SECONDS", "30"))
    if not 10 <= interval <= 300:
        raise ValueError("poll interval must be 10..300 seconds and comply with granted limits")
    chat_id = int(os.environ["EMERGENCY_MAX_CHANNEL_ID"])
    if chat_id != SOURCE_CHAT_ID:
        raise ValueError("emergency source channel ID does not match the pinned MChS channel")
    return (
        interval,
        chat_id,
        os.environ["BOT_TOKEN"],
        os.environ["MAX_SESSION_PATH"],
        os.environ["EMERGENCY_SQLITE_PATH"],
    )


async def serve() -> None:
    require_activation()
    interval, chat_id, bot_token, session_path, sqlite_path = load_configuration()
    from app.emergency_alerts.max_source import AuthorizedMaxSession
    from app.emergency_alerts.pipeline import EmergencyPipeline
    from app.emergency_alerts.rewrite import OriginalRewriter
    from app.emergency_alerts.telegram import EmergencyTelegramSender
    from app.emergency_alerts.worker import run_forever

    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    session = AuthorizedMaxSession(session_path, chat_id, True)
    connection = open_store(sqlite_path)
    sender = None
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    try:
        sender = EmergencyTelegramSender(bot_token)
        await asyncio.wait_for(sender.verify_destination(), timeout=30)
        async with asyncio.timeout(60):
            reader = await session.__aenter__()
        try:
            initial_posts = await asyncio.wait_for(reader.fetch_recent(), timeout=30)
            baseline_count = initialize_without_backfill(connection, initial_posts, datetime.now(UTC))
            logging.info(
                "Emergency initial boundary recorded with %d eligible posts; nothing was published",
                baseline_count,
            )
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
