"""
Error recovery — classifies errors, attempts auto-recovery, notifies via Telegram.
"""
import logging
import traceback
from enum import Enum

logger = logging.getLogger(__name__)


CLAUDE_HANGABOT = "@Claude_hangabot"


class ErrorKind(Enum):
    CREDIT_EXHAUSTED = "credit_exhausted"
    RATE_LIMIT = "rate_limit"
    NETWORK = "network"
    AUTH = "auth"
    DATA = "data"
    UNKNOWN = "unknown"


class ErrorRecovery:
    def classify(self, exc: Exception) -> ErrorKind:
        import asyncio
        if isinstance(exc, asyncio.TimeoutError):
            return ErrorKind.NETWORK
        msg = str(exc).lower()
        if "credit balance is too low" in msg or "credit" in msg and "low" in msg:
            return ErrorKind.CREDIT_EXHAUSTED
        if "rate limit" in msg or "429" in msg:
            return ErrorKind.RATE_LIMIT
        if "network" in msg or "connection" in msg or "timeout" in msg:
            return ErrorKind.NETWORK
        if "auth" in msg or "403" in msg or "401" in msg or "token" in msg:
            return ErrorKind.AUTH
        if "json" in msg or "key" in msg or "index" in msg:
            return ErrorKind.DATA
        return ErrorKind.UNKNOWN

    async def handle(self, exc: Exception, chat_id: int = None, context: str = ""):
        kind = self.classify(exc)
        tb = traceback.format_exc()
        logger.error(f"[{kind.value}] Error in {context}: {exc}\n{tb}")

        _solutions = {
            ErrorKind.CREDIT_EXHAUSTED: "API 크레딧 소진 — @Claude_hangabot으로 직접 요청",
            ErrorKind.RATE_LIMIT: "API 요청 한도 도달 — 잠시 후 재시도",
            ErrorKind.NETWORK: "응답 시간 초과 — 요청을 더 작게 나누거나 재시도",
            ErrorKind.AUTH: "인증 오류 — API 키 확인 필요",
            ErrorKind.DATA: f"데이터 처리 오류: {str(exc)[:80]}",
            ErrorKind.UNKNOWN: f"알 수 없는 오류: {str(exc)[:80]}",
        }
        try:
            from systems.error_memory import ErrorMemory
            ErrorMemory().save(kind.value, context, _solutions.get(kind, str(exc)[:80]))
        except Exception as mem_exc:
            logger.warning(f"Failed to save error memory: {mem_exc}")

        if chat_id is None:
            return

        from systems.telegram_sender import TelegramSender
        sender = TelegramSender()

        messages = {
            ErrorKind.CREDIT_EXHAUSTED: (
                f"💳 *Jarvis API 크레딧 소진*\n"
                f"이 요청은 AI 처리가 필요해서 Jarvis가 처리할 수 없어요.\n\n"
                f"👉 {CLAUDE_HANGABOT} 으로 같은 내용을 보내주세요."
            ),
            ErrorKind.RATE_LIMIT: "⏳ Claude API 요청 한도 도달. 잠시 후 자동 재시도합니다.",
            ErrorKind.NETWORK: "⏱️ 응답 시간 초과 (95초). Claude CLI가 오래 걸리고 있습니다. 잠시 후 다시 시도해주세요.",
            ErrorKind.AUTH: "🔑 인증 오류입니다. API 키를 확인해주세요.",
            ErrorKind.DATA: f"📋 데이터 처리 오류: `{exc}`",
            ErrorKind.UNKNOWN: f"⚠️ 오류 발생 [{context}]: `{exc}`",
        }
        try:
            await sender.send(chat_id, messages.get(kind, str(exc)))
        except Exception as send_exc:
            logger.critical(f"Failed to send error notification to {chat_id}: {send_exc}")
