"""
Router/ErrorRecovery 에러 처리 테스트
- route() classify 실패 시 사용자에게 응답 전달
- _dispatch_backlog() TriageAgent 실패 시 응답 전달
- error_recovery.handle() 내부 sender.send() 실패 시 logger.critical만 기록
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Router.route() — classify 실패 ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_route_classify_failure_sends_error_to_user():
    """classify()가 예외를 던지면 사용자에게 에러 메시지가 전달된다."""
    from orchestrator.router import Router

    with patch("orchestrator.router.TelegramSender"):
        with patch("orchestrator.router.UsageManager"):
            with patch("orchestrator.router.ErrorRecovery") as MockER:
                er_inst = MockER.return_value
                er_inst.handle = AsyncMock()

                router = Router()
                router.classifier.classify = AsyncMock(side_effect=RuntimeError("classify crash"))

                await router.route("테스트", chat_id=123, user_id=1, message_id=1)

    er_inst.handle.assert_called_once()
    call_kwargs = er_inst.handle.call_args
    assert call_kwargs.kwargs.get("chat_id") == 123 or call_kwargs.args[1] == 123
    assert "route" in (call_kwargs.kwargs.get("context", "") or "")


@pytest.mark.asyncio
async def test_route_classify_failure_does_not_propagate():
    """classify() 실패가 route() 밖으로 예외를 터뜨리지 않는다."""
    from orchestrator.router import Router

    with patch("orchestrator.router.TelegramSender"):
        with patch("orchestrator.router.UsageManager"):
            with patch("orchestrator.router.ErrorRecovery") as MockER:
                er_inst = MockER.return_value
                er_inst.handle = AsyncMock()

                router = Router()
                router.classifier.classify = AsyncMock(side_effect=ValueError("bad"))

                # 예외가 밖으로 새지 않아야 한다
                await router.route("테스트", chat_id=1, user_id=1, message_id=1)


# ── Router._dispatch_backlog() — TriageAgent 실패 ─────────────────────────────

@pytest.mark.asyncio
async def test_dispatch_backlog_triage_failure_sends_error():
    """TriageAgent.handle()이 실패하면 error_recovery.handle()이 호출된다."""
    from orchestrator.router import Router
    from orchestrator.intent_classifier import Intent

    intent = Intent(
        domain="triage", urgency="backlog",
        confidence=1.0, summary="나중에 처리", raw_message="나중에 해줘",
    )

    with patch("orchestrator.router.TelegramSender"):
        with patch("orchestrator.router.UsageManager"):
            with patch("orchestrator.router.ErrorRecovery") as MockER:
                er_inst = MockER.return_value
                er_inst.handle = AsyncMock()

                router = Router()

                with patch("agents.inbox_trage.trage_agent.TriageAgent") as MockTriage:
                    triage_inst = MockTriage.return_value
                    triage_inst.handle = AsyncMock(side_effect=RuntimeError("triage crash"))

                    with patch("orchestrator.router.TriageAgent", MockTriage, create=True):
                        # _dispatch_backlog을 직접 호출
                        with patch("orchestrator.router.__builtins__", create=True):
                            pass

                    # 모듈 레벨에서 패치
                    import orchestrator.router as router_mod
                    original = getattr(router_mod, "TriageAgent", None)
                    router_mod.TriageAgent = MockTriage  # type: ignore
                    try:
                        await router._dispatch_backlog(intent, chat_id=456)
                    finally:
                        if original is None:
                            delattr(router_mod, "TriageAgent")
                        else:
                            router_mod.TriageAgent = original

    er_inst.handle.assert_called_once()
    call_kwargs = er_inst.handle.call_args
    assert call_kwargs.kwargs.get("chat_id") == 456 or call_kwargs.args[1] == 456
    assert "backlog" in (call_kwargs.kwargs.get("context", "") or "")


@pytest.mark.asyncio
async def test_dispatch_backlog_failure_does_not_propagate():
    """_dispatch_backlog() 내부 예외가 밖으로 터지지 않는다."""
    from orchestrator.router import Router
    from orchestrator.intent_classifier import Intent

    intent = Intent(
        domain="triage", urgency="backlog",
        confidence=1.0, summary="test", raw_message="나중에",
    )

    with patch("orchestrator.router.TelegramSender"):
        with patch("orchestrator.router.UsageManager"):
            with patch("orchestrator.router.ErrorRecovery") as MockER:
                er_inst = MockER.return_value
                er_inst.handle = AsyncMock()
                router = Router()

                with patch("agents.inbox_trage.trage_agent.TriageAgent") as MockTriage:
                    triage_inst = MockTriage.return_value
                    triage_inst.handle = AsyncMock(side_effect=Exception("boom"))

                    import orchestrator.router as router_mod
                    original = getattr(router_mod, "TriageAgent", None)
                    router_mod.TriageAgent = MockTriage  # type: ignore
                    try:
                        await router._dispatch_backlog(intent, chat_id=1)
                    finally:
                        if original is None:
                            delattr(router_mod, "TriageAgent")
                        else:
                            router_mod.TriageAgent = original


# ── ErrorRecovery.handle() — sender.send() 실패 ───────────────────────────────

@pytest.mark.asyncio
async def test_error_recovery_send_failure_logs_critical():
    """sender.send()가 실패해도 handle()이 예외를 밖으로 던지지 않고 critical 로그만 남긴다."""
    from systems.error_recovery import ErrorRecovery
    import logging

    er = ErrorRecovery()

    with patch("systems.telegram_sender.TelegramSender") as MockSender:
        sender_inst = MockSender.return_value
        sender_inst.send = AsyncMock(side_effect=ConnectionError("telegram down"))

        with patch.object(
            logging.getLogger("systems.error_recovery"),
            "critical",
        ) as mock_critical:
            # 예외가 밖으로 새지 않아야 한다
            await er.handle(ValueError("some error"), chat_id=99, context="test")

        mock_critical.assert_called_once()
        assert "99" in str(mock_critical.call_args) or "telegram" in str(mock_critical.call_args).lower()


@pytest.mark.asyncio
async def test_error_recovery_send_failure_does_not_raise():
    """sender.send() 실패 시 handle()이 예외를 전파하지 않는다."""
    from systems.error_recovery import ErrorRecovery

    er = ErrorRecovery()
    with patch("systems.telegram_sender.TelegramSender") as MockSender:
        MockSender.return_value.send = AsyncMock(side_effect=OSError("network"))
        await er.handle(RuntimeError("original"), chat_id=1, context="ctx")


@pytest.mark.asyncio
async def test_error_recovery_no_chat_id_skips_send():
    """chat_id=None이면 send()를 호출하지 않는다."""
    from systems.error_recovery import ErrorRecovery

    er = ErrorRecovery()
    with patch("systems.telegram_sender.TelegramSender") as MockSender:
        await er.handle(RuntimeError("err"), chat_id=None)
        MockSender.assert_not_called()


@pytest.mark.asyncio
async def test_error_recovery_credit_exhausted_message_contains_bot():
    """CREDIT_EXHAUSTED 에러 시 @Claude_hangabot 안내 메시지가 전송된다."""
    from systems.error_recovery import ErrorRecovery

    er = ErrorRecovery()
    with patch("systems.telegram_sender.TelegramSender") as MockSender:
        sender_inst = MockSender.return_value
        sender_inst.send = AsyncMock()

        await er.handle(Exception("credit balance is too low"), chat_id=7)

        sender_inst.send.assert_called_once()
        sent_text = sender_inst.send.call_args.args[1]
        assert "@Claude_hangabot" in sent_text
