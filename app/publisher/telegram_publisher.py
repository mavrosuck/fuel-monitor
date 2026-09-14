from aiogram import Bot

from app.publisher.cta import with_cta


class TelegramPublisher:
    def __init__(self, token: str, channel: str) -> None:
        self.bot, self.channel = Bot(token), channel

    async def publish(self, text: str) -> int:
        message_text, entities = with_cta(text)
        message = await self.bot.send_message(self.channel, message_text, entities=entities)
        return message.message_id

    async def close(self) -> None:
        await self.bot.session.close()
