"""
Backlog agent — shows, deletes pending backlog items.
"""
import re
from agents.inbox_trage.queue_writer import QueueWriter

_DELETE_ALL = [
    "모두 삭제", "전체 삭제", "다 삭제", "전부 삭제",
    "모두삭제", "전체삭제", "리스트 모두 삭제", "리스트 삭제",
    "전부 삭제처리", "전체 삭제처리", "모두 삭제처리", "다 삭제처리",
    "모두 지워", "전부 지워", "전체 지워", "다 지워",
]


def _escape_md(text: str) -> str:
    for ch in ["_", "*", "[", "]", "`"]:
        text = text.replace(ch, f"\\{ch}")
    return text


class BacklogAgent:
    async def handle(self, intent=None) -> str:
        message = intent.raw_message if intent else ""
        queue = QueueWriter()

        # 전체 삭제
        if any(kw in message for kw in _DELETE_ALL):
            count = queue.delete_all_pending()
            return f"🗑️ 백로그 {count}건 전체 삭제 완료." if count else "📭 삭제할 항목이 없습니다."

        # ID 개별 삭제: "백로그 a8bc44ad 삭제"
        id_match = re.search(r'\b([0-9a-f]{8})\b', message)
        if id_match and "삭제" in message:
            entry_id = id_match.group(1)
            ok = queue.delete_by_id(entry_id)
            return f"🗑️ ID `{entry_id}` 삭제 완료." if ok else f"⚠️ ID `{entry_id}` 항목을 찾을 수 없습니다."

        # 목록 조회
        pending = queue.get_pending(limit=20)
        if not pending:
            return "📭 백로그가 비어 있습니다."
        lines = [f"📋 *백로그 ({len(pending)}건)*\n"]
        for i, item in enumerate(pending, 1):
            label = "🔴" if item["priority"] >= 8 else "🟡" if item["priority"] >= 5 else "🟢"
            summary = _escape_md(item["summary"][:80])
            lines.append(
                f"{i}. {label} [{item['domain']}] {summary}\n"
                f"   ID: `{item['id']}` | 우선순위: {item['priority']}/10"
            )
        return "\n".join(lines)
