from __future__ import annotations

import argparse
import asyncio
import os

from app.emergency_alerts.core import TARGET_CHANNEL, open_store
from app.emergency_alerts.telegram import EmergencyTelegramSender


async def telegram_preflight() -> None:
    token = os.environ.get("EMERGENCY_TELEGRAM_BOT_TOKEN", "")
    sender = EmergencyTelegramSender(token)
    try:
        await sender.verify_destination()
    finally:
        await sender.close()
    print(f"Verified emergency bot can post to {TARGET_CHANNEL}; no message was sent.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inactive emergency alert preflight tools")
    parser.add_argument("command", choices=("telegram-preflight", "store-check"))
    args = parser.parse_args()
    if args.command == "telegram-preflight":
        asyncio.run(telegram_preflight())
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
