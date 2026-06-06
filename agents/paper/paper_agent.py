"""
Paper agent — fetches papers from Zotero/Obsidian and produces summaries,
trend analysis, and similarity comparisons.
"""
import asyncio
import json
import logging
import re
from pathlib import Path

from systems.claude_runner import async_ask as claude_ask
from agents.paper.zotero_client import ZoteroClient, TAG_TO_COLLECTION

logger = logging.getLogger(__name__)

SENT_PAPERS_PATH = Path(__file__).resolve().parents[2] / "data" / "sent_papers.json"
EXEC_LOG_PATH = Path(__file__).resolve().parents[2] / "data" / "execution_log.json"

_STATUS_KEYWORDS = ["결과", "됐어", "성공", "실패", "돌았어", "실행됐어", "paperradar", "논문레이더"]
_COLLECT_SYNC_KWS = ["컬렉션 동기화", "컬렉션 생성", "컬렉션 정리", "컬렉션 업데이트",
                     "collection sync", "태그로 컬렉션"]
_LANDSCAPE_KWS   = ["landscape", "라이브러리 분석", "논문 통계", "논문 현황",
                    "저자 통계", "태그 통계", "연도별 논문"]
_TAG_SEARCH_KWS = ["태그 검색", "태그로 찾", "태그 조합", "태그 필터"]
# "dt AND rl" 또는 "dt OR agent" 형태 감지
_AND_OR_RE = re.compile(r'([\w-]+)\s+(AND|OR)\s+([\w-]+(?:\s+(?:AND|OR)\s+[\w-]+)*)', re.IGNORECASE)

_SYSTEM = """
You are a research assistant for an AI/ML researcher.
You have access to their Zotero library and Obsidian notes.
Reply in Korean unless asked otherwise.
Be concise but insightful. Highlight connections between papers.
""".strip()


def _load_sent_keys() -> set:
    if SENT_PAPERS_PATH.exists():
        try:
            return set(json.loads(SENT_PAPERS_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    return set()


def _save_sent_keys(keys: set):
    SENT_PAPERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SENT_PAPERS_PATH.write_text(json.dumps(list(keys), ensure_ascii=False), encoding="utf-8")


class PaperAgent:
    def __init__(self):
        self.library = ZoteroClient()

    async def handle(self, intent) -> str:
        msg = intent.raw_message.lower()

        # PaperRadar 실행 결과 조회
        if any(kw in msg for kw in _STATUS_KEYWORDS):
            status = self._paperradar_status()
            if status:
                return status

        # 라이브러리 분석 / landscape
        if any(kw in msg for kw in _LANDSCAPE_KWS):
            return await asyncio.to_thread(self.library.build_landscape)

        # 컬렉션 동기화 — 논문 수가 많아 백그라운드 실행 후 완료 시 Telegram 알림
        if any(kw in msg for kw in _COLLECT_SYNC_KWS):
            chat_id = getattr(intent, "chat_id", 0)
            asyncio.create_task(self._bg_sync_collections(chat_id))
            return "🔄 컬렉션 동기화를 백그라운드에서 시작했습니다.\n논문 수가 많아 수 분 소요될 수 있습니다. 완료 시 알림 드릴게요."

        # 태그 검색 — "태그 검색 dt AND rl" 또는 "dt AND rl" 직접 입력
        raw = intent.raw_message
        tag_query_str: str | None = None
        if any(kw in msg for kw in _TAG_SEARCH_KWS):
            tag_query_str = re.sub(
                r'태그\s*(?:검색|로\s*찾\w*|조합|필터)\s*', '', raw, flags=re.IGNORECASE
            ).strip()
        elif _AND_OR_RE.search(raw):
            tag_query_str = raw.strip()

        if tag_query_str:
            ao = re.search(r'\b(AND|OR)\b', tag_query_str, re.IGNORECASE)
            operator = ao.group(1).upper() if ao else "AND"
            tags = [t.strip() for t in re.split(r'\b(?:AND|OR)\b', tag_query_str, flags=re.IGNORECASE) if t.strip()]
            tags = [t for t in tags if t]  # 빈 문자열 제거
            if tags:
                papers = await asyncio.to_thread(self.library.search_by_tags, tags, operator)
                return self._format_tag_search(tags, operator, papers)

        all_papers = self.library.get_recent_papers(limit=20)
        sent_keys = _load_sent_keys()
        papers = [p for p in all_papers if p.get("key") not in sent_keys]

        if not papers:
            return "📄 새로운 논문이 없습니다. (이미 전송한 논문만 있음)"

        context = self._build_context(papers)
        try:
            prompt = f"내 라이브러리 최근 논문 ({len(papers)}편, 신규):\n{context}\n\n요청: {intent.raw_message}"
            result = await claude_ask(prompt, system=_SYSTEM, max_tokens=1024)
            sent_keys.update(p["key"] for p in papers if p.get("key"))
            _save_sent_keys(sent_keys)
            return result
        except Exception as e:
            logger.error(f"PaperAgent error: {e}")
            return f"📄 논문 처리 중 오류: {e}"

    async def _bg_sync_collections(self, chat_id: int):
        """컬렉션 동기화를 백그라운드 스레드에서 실행하고 완료 시 Telegram 알림."""
        from systems.telegram_sender import TelegramSender
        sender = TelegramSender()
        try:
            result = await asyncio.to_thread(self.library.sync_collections_from_tags)
            if chat_id:
                await sender.send(chat_id, f"✅ 컬렉션 동기화 완료\n\n{result}")
        except Exception as e:
            logger.error(f"bg_sync_collections error: {e}", exc_info=True)
            if chat_id:
                await sender.send(chat_id, f"⚠️ 컬렉션 동기화 오류: {e}")

    async def summarize_all(self) -> str:
        all_papers = self.library.get_recent_papers(limit=20)
        sent_keys = _load_sent_keys()
        papers = [p for p in all_papers if p.get("key") not in sent_keys]

        if not papers:
            return "📚 새로운 논문이 없습니다."

        context = self._build_context(papers)
        result = await claude_ask(
            f"다음 논문들의 트렌드, 공통점, 차이점을 분석해줘:\n{context}",
            system=_SYSTEM,
            max_tokens=2048,
        )
        sent_keys.update(p["key"] for p in papers if p.get("key"))
        _save_sent_keys(sent_keys)
        return result

    @staticmethod
    def _paperradar_status() -> str | None:
        """execution_log.json에서 최근 PaperRadar 실행 결과를 읽어 반환."""
        if not EXEC_LOG_PATH.exists():
            return None
        try:
            log = json.loads(EXEC_LOG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return None

        runs = [e for e in log if e.get("agent") == "PaperRadar" and e.get("event") == "run"]
        if not runs:
            return None

        last = runs[-1]
        from datetime import datetime, timezone
        ts = datetime.fromisoformat(last["ts"]).astimezone()
        ts_str = ts.strftime("%m/%d %H:%M")
        icon = "✅" if last.get("success") else "❌"
        sent = last.get("papers_sent", 0)
        zotero = last.get("zotero_added", 0)
        errors = last.get("errors", [])

        lines = [f"{icon} *PaperRadar 최근 실행* ({ts_str})"]
        if sent == 0:
            lines.append("📄 새로운 논문 없음")
        else:
            lines.append(f"📨 논문 {sent}편 발송 (paperSearch_bot)")
            lines.append(f"📚 Zotero {zotero}편 추가")
        if errors:
            lines.append(f"⚠️ 오류: {'; '.join(errors[:2])}")
        return "\n".join(lines)

    @staticmethod
    def _format_tag_search(tags: list[str], operator: str, papers: list[dict]) -> str:
        tags_str = f" {operator} ".join(t.upper() for t in tags)
        if not papers:
            return f"🔍 태그 조건에 맞는 논문이 없습니다: `{tags_str}`"
        lines = [f"🔍 *태그 검색결과* [{tags_str}] — {len(papers)}편\n"]
        for i, p in enumerate(papers, 1):
            tag_str = ""
            if p.get("tags"):
                tag_str = "  `" + "` `".join(p["tags"][:6]) + "`"
            lines.append(f"{i}. [{p['year']}] {p['title'][:70]}\n   👤 {p['authors'][:40]}{tag_str}")
        return "\n".join(lines)

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
