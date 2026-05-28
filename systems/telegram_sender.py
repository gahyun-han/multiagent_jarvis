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
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN not set")
        self.bot = Bot(token=token)

    async def send(self, chat_id: int, text: str, parse_mode: str = "Markdown") -> bool:
        try:
            await self.bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
            return True
        except TelegramError as e:
            logger.error(f"Telegram send error to {chat_id}: {e}")
            return False

    async def send_plain(self, chat_id: int, text: str) -> bool:
        return await self.send(chat_id, text, parse_mode=None)
