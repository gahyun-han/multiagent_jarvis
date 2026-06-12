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
_NLM_KWS = ["notebooklm", "노트북lm", "노트북 lm", "nlm에", "nlm으로", "nlm 올려", "nlm에 올려",
            "노트북에 올려", "노트북으로 올려"]
_OBS_WRITE_KWS = ["옵시디언에", "옵시디언 저장", "옵시디언 메모", "옵시디언에 추가", "옵시디언에 적어",
                  "obsidian에", "obsidian 저장"]
# "dt AND rl" 또는 "dt OR agent" 형태 감지
_AND_OR_RE = re.compile(r'([\w-]+)\s+(AND|OR)\s+([\w-]+(?:\s+(?:AND|OR)\s+[\w-]+)*)', re.IGNORECASE)

# "TOPIC 알아봐주고/조사해주고 + 옵시디언에 FILE.md에 추가" 복합 요청
_RESEARCH_SAVE_RE = re.compile(
    r'(.+?)\s+(?:알아봐주고|알아보고|알아봐줘|조사해주고|조사해줘|검색해주고|찾아봐주고)[,\s]+'
    r'(?:옵시디언|obsidian).+?([^\s,/]+\.md)',
    re.IGNORECASE | re.DOTALL,
)

_SYSTEM = """
You are a research assistant for an AI/ML researcher.
You have access to their Zotero library and Obsidian notes.
Reply in Korean unless asked otherwise.
Be concise but insightful. Highlight connections between papers.
""".strip()


def _parse_obs_request(message: str) -> tuple[str | None, str]:
    """메시지에서 (파일 참조, 저장할 내용) 분리.

    패턴 A: "X.md에 CONTENT 추가해줘"  → file_ref=X, content=CONTENT
    패턴 B: "옵시디언에 FILE_DESC 거기에 CONTENT 추가해줘" → file_ref=FILE_DESC, content=CONTENT
    패턴 C: "옵시디언에 CONTENT 추가해줘"  → file_ref=None, content=CONTENT
    """
    # 패턴 A': "옵시디언에 파일명.md에 CONTENT" — .md가 문장 중간에 있는 경우 (A보다 먼저 확인)
    m = re.search(
        r'(?:옵시디언|obsidian)\s*에\s+([^\s,]+?\.md)\s*에\s+(.+?)(?:\s+(?:추가|저장|적어|넣어)\s*해?\s*줘?\.?)?$',
        message, re.IGNORECASE | re.DOTALL,
    )
    if m:
        return m.group(1).replace(".md", "").strip(), _strip_action_suffix(m.group(2) or "")

    # 패턴 A: "파일명.md에 ... 추가/저장/적어줘"
    m = re.match(r'^(.+?\.md)\s*에\s+(.+?)(?:\s+(?:추가|저장|적어|넣어)\s*해?\s*줘?\.?)?$',
                 message, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).replace(".md", "").strip(), _strip_action_suffix(m.group(2))

    # 옵시디언 prefix 제거
    text = re.sub(
        r'^옵시디언\s*(?:에다가|에다|에)?\s*|^obsidian\s*(?:에다가|에다|에)?\s*',
        '', message, flags=re.IGNORECASE,
    ).strip()

    # 패턴 B: "FILE_DESC 거기에 CONTENT 추가해줘"
    m = re.search(r'^(.+?)\s+거기에\s+(.+)', text, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip(), _strip_action_suffix(m.group(2))

    # 패턴 C: 파일 참조 없음
    return None, _strip_action_suffix(text)


def _strip_action_suffix(text: str) -> str:
    text = re.sub(
        r'\s*(?:적어서\s*)?(?:추가|저장|메모|기록)\s*해\s*줘?\s*$|'
        r'\s*적어\s*줘?\s*$|\s*넣어\s*줘?\s*$',
        '', text.strip(), flags=re.IGNORECASE,
    )
    return text.strip().strip('"').strip('"').strip()


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

        # "TOPIC 알아봐주고 + 옵시디언에 FILE.md에 추가" 복합 요청
        m = _RESEARCH_SAVE_RE.search(intent.raw_message)
        if m:
            topic = m.group(1).strip()
            file_ref = m.group(2).replace(".md", "").strip()
            return await self._handle_research_and_save(topic, file_ref)

        # Obsidian 직접 노트 저장
        if any(kw in msg for kw in _OBS_WRITE_KWS):
            return await self._handle_obsidian_write(intent.raw_message)

        # NotebookLM 업로드 — "Domain/robotics NotebookLM에 올려줘"
        if any(kw in msg for kw in _NLM_KWS):
            chat_id = getattr(intent, "chat_id", 0)
            asyncio.create_task(self._bg_notebooklm_upload(intent.raw_message, chat_id))
            return "📓 NotebookLM 업로드를 백그라운드에서 시작합니다.\n완료 시 알림 드릴게요."

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
            result = await claude_ask(prompt, system=_SYSTEM, max_tokens=1024, no_tools=True)
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

    async def _bg_notebooklm_upload(self, raw_message: str, chat_id: int):
        """특정 컬렉션(또는 전체)을 NotebookLM에 업로드 + 분석 질문 + Obsidian 저장."""
        from systems.telegram_sender import TelegramSender
        from agents.paper.notebooklm_uploader import upload_papers
        from agents.paper.obsidian_client import ObsidianClient
        sender = TelegramSender()
        try:
            col_name = self._parse_collection_name(raw_message)
            papers = await asyncio.to_thread(self._get_papers_for_nlm, col_name)

            if not papers:
                label = f"'{col_name}'" if col_name else "전체 라이브러리"
                if chat_id:
                    await sender.send(chat_id, f"⚠️ {label}에서 논문을 찾지 못했습니다.")
                return

            label = f"'{col_name}'" if col_name else "전체 라이브러리"
            notebook_title = f"PaperRadar — {col_name}" if col_name else "PaperRadar — AI/DT 논문"
            added, errors, answer = await asyncio.to_thread(
                upload_papers, papers, notebook_title, True  # ask_question=True
            )
            summary = f"📓 NotebookLM 완료 ({label})\n✅ {added}/{len(papers)}편 추가"
            if errors:
                summary += f"\n⚠️ 오류 {len(errors)}건: {errors[0]}"

            if answer and col_name:
                obs = ObsidianClient()
                try:
                    saved_path = await asyncio.to_thread(
                        obs.save_analysis, col_name, answer, len(papers)
                    )
                    summary += f"\n📝 Obsidian 저장: NotebookLM/{saved_path.parent.name}/{saved_path.name}"
                except Exception as e:
                    logger.error(f"Obsidian save error: {e}")
                    summary += f"\n⚠️ Obsidian 저장 실패: {e}"

            if chat_id:
                await sender.send_plain(chat_id, summary)

            if answer and col_name and chat_id:
                header = f"📊 분석 결과 — {col_name}\n{'─'*30}\n"
                await sender.send_chunks(chat_id, header + answer, chunk_size=3800)
        except Exception as e:
            logger.error(f"bg_notebooklm_upload error: {e}", exc_info=True)
            if chat_id:
                await sender.send(chat_id, f"⚠️ NotebookLM 업로드 오류: {e}")

    async def upload_collection_by_key(self, col_key: str, chat_id: int):
        """컬렉션 키로 직접 NotebookLM 업로드 + 분석 질문 + Obsidian 저장."""
        from systems.telegram_sender import TelegramSender
        from agents.paper.notebooklm_uploader import upload_papers
        from agents.paper.obsidian_client import ObsidianClient
        sender = TelegramSender()
        try:
            col_path, papers = await asyncio.to_thread(self._get_col_path_and_papers, col_key)
            if not papers:
                if chat_id:
                    await sender.send(chat_id, f"⚠️ '{col_path}' 컬렉션에 URL이 있는 논문이 없습니다.")
                return

            if chat_id:
                await sender.send(
                    chat_id,
                    f"📓 *{col_path}* 업로드 + 분석 시작 ({len(papers)}편)…\n"
                    f"소스 처리 후 질문 전송까지 수 분 소요됩니다.",
                )

            notebook_title = f"PaperRadar — {col_path}"
            added, errors, answer = await asyncio.to_thread(
                upload_papers, papers, notebook_title, True  # ask_question=True
            )

            # ── 1. 완료 요약 메시지 (plain text, 안전) ──────────────────
            summary = f"📓 NotebookLM 완료 — {col_path}\n✅ {added}/{len(papers)}편 추가"
            if errors:
                summary += f"\n⚠️ 오류 {len(errors)}건: {errors[0]}"

            if answer:
                obs = ObsidianClient()
                try:
                    saved_path = await asyncio.to_thread(
                        obs.save_analysis, col_path, answer, len(papers)
                    )
                    summary += f"\n📝 Obsidian 저장: NotebookLM/{saved_path.parent.name}/{saved_path.name}"
                except Exception as e:
                    logger.error(f"Obsidian save error: {e}")
                    summary += f"\n⚠️ Obsidian 저장 실패: {e}"
            else:
                summary += "\n⚠️ 분석 결과 없음 (소스 처리 중일 수 있음)"

            if chat_id:
                await sender.send_plain(chat_id, summary)

            # ── 2. 분석 결과 별도 메시지 (1000자씩 청크) ────────────────
            if answer and chat_id:
                header = f"📊 분석 결과 — {col_path}\n{'─'*30}\n"
                await sender.send_chunks(chat_id, header + answer, chunk_size=3800)
        except Exception as e:
            logger.error(f"upload_collection_by_key error: {e}", exc_info=True)
            if chat_id:
                await sender.send(chat_id, f"⚠️ NotebookLM 업로드 오류: {e}")

    def _get_col_path_and_papers(self, col_key: str) -> tuple[str, list[dict]]:
        """컬렉션 키로 경로명 + 논문 목록 반환."""
        zot = self.library.zot
        if not zot:
            return col_key, []
        all_cols = zot.everything(zot.collections())
        col_by_key = {c["data"]["key"]: c["data"] for c in all_cols}
        col_data = col_by_key.get(col_key, {})
        name = col_data.get("name", col_key)
        parent_key = col_data.get("parentCollection", "")
        if parent_key and parent_key in col_by_key:
            col_path = f"{col_by_key[parent_key]['name']}/{name}"
        else:
            col_path = name
        items = zot.everything(zot.collection_items(col_key))
        papers = [
            {"url": i["data"].get("url", ""), "title": i["data"].get("title", "")}
            for i in items
            if i["data"].get("itemType") != "attachment" and i["data"].get("url")
        ]
        return col_path, papers

    async def _handle_research_and_save(self, topic: str, file_ref: str) -> str:
        """TOPIC을 Claude로 조사한 뒤 Obsidian의 file_ref 파일에 추가."""
        _RESEARCH_SYSTEM = """
You are a knowledgeable research assistant. When asked to research a topic,
provide a well-structured Korean summary including: overview, key concepts,
characteristics, and practical applications. Use markdown formatting.
""".strip()
        try:
            research = await claude_ask(
                f"{topic}에 대해 조사해줘. 개념 개요, 핵심 특징, 동작 원리, 활용 사례를 체계적으로 정리해줘.",
                system=_RESEARCH_SYSTEM, max_tokens=2048, no_tools=True,
            )
        except Exception as e:
            return f"⚠️ 조사 중 오류: {e}"

        from agents.paper.obsidian_client import ObsidianClient
        obs = ObsidianClient()
        content_to_save = f"## {topic}\n\n{research}"
        try:
            target = await asyncio.to_thread(obs.find_note, file_ref)
            if target:
                path = await asyncio.to_thread(obs.append_to_note, target, content_to_save)
            else:
                path = await asyncio.to_thread(obs.add_note, content_to_save, topic)
            rel = path.relative_to(obs.vault_path)
            return f"🔍 **{topic}** 조사 완료\n📝 Obsidian 저장: {rel}\n\n{research}"
        except Exception as e:
            logger.error(f"Obsidian save error: {e}")
            return f"🔍 **{topic}** 조사 완료 (Obsidian 저장 실패: {e})\n\n{research}"

    async def _handle_obsidian_write(self, raw_message: str) -> str:
        file_ref, content = _parse_obs_request(raw_message)
        if not content:
            return "⚠️ 옵시디언에 저장할 내용을 찾지 못했습니다."
        from agents.paper.obsidian_client import ObsidianClient
        obs = ObsidianClient()
        try:
            if file_ref:
                target = await asyncio.to_thread(obs.find_note, file_ref)
                if target:
                    path = await asyncio.to_thread(obs.append_to_note, target, content)
                    rel = path.relative_to(obs.vault_path)
                    return f"📝 Obsidian 추가 완료: {rel}"
                # 파일을 못 찾으면 새 파일로 생성
            path = await asyncio.to_thread(obs.add_note, content)
            rel = path.relative_to(obs.vault_path)
            return f"📝 Obsidian 저장 완료: {rel}"
        except Exception as e:
            logger.error(f"Obsidian write error: {e}")
            return f"⚠️ Obsidian 저장 실패: {e}"

    def _parse_collection_name(self, message: str) -> str | None:
        """메시지에서 컬렉션명 추출. 예: 'Domain/robotics NLM 올려줘' → 'Domain/robotics'"""
        # NLM 키워드 앞에 오는 단어/경로 추출
        cleaned = re.sub(
            r'(notebooklm|노트북\s*lm|nlm)[^\w가-힣]*(?:에|으로|에\s*올려|올려|업로드)?',
            '', message, flags=re.IGNORECASE
        ).strip()
        # "올려줘", "업로드해줘" 등 동사 제거
        cleaned = re.sub(r'(올려줘?|업로드\s*해줘?|추가해줘?|넣어줘?|전체|모두|다)', '', cleaned).strip()
        return cleaned if cleaned else None

    def _get_papers_for_nlm(self, col_name: str | None) -> list[dict]:
        """컬렉션명으로 논문 조회. None이면 전체 라이브러리."""
        if not self.library.zot:
            return []
        if not col_name:
            items = self.library.zot.everything(self.library.zot.top())
        else:
            # 컬렉션 키 검색
            all_cols = self.library.zot.everything(self.library.zot.collections())
            col_key = None
            for col in all_cols:
                d = col["data"]
                # "Domain/robotics" 또는 "robotics" 둘 다 매칭
                full_path = d["name"].lower()
                if col_name.lower() in full_path or full_path in col_name.lower():
                    col_key = d["key"]
                    break
            if not col_key:
                return []
            items = self.library.zot.everything(self.library.zot.collection_items(col_key))
        return [
            {"url": i["data"].get("url", ""), "title": i["data"].get("title", "")}
            for i in items
            if i["data"].get("itemType") != "attachment" and i["data"].get("url")
        ]

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
            no_tools=True,
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
