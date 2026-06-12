"""
Router — receives an Intent and dispatches to the correct agent.
Immediate intents are handled inline; ambiguous intents get an inline keyboard.
"""
import logging
import uuid
from orchestrator.intent_classifier import IntentClassifier, Intent
from systems.telegram_sender import TelegramSender
from systems.usage_manager import UsageManager
from systems.error_recovery import ErrorRecovery
from systems.error_memory import ErrorMemory

logger = logging.getLogger(__name__)

# 미확정 intent 임시 저장 (callback 버튼 응답 대기)
_pending: dict[str, Intent] = {}


def store_pending(intent: Intent) -> str:
    pid = str(uuid.uuid4())[:8]
    _pending[pid] = intent
    return pid


def pop_pending(pid: str) -> Intent | None:
    return _pending.pop(pid, None)


class Router:
    def __init__(self):
        self.classifier = IntentClassifier()
        self.sender = TelegramSender()
        self.usage = UsageManager()
        self.error_recovery = ErrorRecovery()
        self.error_memory = ErrorMemory()

    async def route(self, message: str, chat_id: int, user_id: int, message_id: int):
        try:
            intent = await self.classifier.classify(message)
            logger.info(f"Intent: domain={intent.domain} urgency={intent.urgency} conf={intent.confidence:.2f}")

            if intent.action == "clarify":
                await self._ask_urgency(intent, chat_id)
            elif intent.urgency == "immediate":
                await self._dispatch_immediate(intent, chat_id)
            else:
                await self._dispatch_backlog(intent, chat_id)
        except Exception as e:
            await self.error_recovery.handle(e, chat_id=chat_id, context="route")

    async def _dispatch_immediate(self, intent: Intent, chat_id: int):
        if not self.usage.has_budget():
            await self.sender.send(chat_id, "⚠️ 현재 Claude 토큰 예산이 부족합니다. 잠시 후 다시 시도해주세요.")
            return
        try:
            intent.chat_id = chat_id  # agent가 백그라운드 완료 알림에 사용
            intent.error_hints = self.error_memory.load_relevant(intent.domain)
            agent = self._get_agent(intent.domain)
            if agent is None:
                await self.sender.send(chat_id, f"❓ 처리할 수 없는 요청입니다: {intent.summary}")
                return
            result = await agent.handle(intent)
            await self.sender.send(chat_id, result)
            self.usage.record_usage(intent.domain, tokens_used=500)
        except Exception as e:
            await self.error_recovery.handle(e, chat_id=chat_id, context=f"immediate:{intent.domain}")

    async def _dispatch_backlog(self, intent: Intent, chat_id: int):
        try:
            from agents.inbox_trage.trage_agent import TriageAgent
            triage = TriageAgent(sender=self.sender)
            await triage.handle(intent, chat_id=chat_id)
        except Exception as e:
            await self.error_recovery.handle(e, chat_id=chat_id, context="backlog")

    async def _ask_urgency(self, intent: Intent, chat_id: int):
        """백로그 여부가 불확실할 때 인라인 버튼으로 사용자에게 직접 물어봄."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        pid = store_pending(intent)
        preview = intent.summary[:60] if intent.summary else intent.raw_message[:60]

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚡ 지금 바로", callback_data=f"now:{pid}"),
                InlineKeyboardButton("📋 나중에", callback_data=f"later:{pid}"),
            ]
        ])
        await self.sender.send_with_reply_markup(
            chat_id,
            f"📌 {preview}\n\n지금 처리할까요, 나중에 할까요?",
            reply_markup=keyboard,
        )

    async def handle_callback(self, action: str, pid: str, chat_id: int):
        """인라인 버튼 콜백 처리."""
        intent = pop_pending(pid)
        if intent is None:
            await self.sender.send(chat_id, "⚠️ 만료된 요청입니다. 다시 보내주세요.")
            return
        if action == "now":
            await self._dispatch_immediate(intent, chat_id)
        else:
            await self._dispatch_backlog(intent, chat_id)

    def _get_agent(self, domain: str):
        if domain == "calendar":
            from agents.calendar.calendar_agent import CalendarAgent
            return CalendarAgent()
        if domain == "paper":
            from agents.paper.paper_agent import PaperAgent
            return PaperAgent()
        if domain == "finance":
            from agents.finance.finance_agent import FinanceAgent
            return FinanceAgent()
        if domain == "dev":
            from agents.dev.dev_agent import DevAgent
            return DevAgent()
        if domain == "usage":
            from agents.usage.usage_agent import UsageAgent
            return UsageAgent()
        if domain == "backlog":
            from agents.backlog.backlog_agent import BacklogAgent
            return BacklogAgent()
        if domain == "youtube":
            from agents.youtube.youtube_agent import YouTubeAgent
            return YouTubeAgent()
        if domain in ("triage", "unknown"):
            from agents.general.general_agent import GeneralAgent
            return GeneralAgent()
        return None
