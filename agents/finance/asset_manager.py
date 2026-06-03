"""
Asset manager — stores and summarizes all asset types:
accounts, savings (적금), loans (대출), real estate (부동산).
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

ASSET_PATH = Path(__file__).resolve().parents[2] / "data" / "assets.json"

_EMPTY = {"accounts": [], "savings": [], "loans": [], "real_estate": [], "stocks": []}


class AssetManager:
    def load(self) -> dict:
        if not ASSET_PATH.exists():
            return _EMPTY.copy()
        try:
            data = json.loads(ASSET_PATH.read_text(encoding="utf-8"))
            # 기존 포맷(list)이면 마이그레이션
            if isinstance(data, list):
                return {**_EMPTY.copy(), "accounts": data}
            return {**_EMPTY.copy(), **data}
        except Exception:
            return _EMPTY.copy()

    def save(self, data: dict):
        ASSET_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def upsert(self, category: str, items: list[dict]):
        """category: accounts | savings | loans | real_estate"""
        data = self.load()
        existing = {item["name"]: item for item in data.get(category, [])}
        for item in items:
            existing[item["name"]] = item
        data[category] = list(existing.values())
        self.save(data)

    def net_worth_summary(self) -> str:
        data = self.load()

        accounts = data.get("accounts", [])
        savings = data.get("savings", [])
        loans = data.get("loans", [])
        real_estate = data.get("real_estate", [])
        stocks = data.get("stocks", [])

        total_assets = 0
        total_liabilities = 0
        lines = []

        if accounts:
            lines.append("🏦 *통장/계좌*")
            for a in accounts:
                bal = a.get("balance", 0)
                total_assets += bal
                lines.append(f"  • {a['name']}: {bal:,}원")

        if savings:
            lines.append("\n💚 *적금*")
            for s in savings:
                bal = s.get("balance", 0)
                total_assets += bal
                rate = f" ({s['interest_rate']}%)" if s.get("interest_rate") else ""
                maturity = f" | 만기: {s['maturity_date']}" if s.get("maturity_date") else ""
                monthly = f" | 월 {s['monthly']:,}원" if s.get("monthly") else ""
                lines.append(f"  • {s['name']}: {bal:,}원{rate}{monthly}{maturity}")

        if real_estate:
            lines.append("\n🏠 *부동산*")
            for r in real_estate:
                val = r.get("value", 0)
                total_assets += val
                addr = f" ({r['address']})" if r.get("address") else ""
                lines.append(f"  • {r['name']}{addr}: {val:,}원")

        if stocks:
            lines.append("\n📈 *주식/ETF*")
            stock_total = 0
            for s in stocks:
                val = s.get("total_value", 0)
                stock_total += val
                total_assets += val
                ticker = f" ({s['ticker']})" if s.get("ticker") else ""
                qty = f" {s['quantity']}주" if s.get("quantity") else ""
                cur = f" @ {s['current_price']:,}원" if s.get("current_price") else ""
                avg = s.get("avg_price")
                if avg and s.get("current_price"):
                    gain_pct = (s["current_price"] - avg) / avg * 100
                    gain_str = f" ({gain_pct:+.1f}%)"
                else:
                    gain_str = ""
                lines.append(f"  • {s['name']}{ticker}{qty}{cur}: {val:,}원{gain_str}")
            lines.append(f"  소계: {stock_total:,}원")

        if loans:
            lines.append("\n🔴 *대출*")
            for l in loans:
                rem = l.get("remaining", 0)
                total_liabilities += rem
                rate = f" ({l['interest_rate']}%)" if l.get("interest_rate") else ""
                maturity = f" | 만기: {l['maturity_date']}" if l.get("maturity_date") else ""
                monthly = f" | 월상환 {l['monthly_payment']:,}원" if l.get("monthly_payment") else ""
                lines.append(f"  • {l['name']}: {rem:,}원{rate}{monthly}{maturity}")

        net = total_assets - total_liabilities
        lines.append(f"\n{'─'*20}")
        lines.append(f"총 자산: *{total_assets:,}원*")
        if total_liabilities:
            lines.append(f"총 부채: *{total_liabilities:,}원*")
            lines.append(f"순자산: *{net:,}원*")

        if not any([accounts, savings, loans, real_estate, stocks]):
            return "등록된 자산 정보가 없습니다."

        return "\n".join(lines)
