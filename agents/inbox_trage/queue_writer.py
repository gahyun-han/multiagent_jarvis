"""
Queue writer — persists backlog items to backlog_queue.json and reads them back.
"""
import json
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

QUEUE_PATH = Path(__file__).resolve().parents[2] / "data" / "backlog_queue.json"


class QueueWriter:
    def write(self, message: str, summary: str, domain: str, category: str, priority: int) -> dict:
        queue = self._load()
        entry = {
            "id": str(uuid.uuid4())[:8],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "message": message,
            "summary": summary,
            "domain": domain,
            "category": category,
            "priority": priority,
            "status": "pending",
        }
        queue.append(entry)
        # Keep max 100 entries, drop lowest-priority pending ones if over limit
        pending = [e for e in queue if e["status"] == "pending"]
        if len(pending) > 100:
            pending.sort(key=lambda e: e["priority"], reverse=True)
            keep_ids = {e["id"] for e in pending[:100]}
            queue = [e for e in queue if e["status"] != "pending" or e["id"] in keep_ids]
        self._save(queue)
        return entry

    def get_pending(self, limit: int = 10) -> list[dict]:
        queue = self._load()
        pending = [e for e in queue if e["status"] == "pending"]
        pending.sort(key=lambda e: e["priority"], reverse=True)
        return pending[:limit]

    def mark_done(self, entry_id: str):
        queue = self._load()
        for entry in queue:
            if entry["id"] == entry_id:
                entry["status"] = "done"
                entry["completed_at"] = datetime.now(timezone.utc).isoformat()
        self._save(queue)

    def _load(self) -> list:
        if not QUEUE_PATH.exists():
            return []
        try:
            return json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save(self, queue: list):
        QUEUE_PATH.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
