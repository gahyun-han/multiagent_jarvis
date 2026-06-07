"""
Dev agent — code review, debugging help, architecture advice.
Also dispatches autotest requests to AutoTestAgent.
"""
import re
import logging
from pathlib import Path
from systems.claude_runner import async_ask as claude_ask

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_AUTOTEST_TRIGGERS = ["autotest", "자동 테스트", "자동테스트", "테스트 자동화"]

# .py 경로가 포함된 메시지에서 수정 요청 감지
_FIX_TRIGGERS = ["수정", "고쳐", "변경", "추가해줘", "제거해줘", "삭제해줘", "바꿔줘", "fix", "refactor"]

# 프로젝트 실행 요청 감지
_RUN_TRIGGERS = ["실행", "돌려줘", "실행해줘", "돌려", "run", "실행시켜"]
_KNOWN_PROJECTS = ["TrendNotifier", "PaperRadar", "Stock-agent", "techTerminologyRadar",
                   "UserCustomStockinfo_agent", "트렌드", "주식", "논문레이더",
                   "itTerminology", "ItTerminology", "itterminology", "it용어", "용어레이더", "terminology"]

_SYSTEM = """
You are a senior software engineer assistant integrated into Jarvis.
Reply in Korean unless the user writes in English.
Help with: code review, debugging, architecture, best practices, PR descriptions.
When showing code, use markdown code blocks with language tags.
Be direct and practical. Highlight the most important issues first.
""".strip()


class DevAgent:
    async def handle(self, intent) -> str:
        message = intent.raw_message

        if any(t in message.lower() for t in _AUTOTEST_TRIGGERS):
            return await self._run_autotest(message)

        # 프로젝트 이름 + 실행 키워드 → RunAgent
        if any(p.lower() in message.lower() for p in _KNOWN_PROJECTS) and \
           any(t in message for t in _RUN_TRIGGERS):
            return await self._run_project(intent)

        # .py 경로 + 수정 키워드 → FixAgent
        if re.search(r"[\w/\-~]+\.py", message) and any(t in message for t in _FIX_TRIGGERS):
            return await self._run_fix(intent)

        try:
            return await claude_ask(message, system=_SYSTEM, max_tokens=2048, no_tools=True)
        except Exception as e:
            logger.error(f"DevAgent error: {e}")
            return f"💻 개발 도움 처리 중 오류: {e}"

    async def _run_autotest(self, message: str) -> str:
        from agents.dev.autotest_agent import AutoTestAgent
        match = re.search(r"(agents/[\w/]+\.py|systems/[\w/]+\.py)", message)
        if not match:
            return (
                "⚠️ 테스트할 파일 경로를 포함해 주세요.\n"
                "예: `autotest agents/finance/ledger_parser.py`"
            )
        return await AutoTestAgent().run(PROJECT_ROOT / match.group(1))

    async def _run_fix(self, intent) -> str:
        from agents.dev.fix_agent import FixAgent
        return await FixAgent().handle(intent)

    async def _run_project(self, intent) -> str:
        from agents.dev.run_agent import RunAgent
        return await RunAgent().handle(intent)
