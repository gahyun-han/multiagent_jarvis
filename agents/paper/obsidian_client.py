"""
Obsidian client — Obsidian vault에서 .md 노트를 읽어오는 클라이언트.
"""
import os
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
