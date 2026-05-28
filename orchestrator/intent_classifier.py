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
- finance: 돈, 지출, 수입, 가계부, 저축, 대출, 적금, 자산, 통장, 계좌, 잔액, 월급, 이체, 투자, 주식, 펀드, budget, expense, asset, account, balance
- dev: 코드, 개발, 버그, 테스트, PR, code, debug, test
- triage: ONLY when the user explicitly says 나중에/이따/다음에/언젠가 or the message is a vague memo with no actionable domain
- unknown: cannot determine

Urgency rules — read carefully:
- immediate: ANY direct question or action request the assistant can handle right now.
  Examples: "일정 추가해줘", "일정 있어?", "지출 알려줘", "코드 리뷰해줘", "논문 요약해줘"
  "해줘" alone means the user wants it done NOW — it is NOT a backlog signal.
- backlog: ONLY when the user explicitly defers with 나중에, 이따, 다음에, 언제, 언젠가, or the message is a raw memo/note with no clear action

When in doubt, choose immediate.

Output ONLY valid JSON, no markdown fences.
""".strip()


# 키워드 기반 사전 판별 규칙 — LLM 호출 전에 확정적으로 분류
_KEYWORD_RULES: list[tuple[list[str], str, str]] = [
    # (키워드 목록,  domain,     urgency)
    (["자산 목록", "자산목록", "자산 추가", "통장 추가", "계좌 추가",
      "적금 추가", "대출 추가", "부동산 추가"],          "finance",  "immediate"),
    (["지출", "수입", "가계부", "이번 달 지출", "월급"],  "finance",  "immediate"),
    (["일정 추가", "일정 등록", "약속 추가", "리마인더"],  "calendar", "immediate"),
    (["오늘 일정", "내일 일정", "이번 주 일정"],          "calendar", "immediate"),
    (["논문 요약", "논문 정리", "최근 논문"],              "paper",    "immediate"),
    (["코드 리뷰", "버그", "테스트 코드"],                "dev",      "immediate"),
]

_BACKLOG_SIGNALS = ["나중에", "이따", "다음에", "언젠가", "언제 한번"]


class IntentClassifier:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))
        self.model = "claude-haiku-4-5-20251001"

    def classify(self, message: str) -> Intent:
        # 1단계: 명시적 backlog 신호가 있으면 바로 triage
        if any(sig in message for sig in _BACKLOG_SIGNALS):
            return Intent(
                domain="triage", urgency="backlog",
                confidence=1.0, summary=message[:80], raw_message=message,
            )

        # 2단계: 키워드 사전 판별
        for keywords, domain, urgency in _KEYWORD_RULES:
            if any(kw in message for kw in keywords):
                logger.info(f"Pre-classified: domain={domain} urgency={urgency}")
                return Intent(
                    domain=domain, urgency=urgency,
                    confidence=1.0, summary=message[:80], raw_message=message,
                )

        # 3단계: LLM 판별
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
                domain="triage", urgency="backlog",
                confidence=0.0, summary=message[:80], raw_message=message,
            )
