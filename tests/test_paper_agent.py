import asyncio
from unittest.mock import MagicMock, patch

from agents.paper.paper_agent import PaperAgent, _SYSTEM


def _make_intent(raw_message: str):
    intent = MagicMock()
    intent.raw_message = raw_message
    return intent


def _make_papers(n: int) -> list[dict]:
    return [
        {
            "year": 2020 + i,
            "title": f"Paper {i}",
            "authors": f"Author {i}",
            "abstract": f"Abstract for paper {i}",
        }
        for i in range(n)
    ]


class TestPaperAgentInit:
    def test_init_creates_library_client(self):
        with patch("agents.paper.paper_agent.ZoteroClient") as MockClient:
            agent = PaperAgent()
        MockClient.assert_called_once()
        assert agent.library is MockClient.return_value


class TestPaperAgentHandle:
    def test_handle_happy_path(self):
        """논문이 있으면 백그라운드 시작 메시지를 즉시 반환한다."""
        intent = _make_intent("최근 트랜스포머 논문 알려줘")
        intent.chat_id = 0
        with patch("agents.paper.paper_agent.ZoteroClient") as MockClient:
            MockClient.return_value.get_recent_papers.return_value = _make_papers(3)
            with patch("agents.paper.paper_agent.claude_ask", return_value="Claude response"):
                agent = PaperAgent()
                result = asyncio.run(agent.handle(intent))
        assert "백그라운드" in result
        assert "3편" in result

    def test_handle_empty_library(self):
        intent = _make_intent("요약해줘")
        with patch("agents.paper.paper_agent.ZoteroClient") as MockClient:
            MockClient.return_value.get_recent_papers.return_value = []
            with patch("agents.paper.paper_agent._load_sent_keys", return_value=set()):
                with patch("agents.paper.paper_agent.claude_ask") as mock_ask:
                    agent = PaperAgent()
                    result = asyncio.run(agent.handle(intent))
        assert result == "📄 새로운 논문이 없습니다. (이미 전송한 논문만 있음)"
        mock_ask.assert_not_called()

    def test_handle_claude_raises_exception(self):
        """논문이 있으면 claude_ask 오류 여부와 무관하게 백그라운드 시작 메시지를 반환한다."""
        intent = _make_intent("요약해줘")
        intent.chat_id = 0
        with patch("agents.paper.paper_agent.ZoteroClient") as MockClient:
            MockClient.return_value.get_recent_papers.return_value = _make_papers(1)
            with patch("agents.paper.paper_agent.claude_ask", side_effect=RuntimeError("timeout")):
                agent = PaperAgent()
                result = asyncio.run(agent.handle(intent))
        assert "백그라운드" in result

    def test_handle_passes_raw_message_in_prompt(self):
        intent = _make_intent("특정 키워드 검색")
        with patch("agents.paper.paper_agent.ZoteroClient") as MockClient:
            MockClient.return_value.get_recent_papers.return_value = _make_papers(1)
            with patch("agents.paper.paper_agent.claude_ask", return_value="r") as mock_ask:
                agent = PaperAgent()
                asyncio.run(agent.handle(intent))
        prompt_arg = mock_ask.call_args[0][0]
        assert "특정 키워드 검색" in prompt_arg

    def test_handle_uses_correct_system_prompt(self):
        intent = _make_intent("query")
        with patch("agents.paper.paper_agent.ZoteroClient") as MockClient:
            MockClient.return_value.get_recent_papers.return_value = _make_papers(1)
            with patch("agents.paper.paper_agent.claude_ask", return_value="r") as mock_ask:
                agent = PaperAgent()
                asyncio.run(agent.handle(intent))
        assert mock_ask.call_args[1].get("system") == _SYSTEM

    def test_handle_calls_get_recent_papers_with_limit_20(self):
        intent = _make_intent("query")
        with patch("agents.paper.paper_agent.ZoteroClient") as MockClient:
            mock_lib = MockClient.return_value
            mock_lib.get_recent_papers.return_value = []
            with patch("agents.paper.paper_agent.claude_ask", return_value="r"):
                agent = PaperAgent()
                asyncio.run(agent.handle(intent))
        mock_lib.get_recent_papers.assert_called_once_with(limit=20)


class TestPaperAgentSummarizeAll:
    def test_summarize_all_happy_path(self):
        with patch("agents.paper.paper_agent.ZoteroClient") as MockClient:
            MockClient.return_value.get_recent_papers.return_value = _make_papers(5)
            with patch("agents.paper.paper_agent.claude_ask", return_value="Claude summary") as mock_ask:
                agent = PaperAgent()
                result = asyncio.run(agent.summarize_all())
        assert result == "Claude summary"
        assert mock_ask.call_args[1].get("max_tokens") == 2048

    def test_summarize_all_empty_library(self):
        with patch("agents.paper.paper_agent.ZoteroClient") as MockClient:
            MockClient.return_value.get_recent_papers.return_value = []
            agent = PaperAgent()
            result = asyncio.run(agent.summarize_all())
        assert result == "📚 새로운 논문이 없습니다."

    def test_summarize_all_does_not_call_claude_when_empty(self):
        with patch("agents.paper.paper_agent.ZoteroClient") as MockClient:
            MockClient.return_value.get_recent_papers.return_value = []
            with patch("agents.paper.paper_agent.claude_ask") as mock_ask:
                agent = PaperAgent()
                asyncio.run(agent.summarize_all())
        mock_ask.assert_not_called()

    def test_summarize_all_calls_get_recent_papers_with_limit_20(self):
        with patch("agents.paper.paper_agent.ZoteroClient") as MockClient:
            mock_lib = MockClient.return_value
            mock_lib.get_recent_papers.return_value = _make_papers(3)
            with patch("agents.paper.paper_agent.claude_ask", return_value="r"):
                agent = PaperAgent()
                asyncio.run(agent.summarize_all())
        mock_lib.get_recent_papers.assert_called_once_with(limit=20)


class TestBuildContext:
    def test_build_context_empty_list(self):
        assert PaperAgent._build_context([]) == "(논문 없음)"

    def test_build_context_single_paper_with_abstract(self):
        papers = [{"year": 2024, "title": "Attention", "authors": "Vaswani", "abstract": "A" * 300}]
        result = PaperAgent._build_context(papers)
        assert "1. [2024] Attention — Vaswani" in result
        assert "초록: " + "A" * 200 in result

    def test_build_context_abstract_truncated_at_200(self):
        abstract = "B" * 250
        papers = [{"year": 2024, "title": "Test", "authors": "Auth", "abstract": abstract}]
        result = PaperAgent._build_context(papers)
        lines = result.split("\n")
        abstract_line = next(line for line in lines if "초록:" in line)
        abstract_content = abstract_line.split("초록: ")[1]
        assert len(abstract_content) == 200
        assert abstract_content == "B" * 200

    def test_build_context_empty_abstract(self):
        papers = [{"year": 2023, "title": "T", "authors": "A", "abstract": ""}]
        result = PaperAgent._build_context(papers)
        assert "초록:" not in result

    def test_build_context_none_abstract(self):
        papers = [{"year": 2023, "title": "T", "authors": "A", "abstract": None}]
        result = PaperAgent._build_context(papers)
        assert "초록:" not in result

    def test_build_context_multiple_papers_numbered(self):
        papers = _make_papers(3)
        result = PaperAgent._build_context(papers)
        numbered_lines = [line for line in result.split("\n") if line and not line.startswith("   ")]
        assert numbered_lines[0].startswith("1.")
        assert numbered_lines[1].startswith("2.")
        assert numbered_lines[2].startswith("3.")

    def test_build_context_short_abstract_not_truncated(self):
        papers = [{"year": 2023, "title": "T", "authors": "A", "abstract": "short text"}]
        result = PaperAgent._build_context(papers)
        assert "short text" in result