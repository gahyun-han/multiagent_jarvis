"""
NotebookLM uploader — Zotero 컬렉션/라이브러리 논문 URL을 NotebookLM 소스로 추가.
인증 파일: ~/.notebooklm/profiles/default/storage_state.json
최초 1회: PaperRadar venv에서 `notebooklm login` 실행 필요.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

NLM_TITLE_PREFIX = "PaperRadar"


async def _upload_urls(urls: list[str], notebook_title: str = "PaperRadar — AI/DT 논문") -> tuple[int, list[str]]:
    try:
        from notebooklm import NotebookLMClient
        from notebooklm.exceptions import NotebookLMError, AuthError
    except ImportError:
        return 0, ["notebooklm-py 미설치: pip install 'notebooklm-py[browser]'"]

    if not urls:
        return 0, []

    added = 0
    errors = []

    try:
        async with NotebookLMClient.from_storage() as client:
            notebooks = await client.notebooks.list()
            notebook = next((nb for nb in notebooks if nb.title == notebook_title), None)
            if notebook is None:
                notebook = await client.notebooks.create(title=notebook_title)
                logger.info(f"NotebookLM 노트북 생성: {notebook_title}")
            else:
                logger.info(f"NotebookLM 기존 노트북 사용: {notebook.id} ({notebook_title})")

            for url in urls:
                try:
                    await client.sources.add_url(notebook_id=notebook.id, url=url, wait=False)
                    added += 1
                except NotebookLMError as e:
                    errors.append(f"{url[:60]}: {e}")

    except AuthError:
        return 0, ["NotebookLM 인증 필요: `notebooklm login` 실행 후 재시도"]
    except Exception as e:
        return 0, [f"NotebookLM 연결 실패: {e}"]

    return added, errors


def upload_urls(urls: list[str], notebook_title: str = "PaperRadar — AI/DT 논문") -> tuple[int, list[str]]:
    return asyncio.run(_upload_urls(urls, notebook_title=notebook_title))


def upload_papers(papers: list[dict], notebook_title: str = "PaperRadar — AI/DT 논문") -> tuple[int, list[str]]:
    """papers: list of dicts with 'url' or 'link' key."""
    urls = [p.get("url") or p.get("link", "") for p in papers]
    urls = [u for u in urls if u]
    return upload_urls(urls, notebook_title=notebook_title)
