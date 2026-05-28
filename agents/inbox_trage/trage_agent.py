"""
Triage agent — main entry point for backlog items.
Flow: classify → score → queue_writer → telegram confirm
"""
import logging
from orchestrator.intent_classifier import Intent
from agents.inbox_trage.classifier import TriageClassifier
from agents.inbox_trage.priority_scorer import PriorityScorer
from agents.inbox_trage.queue_writer import QueueWriter
from systems.telegram_sender import TelegramSender

logger = logging.getLogger(__name__)


class TriageAgent:
    def __init__(self, sender: TelegramSender = None):
        self.classifier = TriageClassifier()
        self.scorer = PriorityScorer()
        self.queue_writer = QueueWriter()
        self.sender = sender or TelegramSender()

    async def handle(self, intent: Intent, chat_id: int):
        try:
            category = self.classifier.classify(intent.raw_message, intent.domain)
            score = self.scorer.score(intent.raw_message, category)
            entry = self.queue_writer.write(
                message=intent.raw_message,
                summary=intent.summary,
                domain=intent.domain,
                category=category,
                priority=score,
            )
            label = self._priority_label(score)
            await self.sender.send(
                chat_id,
                f"✅ 백로그에 저장했습니다.\n"
                f"📌 *{intent.summary}*\n"
                f"분류: `{category}` | 우선순위: {label} ({score}/10)\n"
                f"ID: `{entry['id']}`",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"TriageAgent error: {e}", exc_info=True)
            await self.sender.send(chat_id, f"⚠️ 백로그 저장 중 오류가 발생했습니다: {e}")

    @staticmethod
    def _priority_label(score: int) -> str:
        if score >= 8:
            return "🔴 높음"
        if score >= 5:
            return "🟡 보통"
        return "🟢 낮음"
