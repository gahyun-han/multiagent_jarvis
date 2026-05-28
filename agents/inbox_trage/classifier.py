"""
Message classifier — assigns a fine-grained category and responsible agent tag.
"""
import os
import json
import logging
import anthropic
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """
You are a task classifier for a personal assistant.
Given a message and its broad domain, output JSON:
{
  "category": short kebab-case label (e.g. "read-later", "follow-up", "idea", "errand", "study", "code-review"),
  "agent_tag": which agent should eventually handle it (calendar/paper/finance/dev/self)
}
Output ONLY valid JSON.
""".strip()


class TriageClassifier:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))
        self.model = "claude-haiku-4-5-20251001"

    def classify(self, message: str, domain: str) -> str:
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=128,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": f"domain: {domain}\nmessage: {message}"}],
            )
            data = json.loads(response.content[0].text.strip())
            return data.get("category", "misc")
        except Exception as e:
            logger.error(f"TriageClassifier error: {e}")
            return "misc"
