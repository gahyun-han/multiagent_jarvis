"""
General agent — handles unclassified immediate requests.
If the message references a known external project, injects its file tree
and relevant file contents so Claude has real context.
"""
import asyncio
import logging
import re
from pathlib import Path
from systems.claude_runner import async_ask as claude_ask

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXTERNAL_DIR = PROJECT_ROOT / "external"

_SYSTEM = """
You are Jarvis, a personal AI assistant. Answer the user's question or request directly and concisely in Korean only. Do not provide English analysis followed by Korean translation — respond in Korean from the start.
""".strip()


class GeneralAgent:
    async def handle(self, intent) -> str:
        message = intent.raw_message
        chat_id = getattr(intent, "chat_id", 0)
        logger.info(f"GeneralAgent handling: {message[:60]}")

        context = self._build_context(message)
        prompt = f"{context}\n\n{message}".strip() if context else message

        asyncio.create_task(self._bg_ask(prompt, chat_id))
        return "🤔 분석 중입니다. 완료 시 답변을 보내드릴게요."

    async def _bg_ask(self, prompt: str, chat_id: int):
        from systems.telegram_sender import TelegramSender
        sender = TelegramSender()
        try:
            result = await claude_ask(prompt, system=_SYSTEM, max_tokens=1024, no_tools=True)
            if chat_id:
                await sender.send_chunks(chat_id, result)
        except Exception as e:
            logger.error(f"GeneralAgent bg_ask failed: {e}")
            if chat_id:
                await sender.send(chat_id, f"⚠️ 처리 중 오류가 발생했습니다: {e}")

    def _build_context(self, message: str) -> str:
        """메시지에 외부 프로젝트 언급이 있으면 파일 구조와 main.py를 컨텍스트로 추가."""
        if not EXTERNAL_DIR.exists():
            return ""

        for proj_dir in EXTERNAL_DIR.iterdir():
            if proj_dir.name.lower() in message.lower():
                real = proj_dir.resolve()
                lines = [f"[프로젝트: {proj_dir.name}]"]
                # 파일 목록
                py_files = sorted(real.rglob("*.py"))
                lines.append("파일 목록: " + ", ".join(
                    str(f.relative_to(real)) for f in py_files
                    if "__pycache__" not in str(f)
                ))
                # main.py 내용 첨부 (있으면)
                main = real / "main.py"
                if main.exists():
                    content = main.read_text(encoding="utf-8")[:2000]
                    lines.append(f"\nmain.py:\n```python\n{content}\n```")
                return "\n".join(lines)

        return ""
