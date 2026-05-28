"""
Savings tracker — tracks savings accounts, installment plans, and loan status.
"""
import json
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

SAVINGS_PATH = Path(__file__).resolve().parents[2] / "data" / "savings.json"


class SavingsTracker:
    def load(self) -> dict:
        if not SAVINGS_PATH.exists():
            return {"accounts": [], "loans": [], "last_updated": None}
        try:
            return json.loads(SAVINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {"accounts": [], "loans": [], "last_updated": None}

    def add_account(self, name: str, balance: int, monthly: int = 0, maturity_date: str = None):
        data = self.load()
        data["accounts"].append({
            "name": name,
            "balance": balance,
            "monthly_contribution": monthly,
            "maturity_date": maturity_date,
        })
        data["last_updated"] = date.today().isoformat()
        self._save(data)

    def get_summary(self) -> str:
        data = self.load()
        accounts = data.get("accounts", [])
        loans = data.get("loans", [])
        if not accounts and not loans:
            return "등록된 저축/대출 정보가 없습니다."
        lines = ["💰 *저축 현황*"]
        total = 0
        for acc in accounts:
            bal = acc.get("balance", 0)
            total += bal
            lines.append(f"  • {acc['name']}: {bal:,}원" +
                         (f" (만기: {acc['maturity_date']})" if acc.get("maturity_date") else ""))
        lines.append(f"  총합: {total:,}원")
        if loans:
            lines.append("\n🏦 *대출 현황*")
            for loan in loans:
                lines.append(f"  • {loan['name']}: {loan.get('remaining', 0):,}원")
        return "\n".join(lines)

    def _save(self, data: dict):
        SAVINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
