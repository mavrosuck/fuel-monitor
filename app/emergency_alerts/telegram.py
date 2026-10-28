from __future__ import annotations

import os

from aiogram import Bot

from app.emergency_alerts.core import TARGET_CHANNEL


class EmergencyTelegramSender:
    def __init__(self, token: str, destination: str = TARGET_CHANNEL, bot_factory=Bot) -> None:
        if destination != TARGET_CHANNEL:
            raise ValueError("unauthorized emergency destination")
        if not token:
            raise ValueError("separate emergency bot token required")
        if token == os.environ.get("BOT_TOKEN"):
            raise ValueError("fuel summary bot token cannot be used for emergency alerts")
        self.bot = bot_factory(token)
        self._verified = False

    async def verify_destination(self) -> None:
        bot = await self.bot.get_me()
        chat = await self.bot.get_chat(TARGET_CHANNEL)
        if str(getattr(chat, "username", "")).casefold() != TARGET_CHANNEL[1:]:
            raise ValueError("Telegram destination identity mismatch")
        membership = await self.bot.get_chat_member(chat.id, bot.id)
        if str(getattr(membership, "status", "")) not in {"administrator", "creator"}:
            raise ValueError("emergency bot is not a channel administrator")
        if getattr(membership, "can_post_messages", False) is not True:
            raise ValueError("emergency bot cannot post to the channel")
        self._verified = True

    async def send(self, destination: str, text: str) -> str:
        if destination != TARGET_CHANNEL:
            raise ValueError("unauthorized emergency destination")
        if not self._verified:
            await self.verify_destination()
        message = await self.bot.send_message(TARGET_CHANNEL, text, disable_web_page_preview=True)
        return str(message.message_id)

    async def close(self) -> None:
        await self.bot.session.close()
