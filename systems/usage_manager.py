"""
Usage manager — tracks Claude token usage within a rolling 5-hour window.
When budget frees up, triggers backlog processing.
"""
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

USAGE_PATH = Path(__file__).resolve().parents[1] / "data" / "token_usage.json"
LOG_PATH = Path(__file__).resolve().parents[1] / "data" / "execution_log.json"

WINDOW_HOURS = 5
DEFAULT_BUDGET = 100_000


class UsageManager:
    def __init__(self):
        self._ensure_files()

    def has_budget(self) -> bool:
        usage = self._load_usage()
        self._evict_old(usage)
        used = sum(e["tokens"] for e in usage["window"])
        budget = usage.get("budget", DEFAULT_BUDGET)
        return used < budget * 0.95

    def record_usage(self, agent: str, tokens_used: int):
        usage = self._load_usage()
        self._evict_old(usage)
        usage["window"].append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "tokens": tokens_used,
        })
        self._save_usage(usage)
        self._append_log(agent, tokens_used)

    def get_status_summary(self) -> str:
        usage = self._load_usage()
        self._evict_old(usage)
        used = sum(e["tokens"] for e in usage["window"])
        budget = usage.get("budget", DEFAULT_BUDGET)
        pct = used / budget * 100
        remaining = budget - used
        bar_filled = int(pct / 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)
        return (
            f"📊 *Claude 토큰 사용 현황 (5h 윈도우)*\n"
            f"`[{bar}]` {pct:.1f}%\n"
            f"사용: {used:,} / {budget:,} 토큰\n"
            f"잔여: {remaining:,} 토큰"
        )

    def trigger_backlog_if_ready(self, chat_id: int):
        if not self.has_budget():
            return
        from agents.inbox_trage.queue_writer import QueueWriter
        import asyncio
        from systems.telegram_sender import TelegramSender
        queue = QueueWriter()
        pending = queue.get_pending(limit=3)
        if not pending:
            return
        sender = TelegramSender()
        for item in pending:
            asyncio.create_task(self._process_backlog_item(item, chat_id, queue, sender))

    async def _process_backlog_item(self, item: dict, chat_id: int, queue, sender):
        from orchestrator.intent_classifier import Intent
        from orchestrator.router import Router
        intent = Intent(
            domain=item["domain"],
            urgency="immediate",
            confidence=1.0,
            summary=item["summary"],
            raw_message=item["message"],
        )
        router = Router()
        await router._dispatch_immediate(intent, chat_id)
        queue.mark_done(item["id"])

    def _evict_old(self, usage: dict):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
        usage["window"] = [
            e for e in usage["window"]
            if datetime.fromisoformat(e["ts"]) > cutoff
        ]

    def _load_usage(self) -> dict:
        if not USAGE_PATH.exists():
            return {"budget": DEFAULT_BUDGET, "window": []}
        try:
            return json.loads(USAGE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {"budget": DEFAULT_BUDGET, "window": []}

    def _save_usage(self, usage: dict):
        USAGE_PATH.write_text(json.dumps(usage, ensure_ascii=False, indent=2), encoding="utf-8")

    def _append_log(self, agent: str, tokens: int):
        try:
            log = []
            if LOG_PATH.exists():
                log = json.loads(LOG_PATH.read_text(encoding="utf-8"))
            log.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "agent": agent,
                "tokens": tokens,
            })
            log = log[-1000:]
            LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Log append error: {e}")

    def _ensure_files(self):
        USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not USAGE_PATH.exists():
            self._save_usage({"budget": DEFAULT_BUDGET, "window": []})
