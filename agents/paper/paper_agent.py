"""
Paper agent — fetches papers from Zotero/Obsidian and produces summaries,
trend analysis, and similarity comparisons via Claude.
"""
import os
import json
import logging
import anthropic
from dotenv import load_dotenv
from agents.paper.zotero_obsidian_client import ZoteroObsidianClient

load_dotenv()
logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """
You are a research assistant for an AI/ML researcher.
You have access to their Zotero library and Obsidian notes.
Reply in Korean unless asked otherwise.
Be concise but insightful. Highlight connections between papers.
""".strip()


class PaperAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))
        self.model = "claude-sonnet-4-6"
        self.library = ZoteroObsidianClient()

    async def handle(self, intent) -> str:
        message = intent.raw_message
        papers = self.library.get_recent_papers(limit=20)
        context = self._build_context(papers)
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=_SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": f"내 라이브러리 최근 논문:\n{context}\n\n요청: {message}"},
                ],
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.error(f"PaperAgent error: {e}")
            return f"📄 논문 처리 중 오류: {e}"

    async def summarize_all(self) -> str:
        papers = self.library.get_recent_papers(limit=20)
        if not papers:
            return "📚 Zotero 라이브러리에서 논문을 가져오지 못했습니다."
        context = self._build_context(papers)
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"다음 논문들의 트렌드, 공통점, 차이점을 분석해줘:\n{context}"}],
        )
        return response.content[0].text.strip()

    @staticmethod
    def _build_context(papers: list[dict]) -> str:
        if not papers:
            return "(논문 없음)"
        lines = []
        for i, p in enumerate(papers, 1):
            lines.append(f"{i}. [{p['year']}] {p['title']} — {p['authors']}")
            if p["abstract"]:
                lines.append(f"   초록: {p['abstract'][:200]}")
        return "\n".join(lines)
