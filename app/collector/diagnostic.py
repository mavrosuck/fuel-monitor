"""CLI-проверка Telegram sources без отправки сообщений и без интерактивного входа."""

import asyncio
import logging

from app.collector.telegram_client import create_telegram_client, inspect_source_chats
from app.config import get_settings


async def run_diagnostic() -> int:
    settings = get_settings()
    client = create_telegram_client(settings)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            logging.error("Telethon session is not authorized; run python -m app.collector.login first")
            return 1
        diagnostics = await inspect_source_chats(client, settings.source_chats, limit=5)
        failed = False
        for diagnostic in diagnostics:
            if diagnostic.error:
                print(f"source={diagnostic.source} error={diagnostic.error}")
                failed = True
                continue
            print(
                f"source={diagnostic.source} chat_id={diagnostic.chat_id} "
                f"title={diagnostic.title!r} username={diagnostic.username!r}"
            )
            for message_id, message_date, text in diagnostic.messages:
                print(f"  message_id={message_id} date={message_date.isoformat()} text={text!r}")
        return 1 if failed else 0
    finally:
        await client.disconnect()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    raise SystemExit(asyncio.run(run_diagnostic()))


if __name__ == "__main__":
    main()
