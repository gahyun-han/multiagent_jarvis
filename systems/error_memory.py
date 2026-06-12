"""
Error memory — Dreaming 패턴 기반 에러 메모리.
에러 패턴을 data/error_memory.json에 저장하고,
같은 context에서 반복되는 에러를 에이전트 프롬프트에 주입한다.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_MEMORY_PATH = Path(__file__).parent.parent / "data" / "error_memory.json"
_MAX_ENTRIES = 50
_MAX_RELEVANT = 5


class ErrorMemory:
    def save(self, error_type: str, context: str, solution: str) -> None:
        """에러 처리 결과 저장. 동일 error_type+context 조합은 count만 증가."""
        entries = self._load_all()
        for entry in entries:
            if entry["error_type"] == error_type and entry["context"] == context:
                entry["count"] += 1
                entry["last_seen"] = _now()
                entry["solution"] = solution
                self._save_all(entries)
                return
        entries.append({
            "error_type": error_type,
            "context": context,
            "solution": solution,
            "count": 1,
            "last_seen": _now(),
        })
        if len(entries) > _MAX_ENTRIES:
            entries.sort(key=lambda e: e["last_seen"])
            entries = entries[len(entries) - _MAX_ENTRIES:]
        self._save_all(entries)

    def load_relevant(self, context: str) -> list[dict]:
        """context와 일치하거나 포함 관계인 과거 에러 패턴 반환 (최대 5개, 빈도 순)."""
        entries = self._load_all()
        relevant = [
            e for e in entries
            if e["context"] == context
            or context in e["context"]
            or e["context"] in context
        ]
        relevant.sort(key=lambda e: e["count"], reverse=True)
        return relevant[:_MAX_RELEVANT]

    def to_prompt_str(self, entries: list[dict] | None = None) -> str:
        """에이전트 프롬프트에 주입할 문자열. entries 미지정 시 전체 메모리 사용."""
        if entries is None:
            entries = self._load_all()
        if not entries:
            return ""
        lines = ["[과거 에러 패턴 — 참고용]"]
        for e in entries:
            lines.append(
                f"- [{e['error_type']}] context={e['context']}: "
                f"{e['solution']} (발생 {e['count']}회, 마지막: {e['last_seen'][:10]})"
            )
        return "\n".join(lines)

    def _load_all(self) -> list[dict]:
        if not _MEMORY_PATH.exists():
            return []
        try:
            return json.loads(_MEMORY_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to load error memory: {e}")
            return []

    def _save_all(self, entries: list[dict]) -> None:
        try:
            _MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            _MEMORY_PATH.write_text(
                json.dumps(entries, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"Failed to save error memory: {e}")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
