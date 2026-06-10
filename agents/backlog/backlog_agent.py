"""
Backlog agent — shows, deletes, and manually executes pending backlog items.
"""
import re
from agents.inbox_trage.queue_writer import QueueWriter

_DELETE_ALL = [
    "모두 삭제", "전체 삭제", "다 삭제", "전부 삭제",
    "모두삭제", "전체삭제", "리스트 모두 삭제", "리스트 삭제",
    "전부 삭제처리", "전체 삭제처리", "모두 삭제처리", "다 삭제처리",
    "모두 지워", "전부 지워", "전체 지워", "다 지워",
]
_EXECUTE_TRIGGERS = ["수행", "처리", "실행"]


def _escape_md(text: str) -> str:
    for ch in ["_", "*", "[", "]", "`"]:
        text = text.replace(ch, f"\\{ch}")
    return text


class BacklogAgent:
    async def handle(self, intent=None) -> str:
        message = intent.raw_message if intent else ""
        queue = QueueWriter()

        # 수동 실행 트리거: "백로그 수행/처리/실행"
        if any(kw in message for kw in _EXECUTE_TRIGGERS):
            return await self._execute_backlog(intent)

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

    async def _execute_backlog(self, intent) -> str:
        from systems.usage_manager import UsageManager
        chat_id = getattr(intent, "chat_id", 0)
        mgr = UsageManager()
        if not mgr.has_budget():
            return "⚠️ Claude 토큰 예산이 부족합니다. 잠시 후 다시 시도해주세요."
        queue = QueueWriter()
        pending = queue.get_pending(limit=10)
        if not pending:
            return "📭 실행할 백로그 항목이 없습니다."
        import asyncio
        from systems.telegram_sender import TelegramSender
        sender = TelegramSender()
        await sender.send(
            chat_id,
            f"⚡ *백로그 수동 실행 시작*\n📋 대기 작업 {len(pending)}건 순차 실행합니다.",
        )
        for item in pending:
            if mgr.has_budget():
                asyncio.create_task(mgr._process_backlog_item(item, chat_id, queue, sender))
            else:
                await sender.send(chat_id, "⚠️ 예산 소진으로 중단했습니다.")
                break
        return f"✅ 백로그 {len(pending)}건 실행 요청 완료."
