"""
Report generator — 월별 자산 트렌드 리포트.

데이터 소스:
- data/assets.json (AssetManager): 주식, 부동산, 통장, 적금 잔액
- data/finance/assets.json: 고정 설정 (월급, 적금납입액, 고정지출 목록)
- data/finance/transactions.json: 카드 문자 기반 지출 내역
- data/finance/monthly_snapshot.json: 월별 스냅샷 (트렌드 비교용)
"""
import json
import logging
from datetime import date
from pathlib import Path

from collections import defaultdict

from agents.finance.asset_manager import AssetManager
from agents.finance.sms_parser import load_income_for_month, load_transactions_for_month

logger = logging.getLogger(__name__)

_FINANCE_DIR = Path(__file__).resolve().parents[2] / "data" / "finance"
_FINANCE_ASSETS_PATH = _FINANCE_DIR / "finance_assets.json"
_SNAPSHOT_PATH = _FINANCE_DIR / "monthly_snapshot.json"

_EMPTY_FINANCE_ASSETS = {
    "updated_at": "",
    "fixed": {
        "salary": 0,
        "savings": 0,
        "fixed_expenses": [],
    },
}


def generate_monthly_report(month: str = None) -> str:
    """
    월별 종합 자산 리포트 생성 후 Telegram 마크다운 문자열 반환.
    리포트 생성 시마다 monthly_snapshot.json에 스냅샷 append.
    """
    target = month or _today_month()

    assets = AssetManager().load()
    finance_cfg = _load_finance_assets()
    transactions = load_transactions_for_month(target)
    income_transactions = load_income_for_month(target)
    snapshots = _load_snapshots()
    prev_snap = _find_snapshot(snapshots, _prev_month(target))

    # ── 자산 계산 ──────────────────────────────────────────────────────────────
    stock_value = sum(s.get("total_value", 0) for s in assets.get("stocks", []))
    re_value = sum(r.get("value", 0) for r in assets.get("real_estate", []))
    account_value = sum(a.get("balance", 0) for a in assets.get("accounts", []))
    savings_balance = sum(s.get("balance", 0) for s in assets.get("savings", []))
    loan_balance = sum(l.get("remaining", 0) for l in assets.get("loans", []))

    gross_assets = stock_value + re_value + account_value + savings_balance
    net_assets = gross_assets - loan_balance

    # ── 수입/지출 계산 ─────────────────────────────────────────────────────────
    card_spend = sum(t.get("amount", 0) for t in transactions)
    extra_income = sum(t.get("amount", 0) for t in income_transactions)
    fixed = finance_cfg.get("fixed", {})
    salary = fixed.get("salary", 0)
    savings_monthly = fixed.get("savings", 0)
    fixed_expenses = fixed.get("fixed_expenses", [])
    fixed_total = sum(e.get("amount", 0) for e in fixed_expenses) + savings_monthly
    total_income = salary + extra_income
    total_expense = fixed_total + card_spend
    estimated_remainder = total_income - total_expense

    # ── 카드사별 지출 ───────────────────────────────────────────────────────────
    card_breakdown: dict[str, int] = defaultdict(int)
    for t in transactions:
        card = t.get("card") or "기타"
        card_breakdown[card] += t.get("amount", 0)

    # ── 스냅샷 저장 ────────────────────────────────────────────────────────────
    snapshot = {
        "month": target,
        "net_assets": net_assets,
        "stock_value": stock_value,
        "real_estate_value": re_value,
        "card_spend": card_spend,
    }
    _append_snapshot(snapshots, snapshot)

    # ── 리포트 조립 ────────────────────────────────────────────────────────────
    lines = [f"📊 *{target} 월별 자산 리포트*", ""]

    # ① 순자산 현황
    lines.append("*① 순자산 현황*")
    if stock_value:
        lines.append(f"  📈 주식/ETF: {stock_value:,}원")
    if re_value:
        lines.append(f"  🏠 부동산:  {re_value:,}원")
    if account_value:
        lines.append(f"  🏦 통장/계좌: {account_value:,}원")
    if savings_balance:
        lines.append(f"  💚 적금 잔액: {savings_balance:,}원")
    if loan_balance:
        lines.append(f"  🔴 대출:   -{loan_balance:,}원")
    lines.append(f"  {'─'*18}")
    lines.append(f"  💰 *순자산: {net_assets:,}원*")
    lines.append("")

    # ② 이번 달 수입/지출 요약
    lines.append("*② 이번 달 수입/지출 요약*")
    if salary:
        lines.append(f"  💵 월급: {salary:,}원")
    for inc in income_transactions:
        lines.append(f"  💵 {inc.get('merchant', '기타수입')}: +{inc.get('amount', 0):,}원")
    if extra_income:
        lines.append(f"  {'─'*16}")
        lines.append(f"  💵 *총 수입: {total_income:,}원*")
    lines.append("")
    if fixed_expenses:
        lines.append(f"  🔒 고정지출: -{fixed_total:,}원")
        for fe in fixed_expenses:
            lines.append(f"     • {fe['name']}: {fe['amount']:,}원")
        if savings_monthly:
            lines.append(f"     • 적금납입: {savings_monthly:,}원")
    card_note = f" _(카드 {len(transactions)}건, 누락 있을 수 있음)_" if transactions else " _(기록 없음)_"
    lines.append(f"  💳 카드지출: -{card_spend:,}원{card_note}")
    if card_breakdown:
        for card, amount in sorted(card_breakdown.items(), key=lambda x: -x[1]):
            lines.append(f"     • {card}: {amount:,}원")
    if total_income or total_expense:
        lines.append(f"  {'─'*16}")
        lines.append(f"  📊 총 지출: -{total_expense:,}원")
        sign = "+" if estimated_remainder >= 0 else ""
        icon = "✅" if estimated_remainder >= 0 else "🔴"
        lines.append(f"  {icon} 추정 잔여: {sign}{estimated_remainder:,}원")
    lines.append("")

    # ③ 전월 대비 트렌드
    lines.append("*③ 전월 대비 트렌드*")
    if prev_snap:
        delta = net_assets - prev_snap["net_assets"]
        pct = (delta / prev_snap["net_assets"] * 100) if prev_snap["net_assets"] else 0
        sign = "+" if delta >= 0 else ""
        icon = "📈" if delta >= 0 else "📉"
        lines.append(f"  전월 ({_prev_month(target)}) 순자산: {prev_snap['net_assets']:,}원")
        lines.append(f"  {icon} 순자산 변화: {sign}{delta:,}원 ({sign}{pct:.1f}%)")
        stock_delta = stock_value - prev_snap.get("stock_value", 0)
        if stock_delta:
            s_sign = "+" if stock_delta >= 0 else ""
            lines.append(f"  📈 주식 변화: {s_sign}{stock_delta:,}원")
    else:
        lines.append(f"  📭 전월 데이터 없음 (다음 달부터 비교 가능)")

    return "\n".join(lines)


def load_finance_assets() -> dict:
    """외부에서 finance_assets.json 읽기용."""
    return _load_finance_assets()


def save_finance_assets(data: dict) -> None:
    """finance_assets.json 저장."""
    _FINANCE_DIR.mkdir(parents=True, exist_ok=True)
    _FINANCE_ASSETS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

def _today_month() -> str:
    return date.today().strftime("%Y-%m")


def _prev_month(month: str) -> str:
    y, m = map(int, month.split("-"))
    m -= 1
    if m == 0:
        y -= 1
        m = 12
    return f"{y:04d}-{m:02d}"


def _load_finance_assets() -> dict:
    if not _FINANCE_ASSETS_PATH.exists():
        return _EMPTY_FINANCE_ASSETS.copy()
    try:
        return json.loads(_FINANCE_ASSETS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Failed to load finance_assets: {e}")
        return _EMPTY_FINANCE_ASSETS.copy()


def _load_snapshots() -> list[dict]:
    if not _SNAPSHOT_PATH.exists():
        return []
    try:
        return json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Failed to load snapshots: {e}")
        return []


def _find_snapshot(snapshots: list[dict], month: str) -> dict | None:
    return next((s for s in reversed(snapshots) if s["month"] == month), None)


def _append_snapshot(existing: list[dict], new: dict) -> None:
    today_month = date.today().strftime("%Y-%m")
    for i, s in enumerate(existing):
        if s["month"] == new["month"]:
            if s["month"] == today_month:
                # 당월은 전체 업데이트 (현재 자산값 반영)
                existing[i] = new
            else:
                # 과거 월은 card_spend만 갱신 — 자산 스냅샷 보존
                existing[i]["card_spend"] = new["card_spend"]
            break
    else:
        existing.append(new)
    try:
        _FINANCE_DIR.mkdir(parents=True, exist_ok=True)
        _SNAPSHOT_PATH.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"Failed to save snapshot: {e}")
