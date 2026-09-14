import logging

from aiogram import Bot
from app.publisher.cta import with_cta
from app.services.formatter import FormattedSummary
from app.services.retry import is_safe_telegram_send_retry, retry_async

logger = logging.getLogger(__name__)


class TelegramPublisher:
    def __init__(self, token: str, channel: str) -> None:
        self.bot, self.channel = Bot(token), channel

    async def log_identity(self) -> None:
        bot = await self.bot.get_me()
        logger.info("Telegram publisher bot: @%s", bot.username or "(no username)")
        logger.info("Telegram target channel: %s", self.channel)

    async def publish(self, text: str | FormattedSummary) -> int:
        await self.log_identity()
        message_text, entities = with_cta(text)
        async def send():
            return await self.bot.send_message(self.channel, message_text, entities=entities)

        message = await retry_async(
            send,
            is_retryable=is_safe_telegram_send_retry,
            operation_name="Telegram publication",
        )
        return message.message_id

    async def close(self) -> None:
        await self.bot.session.close()
