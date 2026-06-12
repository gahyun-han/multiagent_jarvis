"""
에러 메모리 시스템 테스트
- ErrorMemory.save(): 신규 저장, 중복 시 count 증가
- ErrorMemory.load_relevant(): context 매칭, 빈도 정렬, 최대 5개
- ErrorMemory.to_prompt_str(): 빈 목록, 단건, 다건 포맷
- ErrorRecovery.handle()이 ErrorMemory.save() 호출 여부
- Router._dispatch_immediate()이 error_hints를 intent에 주입 여부
- Intent.error_hints 기본값
"""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call
import tempfile

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── ErrorMemory 단위 테스트 ───────────────────────────────────────────────────

def _make_memory(tmp_path):
    from systems.error_memory import ErrorMemory, _MEMORY_PATH
    mem = ErrorMemory()
    # 테스트용 임시 파일 경로로 패치
    import systems.error_memory as em_mod
    em_mod._MEMORY_PATH = tmp_path / "error_memory.json"
    return mem, em_mod


def test_save_creates_new_entry(tmp_path):
    mem, em_mod = _make_memory(tmp_path)
    mem.save("network", "dev", "재시도 필요")

    data = json.loads((tmp_path / "error_memory.json").read_text())
    assert len(data) == 1
    assert data[0]["error_type"] == "network"
    assert data[0]["context"] == "dev"
    assert data[0]["count"] == 1


def test_save_increments_count_on_duplicate(tmp_path):
    mem, em_mod = _make_memory(tmp_path)
    mem.save("network", "dev", "재시도")
    mem.save("network", "dev", "재시도 v2")

    data = json.loads((tmp_path / "error_memory.json").read_text())
    assert len(data) == 1
    assert data[0]["count"] == 2
    assert data[0]["solution"] == "재시도 v2"  # 최신 solution으로 갱신


def test_save_different_context_creates_separate_entry(tmp_path):
    mem, em_mod = _make_memory(tmp_path)
    mem.save("network", "dev", "솔루션A")
    mem.save("network", "paper", "솔루션B")

    data = json.loads((tmp_path / "error_memory.json").read_text())
    assert len(data) == 2


def test_save_trims_to_max_50(tmp_path):
    mem, em_mod = _make_memory(tmp_path)
    for i in range(55):
        mem.save(f"type_{i}", f"ctx_{i}", f"sol_{i}")

    data = json.loads((tmp_path / "error_memory.json").read_text())
    assert len(data) == 50


def test_load_relevant_exact_match(tmp_path):
    mem, em_mod = _make_memory(tmp_path)
    mem.save("network", "dev", "sol1")
    mem.save("data", "paper", "sol2")

    results = mem.load_relevant("dev")
    assert len(results) == 1
    assert results[0]["context"] == "dev"


def test_load_relevant_substring_match(tmp_path):
    """'immediate:dev'는 'dev' context 패턴과 매칭되어야 한다."""
    mem, em_mod = _make_memory(tmp_path)
    mem.save("unknown", "immediate:dev", "sol")

    results = mem.load_relevant("dev")
    assert len(results) == 1


def test_load_relevant_sorted_by_count(tmp_path):
    mem, em_mod = _make_memory(tmp_path)
    mem.save("network", "dev", "sol1")
    mem.save("data", "dev", "sol2")
    mem.save("data", "dev", "sol2")  # count=2

    results = mem.load_relevant("dev")
    assert results[0]["error_type"] == "data"  # count 높은 것이 먼저


def test_load_relevant_max_5(tmp_path):
    mem, em_mod = _make_memory(tmp_path)
    for i in range(8):
        mem.save(f"type_{i}", "dev", f"sol_{i}")

    results = mem.load_relevant("dev")
    assert len(results) <= 5


def test_load_relevant_empty_file_returns_empty(tmp_path):
    mem, em_mod = _make_memory(tmp_path)
    results = mem.load_relevant("dev")
    assert results == []


def test_to_prompt_str_empty_returns_empty_string(tmp_path):
    mem, em_mod = _make_memory(tmp_path)
    result = mem.to_prompt_str([])
    assert result == ""


def test_to_prompt_str_includes_error_type_and_solution(tmp_path):
    mem, em_mod = _make_memory(tmp_path)
    entries = [{"error_type": "network", "context": "dev", "solution": "재시도", "count": 3, "last_seen": "2026-06-12T00:00:00"}]
    result = mem.to_prompt_str(entries)
    assert "network" in result
    assert "재시도" in result
    assert "3" in result


def test_to_prompt_str_no_args_uses_all_stored(tmp_path):
    mem, em_mod = _make_memory(tmp_path)
    mem.save("auth", "route", "API 키 확인")
    result = mem.to_prompt_str()
    assert "auth" in result


def test_save_handles_corrupted_json_gracefully(tmp_path):
    mem, em_mod = _make_memory(tmp_path)
    (tmp_path / "error_memory.json").write_text("not valid json")
    mem.save("network", "dev", "sol")  # 에러 없이 새 파일로 대체
    data = json.loads((tmp_path / "error_memory.json").read_text())
    assert len(data) == 1


# ── ErrorRecovery.handle()이 ErrorMemory.save() 호출 ─────────────────────────

@pytest.mark.asyncio
async def test_error_recovery_handle_calls_error_memory_save():
    """handle()이 ErrorMemory.save()를 호출한다."""
    from systems.error_recovery import ErrorRecovery

    er = ErrorRecovery()
    with patch("systems.error_memory.ErrorMemory.save") as mock_save:
        with patch("systems.telegram_sender.TelegramSender"):
            await er.handle(RuntimeError("test error"), chat_id=None, context="dev")
    mock_save.assert_called_once()
    args = mock_save.call_args.args
    assert args[0] == "unknown"  # RuntimeError → UNKNOWN kind
    assert args[1] == "dev"      # context


@pytest.mark.asyncio
async def test_error_recovery_saves_network_kind():
    """TimeoutError는 'network' kind로 저장된다."""
    import asyncio
    from systems.error_recovery import ErrorRecovery

    er = ErrorRecovery()
    with patch("systems.error_memory.ErrorMemory.save") as mock_save:
        with patch("systems.telegram_sender.TelegramSender"):
            await er.handle(asyncio.TimeoutError(), chat_id=None, context="paper")
    args = mock_save.call_args.args
    assert args[0] == "network"


@pytest.mark.asyncio
async def test_error_recovery_save_failure_does_not_propagate():
    """ErrorMemory.save()가 실패해도 handle()이 예외를 전파하지 않는다."""
    from systems.error_recovery import ErrorRecovery

    er = ErrorRecovery()
    with patch("systems.error_memory.ErrorMemory.save", side_effect=OSError("disk full")):
        with patch("systems.telegram_sender.TelegramSender"):
            await er.handle(ValueError("some error"), chat_id=None, context="ctx")


# ── Router._dispatch_immediate(): error_hints 주입 ───────────────────────────

@pytest.mark.asyncio
async def test_router_injects_error_hints_into_intent():
    """_dispatch_immediate()이 agent.handle() 호출 전에 intent.error_hints를 설정한다."""
    from orchestrator.router import Router
    from orchestrator.intent_classifier import Intent

    intent = Intent(
        domain="dev", urgency="immediate",
        confidence=1.0, summary="코드 수정", raw_message="버그 고쳐줘",
    )
    fake_hints = [{"error_type": "network", "context": "dev", "solution": "재시도", "count": 2, "last_seen": "2026-06-12T00:00:00"}]

    with patch("orchestrator.router.TelegramSender"):
        with patch("orchestrator.router.UsageManager") as MockUsage:
            MockUsage.return_value.has_budget.return_value = True
            with patch("orchestrator.router.ErrorRecovery"):
                with patch("orchestrator.router.ErrorMemory") as MockEM:
                    em_inst = MockEM.return_value
                    em_inst.load_relevant.return_value = fake_hints

                    router = Router()

                    captured_intent = None

                    async def fake_handle(intent_arg):
                        nonlocal captured_intent
                        captured_intent = intent_arg
                        return "ok"

                    mock_agent = MagicMock()
                    mock_agent.handle = fake_handle
                    router._get_agent = MagicMock(return_value=mock_agent)
                    router.sender.send = AsyncMock()

                    await router._dispatch_immediate(intent, chat_id=1)

    assert captured_intent is not None
    assert captured_intent.error_hints == fake_hints
    em_inst.load_relevant.assert_called_once_with("dev")


@pytest.mark.asyncio
async def test_router_error_hints_empty_when_no_history():
    """과거 에러가 없으면 error_hints는 빈 리스트다."""
    from orchestrator.router import Router
    from orchestrator.intent_classifier import Intent

    intent = Intent(
        domain="calendar", urgency="immediate",
        confidence=1.0, summary="일정", raw_message="오늘 일정",
    )

    with patch("orchestrator.router.TelegramSender"):
        with patch("orchestrator.router.UsageManager") as MockUsage:
            MockUsage.return_value.has_budget.return_value = True
            with patch("orchestrator.router.ErrorRecovery"):
                with patch("orchestrator.router.ErrorMemory") as MockEM:
                    em_inst = MockEM.return_value
                    em_inst.load_relevant.return_value = []

                    router = Router()

                    async def fake_handle(intent_arg):
                        return "ok"

                    mock_agent = MagicMock()
                    mock_agent.handle = fake_handle
                    router._get_agent = MagicMock(return_value=mock_agent)
                    router.sender.send = AsyncMock()

                    await router._dispatch_immediate(intent, chat_id=1)

    assert intent.error_hints == []


# ── Intent 기본값 ─────────────────────────────────────────────────────────────

def test_intent_error_hints_default_is_empty_list():
    """error_hints 기본값은 빈 리스트 (기존 코드 호환)."""
    from orchestrator.intent_classifier import Intent

    intent = Intent(
        domain="dev", urgency="immediate",
        confidence=1.0, summary="test", raw_message="test",
    )
    assert intent.error_hints == []
    assert isinstance(intent.error_hints, list)
