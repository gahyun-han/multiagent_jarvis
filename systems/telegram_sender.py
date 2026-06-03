"""
Telegram sender — thin wrapper around Bot.send_message for use outside handlers.
"""
import os
import logging
from telegram import Bot
from telegram.error import TelegramError
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class TelegramSender:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN not set")

    async def send(self, chat_id: int, text: str, parse_mode: str = "Markdown") -> bool:
        try:
            async with Bot(token=self.token) as bot:
                await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
            return True
        except TelegramError as e:
            logger.error(f"Telegram send error to {chat_id}: {e}")
            return False

    async def send_plain(self, chat_id: int, text: str) -> bool:
        return await self.send(chat_id, text, parse_mode=None)

    async def send_with_reply_markup(self, chat_id: int, text: str, reply_markup) -> bool:
        try:
            async with Bot(token=self.token) as bot:
                await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
            return True
        except TelegramError as e:
            logger.error(f"Telegram send_with_reply_markup error to {chat_id}: {e}")
            return False
