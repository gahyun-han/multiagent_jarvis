"""
AutoTest agent — generates unit tests for provided code snippets or file paths.
"""
import os
import logging
import anthropic
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """
You are a test-writing expert. Given code, generate comprehensive pytest unit tests.
Reply in English for code/tests. Brief Korean explanation of what was covered.
Follow pytest best practices: descriptive names, arrange-act-assert, edge cases.
""".strip()


class AutoTestAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))
        self.model = "claude-sonnet-4-6"

    async def generate_tests(self, code: str, filename: str = "unknown") -> str:
        prompt = f"File: {filename}\n\n```python\n{code}\n```\n\nGenerate pytest tests for the above code."
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.error(f"AutoTestAgent error: {e}")
            return f"테스트 생성 중 오류: {e}"

    async def handle(self, intent) -> str:
        return await self.generate_tests(intent.raw_message)
