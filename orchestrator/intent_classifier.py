"""
Intent classifier — decides if a message needs immediate handling or can be queued.
Also identifies the domain (calendar / paper / finance / dev / triage).
"""
import os
import json
import logging
from dataclasses import dataclass
from typing import Literal
import anthropic
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

Domain = Literal["calendar", "paper", "finance", "dev", "triage", "unknown"]
Urgency = Literal["immediate", "backlog"]


@dataclass
class Intent:
    domain: Domain
    urgency: Urgency
    confidence: float
    summary: str
    raw_message: str


_SYSTEM_PROMPT = """
You are an intent classifier for a personal AI assistant (Jarvis).
Given a Korean or English message from the user, output JSON with:
{
  "domain": one of ["calendar", "paper", "finance", "dev", "triage", "unknown"],
  "urgency": "immediate" if the request needs to be handled right now, else "backlog",
  "confidence": float 0-1,
  "summary": one-line Korean summary of what the user wants
}

Domain rules:
- calendar: 일정, 약속, 미팅, 리마인더, 알림, schedule, meeting, reminder
- paper: 논문, 연구, paper, zotero, obsidian, 문헌
- finance: 돈, 지출, 수입, 가계부, 저축, 대출, 적금, budget, expense
- dev: 코드, 개발, 버그, 테스트, PR, code, debug, test
- triage: 할 일, 메모, 나중에, todo, task, note — anything that should be saved for later
- unknown: cannot determine

Urgency rules:
- immediate: 지금, 급해, 긴급, 당장, now, urgent, asap, or requires real-time data (current schedule, today's finance)
- backlog: 나중에, 언제, 해줘 (future tense), or no explicit time pressure

Output ONLY valid JSON, no markdown fences.
""".strip()


class IntentClassifier:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))
        self.model = "claude-haiku-4-5-20251001"

    def classify(self, message: str) -> Intent:
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=256,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": message}],
            )
            raw = response.content[0].text.strip()
            data = json.loads(raw)
            return Intent(
                domain=data.get("domain", "unknown"),
                urgency=data.get("urgency", "backlog"),
                confidence=float(data.get("confidence", 0.5)),
                summary=data.get("summary", message[:80]),
                raw_message=message,
            )
        except Exception as e:
            logger.error(f"Intent classification failed: {e}")
            return Intent(
                domain="triage",
                urgency="backlog",
                confidence=0.0,
                summary=message[:80],
                raw_message=message,
            )
