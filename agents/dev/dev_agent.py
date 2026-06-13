"""
Dev agent — code review, debugging help, architecture advice.
Also dispatches autotest requests to AutoTestAgent.
"""
import re
import asyncio
import logging
from pathlib import Path
from systems.claude_runner import async_ask as claude_ask

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_AUTOTEST_TRIGGERS = ["autotest", "자동 테스트", "자동테스트", "테스트 자동화"]
# 개념 설명/비교 질문은 autotest 실행이 아닌 일반 답변으로
_CONCEPT_SIGNALS = ["차이", "비교", "개념", "설명", "뭐야", "뭔지", "어떤 차이", "어떻게 달라",
                    "관심있", "알려줘", "무엇", "what is", "difference", "compare"]

# .py 경로가 포함된 메시지에서 수정 요청 감지
_FIX_TRIGGERS = ["수정", "고쳐", "변경", "추가해줘", "제거해줘", "삭제해줘", "바꿔줘", "fix", "refactor"]

# 프로젝트 실행 요청 감지
_RUN_TRIGGERS = ["실행", "돌려줘", "실행해줘", "돌려", "run", "실행시켜"]
_KNOWN_PROJECTS = ["TrendNotifier", "PaperRadar", "Stock-agent", "techTerminologyRadar",
                   "UserCustomStockinfo_agent", "트렌드", "주식", "논문레이더",
                   "itTerminology", "ItTerminology", "itterminology", "it용어", "용어레이더", "terminology"]

_SYSTEM = """
You are a senior software engineer assistant integrated into Jarvis.
Reply in Korean only. Do not provide English analysis followed by Korean translation — respond in Korean from the start.
Help with: code review, debugging, architecture, best practices, PR descriptions.
When showing code, use markdown code blocks with language tags.
Be direct and practical. Highlight the most important issues first.
""".strip()


class DevAgent:
    async def handle(self, intent) -> str:
        message = intent.raw_message

        chat_id = getattr(intent, "chat_id", 0)
        msg_lower = message.lower()
        is_concept = any(s in msg_lower for s in _CONCEPT_SIGNALS)
        if any(t in msg_lower for t in _AUTOTEST_TRIGGERS) and not is_concept:
            if not re.search(r"(agents/[\w/]+\.py|systems/[\w/]+\.py)", message):
                return (
                    "⚠️ 테스트할 파일 경로를 포함해 주세요.\n"
                    "예: `autotest agents/finance/ledger_parser.py`"
                )
            asyncio.create_task(self._bg_run(self._run_autotest, message, chat_id))
            return "🧪 자동 테스트 생성을 시작합니다. 완료 시 결과를 보내드릴게요."

        # 프로젝트 이름 + 실행 키워드 → RunAgent
        if any(p.lower() in message.lower() for p in _KNOWN_PROJECTS) and \
           any(t in message for t in _RUN_TRIGGERS):
            asyncio.create_task(self._bg_run(self._run_project, intent, chat_id))
            return "🚀 프로젝트 실행을 시작합니다. 완료 시 결과를 보내드릴게요."

        # .py 경로 + 수정 키워드 → FixAgent
        if re.search(r"[\w/\-~]+\.py", message) and any(t in message for t in _FIX_TRIGGERS):
            asyncio.create_task(self._bg_run(self._run_fix, intent, chat_id))
            return "🔧 코드 수정을 시작합니다. 완료 시 결과를 보내드릴게요."

        chat_id = getattr(intent, "chat_id", 0)
        asyncio.create_task(self._bg_dev_ask(message, chat_id))
        return "💻 분석 중입니다. 완료 시 답변을 보내드릴게요."

    async def _bg_dev_ask(self, message: str, chat_id: int):
        from systems.telegram_sender import TelegramSender
        sender = TelegramSender()
        try:
            result = await claude_ask(message, system=_SYSTEM, max_tokens=2048, no_tools=True)
            if chat_id:
                await sender.send_chunks(chat_id, result)
        except Exception as e:
            logger.error(f"DevAgent bg error: {e}")
            if chat_id:
                await sender.send(chat_id, f"💻 개발 도움 처리 중 오류: {e}")

    async def _bg_run(self, fn, arg, chat_id: int):
        """범용 백그라운드 래퍼 — fn(arg)를 실행하고 완료 시 Telegram 전송."""
        from systems.telegram_sender import TelegramSender
        sender = TelegramSender()
        try:
            result = await fn(arg)
            if chat_id and result:
                await sender.send_chunks(chat_id, result)
        except Exception as e:
            logger.error(f"DevAgent bg_run error: {e}")
            if chat_id:
                await sender.send(chat_id, f"⚠️ 처리 중 오류: {e}")

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
