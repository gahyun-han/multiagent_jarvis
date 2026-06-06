"""
NotebookLM uploader + query — Zotero 컬렉션 논문을 NotebookLM에 올리고
정해진 질문으로 분석 결과를 받아온다.

인증 파일: ~/.notebooklm/profiles/default/storage_state.json
최초 1회: `notebooklm login` 실행 필요.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

ANALYSIS_QUESTION = """이 논문들을 분석하여 다음 형식으로 정리해줘.
1. 공통적으로 해결하려는 문제
2. 논문별 해결 방법
3. 논문별 장점
4. 논문별 한계점
5. 남아있는 연구 공백(Research Gap)"""


async def _get_or_create_notebook(client, notebook_title: str):
    notebooks = await client.notebooks.list()
    notebook = next((nb for nb in notebooks if nb.title == notebook_title), None)
    if notebook is None:
        notebook = await client.notebooks.create(title=notebook_title)
        logger.info(f"NotebookLM 노트북 생성: {notebook_title}")
    else:
        logger.info(f"NotebookLM 기존 노트북 사용: {notebook.id}")
    return notebook


async def _upload_urls(
    urls: list[str],
    notebook_title: str = "PaperRadar — AI/DT 논문",
    ask_question: bool = False,
) -> tuple[int, list[str], str | None]:
    """논문 URL을 NotebookLM에 업로드하고 선택적으로 분석 질문을 던진다.

    Returns:
        (added_count, errors, answer_or_None)
    """
    try:
        from notebooklm import NotebookLMClient
        from notebooklm.exceptions import NotebookLMError, AuthError
    except ImportError:
        return 0, ["notebooklm-py 미설치: pip install 'notebooklm-py[browser]'"], None

    if not urls:
        return 0, [], None

    added = 0
    errors: list[str] = []
    new_sources = []

    try:
        async with NotebookLMClient.from_storage() as client:
            notebook = await _get_or_create_notebook(client, notebook_title)

            # 기존 소스 URL 수집 (중복 방지)
            existing = await client.sources.list(notebook.id)
            existing_urls = {s.url for s in existing if s.url}

            for url in urls:
                if url in existing_urls:
                    logger.debug(f"이미 존재: {url[:60]}")
                    continue
                try:
                    source = await client.sources.add_url(
                        notebook.id, url, wait=False
                    )
                    new_sources.append(source)
                    added += 1
                except NotebookLMError as e:
                    errors.append(f"{url[:60]}: {e}")

            answer: str | None = None
            if ask_question:
                # 새로 추가된 소스가 있으면 처리 완료 대기
                if new_sources:
                    logger.info(f"{len(new_sources)}개 소스 처리 대기 중…")
                    wait_tasks = [
                        client.sources.wait_until_ready(
                            notebook.id, s.id, timeout=300
                        )
                        for s in new_sources
                    ]
                    results = await asyncio.gather(*wait_tasks, return_exceptions=True)
                    for r in results:
                        if isinstance(r, Exception):
                            logger.warning(f"소스 대기 오류: {r}")

                # 소스가 하나라도 있을 때만 질문
                all_sources = await client.sources.list(notebook.id)
                if all_sources:
                    logger.info("NotebookLM에 분석 질문 전송 중…")
                    result = await client.chat.ask(notebook.id, ANALYSIS_QUESTION)
                    answer = result.answer
                    logger.info("분석 답변 수신 완료")
                else:
                    logger.warning("질문 가능한 소스 없음")

    except AuthError:
        return 0, ["NotebookLM 인증 필요: `notebooklm login` 실행 후 재시도"], None
    except Exception as e:
        return 0, [f"NotebookLM 연결 실패: {e}"], None

    return added, errors, answer


def upload_urls(
    urls: list[str],
    notebook_title: str = "PaperRadar — AI/DT 논문",
    ask_question: bool = False,
) -> tuple[int, list[str], str | None]:
    return asyncio.run(_upload_urls(urls, notebook_title=notebook_title, ask_question=ask_question))


def upload_papers(
    papers: list[dict],
    notebook_title: str = "PaperRadar — AI/DT 논문",
    ask_question: bool = False,
) -> tuple[int, list[str], str | None]:
    """papers: list of dicts with 'url' or 'link' key."""
    urls = [p.get("url") or p.get("link", "") for p in papers]
    urls = [u for u in urls if u]
    return upload_urls(urls, notebook_title=notebook_title, ask_question=ask_question)


async def query_existing_notebook(notebook_title: str) -> str | None:
    """이미 업로드된 노트북에 분석 질문만 던진다."""
    try:
        from notebooklm import NotebookLMClient
        from notebooklm.exceptions import AuthError
    except ImportError:
        return None

    try:
        async with NotebookLMClient.from_storage() as client:
            notebooks = await client.notebooks.list()
            notebook = next((nb for nb in notebooks if nb.title == notebook_title), None)
            if not notebook:
                logger.warning(f"노트북 없음: {notebook_title}")
                return None
            result = await client.chat.ask(notebook.id, ANALYSIS_QUESTION)
            return result.answer
    except AuthError:
        return None
    except Exception as e:
        logger.error(f"query_existing_notebook error: {e}", exc_info=True)
        return None
