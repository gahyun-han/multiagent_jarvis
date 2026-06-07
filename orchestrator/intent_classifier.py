"""
Intent classifier — decides if a message needs immediate handling or can be queued.
Also identifies the domain (calendar / paper / finance / dev / triage).
"""
import json
import logging
from dataclasses import dataclass
from typing import Literal
from systems.claude_runner import async_ask as claude_ask_async

logger = logging.getLogger(__name__)

Domain = Literal["calendar", "paper", "finance", "dev", "usage", "backlog", "triage", "unknown"]
Urgency = Literal["immediate", "backlog"]


@dataclass
class Intent:
    domain: Domain
    urgency: Urgency
    confidence: float
    summary: str
    raw_message: str
    chat_id: int = 0


_SYSTEM_PROMPT = """
You are an intent classifier for a personal AI assistant (Jarvis).
Given a Korean or English message from the user, output JSON with:
{
  "domain": one of ["calendar", "paper", "finance", "dev", "backlog", "triage", "unknown"],
  "urgency": "immediate" if the request needs to be handled right now, else "backlog",
  "confidence": float 0-1,
  "summary": one-line Korean summary of what the user wants
}

Domain rules:
- calendar: 일정, 약속, 미팅, 리마인더, 알림, schedule, meeting, reminder
- paper: 논문, 연구, paper, zotero, obsidian, 문헌
- finance: 돈, 지출, 수입, 가계부, 저축, 대출, 적금, 자산, 통장, 계좌, 잔액, 월급, 이체, 투자, 주식, 펀드, budget, expense, asset, account, balance
- dev: 코드, 개발, 버그, 테스트, PR, code, debug, test
- backlog: 백로그 조회/삭제/수행 요청 (backlog list, delete, clear)
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
      "적금 추가", "대출 추가", "부동산 추가",
      "부동산 수정", "부동산 업데이트", "집값 수정", "아파트 수정",
      "주식 추가", "주식 수정", "주식 업데이트", "종목 추가", "종목 수정",
      "자산 수정", "자산 업데이트"],                      "finance",  "immediate"),
    (["지출", "수입", "가계부", "이번 달 지출", "월급",
      "월별 요약", "월별 그래프", "가계부 요약", "가계부 정리",
      "월별 정리", "지출 요약", "지출 비교"],            "finance",  "immediate"),
    (["일정 추가", "일정 등록", "약속 추가", "리마인더"],  "calendar", "immediate"),
    (["오늘 일정", "내일 일정", "이번 주 일정"],          "calendar", "immediate"),
    (["논문 요약", "논문 정리", "최근 논문",
      "컬렉션 동기화", "컬렉션 생성", "컬렉션 정리", "컬렉션 업데이트",
      "태그 검색", "태그로 찾", "태그 조합", "태그 필터",
      "landscape", "라이브러리 분석", "논문 통계", "논문 현황",
      "저자 통계", "연도별 논문"],                          "paper",    "immediate"),
    (["코드 리뷰", "버그", "테스트 코드", "autotest", "자동 테스트", "자동테스트",
      ".py 수정", ".py 고쳐", "코드 수정", "소스 수정", "파일 수정"],             "dev", "immediate"),
    # 외부 프로젝트 실행/수정 요청
    (["TrendNotifier", "PaperRadar", "Stock-agent", "techTerminologyRadar",
      "트렌드노티파이어", "논문레이더",
      "itTerminology", "ItTerminology", "it용어", "용어레이더"],               "dev", "immediate"),
    (["사용량", "사용률", "claude 사용", "클로드 사용", "토큰", "리셋"],  "usage",   "immediate"),
    (["백로그 목록", "백로그 보여", "백로그 알려", "백로그 리스트",
      "백로그 조회", "백로그 확인", "대기작업 리스트", "대기 작업 리스트",
      "대기 작업 목록", "대기작업 목록"],                                "backlog",  "immediate"),
    (["백로그 삭제", "백로그 전부", "백로그 전체 삭제", "백로그 모두 삭제",
      "백로그 다 삭제", "백로그 지워", "백로그 다 지워", "백로그 수행",
      "백로그 처리"],                                                    "backlog",  "immediate"),
    # 백로그 직접 추가 요청 — "해줘" 등 요청 어미와 무관하게 backlog urgency로 판별
    (["백로그에 넣어", "백로그에 추가", "백로그 추가", "백로그에 저장",
      "백로그로 넣어", "백로그에 올려", "나중에 수행", "나중에 처리해"],  "triage",   "backlog"),
]

_BACKLOG_SIGNALS = ["나중에", "이따", "다음에", "언젠가", "언제 한번"]

# 명시적 '지금 당장' 신호만 포함 — "해줘"/"알려줘" 등 요청 어미는 제외
# (e.g. "나중에 해줘"에서 "해줘"가 즉시 신호로 오해되는 것 방지)
_IMMEDIATE_SIGNALS = ["지금", "바로", "즉시", "지금 당장", "빨리"]


class IntentClassifier:
    async def classify(self, message: str) -> Intent:
        # 1단계: backlog 신호 확인 — 단, 즉시 신호(지금/바로 등)가 함께 있으면 무시
        has_backlog = any(sig in message for sig in _BACKLOG_SIGNALS)
        has_immediate = any(sig in message for sig in _IMMEDIATE_SIGNALS)
        if has_backlog and not has_immediate:
            return Intent(
                domain="triage", urgency="backlog",
                confidence=1.0, summary=message[:80], raw_message=message,
            )

        # 2단계: 키워드 사전 판별 (LLM 호출 없이 즉시 분류)
        msg_lower = message.lower()
        for keywords, domain, urgency in _KEYWORD_RULES:
            if any(kw.lower() in msg_lower for kw in keywords):
                logger.info(f"Pre-classified: domain={domain} urgency={urgency}")
                return Intent(
                    domain=domain, urgency=urgency,
                    confidence=1.0, summary=message[:80], raw_message=message,
                )

        # 3단계: Claude Code CLI로 LLM 판별 (비동기 — 이벤트 루프 비블로킹)
        try:
            raw = await claude_ask_async(message, system=_SYSTEM_PROMPT, max_tokens=256, no_tools=True)
            data = json.loads(raw)
            urgency = data.get("urgency", "immediate")
            if has_immediate:
                urgency = "immediate"
            elif urgency == "backlog" and not has_backlog:
                urgency = "immediate"
            return Intent(
                domain=data.get("domain", "unknown"),
                urgency=urgency,
                confidence=float(data.get("confidence", 0.5)),
                summary=data.get("summary", message[:80]),
                raw_message=message,
            )
        except Exception as e:
            logger.error(f"Intent classification failed: {e}")
            return Intent(
                domain="unknown", urgency="immediate",
                confidence=0.0, summary=message[:80], raw_message=message,
            )
