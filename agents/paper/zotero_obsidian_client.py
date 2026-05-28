"""
Zotero & Obsidian client — fetches paper metadata from Zotero and notes from Obsidian vault.
"""
import os
import logging
from pathlib import Path
from pyzotero import zotero
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class ZoteroObsidianClient:
    def __init__(self):
        api_key = os.getenv("ZOTERO_API_KEY")
        user_id = os.getenv("ZOTERO_USER_ID")
        self.vault_path = Path(os.getenv("OBSIDIAN_VAULT_PATH", ""))
        if api_key and user_id:
            self.zot = zotero.Zotero(user_id, "user", api_key)
        else:
            self.zot = None
            logger.warning("Zotero credentials not set — paper features limited")

    def get_recent_papers(self, limit: int = 20) -> list[dict]:
        if not self.zot:
            return []
        try:
            items = self.zot.top(limit=limit, itemType="journalArticle || conferencePaper || preprint")
            return [self._parse_item(i) for i in items]
        except Exception as e:
            logger.error(f"Zotero fetch error: {e}")
            return []

    def search_papers(self, query: str, limit: int = 10) -> list[dict]:
        if not self.zot:
            return []
        try:
            items = self.zot.items(q=query, limit=limit)
            return [self._parse_item(i) for i in items]
        except Exception as e:
            logger.error(f"Zotero search error: {e}")
            return []

    def get_obsidian_notes(self, subfolder: str = "papers") -> list[dict]:
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

    @staticmethod
    def _parse_item(item: dict) -> dict:
        data = item.get("data", {})
        creators = data.get("creators", [])
        authors = ", ".join(
            f"{c.get('lastName', '')} {c.get('firstName', '')}".strip()
            for c in creators[:3]
        )
        return {
            "title": data.get("title", "Unknown"),
            "authors": authors,
            "year": data.get("date", "")[:4],
            "abstract": data.get("abstractNote", "")[:500],
            "key": data.get("key", ""),
            "url": data.get("url", ""),
        }
