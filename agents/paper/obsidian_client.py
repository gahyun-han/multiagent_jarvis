"""
Obsidian client — Obsidian vault에서 .md 노트를 읽고 쓰는 클라이언트.
"""
import os
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class ObsidianClient:
    def __init__(self):
        self.vault_path = Path(os.getenv("OBSIDIAN_VAULT_PATH", ""))

    def get_notes(self, subfolder: str = "papers") -> list[dict]:
        """vault_path/subfolder 아래 .md 파일을 재귀적으로 읽어 반환."""
        notes = []
        target = self.vault_path / subfolder
        if not target.exists():
            return notes
        for md_file in target.glob("**/*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                notes.append({"filename": md_file.name, "content": content[:2000]})
            except Exception:
                pass
        return notes

    def save_analysis(
        self,
        collection_path: str,
        answer: str,
        paper_count: int = 0,
    ) -> Path:
        """NotebookLM 분석 결과를 Obsidian에 저장.

        저장 위치: vault/NotebookLM/{collection_path}.md
        collection_path 예: "Method/digital_twin + llm + multi_agent + rag"
        """
        from agents.paper.notebooklm_uploader import ANALYSIS_QUESTION

        # 컬렉션 경로를 파일명으로 변환 (슬래시 → 하위 폴더)
        parts = collection_path.replace("\\", "/").split("/", 1)
        if len(parts) == 2:
            folder = self.vault_path / "NotebookLM" / parts[0]
            filename = _safe_filename(parts[1]) + ".md"
        else:
            folder = self.vault_path / "NotebookLM"
            filename = _safe_filename(parts[0]) + ".md"

        folder.mkdir(parents=True, exist_ok=True)
        filepath = folder / filename

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        count_str = f"{paper_count}편" if paper_count else "전체"

        content = f"""---
collection: {collection_path}
papers: {count_str}
analyzed: {now}
source: NotebookLM
---

# {collection_path}

> **분석 기준**: {now} ({count_str})

## 질문

{ANALYSIS_QUESTION}

---

## 분석 결과

{answer}
"""
        filepath.write_text(content, encoding="utf-8")
        return filepath


def _safe_filename(name: str) -> str:
    """파일명에 사용할 수 없는 문자 제거."""
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip()
