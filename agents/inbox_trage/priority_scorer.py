"""
Priority scorer — assigns a numeric priority (1-10) to a backlog item.
Higher score = should be processed sooner.
"""
import os
import json
import logging
import anthropic
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """
You are a priority scorer for a personal task backlog.
Given a message and its category, score urgency/importance from 1 (low) to 10 (high).
Output JSON: {"score": <int 1-10>, "reason": "<short reason in Korean>"}
Output ONLY valid JSON.
""".strip()

_KEYWORD_BOOSTS = {
    "마감": 3, "deadline": 3, "오늘": 2, "today": 2, "내일": 1,
    "중요": 2, "important": 2, "까먹": 1, "잊": 1,
}


class PriorityScorer:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))
        self.model = "claude-haiku-4-5-20251001"

    def score(self, message: str, category: str) -> int:
        base = self._keyword_score(message)
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=64,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": f"category: {category}\nmessage: {message}"}],
            )
            data = json.loads(response.content[0].text.strip())
            ai_score = int(data.get("score", 5))
            return max(1, min(10, (base + ai_score) // 2))
        except Exception as e:
            logger.error(f"PriorityScorer error: {e}")
            return max(1, min(10, base))

    def _keyword_score(self, message: str) -> int:
        score = 5
        lower = message.lower()
        for kw, boost in _KEYWORD_BOOSTS.items():
            if kw in lower:
                score += boost
        return max(1, min(10, score))
