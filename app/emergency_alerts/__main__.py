from __future__ import annotations

import argparse
import asyncio
import os
import tempfile
from pathlib import Path

from app.emergency_alerts.core import TARGET_CHANNEL, classify, open_store
from app.emergency_alerts.telegram import EmergencyTelegramSender


async def telegram_preflight() -> None:
    token = os.environ.get("BOT_TOKEN", "")
    sender = EmergencyTelegramSender(token)
    try:
        await sender.verify_destination()
    finally:
        await sender.close()
    print(f"Verified emergency bot can post to {TARGET_CHANNEL}; no message was sent.")


async def max_dry_run() -> None:
    if os.environ.get("EMERGENCY_MAX_PERMISSION_CONFIRMED") != "true":
        raise PermissionError("written MAX permission must be confirmed before collection")
    from app.emergency_alerts.max_source import AuthorizedMaxSession
    chat_id = int(os.environ["EMERGENCY_MAX_CHANNEL_ID"])
    async with AuthorizedMaxSession(
        os.environ["MAX_SESSION_PATH"], chat_id, permission_confirmed=True
    ) as reader:
        posts = await reader.fetch_recent()
    from app.emergency_alerts.pipeline import EmergencyPipeline
    from app.emergency_alerts.rewrite import OriginalRewriter

    class PreviewSender:
        async def verify_destination(self) -> None:
            pass

        async def send(self, destination: str, text: str) -> str:
            if destination != TARGET_CHANNEL or not text:
                raise ValueError("invalid preview destination or message")
            return "dry-run-only"

    prepared = 0
    with tempfile.TemporaryDirectory(prefix="emergency-preview-") as directory:
        connection = open_store(str(Path(directory) / "preview.sqlite3"))
        try:
            pipeline = EmergencyPipeline(connection, OriginalRewriter(), PreviewSender())
            for post in sorted(posts, key=lambda item: item.published_at):
                prepared += await pipeline.process(post)
        finally:
            connection.close()
    eligible = sum(classify(post) is not None for post in posts)
    print(f"Read {len(posts)} official channel posts; {eligible} match emergency topics; {prepared} fresh previews passed the pipeline. Nothing was published.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inactive emergency alert preflight tools")
    parser.add_argument("command", choices=("telegram-preflight", "store-check", "max-dry-run", "run", "health"))
    args = parser.parse_args()
    if args.command == "telegram-preflight":
        asyncio.run(telegram_preflight())
    elif args.command == "max-dry-run":
        asyncio.run(max_dry_run())
    elif args.command == "run":
        from app.emergency_alerts.service import serve

        asyncio.run(serve())
    elif args.command == "health":
        from app.emergency_alerts.service import check_health

        check_health()
    else:
        path = os.environ.get("EMERGENCY_SQLITE_PATH", "")
        if not path:
            parser.error("EMERGENCY_SQLITE_PATH is required")
        connection = open_store(path)
        try:
            result = connection.execute("PRAGMA integrity_check").fetchone()
            if result != ("ok",):
                raise RuntimeError("emergency SQLite integrity check failed")
        finally:
            connection.close()
        print("Emergency SQLite storage is writable and healthy.")


if __name__ == "__main__":
    main()
