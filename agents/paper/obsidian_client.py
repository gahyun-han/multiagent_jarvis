"""
Obsidian client — Obsidian vault에서 .md 노트를 읽고 쓰는 클라이언트.
"""
import os
import re
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

    def find_note(self, query: str) -> Path | None:
        """쿼리 키워드와 가장 일치하는 노트 파일 반환.

        Inbox/ 는 신규 생성 전용이므로 검색 제외.
        매칭 비율(일치 단어 수 / 파일명 단어 수)이 높을수록 우선.
        """
        query_clean = query.lower().replace(".md", "").strip()
        words = [w for w in query_clean.split() if len(w) > 1]
        if not words:
            return None
        inbox = self.vault_path / "Inbox"
        best: Path | None = None
        best_score = 0.0
        for md_file in self.vault_path.glob("**/*.md"):
            try:
                md_file.relative_to(inbox)
                continue  # Inbox 하위 파일 건너뜀
            except ValueError:
                pass
            name = md_file.stem.lower()
            name_words = [w for w in name.split() if len(w) > 1] or [name]
            matches = sum(1 for w in words if w in name)
            if matches == 0:
                continue
            score = matches / len(name_words)
            if score > best_score:
                best_score = score
                best = md_file
        return best if best_score > 0 else None

    def read_note(self, filepath: Path) -> str:
        """노트 전체 내용 반환."""
        return filepath.read_text(encoding="utf-8")

    def search_in_note(self, filepath: Path, query: str) -> list[str]:
        """query 키워드가 포함된 단락 목록 반환."""
        content = filepath.read_text(encoding="utf-8")
        keywords = [w.lower() for w in query.split() if len(w) > 1]
        if not keywords:
            return []
        return [
            s.strip()
            for s in re.split(r"\n{2,}", content)
            if s.strip() and any(kw in s.lower() for kw in keywords)
        ]

    def search_vault(self, query: str, max_results: int = 5) -> list[dict]:
        """vault 전체에서 query가 언급된 파일과 해당 단락 반환."""
        if not self.vault_path or not self.vault_path.exists():
            return []
        keywords = [w.lower() for w in query.split() if len(w) > 1]
        if not keywords:
            return []
        results = []
        for md_file in sorted(self.vault_path.glob("**/*.md")):
            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception:
                continue
            if not any(kw in content.lower() for kw in keywords):
                continue
            matching = [
                s.strip()
                for s in re.split(r"\n{2,}", content)
                if s.strip() and any(kw in s.lower() for kw in keywords)
            ]
            if matching:
                rel = md_file.relative_to(self.vault_path)
                results.append({
                    "filename": md_file.stem,
                    "rel_path": str(rel),
                    "sections": matching[:5],
                })
            if len(results) >= max_results:
                break
        return results

    def append_to_note(self, filepath: Path, content: str) -> Path:
        """기존 노트 파일 끝에 내용 추가."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        existing = filepath.read_text(encoding="utf-8") if filepath.exists() else ""
        separator = "\n\n---\n" if existing.strip() else ""
        filepath.write_text(
            f"{existing}{separator}*{now} 추가*\n\n{content}\n",
            encoding="utf-8",
        )
        return filepath

    def add_note(self, content: str, title: str | None = None, folder: str = "Inbox") -> Path:
        """임의 내용을 vault/folder/ 아래 새 노트로 저장."""
        now = datetime.now()
        if not title:
            first_line = content.split("\n")[0].strip()
            title = first_line[:40] if first_line else now.strftime("%Y-%m-%d %H%M")

        target = self.vault_path / folder
        target.mkdir(parents=True, exist_ok=True)

        filepath = target / (_safe_filename(title) + ".md")
        date_str = now.strftime("%Y-%m-%d %H:%M")
        filepath.write_text(
            f"---\ncreated: {date_str}\n---\n\n# {title}\n\n{content}\n",
            encoding="utf-8",
        )
        return filepath

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
