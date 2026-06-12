"""
일회성 재무 데이터 시드 스크립트.
finance_assets.json + transactions.json 생성 후 월별 리포트 출력.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FINANCE_DIR = ROOT / "data" / "finance"
FINANCE_DIR.mkdir(parents=True, exist_ok=True)

# ── finance_assets.json ───────────────────────────────────────────────────────
finance_assets = {
    "updated_at": "2026-06-12",
    "fixed": {
        "salary": 9_800_000,
        "savings": 200_000,
        "fixed_expenses": [
            {"name": "관리비",          "amount": 300_000},
            {"name": "보험(가현)",       "amount": 117_000},
            {"name": "보험(현수)",       "amount": 100_000},
            {"name": "클로드 구독",      "amount":  35_000},
            {"name": "네이버 구독",      "amount":   3_900},
            {"name": "티빙",            "amount":   9_000},
            {"name": "통신비(가현)",     "amount": 155_900},
            {"name": "통신비(현수)",     "amount":  22_000},
            {"name": "다이어트약",       "amount": 530_000},
            {"name": "용돈(양가+할머님)", "amount": 250_000},
            {"name": "대출상환",         "amount": 3_260_000},
        ],
    },
}
(FINANCE_DIR / "finance_assets.json").write_text(
    json.dumps(finance_assets, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("✅ finance_assets.json 저장 완료")

# ── transactions.json (카드별 월별 합계 → source=manual) ─────────────────────
card_data = {
    "2026-03": {
        "토스카드":   103_258,
        "하나카드": 1_157_390,
        "삼성카드": 1_580_283,
        "우리카드":   620_310,
        "남편카드":   350_000,
    },
    "2026-04": {
        "토스카드":   600_313,
        "하나카드":   357_618,
        "삼성카드": 1_814_920,
        "우리카드":   603_789,
        "남편카드":   350_000,
    },
    "2026-05": {
        "토스카드":   248_650,
        "하나카드":    69_530,
        "삼성카드": 1_910_560,
        "우리카드":   297_939,
        "남편카드":   350_000,
    },
    "2026-06": {
        "토스카드":    79_840,
        # 하나카드 해지, 삼성/우리 청구서 미발행
        "남편카드":   350_000,
    },
}

transactions = []
for month, cards in card_data.items():
    for card, amount in cards.items():
        transactions.append({
            "date":     f"{month}-01",
            "amount":   amount,
            "merchant": "월합산",
            "card":     card,
            "source":   "manual",
        })

# ── 월별 수입 (월급 외 보너스/성과금) ──────────────────────────────────────────
extra_income = {
    "2026-04": [
        {"merchant": "업무성과금(가현)", "amount": 6_376_700},
        {"merchant": "특별보상(가현)",   "amount": 1_432_000},
    ],
}
for month, items in extra_income.items():
    for item in items:
        transactions.append({
            "date":     f"{month}-01",
            "amount":   item["amount"],
            "merchant": item["merchant"],
            "card":     "",
            "source":   "income",
        })

(FINANCE_DIR / "transactions.json").write_text(
    json.dumps(transactions, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(f"✅ transactions.json 저장 완료 ({len(transactions)}건)")

# ── 월별 리포트 생성 (3→4→5→6월 순서로 스냅샷 누적) ──────────────────────────
from agents.finance.report_generator import generate_monthly_report

print("\n" + "="*50)
for month in ["2026-03", "2026-04", "2026-05", "2026-06"]:
    report = generate_monthly_report(month)
    print(report)
    print("="*50)
