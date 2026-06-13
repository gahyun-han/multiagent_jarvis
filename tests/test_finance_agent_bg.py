"""
FinanceAgent background conversion tests.
Covers: fallthrough bg_finance_ask, asset update bg_asset_update.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.finance.finance_agent import FinanceAgent


def _make_intent(raw: str, chat_id: int = 0):
    intent = MagicMock()
    intent.raw_message = raw
    intent.chat_id = chat_id
    return intent


def _patch_deps():
    """Patch heavy init deps that require env/files."""
    patches = [
        patch("agents.finance.finance_agent.LedgerParser"),
        patch("agents.finance.finance_agent.SavingsTracker"),
        patch("agents.finance.finance_agent.AssetManager"),
        patch("agents.finance.finance_agent.TelegramSender"),
    ]
    return patches


class TestFallthroughBackground:
    def test_fallthrough_returns_background_message(self):
        """일반 재무 질문은 즉시 백그라운드 메시지를 반환한다."""
        intent = _make_intent("저번 달 지출이 많았나요?", chat_id=0)
        patches = _patch_deps()
        started = [p.start() for p in patches]
        try:
            agent = FinanceAgent()
            agent._build_context = MagicMock(return_value="context")
            # parse_many returns empty so it falls through to bg path
            agent.parser.parse_many = AsyncMock(return_value=[])
            with patch("agents.finance.finance_agent.asyncio") as mock_asyncio:
                mock_asyncio.create_task = MagicMock()
                result = asyncio.run(agent.handle(intent))
            assert "재무 분석" in result
            mock_asyncio.create_task.assert_called_once()
        finally:
            for p in patches:
                p.stop()

    def test_fallthrough_does_not_call_claude_directly(self):
        intent = _make_intent("이번 달 예산은 얼마나 남았어?", chat_id=0)
        patches = _patch_deps()
        [p.start() for p in patches]
        try:
            agent = FinanceAgent()
            agent._build_context = MagicMock(return_value="")
            agent.parser.parse_many = AsyncMock(return_value=[])
            with patch("agents.finance.finance_agent.claude_ask") as mock_ask:
                with patch("agents.finance.finance_agent.asyncio") as mock_asyncio:
                    mock_asyncio.create_task = MagicMock()
                    asyncio.run(agent.handle(intent))
            mock_ask.assert_not_called()
        finally:
            for p in patches:
                p.stop()


class TestAssetUpdateBackground:
    def test_asset_update_returns_background_message(self):
        """자산 업데이트 요청도 즉시 백그라운드 메시지를 반환한다."""
        intent = _make_intent("통장 추가해줘 — 국민은행 200만원", chat_id=5)
        patches = _patch_deps()
        [p.start() for p in patches]
        try:
            agent = FinanceAgent()
            with patch("agents.finance.finance_agent.asyncio") as mock_asyncio:
                mock_asyncio.create_task = MagicMock()
                result = asyncio.run(agent.handle(intent))
            assert "자산 업데이트" in result
            mock_asyncio.create_task.assert_called_once()
        finally:
            for p in patches:
                p.stop()


class TestBgFinanceAsk:
    @pytest.mark.asyncio
    async def test_bg_finance_ask_sends_result(self):
        patches = _patch_deps()
        started = [p.start() for p in patches]
        try:
            agent = FinanceAgent()
            with patch("agents.finance.finance_agent.claude_ask", new=AsyncMock(return_value="분석 결과")):
                with patch("agents.finance.finance_agent.TelegramSender") as MockSender:
                    sender_inst = MockSender.return_value
                    sender_inst.send_chunks = AsyncMock()
                    await agent._bg_finance_ask("ctx", "질문", chat_id=7)
            sender_inst.send_chunks.assert_called_once_with(7, "분석 결과")
        finally:
            for p in patches:
                p.stop()

    @pytest.mark.asyncio
    async def test_bg_finance_ask_no_send_when_no_chat_id(self):
        patches = _patch_deps()
        [p.start() for p in patches]
        try:
            agent = FinanceAgent()
            with patch("agents.finance.finance_agent.claude_ask", new=AsyncMock(return_value="분석 결과")):
                with patch("agents.finance.finance_agent.TelegramSender") as MockSender:
                    sender_inst = MockSender.return_value
                    sender_inst.send_chunks = AsyncMock()
                    await agent._bg_finance_ask("ctx", "질문", chat_id=0)
            sender_inst.send_chunks.assert_not_called()
        finally:
            for p in patches:
                p.stop()

    @pytest.mark.asyncio
    async def test_bg_finance_ask_sends_error_on_exception(self):
        patches = _patch_deps()
        [p.start() for p in patches]
        try:
            agent = FinanceAgent()
            with patch("agents.finance.finance_agent.claude_ask", new=AsyncMock(side_effect=RuntimeError("fail"))):
                with patch("agents.finance.finance_agent.TelegramSender") as MockSender:
                    sender_inst = MockSender.return_value
                    sender_inst.send = AsyncMock()
                    await agent._bg_finance_ask("ctx", "질문", chat_id=9)
            sender_inst.send.assert_called_once()
            assert "오류" in sender_inst.send.call_args[0][1]
        finally:
            for p in patches:
                p.stop()


class TestBgAssetUpdate:
    @pytest.mark.asyncio
    async def test_bg_asset_update_sends_result(self):
        patches = _patch_deps()
        [p.start() for p in patches]
        try:
            agent = FinanceAgent()
            agent._handle_asset_update = AsyncMock(return_value="💰 자산 업데이트 완료 (1건)\n총 순자산: 5,000,000원")
            with patch("agents.finance.finance_agent.TelegramSender") as MockSender:
                sender_inst = MockSender.return_value
                sender_inst.send_chunks = AsyncMock()
                await agent._bg_asset_update("통장 추가", chat_id=3)
            sender_inst.send_chunks.assert_called_once()
        finally:
            for p in patches:
                p.stop()

    @pytest.mark.asyncio
    async def test_bg_asset_update_sends_error_on_exception(self):
        patches = _patch_deps()
        [p.start() for p in patches]
        try:
            agent = FinanceAgent()
            agent._handle_asset_update = AsyncMock(side_effect=RuntimeError("parse fail"))
            with patch("agents.finance.finance_agent.TelegramSender") as MockSender:
                sender_inst = MockSender.return_value
                sender_inst.send = AsyncMock()
                await agent._bg_asset_update("통장 추가", chat_id=4)
            sender_inst.send.assert_called_once()
            assert "오류" in sender_inst.send.call_args[0][1]
        finally:
            for p in patches:
                p.stop()
