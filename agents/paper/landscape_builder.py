"""
Zotero 라이브러리 전체를 분석해 landscape/summary.json 을 생성한다.
pyzotero Zotero 인스턴스를 직접 받으므로 ZoteroObsidianClient 에 종속되지 않는다.
"""
import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

LANDSCAPE_PATH = Path(__file__).resolve().parents[2] / "landscape" / "summary.json"


def build_landscape(zot) -> dict:
    """전체 라이브러리를 읽어 통계 dict 를 반환한다."""
    all_items = [
        i for i in zot.everything(zot.top())
        if i.get("data", {}).get("itemType") != "attachment"
    ]

    by_year:   Counter = Counter()
    by_tag:    Counter = Counter()
    authors:   Counter = Counter()
    venues:    Counter = Counter()

    for item in all_items:
        data = item["data"]

        # 연도
        year = (data.get("date") or "")[:4]
        if year.isdigit():
            by_year[year] += 1

        # 태그
        for t in data.get("tags", []):
            tag = t.get("tag", "").strip()
            if tag:
                by_tag[tag] += 1

        # 저자
        for creator in data.get("creators", []):
            if creator.get("creatorType") == "author":
                last  = creator.get("lastName", "").strip()
                first = creator.get("firstName", "").strip()
                name  = f"{last}, {first}".strip(", ") if last else creator.get("name", "").strip()
                if name:
                    authors[name] += 1

        # 저널/학술대회/저장소
        venue = (
            data.get("publicationTitle")
            or data.get("proceedingsTitle")
            or data.get("bookTitle")
            or data.get("repository")
            or ""
        ).strip()
        if venue:
            venues[venue] += 1

    # 최근 3년 증가율
    now_year = datetime.now(timezone.utc).year
    growth: dict = {}
    for yr in range(now_year - 2, now_year + 1):
        growth[str(yr)] = by_year.get(str(yr), 0)

    yrs = sorted(growth.keys())
    for i in range(1, len(yrs)):
        y0, y1 = yrs[i - 1], yrs[i]
        c0, c1 = growth[y0], growth[y1]
        if c0 > 0:
            pct = round((c1 - c0) / c0 * 100, 1)
            growth[f"yoy_{y0}_{y1}"] = f"{pct:+.1f}%"
        else:
            growth[f"yoy_{y0}_{y1}"] = "N/A"

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_papers": len(all_items),
        "by_year":      dict(sorted(by_year.items())),
        "by_tag":       dict(by_tag.most_common()),
        "top_authors":  [{"name": n, "count": c} for n, c in authors.most_common(20)],
        "top_venues":   [{"name": v, "count": c} for v, c in venues.most_common(20)],
        "growth_last_3yr": growth,
    }


def save_landscape(data: dict) -> Path:
    LANDSCAPE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LANDSCAPE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(f"Landscape saved → {LANDSCAPE_PATH}")
    return LANDSCAPE_PATH


def format_landscape_message(data: dict) -> str:
    """Telegram 출력용 요약 메시지 생성."""
    total = data["total_papers"]
    by_year = data["by_year"]
    by_tag  = data["by_tag"]
    growth  = data["growth_last_3yr"]
    top_authors = data["top_authors"]
    top_venues  = data["top_venues"]

    lines = [f"📊 *Zotero 라이브러리 분석*\n"]
    lines.append(f"📚 전체 논문: *{total}편*\n")

    # 연도별
    lines.append("📅 *연도별 논문 수*")
    for yr, cnt in sorted(by_year.items()):
        bar = "▪" * min(cnt, 20)
        lines.append(f"  {yr}: {cnt}편 {bar}")

    # 최근 3년 증가율
    yoy = {k: v for k, v in growth.items() if "yoy" in k}
    if yoy:
        lines.append("\n📈 *증가율 (YoY)*")
        for key, val in yoy.items():
            yr_range = key.replace("yoy_", "").replace("_", " → ")
            lines.append(f"  {yr_range}: {val}")

    # 태그별 Top 15
    lines.append("\n🏷 *태그별 논문 수 (Top 15)*")
    for tag, cnt in list(by_tag.items())[:15]:
        lines.append(f"  {tag}: {cnt}편")

    # 저자 Top 10
    lines.append("\n👤 *주요 저자 Top 10*")
    for i, a in enumerate(top_authors[:10], 1):
        lines.append(f"  {i:2}. {a['name']} ({a['count']}편)")

    # 저널 Top 10
    if top_venues:
        lines.append("\n📰 *주요 저널/학술대회 Top 10*")
        for i, v in enumerate(top_venues[:10], 1):
            lines.append(f"  {i:2}. {v['name']} ({v['count']}편)")

    return "\n".join(lines)
