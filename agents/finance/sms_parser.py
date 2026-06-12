"""
SMS parser — 한국 카드사 문자 파싱 후 data/finance/transactions.json에 저장.
파싱 실패 시 raw_text를 source="unknown"으로 저장하고 플래그 반환.
"""
import json
import logging
import re
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

_FINANCE_DIR = Path(__file__).resolve().parents[2] / "data" / "finance"
_TRANSACTIONS_PATH = _FINANCE_DIR / "transactions.json"

_CARD_NAMES = ["신한", "국민", "현대", "삼성", "롯데", "하나", "우리", "씨티", "카카오", "농협", "비씨", "BC"]

# 금액: 12,000 or 12000 앞에 붙은 숫자
_AMOUNT_RE = re.compile(r'([\d,]+)원')

# 카드사 이름
_CARD_RE = re.compile(r'(' + '|'.join(_CARD_NAMES) + r')카드?')

# 월별 총액 문자: "이번달 카드 사용액 XXX원", "5월 이용대금: XXX원"
_MONTHLY_RE = re.compile(
    r'(?:이번\s*달?|(?:\d{1,2}월))\s*'
    r'(?:카드\s*)?(?:사용액|이용금액|이용대금|총\s*사용액).*?([\d,]+)원',
    re.IGNORECASE,
)

# 개별 승인 문자 내 가맹점: 금액+승인/결제 뒤 한글/영문 상호명
_MERCHANT_AFTER_RE = re.compile(
    r'[\d,]+원\s*(?:\([^)]*\))?\s*(?:승인|결제)\s+([가-힣A-Za-z][가-힣A-Za-z0-9·\s\-]{0,25})',
)
# 승인/결제 앞에 상호명이 오는 경우: "스타벅스 12,000원 승인"
_MERCHANT_BEFORE_RE = re.compile(
    r'([가-힣A-Za-z][가-힣A-Za-z0-9·\s\-]{1,20})\s+[\d,]+원\s*(?:승인|결제)',
)


def parse_sms(text: str) -> dict:
    """
    카드 문자 파싱.

    Returns:
        {amount, merchant, card, date, source}
        파싱 실패 시 source="unknown", amount=0 반환.
    """
    text = text.strip()
    today = date.today().isoformat()

    # 월별 총액 패턴
    m = _MONTHLY_RE.search(text)
    if m:
        amount = _parse_amount(m.group(1))
        return {
            "date": today,
            "amount": amount,
            "merchant": "월별합산",
            "card": _extract_card(text),
            "source": "monthly_total",
        }

    # 개별 승인 패턴
    m = _AMOUNT_RE.search(text)
    if m:
        amount = _parse_amount(m.group(1))
        if amount > 0:
            return {
                "date": today,
                "amount": amount,
                "merchant": _extract_merchant(text),
                "card": _extract_card(text),
                "source": "sms",
            }

    # 파싱 실패
    logger.warning(f"SMS parse failed: {text[:60]}")
    return {
        "date": today,
        "amount": 0,
        "merchant": "",
        "card": "",
        "source": "unknown",
        "raw": text,
    }


def save_transaction(parsed: dict) -> None:
    """transactions.json에 거래 내역 추가."""
    transactions = _load_transactions()
    transactions.append(parsed)
    _save_transactions(transactions)


def parse_and_save(sms_text: str) -> tuple[dict, bool]:
    """
    SMS 파싱 후 저장.

    Returns:
        (parsed_dict, success: bool)
        success=False이면 파싱 실패 — 사용자 확인 필요.
    """
    parsed = parse_sms(sms_text)
    save_transaction(parsed)
    success = parsed["source"] != "unknown"
    return parsed, success


def load_transactions_for_month(month: str) -> list[dict]:
    """YYYY-MM 형식의 월에 해당하는 지출 거래 목록 반환 (monthly_total/unknown/income 제외)."""
    return [
        t for t in _load_transactions()
        if t.get("date", "")[:7] == month
        and t.get("source") not in ("monthly_total", "unknown", "income")
    ]


def load_income_for_month(month: str) -> list[dict]:
    """YYYY-MM 형식의 월에 해당하는 수입 거래 목록 반환."""
    return [
        t for t in _load_transactions()
        if t.get("date", "")[:7] == month
        and t.get("source") == "income"
    ]


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

def _parse_amount(raw: str) -> int:
    try:
        return int(raw.replace(",", ""))
    except ValueError:
        return 0


def _extract_card(text: str) -> str:
    m = _CARD_RE.search(text)
    return m.group(1) if m else "알 수 없음"


def _extract_merchant(text: str) -> str:
    m = _MERCHANT_AFTER_RE.search(text)
    if m:
        return _clean_merchant(m.group(1))
    m = _MERCHANT_BEFORE_RE.search(text)
    if m:
        return _clean_merchant(m.group(1))
    return "알 수 없음"


def _clean_merchant(name: str) -> str:
    # 날짜/시간 패턴, 잔여한도 등 후처리 제거
    name = re.split(r'\s*\d{2}[/\-]\d{2}|\s*\d{2}:\d{2}|\s*잔여|\s*누적', name)[0]
    return name.strip()[:20]


def _load_transactions() -> list[dict]:
    if not _TRANSACTIONS_PATH.exists():
        return []
    try:
        return json.loads(_TRANSACTIONS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Failed to load transactions: {e}")
        return []


def _save_transactions(data: list[dict]) -> None:
    _FINANCE_DIR.mkdir(parents=True, exist_ok=True)
    _TRANSACTIONS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
