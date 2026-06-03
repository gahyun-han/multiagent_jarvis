"""
Calendar store — local JSON persistence for schedule entries.
"""
import json
import uuid
import logging
from datetime import datetime, timezone, date
from pathlib import Path

logger = logging.getLogger(__name__)

STORE_PATH = Path(__file__).resolve().parents[2] / "data" / "calendar.json"


class CalendarStore:
    # ------------------------------------------------------------------ #
    #  Write                                                               #
    # ------------------------------------------------------------------ #

    def add(self, title: str, dt: str, notes: str = "") -> dict:
        entries = self._load()
        entry = {
            "id": str(uuid.uuid4())[:8],
            "title": title,
            "datetime": dt,          # ISO8601 string
            "notes": notes,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        entries.append(entry)
        self._save(entries)
        return entry

    def delete(self, entry_id: str) -> bool:
        entries = self._load()
        new = [e for e in entries if e["id"] != entry_id]
        if len(new) == len(entries):
            return False
        self._save(new)
        return True

    # ------------------------------------------------------------------ #
    #  Read                                                                #
    # ------------------------------------------------------------------ #

    def get_all(self) -> list[dict]:
        return self._load()

    def get_today(self) -> list[dict]:
        today = date.today().isoformat()
        return [e for e in self._load() if e.get("datetime", "").startswith(today)]

    def get_upcoming(self, days: int = 7) -> list[dict]:
        from datetime import timedelta
        now = datetime.now()
        cutoff = now + timedelta(days=days)
        result = []
        for e in self._load():
            try:
                dt = datetime.fromisoformat(e["datetime"])
                if now <= dt <= cutoff:
                    result.append(e)
            except Exception:
                pass
        return sorted(result, key=lambda e: e["datetime"])

    def get_by_date(self, date_str: str) -> list[dict]:
        """date_str: YYYY-MM-DD"""
        return [e for e in self._load() if e.get("datetime", "").startswith(date_str)]

    # ------------------------------------------------------------------ #
    #  Formatting                                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def format_entry(e: dict) -> str:
        try:
            dt = datetime.fromisoformat(e["datetime"])
            dt_str = dt.strftime("%m/%d %H:%M")
        except Exception:
            dt_str = e.get("datetime", "?")
        notes = f" — {e['notes']}" if e.get("notes") else ""
        return f"• `{e['id']}` {dt_str} *{e['title']}*{notes}"

    def format_list(self, entries: list[dict]) -> str:
        if not entries:
            return "등록된 일정이 없습니다."
        return "\n".join(self.format_entry(e) for e in entries)

    # ------------------------------------------------------------------ #
    #  Internal                                                            #
    # ------------------------------------------------------------------ #

    def _load(self) -> list[dict]:
        if not STORE_PATH.exists():
            return []
        try:
            return json.loads(STORE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save(self, entries: list[dict]):
        STORE_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
