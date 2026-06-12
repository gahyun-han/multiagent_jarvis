"""
IntentClassifier 오분류 개선 테스트
- _SYSTEM_PROMPT에 usage/youtube 도메인 포함 여부
- 슬래시 커맨드 키워드 규칙 사전 분류
- confidence < 0.7 → action="clarify"
- few-shot 예시 문구 포함 여부
- Router의 action=="clarify" 분기 연동
"""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.intent_classifier import IntentClassifier, Intent, _SYSTEM_PROMPT, _KEYWORD_RULES


# ── Fix 1: _SYSTEM_PROMPT domain 목록 ────────────────────────────────────────

def test_system_prompt_contains_usage_domain():
    assert "usage" in _SYSTEM_PROMPT


def test_system_prompt_contains_youtube_domain():
    assert "youtube" in _SYSTEM_PROMPT


def test_system_prompt_usage_description():
    assert "토큰" in _SYSTEM_PROMPT or "크레딧" in _SYSTEM_PROMPT or "사용량" in _SYSTEM_PROMPT


def test_system_prompt_youtube_description():
    assert "유튜브" in _SYSTEM_PROMPT or "youtube.com" in _SYSTEM_PROMPT.lower()


# ── Fix 2: 슬래시 커맨드 키워드 규칙 ─────────────────────────────────────────

def _find_rule(keyword: str) -> tuple | None:
    for keywords, domain, urgency in _KEYWORD_RULES:
        if keyword in keywords:
            return (keywords, domain, urgency)
    return None


def test_slash_list_maps_to_backlog_immediate():
    rule = _find_rule("/list")
    assert rule is not None, "/list 규칙이 없음"
    _, domain, urgency = rule
    assert domain == "backlog"
    assert urgency == "immediate"


def test_slash_backlog_maps_to_backlog_immediate():
    rule = _find_rule("/백로그")
    assert rule is not None
    _, domain, urgency = rule
    assert domain == "backlog"
    assert urgency == "immediate"


def test_slash_usage_maps_to_usage_immediate():
    rule = _find_rule("/사용량")
    assert rule is not None
    _, domain, urgency = rule
    assert domain == "usage"
    assert urgency == "immediate"


def test_slash_token_maps_to_usage_immediate():
    rule = _find_rule("/토큰")
    assert rule is not None
    _, domain, urgency = rule
    assert domain == "usage"
    assert urgency == "immediate"


def test_slash_calendar_maps_to_calendar_immediate():
    rule = _find_rule("/일정")
    assert rule is not None
    _, domain, urgency = rule
    assert domain == "calendar"
    assert urgency == "immediate"


@pytest.mark.asyncio
async def test_slash_list_classified_without_llm():
    """슬래시 커맨드는 LLM 호출 없이 즉시 분류된다."""
    classifier = IntentClassifier()
    with patch("orchestrator.intent_classifier.claude_ask_async") as mock_llm:
        result = await classifier.classify("/list")
    mock_llm.assert_not_called()
    assert result.domain == "backlog"
    assert result.urgency == "immediate"
    assert result.action == "execute"


@pytest.mark.asyncio
async def test_slash_usage_classified_without_llm():
    classifier = IntentClassifier()
    with patch("orchestrator.intent_classifier.claude_ask_async") as mock_llm:
        result = await classifier.classify("/사용량")
    mock_llm.assert_not_called()
    assert result.domain == "usage"
    assert result.urgency == "immediate"


# ── Fix 3: confidence < 0.7 → action="clarify" ───────────────────────────────

@pytest.mark.asyncio
async def test_low_confidence_sets_action_clarify():
    """LLM이 confidence 0.5를 반환하면 action="clarify"."""
    classifier = IntentClassifier()
    llm_response = json.dumps({
        "domain": "unknown",
        "urgency": "immediate",
        "confidence": 0.5,
        "summary": "모호한 요청",
    })
    with patch("orchestrator.intent_classifier.claude_ask_async", new=AsyncMock(return_value=llm_response)):
        result = await classifier.classify("그거 좀 해줘")
    assert result.action == "clarify"
    assert result.confidence == 0.5


@pytest.mark.asyncio
async def test_high_confidence_sets_action_execute():
    """LLM이 confidence 0.9를 반환하면 action="execute"."""
    classifier = IntentClassifier()
    llm_response = json.dumps({
        "domain": "calendar",
        "urgency": "immediate",
        "confidence": 0.9,
        "summary": "일정 추가",
    })
    with patch("orchestrator.intent_classifier.claude_ask_async", new=AsyncMock(return_value=llm_response)):
        result = await classifier.classify("내일 3시에 회의 추가해줘")
    assert result.action == "execute"
    assert result.confidence == 0.9


@pytest.mark.asyncio
async def test_exactly_07_confidence_is_execute():
    """confidence == 0.7 경계값은 execute (clarify 조건은 strictly < 0.7)."""
    classifier = IntentClassifier()
    llm_response = json.dumps({
        "domain": "finance",
        "urgency": "immediate",
        "confidence": 0.7,
        "summary": "지출 조회",
    })
    with patch("orchestrator.intent_classifier.claude_ask_async", new=AsyncMock(return_value=llm_response)):
        result = await classifier.classify("지출 알려줘")
    assert result.action == "execute"


@pytest.mark.asyncio
async def test_keyword_rule_always_execute():
    """키워드 규칙으로 분류된 경우 action은 항상 execute."""
    classifier = IntentClassifier()
    with patch("orchestrator.intent_classifier.claude_ask_async") as mock_llm:
        result = await classifier.classify("오늘 일정 알려줘")
    mock_llm.assert_not_called()
    assert result.action == "execute"


# ── Fix 3 연동: Router가 action=="clarify"이면 _ask_urgency 호출 ──────────────

@pytest.mark.asyncio
async def test_router_calls_ask_urgency_on_clarify():
    """intent.action == 'clarify'이면 router가 _ask_urgency를 호출한다."""
    from orchestrator.router import Router

    clarify_intent = Intent(
        domain="unknown", urgency="immediate",
        confidence=0.5, summary="모호한 요청", raw_message="그거 좀",
        action="clarify",
    )

    with patch("orchestrator.router.TelegramSender"):
        with patch("orchestrator.router.UsageManager"):
            with patch("orchestrator.router.ErrorRecovery"):
                router = Router()
                router.classifier.classify = AsyncMock(return_value=clarify_intent)
                router._ask_urgency = AsyncMock()
                router._dispatch_immediate = AsyncMock()
                router._dispatch_backlog = AsyncMock()

                await router.route("그거 좀", chat_id=1, user_id=1, message_id=1)

    router._ask_urgency.assert_called_once_with(clarify_intent, 1)
    router._dispatch_immediate.assert_not_called()
    router._dispatch_backlog.assert_not_called()


@pytest.mark.asyncio
async def test_router_does_not_ask_urgency_on_execute():
    """intent.action == 'execute'이면 _ask_urgency를 호출하지 않는다."""
    from orchestrator.router import Router

    execute_intent = Intent(
        domain="calendar", urgency="immediate",
        confidence=0.9, summary="일정 조회", raw_message="오늘 일정",
        action="execute",
    )

    with patch("orchestrator.router.TelegramSender"):
        with patch("orchestrator.router.UsageManager"):
            with patch("orchestrator.router.ErrorRecovery"):
                router = Router()
                router.classifier.classify = AsyncMock(return_value=execute_intent)
                router._ask_urgency = AsyncMock()
                router._dispatch_immediate = AsyncMock()

                await router.route("오늘 일정", chat_id=1, user_id=1, message_id=1)

    router._ask_urgency.assert_not_called()
    router._dispatch_immediate.assert_called_once()


# ── Fix 4: few-shot 예시 포함 여부 ────────────────────────────────────────────

def test_system_prompt_has_fewshot_dev_example():
    assert "dev" in _SYSTEM_PROMPT
    assert "immediate" in _SYSTEM_PROMPT


def test_system_prompt_has_fewshot_triage_backlog_example():
    assert "backlog" in _SYSTEM_PROMPT
    assert "나중에" in _SYSTEM_PROMPT


def test_system_prompt_has_fewshot_usage_example():
    assert "usage" in _SYSTEM_PROMPT


# ── Intent 기본값 호환성 ──────────────────────────────────────────────────────

def test_intent_default_action_is_execute():
    """action 필드 기본값은 'execute' (기존 코드와 호환)."""
    intent = Intent(
        domain="calendar", urgency="immediate",
        confidence=1.0, summary="test", raw_message="test",
    )
    assert intent.action == "execute"


# ── Obsidian 라우팅 버그 수정 검증 ────────────────────────────────────────────
# "옵시디언 연구계획.md 파일에 내용 추가해줘" 패턴에서 "옵시디언에" 파티클이 없어도
# paper 도메인으로 사전 분류되어야 한다 (LLM이 "에이전트" 키워드 때문에 dev로
# 분류하는 오류 방지).

@pytest.mark.asyncio
async def test_obsidian_without_particle_routes_to_paper():
    """'옵시디언 연구계획.md 파일에 내용 추가해줘' → paper 도메인 (LLM 불필요)."""
    classifier = IntentClassifier()
    with patch("orchestrator.intent_classifier.claude_ask_async") as mock_llm:
        result = await classifier.classify(
            "자기학습 에이전트(Dreaming)에 대해서 알아봐주고, 옵시디언 연구계획.md 파일에 내용 추가해줘."
        )
    mock_llm.assert_not_called()
    assert result.domain == "paper"
    assert result.urgency == "immediate"


@pytest.mark.asyncio
async def test_obsidian_md_file_routes_to_paper():
    """'옵시디언 메모.md 파일에 추가해줘' → paper (particle 없이도 분류)."""
    classifier = IntentClassifier()
    with patch("orchestrator.intent_classifier.claude_ask_async") as mock_llm:
        result = await classifier.classify("옵시디언 메모.md 파일에 추가해줘")
    mock_llm.assert_not_called()
    assert result.domain == "paper"


@pytest.mark.asyncio
async def test_obsidian_with_particle_still_routes_to_paper():
    """기존 '옵시디언에 저장' 패턴도 계속 paper 도메인으로 분류된다."""
    classifier = IntentClassifier()
    with patch("orchestrator.intent_classifier.claude_ask_async") as mock_llm:
        result = await classifier.classify("옵시디언에 이 내용 저장해줘")
    mock_llm.assert_not_called()
    assert result.domain == "paper"
