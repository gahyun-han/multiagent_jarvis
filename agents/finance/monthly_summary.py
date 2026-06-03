"""
Monthly summary — aggregates ledger entries by month and renders
ASCII bar charts suitable for Telegram (plain text).
"""
import json
import logging
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

LEDGER_PATH = Path(__file__).resolve().parents[2] / "data" / "ledger.json"

EXPENSE_CATEGORIES = ["식비", "교통", "쇼핑", "의료", "주거", "문화", "저축", "기타"]
INCOME_CATEGORIES = ["수입"]

BAR_WIDTH = 12  # max bar characters


def _load_ledger() -> list:
    if not LEDGER_PATH.exists():
        return []
    try:
        return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _today_str() -> str:
    return date.today().strftime("%Y-%m")


def _entry_month(entry: dict) -> str:
    d = entry.get("date")
    if d and len(d) >= 7:
        return d[:7]
    return _today_str()


def _bar(value: int, max_value: int, width: int = BAR_WIDTH) -> str:
    if max_value == 0:
        return "░" * width
    filled = round(value / max_value * width)
    return "█" * filled + "░" * (width - filled)


def _fmt(amount: int) -> str:
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.1f}M"
    if amount >= 10_000:
        return f"{amount // 10_000}만"
    return f"{amount:,}"


def get_monthly_summary(month: str = None) -> str:
    """
    Returns a formatted monthly income/expense breakdown with ASCII bars.
    month: 'YYYY-MM' (default: current month)
    """
    target = month or _today_str()
    ledger = _load_ledger()

    entries = [e for e in ledger if _entry_month(e) == target]
    if not entries:
        return f"📭 {target} 기록된 가계부 데이터가 없습니다."

    income_total = sum(e["amount"] for e in entries if e["type"] == "income")
    expense_total = sum(e["amount"] for e in entries if e["type"] == "expense")
    balance = income_total - expense_total

    # Category totals (expense only)
    cat_totals: dict[str, int] = defaultdict(int)
    for e in entries:
        if e["type"] == "expense":
            cat_totals[e.get("category", "기타")] += e["amount"]

    max_cat = max(cat_totals.values(), default=1)

    lines = [
        f"📊 {target} 가계부 요약",
        f"{'─' * 22}",
        f"💰 수입:  {income_total:>12,}원",
        f"💸 지출:  {expense_total:>12,}원",
        f"{'─' * 22}",
        f"{'✅' if balance >= 0 else '🔴'} 잔여:  {balance:>12,}원",
        "",
        "[ 지출 카테고리 ]",
    ]

    for cat in EXPENSE_CATEGORIES:
        amt = cat_totals.get(cat, 0)
        if amt == 0:
            continue
        pct = amt / expense_total * 100 if expense_total else 0
        bar = _bar(amt, max_cat)
        lines.append(f"{cat:<4} {bar} {_fmt(amt)} ({pct:.0f}%)")

    return "\n".join(lines)


def get_monthly_graph(months: int = 3) -> str:
    """
    Returns a month-over-month comparison bar chart for the last N months.
    """
    ledger = _load_ledger()
    if not ledger:
        return "📭 기록된 가계부 데이터가 없습니다."

    # Collect all months present in data, pick latest N
    all_months = sorted({_entry_month(e) for e in ledger}, reverse=True)
    selected = list(reversed(all_months[:months]))

    monthly_income: dict[str, int] = defaultdict(int)
    monthly_expense: dict[str, int] = defaultdict(int)
    for e in ledger:
        m = _entry_month(e)
        if m in selected:
            if e["type"] == "income":
                monthly_income[m] += e["amount"]
            else:
                monthly_expense[m] += e["amount"]

    max_val = max(
        *[monthly_income[m] for m in selected],
        *[monthly_expense[m] for m in selected],
        1,
    )

    lines = [f"📈 최근 {len(selected)}개월 수입/지출 비교", "─" * 24]
    for m in selected:
        inc = monthly_income[m]
        exp = monthly_expense[m]
        bal = inc - exp
        sign = "+" if bal >= 0 else ""
        lines.append(f"\n{m}")
        lines.append(f"  💰 {_bar(inc, max_val)} {_fmt(inc)}")
        lines.append(f"  💸 {_bar(exp, max_val)} {_fmt(exp)}")
        lines.append(f"  {'✅' if bal >= 0 else '🔴'} {sign}{_fmt(bal)}")

    return "\n".join(lines)


def get_category_detail(category: str, month: str = None) -> str:
    """Returns itemized list for a specific category in a given month."""
    target = month or _today_str()
    ledger = _load_ledger()
    entries = [
        e for e in ledger
        if _entry_month(e) == target
        and e["type"] == "expense"
        and e.get("category") == category
    ]
    if not entries:
        return f"📭 {target} [{category}] 항목이 없습니다."

    total = sum(e["amount"] for e in entries)
    lines = [f"📋 {target} [{category}] 상세 — 합계 {total:,}원", "─" * 20]
    for e in sorted(entries, key=lambda x: x.get("date") or "", reverse=True):
        d = e.get("date", "")
        lines.append(f"  {d}  {e['description']:<16} {e['amount']:>9,}원")
    return "\n".join(lines)
