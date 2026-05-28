"""
Finance agent — comprehensive asset management: ledger, savings, loans.
"""
import os
import json
import logging
from pathlib import Path
import anthropic
from dotenv import load_dotenv
from agents.finance.ledger_parser import LedgerParser
from agents.finance.savings_tracker import SavingsTracker
from agents.finance.asset_manager import AssetManager

load_dotenv()
logger = logging.getLogger(__name__)

LEDGER_PATH = Path(__file__).resolve().parents[2] / "data" / "ledger.json"

_SYSTEM_PROMPT = """
You are a personal finance assistant for a Korean user.
Reply in Korean. Be concise and practical.
Help with: expense tracking, budget analysis, savings goals, loan management, asset tracking.
When showing amounts, always format as Korean won (원).
""".strip()

_ASSET_PARSE_PROMPT = """
Extract ALL asset items from the user's message and return ONLY a JSON object (no markdown, no explanation).

Rules:
- 통장/계좌/증권계좌 → "accounts": [{"name": str, "balance": int, "type": "checking|savings|parking|investment"}]
- 적금 → "savings": [{"name": str, "balance": int, "monthly": int|null, "interest_rate": float|null, "maturity_date": "YYYY-MM-DD"|null}]
- 대출 → "loans": [{"name": str, "remaining": int, "interest_rate": float|null, "monthly_payment": int|null, "maturity_date": "YYYY-MM-DD"|null}]
- 부동산 → "real_estate": [{"name": str, "value": int, "address": str|null}]

Amount parsing: "10,298,500원" or "10298500원" → 10298500 (integer, no commas)
삼성증권_국내/ISA/해외 → type "investment"
파킹통장 → type "parking"
Omit keys with empty arrays.
Output raw JSON only, starting with {
""".strip()


class FinanceAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))
        self.model = "claude-sonnet-4-6"
        self.parser = LedgerParser()
        self.savings = SavingsTracker()
        self.assets = AssetManager()

    async def handle(self, intent) -> str:
        message = intent.raw_message

        # 자산 목록 추가/업데이트 감지
        asset_keywords = ["자산 목록", "통장 추가", "계좌 추가", "잔액 추가", "자산 추가", "자산목록",
                          "적금 추가", "대출 추가", "부동산 추가"]
        if any(kw in message for kw in asset_keywords) or (
            "추가" in message and any(w in message for w in ["통장", "계좌", "자산", "적금", "대출", "부동산"])
        ):
            return await self._handle_asset_update(message)

        # 단건 지출/수입 기록
        entry = self.parser.parse(message)
        if entry and entry.get("amount"):
            self._save_entry(entry)
            type_label = "지출" if entry["type"] == "expense" else "수입"
            return (
                f"💳 {type_label} 기록 완료\n"
                f"금액: {LedgerParser.format_amount(entry['amount'])}\n"
                f"카테고리: {entry['category']}\n"
                f"내용: {entry['description']}"
            )

        context = self._build_context()
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=512,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": f"재무 현황:\n{context}\n\n질문: {message}"}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.error(f"FinanceAgent error: {e}")
            return f"💰 재무 처리 중 오류: {e}"

    async def _handle_asset_update(self, message: str) -> str:
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=_ASSET_PARSE_PROMPT,
                messages=[{"role": "user", "content": message}],
            )
            raw = response.content[0].text.strip()
            logger.info(f"Asset parse raw response: {raw[:300]}")

            # 마크다운 펜스 제거
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            data = json.loads(raw)

            total_added = 0
            for category in ("accounts", "savings", "loans", "real_estate"):
                items = data.get(category, [])
                if items:
                    self.assets.upsert(category, items)
                    total_added += len(items)

            if total_added == 0:
                return "⚠️ 저장할 자산 항목을 찾지 못했습니다."

            return f"💰 *자산 업데이트 완료* ({total_added}건)\n\n" + self.assets.net_worth_summary()
        except json.JSONDecodeError as e:
            logger.error(f"Asset JSON parse error: {e} | raw: {raw[:200]}")
            return "⚠️ 자산 목록 파싱에 실패했습니다. 형식을 확인해주세요."
        except Exception as e:
            logger.error(f"Asset update error: {e}", exc_info=True)
            return f"⚠️ 자산 업데이트 오류: {e}"

    def _build_context(self) -> str:
        ledger = self._load_ledger()
        savings_summary = self.savings.get_summary()
        recent = ledger[-10:] if ledger else []
        lines = [savings_summary, "\n최근 거래:"]
        for e in recent:
            sign = "-" if e["type"] == "expense" else "+"
            lines.append(f"  {sign}{e['amount']:,}원 [{e['category']}] {e['description']}")
        return "\n".join(lines)

    def _save_entry(self, entry: dict):
        ledger = self._load_ledger()
        ledger.append(entry)
        LEDGER_PATH.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_ledger(self) -> list:
        if not LEDGER_PATH.exists():
            return []
        try:
            return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
