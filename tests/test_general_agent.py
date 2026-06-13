import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.general.general_agent import GeneralAgent


def _make_intent(raw: str, chat_id: int = 0):
    intent = MagicMock()
    intent.raw_message = raw
    intent.chat_id = chat_id
    return intent


class TestGeneralAgentHandle:
    def test_handle_returns_background_message_immediately(self):
        intent = _make_intent("Jarvis가 뭐야?", chat_id=0)
        with patch("agents.general.general_agent.asyncio") as mock_asyncio:
            mock_asyncio.create_task = MagicMock()
            result = asyncio.run(GeneralAgent().handle(intent))
        assert "분석 중" in result
        mock_asyncio.create_task.assert_called_once()

    def test_handle_does_not_await_claude_directly(self):
        """handle()이 claude_ask를 직접 await하지 않는지 확인 — background task로 위임."""
        intent = _make_intent("뭔가 물어봐", chat_id=0)
        with patch("agents.general.general_agent.claude_ask") as mock_ask:
            with patch("agents.general.general_agent.asyncio") as mock_asyncio:
                mock_asyncio.create_task = MagicMock()
                asyncio.run(GeneralAgent().handle(intent))
        mock_ask.assert_not_called()

    def test_handle_with_external_project_context(self):
        """외부 프로젝트가 메시지에 언급될 때도 background 메시지 반환."""
        intent = _make_intent("PaperRadar 설명해줘", chat_id=1)
        with patch("agents.general.general_agent.asyncio") as mock_asyncio:
            mock_asyncio.create_task = MagicMock()
            result = asyncio.run(GeneralAgent().handle(intent))
        assert isinstance(result, str)
        assert len(result) > 0


class TestGeneralAgentBgAsk:
    @pytest.mark.asyncio
    async def test_bg_ask_sends_result_via_telegram(self):
        agent = GeneralAgent()
        with patch("agents.general.general_agent.claude_ask", new=AsyncMock(return_value="답변입니다")):
            with patch("systems.telegram_sender.TelegramSender") as MockSender:
                sender_inst = MockSender.return_value
                sender_inst.send_chunks = AsyncMock()
                await agent._bg_ask("프롬프트", chat_id=123)
        sender_inst.send_chunks.assert_called_once_with(123, "답변입니다")

    @pytest.mark.asyncio
    async def test_bg_ask_no_send_when_no_chat_id(self):
        agent = GeneralAgent()
        with patch("agents.general.general_agent.claude_ask", new=AsyncMock(return_value="답변")):
            with patch("systems.telegram_sender.TelegramSender") as MockSender:
                sender_inst = MockSender.return_value
                sender_inst.send_chunks = AsyncMock()
                await agent._bg_ask("프롬프트", chat_id=0)
        sender_inst.send_chunks.assert_not_called()

    @pytest.mark.asyncio
    async def test_bg_ask_sends_error_on_exception(self):
        agent = GeneralAgent()
        with patch("agents.general.general_agent.claude_ask", new=AsyncMock(side_effect=RuntimeError("timeout"))):
            with patch("systems.telegram_sender.TelegramSender") as MockSender:
                sender_inst = MockSender.return_value
                sender_inst.send = AsyncMock()
                await agent._bg_ask("프롬프트", chat_id=42)
        sender_inst.send.assert_called_once()
        error_msg = sender_inst.send.call_args[0][1]
        assert "오류" in error_msg


class TestBuildContext:
    def test_build_context_returns_empty_when_no_external_dir(self, tmp_path, monkeypatch):
        import agents.general.general_agent as mod
        monkeypatch.setattr(mod, "EXTERNAL_DIR", tmp_path / "nonexistent")
        agent = GeneralAgent()
        assert agent._build_context("anything") == ""

    def test_build_context_returns_empty_when_no_match(self, tmp_path, monkeypatch):
        import agents.general.general_agent as mod
        (tmp_path / "SomeProject").mkdir()
        monkeypatch.setattr(mod, "EXTERNAL_DIR", tmp_path)
        agent = GeneralAgent()
        assert agent._build_context("unrelated message") == ""

    def test_build_context_returns_context_on_match(self, tmp_path, monkeypatch):
        import agents.general.general_agent as mod
        proj = tmp_path / "TestProject"
        proj.mkdir()
        (proj / "main.py").write_text("print('hello')", encoding="utf-8")
        monkeypatch.setattr(mod, "EXTERNAL_DIR", tmp_path)
        agent = GeneralAgent()
        ctx = agent._build_context("TestProject 알려줘")
        assert "TestProject" in ctx
        assert "main.py" in ctx
