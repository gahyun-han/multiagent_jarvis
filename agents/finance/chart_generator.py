"""
Finance chart generator — 월별 수입/지출 추이 그래프 및 Excel 파일 생성.
"""
import io
import json
import logging
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

logger = logging.getLogger(__name__)

_FINANCE_DIR = Path(__file__).resolve().parents[2] / "data" / "finance"
_SNAPSHOT_PATH = _FINANCE_DIR / "monthly_snapshot.json"
_TRANSACTIONS_PATH = _FINANCE_DIR / "transactions.json"
_FINANCE_ASSETS_PATH = _FINANCE_DIR / "finance_assets.json"


# ── 한글 폰트 설정 ────────────────────────────────────────────────────────────

def _setup_korean_font():
    candidates = ["AppleGothic", "Apple SD Gothic Neo", "NanumGothic", "Malgun Gothic", "NanumBarunGothic"]
    available = {f.name for f in fm.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.family"] = name
            return
    plt.rcParams["axes.unicode_minus"] = False


# ── 데이터 로드 헬퍼 ──────────────────────────────────────────────────────────

def _load_snapshots() -> list[dict]:
    if not _SNAPSHOT_PATH.exists():
        return []
    try:
        return json.loads(_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _load_transactions() -> list[dict]:
    if not _TRANSACTIONS_PATH.exists():
        return []
    try:
        return json.loads(_TRANSACTIONS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _load_finance_assets() -> dict:
    if not _FINANCE_ASSETS_PATH.exists():
        return {"fixed": {"salary": 0, "savings": 0, "fixed_expenses": []}}
    try:
        return json.loads(_FINANCE_ASSETS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"fixed": {"salary": 0, "savings": 0, "fixed_expenses": []}}


def _monthly_income(month: str, txs: list[dict]) -> int:
    return sum(t["amount"] for t in txs if t.get("date", "")[:7] == month and t.get("source") == "income")


def _monthly_card_breakdown(month: str, txs: list[dict]) -> dict[str, int]:
    bd: dict[str, int] = defaultdict(int)
    for t in txs:
        if t.get("date", "")[:7] == month and t.get("source") not in ("monthly_total", "unknown", "income"):
            bd[t.get("card") or "기타"] += t.get("amount", 0)
    return dict(bd)


def _build_monthly_data(months: int = 6) -> list[dict]:
    """최근 N개월 수입/지출 데이터 구성."""
    snaps = sorted(_load_snapshots(), key=lambda s: s["month"])[-months:]
    txs = _load_transactions()
    fa = _load_finance_assets()
    fixed = fa.get("fixed", {})
    salary = fixed.get("salary", 0)
    savings_monthly = fixed.get("savings", 0)
    fixed_exp_total = sum(e.get("amount", 0) for e in fixed.get("fixed_expenses", [])) + savings_monthly

    rows = []
    for snap in snaps:
        m = snap["month"]
        extra = _monthly_income(m, txs)
        card_spend = snap.get("card_spend", 0)
        total_income = salary + extra
        total_expense = fixed_exp_total + card_spend
        remainder = total_income - total_expense
        rows.append({
            "month": m,
            "salary": salary,
            "extra_income": extra,
            "total_income": total_income,
            "fixed_expense": fixed_exp_total,
            "card_spend": card_spend,
            "total_expense": total_expense,
            "remainder": remainder,
            "net_assets": snap.get("net_assets", 0),
            "card_breakdown": _monthly_card_breakdown(m, txs),
        })
    return rows


# ── 차트 생성 ─────────────────────────────────────────────────────────────────

def generate_chart(months: int = 4) -> bytes:
    """최근 N개월 수입/지출 바 차트 + 순자산 추이 PNG bytes 반환."""
    _setup_korean_font()
    data = _build_monthly_data(months)
    if not data:
        raise ValueError("스냅샷 데이터 없음")

    labels = [d["month"][5:] + "월" for d in data]  # "2026-04" → "04월"
    incomes = [d["total_income"] / 10000 for d in data]
    expenses = [d["total_expense"] / 10000 for d in data]
    remainders = [d["remainder"] / 10000 for d in data]
    net_assets_eok = [d["net_assets"] / 100_000_000 for d in data]  # 억원

    x = list(range(len(labels)))
    width = 0.35

    fig, ax1 = plt.subplots(figsize=(9, 5))
    fig.patch.set_facecolor("#1e1e2e")
    ax1.set_facecolor("#1e1e2e")

    # 수입/지출 bar (ax1, 만원)
    bars_income = ax1.bar([i - width / 2 for i in x], incomes, width, label="수입", color="#4ade80", alpha=0.85)
    bars_expense = ax1.bar([i + width / 2 for i in x], expenses, width, label="지출", color="#f87171", alpha=0.85)

    # 잔여 line (ax1과 같은 스케일 — 만원)
    line_rem = ax1.plot(x, remainders, "o-", color="#60a5fa", linewidth=2, markersize=6, label="잔여(만원)")

    # 순자산 line (ax2 보조축, 억원)
    ax2 = ax1.twinx()
    line_na = ax2.plot(x, net_assets_eok, "s--", color="#a78bfa", linewidth=2, markersize=6, label="순자산(억원)")

    # bar value labels
    for bar in bars_income:
        h = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width() / 2, h + 2, f"{h:,.0f}", ha="center", va="bottom", fontsize=7, color="#e2e8f0")
    for bar in bars_expense:
        h = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width() / 2, h + 2, f"{h:,.0f}", ha="center", va="bottom", fontsize=7, color="#e2e8f0")

    # 잔여 annotations
    for xi, r in zip(x, remainders):
        color = "#4ade80" if r >= 0 else "#f87171"
        ax1.annotate(f"{r:+,.0f}", (xi, r), textcoords="offset points", xytext=(0, 9),
                     ha="center", fontsize=7, color=color)

    # 순자산 annotations
    for xi, na in zip(x, net_assets_eok):
        ax2.annotate(f"{na:.1f}억", (xi, na), textcoords="offset points", xytext=(0, 9),
                     ha="center", fontsize=7, color="#a78bfa")

    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, color="#e2e8f0")
    ax1.set_ylabel("만원", color="#e2e8f0")
    ax2.set_ylabel("순자산 (억원)", color="#a78bfa")
    ax1.tick_params(colors="#e2e8f0")
    ax2.tick_params(colors="#a78bfa")
    for spine in ax1.spines.values():
        spine.set_edgecolor("#4a4a6a")
    for spine in ax2.spines.values():
        spine.set_edgecolor("#4a4a6a")

    handles = [bars_income, bars_expense, line_rem[0], line_na[0]]
    labels_legend = ["수입", "지출", "잔여", "순자산"]
    ax1.legend(handles, labels_legend, loc="upper left", facecolor="#2e2e4e", labelcolor="#e2e8f0", fontsize=8)

    ax1.set_title("월별 수입/지출 추이 + 순자산", color="#e2e8f0", fontsize=13, pad=12)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.1f}"))
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ── 테이블 이미지 생성 ────────────────────────────────────────────────────────

def generate_table_image(months: int = 4) -> bytes:
    """최근 N개월 가계부 테이블 PNG bytes 반환 (모바일 최적화).

    컬럼: 월 / 총수입 / 고정지출 / 카드지출 / 잔여
    """
    _setup_korean_font()
    data = _build_monthly_data(months)
    if not data:
        raise ValueError("스냅샷 데이터 없음")

    col_labels = ["월", "총수입(원)", "고정지출(원)", "카드지출(원)", "잔여(원)"]
    n_cols = len(col_labels)
    n_rows = len(data)

    cell_text: list[list[str]] = []
    cell_colors: list[list[str]] = []

    for d in data:
        rem = d["remainder"]
        cell_text.append([
            d["month"][5:] + "월",
            f"{d['total_income']:,}",
            f"{d['fixed_expense']:,}",
            f"{d['card_spend']:,}",
            f"{rem:+,}",
        ])
        rem_bg = "#193319" if rem >= 0 else "#331919"
        cell_colors.append(["#252535", "#252535", "#252535", "#252535", rem_bg])

    row_h = 0.48
    fig_h = row_h * (n_rows + 1) + 0.15
    fig, ax = plt.subplots(figsize=(6.0, fig_h))
    fig.patch.set_facecolor("#1e1e2e")
    ax.patch.set_visible(False)  # axes 배경 제거 → tight crop이 테이블 셀만 포함
    ax.axis("off")

    tbl = ax.table(
        cellText=cell_text,
        colLabels=col_labels,
        cellColours=cell_colors,
        colColours=["#1F3864"] * n_cols,
        loc="center",
        cellLoc="right",
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9.5)
    tbl.auto_set_column_width(range(n_cols))
    tbl.scale(1, 1.35)

    for j in range(n_cols):
        cell = tbl[0, j]
        cell.set_text_props(color="#ffffff", fontweight="bold", ha="center")
        cell.set_edgecolor("#3a3a5a")
        cell.PAD = 0.04

    for i in range(1, n_rows + 1):
        d = data[i - 1]
        for j in range(n_cols):
            cell = tbl[i, j]
            cell.set_edgecolor("#3a3a5a")
            cell.PAD = 0.04
            if j == 0:
                cell.set_text_props(color="#c0c0e0", ha="center")
            elif j == n_cols - 1:
                color = "#4ade80" if d["remainder"] >= 0 else "#f87171"
                cell.set_text_props(color=color, fontweight="bold")
            else:
                cell.set_text_props(color="#d0d0e8")

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=160, bbox_inches="tight",
                pad_inches=0.02, facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()
