"""
Zotero client — Zotero 라이브러리 연동 및 컬렉션 동기화.
add_papers(), sync_collections_from_tags(), sync_items_collections(), search_by_tags() 등 제공.
"""
import copy
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from pyzotero import zotero
from dotenv import load_dotenv

try:
    import requests as _requests
    _REQUESTS_OK = True
except ImportError:
    _REQUESTS_OK = False

# tag (lowercase) → canonical collection name
# 풀네임·약어 모두 등록해 어떤 형식으로 저장된 태그도 같은 컬렉션으로 매핑됨.
TAG_TO_COLLECTION: dict[str, str] = {
    # Digital Twin
    "dt":                   "Digital Twin",
    "digital twin":         "Digital Twin",
    # Reinforcement Learning
    "rl":                   "Reinforcement Learning",
    "reinforcement learning": "Reinforcement Learning",
    # Agent
    "agent":                "AI Agent",
    "agentic ai":           "Agentic AI",
    # LLM
    "llm":                  "Large Language Models",
    "large language models": "Large Language Models",
    # NLP / CV / Robotics
    "nlp":                  "NLP",
    "cv":                   "Computer Vision",
    "robotics":             "Robotics",
    # Simulation
    "sim":                  "Simulation",
    "simulation":           "Simulation",
    # Ontology
    "ontology":             "Ontology",
    # Routing
    "routing":              "Routing",
    # RAG
    "rag":                  "RAG",
    "retrieval augmented":  "RAG",
    # Multi-Agent
    "multi-agent":          "Multi-Agent",
    "multiagent":           "Multi-Agent",
    # Scheduling
    "scheduling":           "Scheduling",
    # Survey / Benchmark
    "survey":               "Survey",
    "benchmark":            "Benchmark",
    # Others
    "gnn":                  "Graph Neural Networks",
    "transformer":          "Transformers",
    "diffusion":            "Diffusion Models",
    "planning":             "Planning",
    "reasoning":            "Reasoning",
    "ml":                   "Machine Learning",
    "dl":                   "Deep Learning",
    "foundation":           "Foundation Models",
    "safety":               "AI Safety",
    "federated":            "Federated Learning",
    "graph":                "Graph Learning",
    "industrial ai":        "Industrial AI",
    "factory ai":           "Industrial AI",
    "physical ai":          "Physical AI",
    "semiconductor":        "Semiconductor",
    "knowledge graph":      "Knowledge Graph",
    "kg":                   "Knowledge Graph",
}

# collection 풀네임 → 조합 컬렉션 표시용 짧은 이름
# 이 테이블을 통해 "dt"든 "digital twin"이든 항상 "DT + RAG"로 통일됨.
COLLECTION_ABBREV: dict[str, str] = {
    "Digital Twin":           "DT",
    "Reinforcement Learning": "RL",
    "AI Agent":               "AGENT",
    "Agentic AI":             "AGENTIC AI",
    "Large Language Models":  "LLM",
    "NLP":                    "NLP",
    "Computer Vision":        "CV",
    "Robotics":               "ROBOTICS",
    "Simulation":             "SIM",
    "Ontology":               "ONTOLOGY",
    "Routing":                "ROUTING",
    "RAG":                    "RAG",
    "Multi-Agent":            "MULTI-AGENT",
    "Scheduling":             "SCHEDULING",
    "Survey":                 "SURVEY",
    "Benchmark":              "BENCHMARK",
    "Graph Neural Networks":  "GNN",
    "Transformers":           "TRANSFORMER",
    "Diffusion Models":       "DIFFUSION",
    "Planning":               "PLANNING",
    "Reasoning":              "REASONING",
    "Machine Learning":       "ML",
    "Deep Learning":          "DL",
    "Foundation Models":      "FOUNDATION",
    "AI Safety":              "SAFETY",
    "Federated Learning":     "FEDERATED",
    "Graph Learning":         "GRAPH",
    "Industrial AI":          "INDUSTRIAL AI",
    "Physical AI":            "PHYSICAL AI",
    "Semiconductor":          "SEMICONDUCTOR",
    "Knowledge Graph":        "KG",
}

PDF_DIR = Path.home() / "Documents" / "Papers"
_ARXIV_PDF = "https://arxiv.org/pdf/{arxiv_id}"

load_dotenv()
logger = logging.getLogger(__name__)


def _build_col_index(all_cols: list) -> tuple[dict, dict]:
    """컬렉션 목록 → (top_by_name, sub_by_key) 인덱스 생성.

    중복 이름이 있을 때 first-wins 전략을 사용하고,
    중복 부모 키를 canonical 키로 정규화하여 매번 새 컬렉션이
    생성되는 버그를 방지한다.
    """
    # 1단계: top-level (first wins)
    top_by_name: dict[str, str] = {}
    dup_key_map: dict[str, str] = {}  # 중복 키 → canonical 키

    for c in all_cols:
        d = c["data"]
        if not d.get("parentCollection", False):
            if d["name"] not in top_by_name:
                top_by_name[d["name"]] = d["key"]
            else:
                dup_key_map[d["key"]] = top_by_name[d["name"]]

    # 2단계: sub-collections — 부모 키를 canonical로 정규화 후 first wins
    sub_by_key: dict[tuple[str, str], str] = {}
    for c in all_cols:
        d = c["data"]
        parent = d.get("parentCollection", False)
        if parent:
            canonical_parent = dup_key_map.get(parent, parent)
            if (canonical_parent, d["name"]) not in sub_by_key:
                sub_by_key[(canonical_parent, d["name"])] = d["key"]

    return top_by_name, sub_by_key


class ZoteroClient:
    def __init__(self):
        api_key = os.getenv("ZOTERO_API_KEY")
        user_id = os.getenv("ZOTERO_USER_ID")
        if api_key and user_id:
            self.zot = zotero.Zotero(user_id, "user", api_key)
        else:
            self.zot = None
            logger.warning("Zotero credentials not set — paper features limited")

    def get_recent_papers(self, limit: int = 20) -> list[dict]:
        if not self.zot:
            return []
        try:
            items = self.zot.top(limit=limit, itemType="journalArticle || conferencePaper || preprint")
            return [self._parse_item(i) for i in items]
        except Exception as e:
            logger.error(f"Zotero fetch error: {e}")
            return []

    def search_papers(self, query: str, limit: int = 10) -> list[dict]:
        if not self.zot:
            return []
        try:
            items = self.zot.items(q=query, limit=limit)
            return [self._parse_item(i) for i in items]
        except Exception as e:
            logger.error(f"Zotero search error: {e}")
            return []

    def add_papers(self, papers: list[dict]) -> tuple[int, list[str]]:
        """
        Add arxiv papers to Zotero library with PDF attachments.
        papers: list of dicts with keys: title, summary/abstract, link, arxiv_id, authors, published, keywords
        Returns (added_count, error_messages).
        Zotero desktop does NOT need to be open.
        PDFs are saved to ~/Documents/Papers/{arxiv_id}.pdf.
        """
        if not self.zot or not papers:
            return 0, []

        errors: list[str] = []
        added = 0

        for paper in papers:
            arxiv_id = paper.get("arxiv_id", "")
            title = paper.get("title", arxiv_id)
            try:
                result = self.zot.create_items([self._build_preprint(paper)])
                successful = result.get("successful", {})
                if not successful:
                    for fail in result.get("failed", {}).values():
                        errors.append(fail.get("message", "unknown"))
                    continue
                item_key = list(successful.values())[0]["key"]
                added += 1

                pdf_path = self._download_pdf(arxiv_id)
                if pdf_path:
                    self._attach_pdf(item_key, pdf_path, title)
            except Exception as e:
                logger.error(f"Zotero add_papers error for {arxiv_id}: {e}")
                errors.append(str(e))

        logger.info(f"Zotero: added {added} papers, {len(errors)} errors")
        return added, errors

    # ------------------------------------------------------------------ #
    # Collection sync                                                     #
    # ------------------------------------------------------------------ #

    def sync_collections_from_tags(self) -> str:
        """두 태그 체계를 동시에 처리합니다.

        [A] Atomic tags (domain:X / method:X / problem:X)
            → 계층형 컬렉션: Domain/manufacturing, Method/rag, Problem/scheduling …

        [B] 구형 flat tags (dt, rl, sim, …, TAG_TO_COLLECTION 기준)
            → 조합 컬렉션: DT + RAG, DT + LLM … (기존 로직 유지)
        """
        from itertools import combinations as _comb

        if not self.zot:
            return "⚠️ Zotero 연결 없음"
        try:
            # ── 0. 기존 컬렉션 전체 로드 ─────────────────────────────────
            all_cols = self.zot.everything(self.zot.collections())
            top_by_name, sub_by_key = _build_col_index(all_cols)

            # ── 1. 모든 논문 로드 ─────────────────────────────────────────
            all_items = [
                i for i in self.zot.everything(self.zot.top())
                if i.get("data", {}).get("itemType") != "attachment"
            ]
            logger.info(f"sync_collections: {len(all_items)} items")

            created_count = 0

            # ── A. 계층형 컬렉션 (Atomic tags) ───────────────────────────
            ATOMIC_PARENTS = {"domain": "Domain", "method": "Method", "problem": "Problem"}

            # 각 논문이 필요한 (parent_display, sub_name) 쌍 수집
            item_atomic: dict[str, set[tuple[str, str]]] = {}
            all_atomic_subs: set[tuple[str, str]] = set()

            for item in all_items:
                data = item["data"]
                needs: set[tuple[str, str]] = set()
                for tag_obj in data.get("tags", []):
                    tag = tag_obj["tag"].strip()
                    if ":" in tag:
                        group, sub = tag.split(":", 1)
                        parent_display = ATOMIC_PARENTS.get(group.lower())
                        if parent_display:
                            needs.add((parent_display, sub))
                            all_atomic_subs.add((parent_display, sub))
                if needs:
                    item_atomic[data["key"]] = needs

            # 부모 컬렉션 (Domain / Method / Problem) 없으면 생성
            for parent_display in ATOMIC_PARENTS.values():
                if parent_display not in top_by_name:
                    resp = self.zot.create_collections([{"name": parent_display, "parentCollection": False}])
                    succ = resp.get("successful", {})
                    if succ:
                        pkey = list(succ.values())[0].get("key", "")
                        if pkey:
                            top_by_name[parent_display] = pkey
                            created_count += 1
                            logger.info(f"Created top collection '{parent_display}' ({pkey})")

            # 자식 컬렉션 없으면 생성
            for (parent_display, sub_name) in sorted(all_atomic_subs):
                pkey = top_by_name.get(parent_display)
                if not pkey:
                    continue
                if (pkey, sub_name) not in sub_by_key:
                    resp = self.zot.create_collections([{"name": sub_name, "parentCollection": pkey}])
                    succ = resp.get("successful", {})
                    if succ:
                        ckey = list(succ.values())[0].get("key", "")
                        if ckey:
                            sub_by_key[(pkey, sub_name)] = ckey
                            created_count += 1
                            logger.info(f"Created sub-collection '{parent_display}/{sub_name}' ({ckey})")

            # 논문 → 자식 컬렉션 할당
            atomic_assigned = 0
            for item in all_items:
                data = item["data"]
                item_key = data["key"]
                if item_key not in item_atomic:
                    continue
                needed_keys: set[str] = set()
                for (parent_display, sub_name) in item_atomic[item_key]:
                    pkey = top_by_name.get(parent_display)
                    if pkey:
                        ckey = sub_by_key.get((pkey, sub_name))
                        if ckey:
                            needed_keys.add(ckey)
                current_keys = set(data.get("collections", []))
                to_add = needed_keys - current_keys
                if to_add:
                    if self._update_collections(item, to_add):
                        atomic_assigned += 1

            # ── A2. Method 조합 컬렉션 (method 태그 2개 이상인 경우) ─────────
            method_parent_key = top_by_name.get("Method")
            method_combo_assigned = 0

            if method_parent_key:
                for item in all_items:
                    data = item["data"]
                    methods = sorted(set(
                        tag_obj["tag"].split(":", 1)[1].strip().lower()
                        for tag_obj in data.get("tags", [])
                        if ":" in tag_obj["tag"]
                        and tag_obj["tag"].split(":", 1)[0].lower() == "method"
                    ))
                    if len(methods) < 2:
                        continue

                    combo_name = " + ".join(methods)
                    if (method_parent_key, combo_name) not in sub_by_key:
                        resp = self.zot.create_collections(
                            [{"name": combo_name, "parentCollection": method_parent_key}]
                        )
                        succ = resp.get("successful", {})
                        if succ:
                            ckey = list(succ.values())[0].get("key", "")
                            if ckey:
                                sub_by_key[(method_parent_key, combo_name)] = ckey
                                created_count += 1
                                logger.info(f"Created method combo 'Method/{combo_name}'")

                    ckey = sub_by_key.get((method_parent_key, combo_name))
                    if not ckey:
                        continue
                    current_keys = set(data.get("collections", []))
                    if ckey not in current_keys:
                        if self._update_collections(item, {ckey}):
                            method_combo_assigned += 1

            # ── B. 조합 컬렉션 (구형 flat tags, TAG_TO_COLLECTION) ────────
            def _short(col_name: str) -> str:
                return COLLECTION_ABBREV.get(col_name, col_name.upper())

            paper_shorts: dict[str, list[str]] = {}
            for item in all_items:
                data = item["data"]
                item_key = data["key"]
                seen_cols: set[str] = set()
                shorts: list[str] = []
                for tag_obj in data.get("tags", []):
                    tag = tag_obj["tag"].lower().strip()
                    if ":" not in tag and tag in TAG_TO_COLLECTION:
                        col = TAG_TO_COLLECTION[tag]
                        if col not in seen_cols:
                            seen_cols.add(col)
                            shorts.append(_short(col))
                if shorts:
                    paper_shorts[item_key] = sorted(set(shorts))

            paper_needed: dict[str, set[str]] = {}
            for item_key, shorts in paper_shorts.items():
                if len(shorts) == 1:
                    paper_needed[item_key] = {shorts[0]}
                else:
                    paper_needed[item_key] = {
                        f"{a} + {b}" for a, b in _comb(sorted(shorts), 2)
                    }

            # flat 컬렉션 없으면 생성 (top-level)
            needed_flat = {n for names in paper_needed.values() for n in names}
            for name in sorted(needed_flat):
                if name not in top_by_name:
                    resp = self.zot.create_collections([{"name": name, "parentCollection": False}])
                    succ = resp.get("successful", {})
                    if succ:
                        ckey = list(succ.values())[0].get("key", "")
                        if ckey:
                            top_by_name[name] = ckey
                            created_count += 1
                            logger.info(f"Created flat collection '{name}' ({ckey})")

            flat_assigned = 0
            for item in all_items:
                data = item["data"]
                item_key = data["key"]
                if item_key not in paper_needed:
                    continue
                needed_keys = {top_by_name[n] for n in paper_needed[item_key] if n in top_by_name}
                current_keys = set(data.get("collections", []))
                to_add = needed_keys - current_keys
                if not to_add:
                    continue
                if self._update_collections(item, to_add):
                    flat_assigned += 1

            # ── 결과 ──────────────────────────────────────────────────────
            lines = ["📚 *Zotero 컬렉션 동기화 완료*"]
            if created_count:
                lines.append(f"✨ 신규 컬렉션 생성: {created_count}개")
            lines.append(f"🗂 계층형 할당 (atomic): {atomic_assigned}편")
            if method_combo_assigned:
                lines.append(f"🔀 method 조합 컬렉션 할당: {method_combo_assigned}편")
            lines.append(f"🗂 조합형 할당 (flat): {flat_assigned}편")
            lines.append(f"📄 전체 논문: {len(all_items)}편")
            return "\n".join(lines)

        except Exception as e:
            logger.error(f"sync_collections_from_tags error: {e}", exc_info=True)
            return f"⚠️ 컬렉션 동기화 오류: {e}"

    def sync_items_collections(self, item_keys: list[str]) -> str:
        """지정된 Zotero 항목에만 컬렉션 동기화. 신규 논문 추가 직후 경량 호출용.

        - atomic tags → Domain/Method/Problem 계층 컬렉션
        - method 태그 2개 이상 → Method/{a + b + ...} 조합 컬렉션
        """
        if not self.zot or not item_keys:
            return "항목 없음"

        ATOMIC_PARENTS = {"domain": "Domain", "method": "Method", "problem": "Problem"}

        try:
            # 컬렉션 인덱스 로드
            all_cols = self.zot.everything(self.zot.collections())
            top_by_name, sub_by_key = _build_col_index(all_cols)

            created_count = 0
            assigned = 0

            for zot_key in item_keys:
                try:
                    item = self.zot.item(zot_key)
                except Exception as e:
                    logger.warning(f"항목 로드 실패 {zot_key}: {e}")
                    continue

                data = item["data"]
                needed_keys: set[str] = set()
                method_vals: list[str] = []

                for tag_obj in data.get("tags", []):
                    tag = tag_obj["tag"].strip()
                    if ":" not in tag:
                        continue
                    group, sub = tag.split(":", 1)
                    parent_display = ATOMIC_PARENTS.get(group.lower())
                    if not parent_display:
                        continue

                    # 부모 컬렉션 없으면 생성
                    if parent_display not in top_by_name:
                        resp = self.zot.create_collections(
                            [{"name": parent_display, "parentCollection": False}]
                        )
                        succ = resp.get("successful", {})
                        if succ:
                            pkey = list(succ.values())[0].get("key", "")
                            if pkey:
                                top_by_name[parent_display] = pkey
                                created_count += 1

                    pkey = top_by_name.get(parent_display)
                    if not pkey:
                        continue

                    # 자식 컬렉션 없으면 생성
                    if (pkey, sub) not in sub_by_key:
                        resp = self.zot.create_collections(
                            [{"name": sub, "parentCollection": pkey}]
                        )
                        succ = resp.get("successful", {})
                        if succ:
                            ckey = list(succ.values())[0].get("key", "")
                            if ckey:
                                sub_by_key[(pkey, sub)] = ckey
                                created_count += 1

                    ckey = sub_by_key.get((pkey, sub))
                    if ckey:
                        needed_keys.add(ckey)

                    if group.lower() == "method":
                        method_vals.append(sub.strip().lower())

                # method 조합 컬렉션
                method_parent_key = top_by_name.get("Method")
                if method_parent_key and len(method_vals) >= 2:
                    combo_name = " + ".join(sorted(set(method_vals)))
                    if (method_parent_key, combo_name) not in sub_by_key:
                        resp = self.zot.create_collections(
                            [{"name": combo_name, "parentCollection": method_parent_key}]
                        )
                        succ = resp.get("successful", {})
                        if succ:
                            ckey = list(succ.values())[0].get("key", "")
                            if ckey:
                                sub_by_key[(method_parent_key, combo_name)] = ckey
                                created_count += 1
                                logger.info(f"Created method combo 'Method/{combo_name}'")
                    ckey = sub_by_key.get((method_parent_key, combo_name))
                    if ckey:
                        needed_keys.add(ckey)

                current_keys = set(data.get("collections", []))
                to_add = needed_keys - current_keys
                if to_add and self._update_collections(item, to_add):
                    assigned += 1

            parts = [f"📚 컬렉션 동기화: {assigned}/{len(item_keys)}편"]
            if created_count:
                parts.append(f"✨ 신규 컬렉션 {created_count}개 생성")
            return " | ".join(parts)

        except Exception as e:
            logger.error(f"sync_items_collections error: {e}", exc_info=True)
            return f"⚠️ 컬렉션 동기화 오류: {e}"

    # ------------------------------------------------------------------ #
    # Landscape analysis                                                  #
    # ------------------------------------------------------------------ #

    def build_landscape(self) -> str:
        """전체 라이브러리를 분석해 landscape/summary.json 을 저장하고 요약 반환."""
        if not self.zot:
            return "⚠️ Zotero 연결 없음"
        try:
            from agents.paper.landscape_builder import build_landscape, save_landscape, format_landscape_message
            data = build_landscape(self.zot)
            path = save_landscape(data)
            return format_landscape_message(data) + f"\n\n💾 저장: `{path}`"
        except Exception as e:
            logger.error(f"build_landscape error: {e}", exc_info=True)
            return f"⚠️ 라이브러리 분석 오류: {e}"

    # ------------------------------------------------------------------ #
    # Tag search                                                          #
    # ------------------------------------------------------------------ #

    def search_by_tags(self, tags: list[str], operator: str = "AND") -> list[dict]:
        """태그 기반 논문 검색.
        AND: 모든 태그를 동시에 가진 논문 (Zotero API 네이티브 지원).
        OR : 하나 이상의 태그를 가진 논문 (클라이언트 측 합집합)."""
        if not self.zot or not tags:
            return []
        try:
            tags_lower = [t.lower().strip() for t in tags]
            if operator.upper() == "AND":
                items = self.zot.items(tag=tags_lower, limit=100, itemType="-attachment")
            else:
                seen: set[str] = set()
                items = []
                for tag in tags_lower:
                    for item in self.zot.items(tag=tag, limit=100, itemType="-attachment"):
                        key = item["data"]["key"]
                        if key not in seen:
                            seen.add(key)
                            items.append(item)
            return [self._parse_item_with_tags(i) for i in items]
        except Exception as e:
            logger.error(f"search_by_tags error: {e}")
            return []

    @staticmethod
    def _parse_item_with_tags(item: dict) -> dict:
        data = item.get("data", {})
        creators = data.get("creators", [])
        authors = ", ".join(
            f"{c.get('lastName', '')} {c.get('firstName', '')}".strip()
            for c in creators[:3]
        )
        tags = [t["tag"] for t in data.get("tags", [])]
        return {
            "title": data.get("title", "Unknown"),
            "authors": authors,
            "year": data.get("date", "")[:4],
            "abstract": data.get("abstractNote", "")[:300],
            "key": data.get("key", ""),
            "url": data.get("url", ""),
            "tags": tags,
        }

    def _update_collections(self, item: dict, to_add: set[str]) -> bool:
        """item에 컬렉션 키를 추가. 412 버전 충돌 시 최신 버전 재로딩 후 1회 재시도."""
        for attempt in range(2):
            try:
                current_keys = set(item["data"].get("collections", []))
                updated = copy.deepcopy(item)
                updated["data"]["collections"] = sorted(current_keys | to_add)
                self.zot.update_item(updated)
                return True
            except Exception as e:
                if attempt == 0 and "412" in str(e):
                    try:
                        item = self.zot.item(item["data"]["key"])
                    except Exception:
                        return False
                else:
                    logger.warning(f"update_item failed for {item['data'].get('key')}: {e}")
                    return False
        return False

    def _download_pdf(self, arxiv_id: str) -> Path | None:
        if not _REQUESTS_OK or not arxiv_id:
            return None
        PDF_DIR.mkdir(parents=True, exist_ok=True)
        dest = PDF_DIR / f"{arxiv_id}.pdf"
        if dest.exists():
            return dest
        try:
            resp = _requests.get(
                _ARXIV_PDF.format(arxiv_id=arxiv_id),
                timeout=60,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            logger.info(f"PDF saved: {dest} ({len(resp.content):,} bytes)")
            return dest
        except Exception as e:
            logger.warning(f"PDF download failed for {arxiv_id}: {e}")
            return None

    def _attach_pdf(self, item_key: str, pdf_path: Path, title: str):
        attachment = {
            "itemType": "attachment",
            "parentItem": item_key,
            "linkMode": "linked_file",
            "title": f"{title[:60]}.pdf",
            "path": str(pdf_path),
            "contentType": "application/pdf",
            "tags": [],
            "relations": {},
        }
        self.zot.create_items([attachment])

    @staticmethod
    def _build_preprint(paper: dict) -> dict:
        creators = []
        for name in paper.get("authors", []):
            parts = name.rsplit(" ", 1)
            if len(parts) == 2:
                creators.append({"creatorType": "author", "firstName": parts[0], "lastName": parts[1]})
            else:
                creators.append({"creatorType": "author", "name": name})

        arxiv_id = paper.get("arxiv_id", "")
        link = paper.get("link", "")
        if arxiv_id and "arxiv.org" not in link:
            link = f"https://arxiv.org/abs/{arxiv_id}"

        return {
            "itemType": "preprint",
            "title": paper.get("title", ""),
            "creators": creators,
            "abstractNote": paper.get("abstract", paper.get("summary", ""))[:2000],
            "repository": "arXiv",
            "archiveID": f"arXiv:{arxiv_id}" if arxiv_id else "",
            "date": paper.get("published", paper.get("year", datetime.now(timezone.utc).strftime("%Y-%m-%d"))),
            "url": link,
            "accessDate": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "tags": [{"tag": t} for t in paper.get("tags", paper.get("keywords", []))],
            "collections": [],
            "relations": {},
        }

    @staticmethod
    def _parse_item(item: dict) -> dict:
        data = item.get("data", {})
        creators = data.get("creators", [])
        authors = ", ".join(
            f"{c.get('lastName', '')} {c.get('firstName', '')}".strip()
            for c in creators[:3]
        )
        return {
            "title": data.get("title", "Unknown"),
            "authors": authors,
            "year": data.get("date", "")[:4],
            "abstract": data.get("abstractNote", "")[:500],
            "key": data.get("key", ""),
            "url": data.get("url", ""),
        }
