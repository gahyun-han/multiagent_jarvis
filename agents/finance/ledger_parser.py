"""
Ledger parser — parses natural language expense/income entries into structured records.
"""
import os
import json
import logging
import anthropic
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """
Parse a Korean expense/income message into JSON:
{
  "type": "expense" | "income",
  "amount": <int KRW>,
  "category": one of ["식비", "교통", "쇼핑", "의료", "주거", "문화", "저축", "수입", "기타"],
  "description": "<short description>",
  "date": "YYYY-MM-DD or null if not specified"
}
Output ONLY valid JSON.
""".strip()


class LedgerParser:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))
        self.model = "claude-haiku-4-5-20251001"

    def parse(self, message: str) -> dict | None:
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=128,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": message}],
            )
            return json.loads(response.content[0].text.strip())
        except Exception as e:
            logger.error(f"LedgerParser error: {e}")
            return None

    @staticmethod
    def format_amount(amount: int) -> str:
        return f"{amount:,}원"
