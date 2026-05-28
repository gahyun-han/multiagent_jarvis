"""
Router — receives an Intent and dispatches to the correct agent.
Immediate intents are handled inline; backlog intents are queued.
"""
import logging
from orchestrator.intent_classifier import IntentClassifier, Intent
from systems.telegram_sender import TelegramSender
from systems.usage_manager import UsageManager
from systems.error_recovery import ErrorRecovery

logger = logging.getLogger(__name__)


class Router:
    def __init__(self):
        self.classifier = IntentClassifier()
        self.sender = TelegramSender()
        self.usage = UsageManager()
        self.error_recovery = ErrorRecovery()

    async def route(self, message: str, chat_id: int, user_id: int, message_id: int):
        intent = self.classifier.classify(message)
        logger.info(f"Intent: domain={intent.domain} urgency={intent.urgency} conf={intent.confidence:.2f}")

        if intent.urgency == "immediate":
            await self._dispatch_immediate(intent, chat_id)
        else:
            await self._dispatch_backlog(intent, chat_id)

    async def _dispatch_immediate(self, intent: Intent, chat_id: int):
        if not self.usage.has_budget():
            await self.sender.send(
                chat_id,
                "⚠️ 현재 Claude 토큰 예산이 부족합니다. 잠시 후 다시 시도해주세요.",
            )
            return

        try:
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
        from agents.inbox_trage.trage_agent import TriageAgent
        triage = TriageAgent(sender=self.sender)
        await triage.handle(intent, chat_id=chat_id)

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
        if domain in ("triage", "unknown"):
            return None
        return None
