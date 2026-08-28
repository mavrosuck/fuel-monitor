import asyncio

from telethon import TelegramClient

from app.config import get_settings


async def main() -> None:
    settings = get_settings()
    client = TelegramClient(settings.telethon_session_name, settings.telegram_api_id, settings.telegram_api_hash.get_secret_value())
    await client.start(phone=settings.telegram_phone)
    print("Telethon session created successfully.")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
