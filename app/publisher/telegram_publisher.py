from aiogram import Bot


class TelegramPublisher:
    def __init__(self, token: str, channel: str) -> None:
        self.bot, self.channel = Bot(token), channel

    async def publish(self, text: str) -> int:
        message = await self.bot.send_message(self.channel, text)
        return message.message_id

    async def close(self) -> None:
        await self.bot.session.close()
