"""
Calendar agent — handles schedule queries, reminders, and daily briefings via Claude.
"""
import os
import logging
from datetime import datetime
import anthropic
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """
You are a calendar assistant for a personal AI called Jarvis.
The user's messages are in Korean. Reply in Korean.
Current datetime: {now}

You help with:
- Parsing natural language into structured schedule entries
- Answering questions about the user's schedule
- Generating daily briefings
- Setting reminders

For schedule entries output JSON:
{"action": "add|query|remind", "title": str, "datetime": "ISO8601", "notes": str}
For conversational replies, respond naturally in Korean.
""".strip()


class CalendarAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))
        self.model = "claude-sonnet-4-6"

    async def handle(self, intent) -> str:
        system = _SYSTEM_PROMPT.format(now=datetime.now().strftime("%Y-%m-%d %H:%M"))
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=512,
                system=system,
                messages=[{"role": "user", "content": intent.raw_message}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.error(f"CalendarAgent error: {e}")
            return f"📅 일정 처리 중 오류가 발생했습니다: {e}"

    async def daily_briefing(self, chat_id: int):
        from systems.telegram_sender import TelegramSender
        sender = TelegramSender()
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=512,
                system=_SYSTEM_PROMPT.format(now=datetime.now().strftime("%Y-%m-%d %H:%M")),
                messages=[{"role": "user", "content": "오늘의 일정 브리핑을 해줘"}],
            )
            await sender.send(chat_id, "🌅 *오늘의 브리핑*\n\n" + response.content[0].text.strip())
        except Exception as e:
            logger.error(f"Daily briefing error: {e}")
