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

load_dotenv()
logger = logging.getLogger(__name__)

LEDGER_PATH = Path(__file__).resolve().parents[2] / "data" / "ledger.json"

_SYSTEM_PROMPT = """
You are a personal finance assistant for a Korean user.
Reply in Korean. Be concise and practical.
Help with: expense tracking, budget analysis, savings goals, loan management.
When showing amounts, always format as Korean won (원).
""".strip()


class FinanceAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))
        self.model = "claude-sonnet-4-6"
        self.parser = LedgerParser()
        self.savings = SavingsTracker()

    async def handle(self, intent) -> str:
        message = intent.raw_message
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
