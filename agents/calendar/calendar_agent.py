"""
Calendar agent — natural language → structured action → CalendarStore.
Flow: LLM parses intent → add/query/delete → JSON store.
"""
import json
import logging
import re
from datetime import datetime

from systems.claude_runner import async_ask as claude_ask
from agents.calendar.calendar_store import CalendarStore

logger = logging.getLogger(__name__)

_PARSE_SYSTEM = """
You are a calendar parser for a Korean personal assistant. Today: {now}.
Parse the user message and output ONLY a JSON object (no markdown):
{{
  "action": "add" | "query" | "delete" | "unknown",
  "title": "<event title, Korean OK>",
  "datetime": "<ISO8601 datetime, e.g. 2026-06-01T14:00:00>",
  "notes": "<optional notes>",
  "query_type": "today" | "upcoming" | "date" | "all",
  "date": "<YYYY-MM-DD if query_type=date>",
  "entry_id": "<8-char id if action=delete>"
}}
Rules:
- action=add: user wants to register an event ("추가", "잡아줘", "등록", "일정")
- action=query: user wants to see events ("알려줘", "있어?", "보여줘", "언제", "뭐 있어")
- action=delete: user wants to remove an event ("삭제", "취소", "지워")
- action=unknown: everything else
- For relative dates: 오늘=today, 내일=tomorrow, 모레=day after tomorrow
- If no time given for add, default to 09:00
- Output raw JSON only.
""".strip()

_CHAT_SYSTEM = """
You are a friendly calendar assistant for a Korean user. Reply in Korean, concisely.
""".strip()


class CalendarAgent:
    def __init__(self):
        self.store = CalendarStore()

    async def handle(self, intent) -> str:
        message = intent.raw_message
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        try:
            raw = await claude_ask(message, system=_PARSE_SYSTEM.format(now=now), max_tokens=256)
            raw = re.sub(r"```[a-z]*\n?", "", raw).strip()
            parsed = json.loads(raw)
        except Exception as e:
            logger.warning("Parse failed: %s", e)
            parsed = {"action": "unknown"}

        action = parsed.get("action", "unknown")

        if action == "add":
            return self._add(parsed)
        elif action == "query":
            return self._query(parsed)
        elif action == "delete":
            return self._delete(parsed)
        else:
            reply = await claude_ask(message, system=_CHAT_SYSTEM, max_tokens=256)
            return reply

    def _add(self, parsed: dict) -> str:
        title = parsed.get("title", "무제")
        dt_str = parsed.get("datetime", "")
        notes = parsed.get("notes", "")
        try:
            dt = datetime.fromisoformat(dt_str)
        except Exception:
            dt = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)

        entry = self.store.add_event(title=title, dt=dt.isoformat(), notes=notes)
        dt_display = dt.strftime("%Y년 %m월 %d일 %H:%M")
        return f"일정이 추가되었습니다.\n📅 {title}\n🕐 {dt_display}\nID: {entry['id']}"

    def _query(self, parsed: dict) -> str:
        query_type = parsed.get("query_type", "upcoming")

        if query_type == "today":
            events = self.store.get_today()
            label = "오늘"
        elif query_type == "date":
            date_str = parsed.get("date", "")
            events = self.store.get_by_date(date_str)
            label = date_str
        elif query_type == "all":
            events = self.store.get_all()
            label = "전체"
        else:
            events = self.store.get_upcoming()
            label = "예정된"

        if not events:
            return f"{label} 일정이 없습니다."

        lines = [f"{label} 일정 ({len(events)}건):"]
        for e in events:
            lines.append(f"• [{e['id']}] {e['title']} — {e.get('datetime', '')}")
        return "\n".join(lines)

    def _delete(self, parsed: dict) -> str:
        entry_id = parsed.get("entry_id", "")
        if not entry_id:
            return "삭제할 일정 ID를 알려주세요."

        success = self.store.delete_event(entry_id)
        if success:
            return f"일정이 삭제되었습니다. (ID: {entry_id})"
        return f"해당 ID의 일정을 찾을 수 없습니다. (ID: {entry_id})"