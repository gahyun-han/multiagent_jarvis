"""
Ledger parser — parses natural language expense/income entries into structured records.
"""
import json
import logging
from systems.claude_runner import async_ask as claude_ask

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """
Parse Korean expense/income message(s) into a JSON array.
Each item:
{
  "type": "expense" | "income",
  "amount": <int KRW>,
  "category": one of ["식비", "교통", "쇼핑", "의료", "주거", "문화", "저축", "수입", "기타"],
  "description": "<short description>",
  "date": "YYYY-MM-DD or null if not specified"
}

Date hints: 어제=yesterday, 오늘=today, 그제=2 days ago.
Output ONLY a valid JSON array, even for a single item.
""".strip()


class LedgerParser:
    async def parse(self, message: str) -> dict | None:
        """Parse single entry (legacy). Returns first item or None."""
        entries = await self.parse_many(message)
        return entries[0] if entries else None

    async def parse_many(self, message: str) -> list[dict]:
        """Parse one or more entries. Falls back to regex if API unavailable."""
        from datetime import date, timedelta
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        hint = f"(오늘={today}, 어제={yesterday})"
        try:
            raw = await claude_ask(f"{hint}\n{message}", system=_SYSTEM_PROMPT, max_tokens=512, no_tools=True)
            result = json.loads(raw)
            if isinstance(result, dict):
                return [result]
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.warning(f"LLM parse failed ({e}), falling back to regex")
            return self._regex_parse(message)

    def _regex_parse(self, message: str) -> list[dict]:
        """Regex fallback: parses '설명 금액원' patterns with date hints."""
        import re
        from datetime import date, timedelta

        today = date.today()
        yesterday = today - timedelta(days=1)

        segments: list[tuple[str, str]] = []  # (date_str, text)

        date_pattern = re.compile(
            r'(어제|오늘|그제)\s*[:\-]?\s*[\(（]([^\)）]+)[\)）]'
        )
        found = list(date_pattern.finditer(message))

        if found:
            for m in found:
                label = m.group(1)
                text = m.group(2)
                d = {
                    "어제": yesterday.isoformat(),
                    "오늘": today.isoformat(),
                    "그제": (today - timedelta(days=2)).isoformat(),
                }.get(label, today.isoformat())
                segments.append((d, text))
        else:
            segments.append((today.isoformat(), message))

        _CAT = {
            "식비":   ["밥", "점심", "저녁", "아침", "식사", "음식", "카페", "커피", "배달", "떡볶이", "치킨", "피자", "편의점"],
            "교통":   ["교통", "버스", "지하철", "택시", "주유", "기름", "ktx", "기차"],
            "쇼핑":   ["쇼핑", "옷", "의류", "구매", "마트", "타올", "용품"],
            "문화":   ["영화", "공연", "야구", "콘서트", "게임", "책", "도서"],
            "주거":   ["관리비", "공과금", "전기", "가스", "수도", "월세", "렌트"],
            "의료":   ["병원", "약", "치료", "의료"],
        }

        def _guess_category(desc: str) -> str:
            desc_lower = desc.lower()
            for cat, keywords in _CAT.items():
                if any(k in desc_lower for k in keywords):
                    return cat
            return "기타"

        entries = []
        item_pattern = re.compile(r'([가-힣][가-힣a-zA-Z]*(?:\s+[가-힣a-zA-Z][가-힣a-zA-Z0-9]*)*)\s*([\d,]+)\s*원')

        for date_str, text in segments:
            for m in item_pattern.finditer(text):
                desc = m.group(1).strip()
                amount_str = m.group(2).replace(",", "")
                try:
                    amount = int(amount_str)
                except ValueError:
                    continue
                if amount <= 0 or not desc:
                    continue
                entries.append({
                    "type": "expense",
                    "amount": amount,
                    "category": _guess_category(desc),
                    "description": desc,
                    "date": date_str,
                })

        return entries

    @staticmethod
    def format_amount(amount: int) -> str:
        return f"{amount:,}원"