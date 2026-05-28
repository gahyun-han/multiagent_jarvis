"""
Error recovery — classifies errors, attempts auto-recovery, notifies via Telegram.
"""
import logging
import traceback
from enum import Enum

logger = logging.getLogger(__name__)


class ErrorKind(Enum):
    RATE_LIMIT = "rate_limit"
    NETWORK = "network"
    AUTH = "auth"
    DATA = "data"
    UNKNOWN = "unknown"


class ErrorRecovery:
    def classify(self, exc: Exception) -> ErrorKind:
        msg = str(exc).lower()
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

        if chat_id is None:
            return

        from systems.telegram_sender import TelegramSender
        sender = TelegramSender()

        messages = {
            ErrorKind.RATE_LIMIT: "⏳ Claude API 요청 한도에 도달했습니다. 잠시 후 자동으로 재시도합니다.",
            ErrorKind.NETWORK: "🌐 네트워크 오류가 발생했습니다. 인터넷 연결을 확인해주세요.",
            ErrorKind.AUTH: "🔑 인증 오류입니다. API 키를 확인해주세요.",
            ErrorKind.DATA: f"📋 데이터 처리 오류: `{exc}`",
            ErrorKind.UNKNOWN: f"⚠️ 예상치 못한 오류 발생 [{context}]: `{exc}`",
        }
        await sender.send(chat_id, messages.get(kind, str(exc)))
