"""
Finance agent — comprehensive asset management: ledger, savings, loans.
"""
import json
import logging
from pathlib import Path
from systems.claude_runner import async_ask as claude_ask
from agents.finance.ledger_parser import LedgerParser
from agents.finance.savings_tracker import SavingsTracker
from agents.finance.asset_manager import AssetManager
from agents.finance.monthly_summary import get_monthly_summary, get_monthly_graph, get_category_detail
from agents.finance.report_generator import generate_monthly_report
from agents.finance.sms_parser import parse_and_save

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
- 통장/계좌/증권계좌(계좌 잔액 전체) → "accounts": [{"name": str, "balance": int, "type": "checking|savings|parking|investment"}]
- 적금 → "savings": [{"name": str, "balance": int, "monthly": int|null, "interest_rate": float|null, "maturity_date": "YYYY-MM-DD"|null}]
- 대출 → "loans": [{"name": str, "remaining": int, "interest_rate": float|null, "monthly_payment": int|null, "maturity_date": "YYYY-MM-DD"|null}]
- 부동산 → "real_estate": [{"name": str, "value": int, "address": str|null}]
- 주식/ETF/펀드 종목별 → "stocks": [{"name": str, "ticker": str|null, "quantity": float|null, "avg_price": int|null, "current_price": int|null, "total_value": int}]

Amount parsing: "10,298,500원" or "10298500원" → 10298500 (integer, no commas)
삼성증권_국내/ISA/해외 → accounts, type "investment"
파킹통장 → accounts, type "parking"
주식 종목(삼성전자, AAPL 등) 개별 언급 → stocks
"올랐어/내렸어/바뀌었어" → parse the new value and update that item
Omit keys with empty arrays.
Output raw JSON only, starting with {
""".strip()


class FinanceAgent:
    def __init__(self):
        self.parser = LedgerParser()
        self.savings = SavingsTracker()
        self.assets = AssetManager()

    async def handle(self, intent) -> str:
        message = intent.raw_message

        # 월별 리포트 / 자산 현황
        if any(kw in message for kw in ["월별 리포트", "자산 현황", "월간 리포트", "자산리포트", "월리포트"]):
            import re
            m = re.search(r'(\d{4}[-/]\d{2})', message)
            target_month = m.group(1).replace("/", "-") if m else None
            return generate_monthly_report(target_month)

        # 카드 문자 파싱
        if "카드 문자" in message or "카드문자" in message:
            return await self._handle_sms(message)

        # 월별 그래프 (복수 개월 비교)
        if any(kw in message for kw in ["월별 그래프", "월그래프", "월별그래프", "월별 비교", "지출 비교"]):
            months = 3
            for w in message.split():
                if w.isdigit():
                    months = min(int(w), 12)
            return get_monthly_graph(months)

        # 월별 요약
        if any(kw in message for kw in ["월별 요약", "이번달 요약", "이번 달 요약", "월 요약", "가계부 요약",
                                         "지출 요약", "수입 요약", "월별 정리", "가계부 정리"]):
            import re
            m = re.search(r"(\d{4}[-/]\d{2})", message)
            target_month = m.group(1).replace("/", "-") if m else None
            return get_monthly_summary(target_month)

        # 카테고리 상세
        categories = ["식비", "교통", "쇼핑", "의료", "주거", "문화", "저축", "기타"]
        for cat in categories:
            if cat in message and any(kw in message for kw in ["상세", "내역", "항목"]):
                import re
                m = re.search(r"(\d{4}[-/]\d{2})", message)
                target_month = m.group(1).replace("/", "-") if m else None
                return get_category_detail(cat, target_month)

        # 자산 추가/수정 감지 — "추가" 또는 업데이트 동사
        _ASSET_NOUNS = ["통장", "계좌", "자산", "적금", "대출", "부동산", "주식", "종목", "아파트", "집값"]
        _UPDATE_VERBS = ["추가", "수정", "변경", "업데이트", "바뀌었", "올랐", "내렸", "갱신", "수정해", "바꿔"]
        asset_keywords = ["자산 목록", "자산목록", "잔액 추가", "부동산 추가",
                          "주식 추가", "주식 수정", "주식 업데이트", "종목 추가", "종목 수정"]
        if any(kw in message for kw in asset_keywords) or (
            any(v in message for v in _UPDATE_VERBS)
            and any(n in message for n in _ASSET_NOUNS)
        ):
            return await self._handle_asset_update(message)

        # 단건/다건 지출·수입 기록
        entries = await self.parser.parse_many(message)
        if entries and all(e.get("amount") for e in entries):
            for e in entries:
                self._save_entry(e)
            if len(entries) == 1:
                e = entries[0]
                type_label = "지출" if e["type"] == "expense" else "수입"
                return (
                    f"💳 {type_label} 기록 완료\n"
                    f"금액: {LedgerParser.format_amount(e['amount'])}\n"
                    f"카테고리: {e['category']}\n"
                    f"내용: {e['description']}"
                )
            lines = [f"💳 {len(entries)}건 기록 완료"]
            total = sum(e["amount"] for e in entries if e["type"] == "expense")
            for e in entries:
                icon = "💸" if e["type"] == "expense" else "💰"
                date_str = f" ({e['date']})" if e.get("date") else ""
                lines.append(f"{icon} {e['description']}{date_str}: {LedgerParser.format_amount(e['amount'])}")
            lines.append(f"─────────\n합계 지출: {LedgerParser.format_amount(total)}")
            return "\n".join(lines)

        context = self._build_context()
        try:
            return await claude_ask(
                f"재무 현황:\n{context}\n\n질문: {message}",
                system=_SYSTEM_PROMPT,
                max_tokens=512,
                no_tools=True,
            )
        except Exception as e:
            logger.error(f"FinanceAgent error: {e}")
            return f"💰 재무 처리 중 오류: {e}"

    async def _handle_asset_update(self, message: str) -> str:
        try:
            raw = await claude_ask(message, system=_ASSET_PARSE_PROMPT, max_tokens=1024, no_tools=True)
            logger.info(f"Asset parse raw response: {raw[:300]}")

            # 마크다운 펜스 제거
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            data = json.loads(raw)

            total_added = 0
            for category in ("accounts", "savings", "loans", "real_estate", "stocks"):
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

    async def _handle_sms(self, message: str) -> str:
        """카드 문자 내용을 파싱해서 transactions.json에 저장."""
        # "카드 문자" 또는 "카드문자" 키워드 이후 문자 내용 추출
        import re
        sms_text = re.sub(r'^.*?(?:카드\s*문자)\s*', '', message, count=1, flags=re.IGNORECASE).strip()
        if not sms_text:
            return "⚠️ 카드 문자 내용을 찾지 못했습니다. 예: `카드 문자 신한카드 12,000원 승인 스타벅스`"
        parsed, success = parse_and_save(sms_text)
        if success:
            source_label = "월별합산" if parsed["source"] == "monthly_total" else "건별 승인"
            return (
                f"💳 카드 문자 기록 완료 ({source_label})\n"
                f"카드: {parsed['card']} | 금액: {parsed['amount']:,}원\n"
                f"가맹점: {parsed['merchant']}"
            )
        return (
            f"⚠️ 카드 문자 파싱 실패 — 원본 텍스트로 저장했습니다.\n"
            f"내용: `{sms_text[:80]}`\n"
            f"금액/카드사를 직접 확인해주세요."
        )

    def _load_ledger(self) -> list:
        if not LEDGER_PATH.exists():
            return []
        try:
            return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
