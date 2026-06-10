"""
Telegram message flow integration tests.

Tests the Intent → Router → Agent pipeline without actual Telegram sends.

Usage:
    pytest tests/test_message_flow.py -v
    pytest tests/test_message_flow.py -v -k "classifier"   # classifier only (no LLM, fast)
    pytest tests/test_message_flow.py -v -k "routing"      # routing + agent dispatch
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from orchestrator.intent_classifier import IntentClassifier


# ─────────────────────────────────────────────────────────────────────────────
# 1. Intent Classifier — keyword-based (no LLM call, fast)
# ─────────────────────────────────────────────────────────────────────────────

# (message, expected_domain, expected_urgency)
KEYWORD_CASES = [
    # calendar
    ("내일 오후 3시 회의 일정 추가해줘",         "calendar",  "immediate"),
    ("오늘 일정 있어?",                           "calendar",  "immediate"),
    ("이번 주 일정 알려줘",                       "calendar",  "immediate"),
    # finance
    ("이번 달 지출 얼마야?",                      "finance",   "immediate"),
    ("가계부 정리해줘",                           "finance",   "immediate"),
    ("자산 추가해줘",                             "finance",   "immediate"),
    ("주식 추가",                                 "finance",   "immediate"),
    # paper — keyword 기반
    ("최근 논문 요약해줘",                        "paper",     "immediate"),
    ("컬렉션 동기화해줘",                         "paper",     "immediate"),
    ("태그 검색 dt AND rl",                       "paper",     "immediate"),
    # paper — obsidian write
    ("옵시디언에 오늘 미팅 내용 저장해줘",        "paper",     "immediate"),
    ("옵시디언에 연구실 정보 거기에 메모 추가해줘","paper",     "immediate"),
    ("연구실.md에 내용 추가해줘",                 "paper",     "immediate"),
    # dev
    ("코드 리뷰해줘",                             "dev",       "immediate"),
    ("버그 찾아줘",                               "dev",       "immediate"),
    # usage
    ("claude 사용량 알려줘",                      "usage",     "immediate"),
    ("토큰 얼마 남았어?",                         "usage",     "immediate"),
    # backlog — list/delete
    ("백로그 목록 보여줘",                        "backlog",   "immediate"),
    ("백로그 삭제해줘",                           "backlog",   "immediate"),
    # backlog — explicit defer
    ("백로그에 추가해줘",                         "triage",    "backlog"),
]

# 긴급 신호가 있으면 backlog 신호를 무시해야 함
URGENCY_OVERRIDE_CASES = [
    ("나중에 할게",             "triage",  "backlog"),
    ("지금 바로 일정 추가해줘", "calendar","immediate"),  # 즉시 신호 있으면 backlog 무시
]

@pytest.mark.parametrize("message,expected_domain,expected_urgency", KEYWORD_CASES)
def test_classifier_keyword(message, expected_domain, expected_urgency):
    """키워드 사전 판별 — LLM 호출 없이 즉시 분류되어야 함."""
    classifier = IntentClassifier()
    intent = asyncio.run(classifier.classify(message))
    assert intent.domain == expected_domain, (
        f"[{message!r}] domain: got={intent.domain!r}, expected={expected_domain!r}"
    )
    assert intent.urgency == expected_urgency, (
        f"[{message!r}] urgency: got={intent.urgency!r}, expected={expected_urgency!r}"
    )


@pytest.mark.parametrize("message,expected_domain,expected_urgency", URGENCY_OVERRIDE_CASES)
def test_classifier_urgency_override(message, expected_domain, expected_urgency):
    """긴급/지연 신호 오버라이드 로직 검증."""
    classifier = IntentClassifier()
    intent = asyncio.run(classifier.classify(message))
    assert intent.urgency == expected_urgency, (
        f"[{message!r}] urgency: got={intent.urgency!r}, expected={expected_urgency!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Dev Agent — 개념 질문 vs 실행 요청 분기
# ─────────────────────────────────────────────────────────────────────────────

DEVAGENT_CONCEPT_CASES = [
    # (message, should_ask_for_filepath)
    ("autotest agent랑 테스트 하네스 차이 알려줘",          False),
    ("자동 테스트가 뭐야",                                  False),
    # 파일 경로 없이 autotest만 적으면 경로 요청
    ("autotest 돌려줘",                                     True),
]

@pytest.mark.parametrize("message,expect_filepath_error", DEVAGENT_CONCEPT_CASES)
def test_devagent_concept_vs_run(message, expect_filepath_error):
    """개념 질문은 파일경로 요청 응답을 내면 안 됨."""
    from types import SimpleNamespace
    from agents.dev.dev_agent import DevAgent

    intent = SimpleNamespace(raw_message=message)

    async def _run():
        with patch("agents.dev.dev_agent.claude_ask", new_callable=AsyncMock) as mock_claude:
            mock_claude.return_value = "개념 설명 응답"
            agent = DevAgent()
            return await agent.handle(intent)

    result = asyncio.run(_run())
    asks_for_path = "테스트할 파일 경로" in result
    assert asks_for_path == expect_filepath_error, (
        f"[{message!r}] filepath_error_shown={asks_for_path}, expected={expect_filepath_error}\n"
        f"response: {result[:200]}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Obsidian write — 파싱 및 파일 탐색
# ─────────────────────────────────────────────────────────────────────────────

OBSIDIAN_PARSE_CASES = [
    # (message, expect_file_ref_not_none, expected_content_substr)
    ("옵시디언에 연구실 정보 모아둔 .md가있는데 거기에 교수님 메모 추가해줘",
     True, "교수님 메모"),
    ("연구실.md에 오늘 회의 내용 추가해줘",
     True, "오늘 회의 내용"),
    ("옵시디언에 새 아이디어 저장해줘",
     False, "새 아이디어"),
]

@pytest.mark.parametrize("message,has_file_ref,content_substr", OBSIDIAN_PARSE_CASES)
def test_obsidian_parse(message, has_file_ref, content_substr):
    """_parse_obs_request가 file_ref / content를 올바르게 분리하는지 검증."""
    from agents.paper.paper_agent import _parse_obs_request

    file_ref, content = _parse_obs_request(message)
    assert (file_ref is not None) == has_file_ref, (
        f"[{message!r}] file_ref={file_ref!r}, has_file_ref expected={has_file_ref}"
    )
    assert content_substr.lower() in content.lower(), (
        f"[{message!r}] content={content!r} does not contain {content_substr!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Router dispatch — 도메인별 올바른 agent 호출 검증
# ─────────────────────────────────────────────────────────────────────────────

ROUTER_DISPATCH_CASES = [
    ("오늘 일정 알려줘",          "CalendarAgent"),
    ("이번 달 지출 알려줘",       "FinanceAgent"),
    ("최근 논문 요약해줘",        "PaperAgent"),
    ("코드 리뷰해줘",             "DevAgent"),
    ("claude 사용량 알려줘",      "UsageAgent"),
    ("백로그 목록 보여줘",        "BacklogAgent"),
]

@pytest.mark.parametrize("message,expected_agent", ROUTER_DISPATCH_CASES)
def test_router_dispatches_correct_agent(message, expected_agent):
    """Router가 메시지를 올바른 agent로 라우팅하는지 검증."""
    from orchestrator.router import Router

    router = Router()
    called_agents = []

    async def _run():
        with patch.object(router, "_get_agent") as mock_get:
            mock_agent = AsyncMock()
            mock_agent.handle = AsyncMock(return_value="OK")
            mock_get.return_value = mock_agent

            with patch.object(router.sender, "send", new_callable=AsyncMock):
                await router.route(message=message, chat_id=0, user_id=0, message_id=0)

            called_agents.append(mock_get.call_args[0][0])  # domain arg

    asyncio.run(_run())
    assert called_agents, f"[{message!r}] agent never called"

    from orchestrator.router import Router as R
    # domain → agent class name 매핑
    domain_map = {
        "calendar": "CalendarAgent",
        "finance":  "FinanceAgent",
        "paper":    "PaperAgent",
        "dev":      "DevAgent",
        "usage":    "UsageAgent",
        "backlog":  "BacklogAgent",
    }
    actual_domain = called_agents[0]
    actual_agent = domain_map.get(actual_domain, actual_domain)
    assert actual_agent == expected_agent, (
        f"[{message!r}] dispatched to {actual_agent!r}, expected {expected_agent!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 5. Backlog flow
# ─────────────────────────────────────────────────────────────────────────────

def test_backlog_deferred_goes_to_triage():
    """'나중에' 포함 메시지는 triage/backlog로 분류되어야 함."""
    classifier = IntentClassifier()
    intent = asyncio.run(classifier.classify("나중에 블로그 글 써야 해"))
    assert intent.urgency == "backlog", f"urgency={intent.urgency!r}"


def test_backlog_immediate_override():
    """'지금' + '나중에' 동시 포함 시 immediate 우선."""
    classifier = IntentClassifier()
    intent = asyncio.run(classifier.classify("지금 나중에 할 일정 추가해줘"))
    assert intent.urgency == "immediate", f"urgency={intent.urgency!r}"
