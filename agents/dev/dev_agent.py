"""
Dev agent — code review, debugging help, architecture advice via Claude.
"""
import os
import logging
import anthropic
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """
You are a senior software engineer assistant integrated into Jarvis.
Reply in Korean unless the user writes in English.
Help with: code review, debugging, architecture, best practices, PR descriptions.
When showing code, use markdown code blocks with language tags.
Be direct and practical. Highlight the most important issues first.
""".strip()


class DevAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))
        self.model = "claude-sonnet-4-6"

    async def handle(self, intent) -> str:
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": intent.raw_message}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.error(f"DevAgent error: {e}")
            return f"💻 개발 도움 처리 중 오류: {e}"
