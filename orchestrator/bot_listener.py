"""
Telegram bot listener — entry point for all incoming messages.
Receives messages and passes them to the router.
"""
import os
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from dotenv import load_dotenv

from orchestrator.router import Router
from systems.telegram_sender import TelegramSender
from systems.error_recovery import ErrorRecovery

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

ALLOWED_USER_IDS = set(
    int(uid.strip())
    for uid in os.getenv("ALLOWED_TELEGRAM_USER_IDS", "").split(",")
    if uid.strip()
)


class BotListener:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN not set")
        self.router = Router()
        self.error_recovery = ErrorRecovery()
        self.app = Application.builder().token(self.token).build()
        self._register_handlers()

    def _register_handlers(self):
        self.app.add_handler(CommandHandler("start", self._handle_start))
        self.app.add_handler(CommandHandler("help", self._handle_help))
        self.app.add_handler(CommandHandler("status", self._handle_status))
        self.app.add_handler(CommandHandler("backlog", self._handle_backlog))
        self.app.add_handler(CommandHandler("assets", self._handle_assets))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message))

    def _is_allowed(self, user_id: int) -> bool:
        if not ALLOWED_USER_IDS:
            return True
        return user_id in ALLOWED_USER_IDS

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update.effective_user.id):
            return
        await update.message.reply_text(
            "안녕하세요! Jarvis입니다. 무엇을 도와드릴까요?\n"
            "/help 로 사용 가능한 명령어를 확인하세요."
        )

    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update.effective_user.id):
            return
        help_text = (
            "📋 *Jarvis 사용 가능 기능*\n\n"
            "• 일정 관련: '내일 오후 3시 회의 잡아줘'\n"
            "• 논문 정리: '최근 추가한 논문 요약해줘'\n"
            "• 가계부: '이번 달 지출 현황 알려줘'\n"
            "• 할 일 등록: '나중에 블로그 글 써야 해'\n"
            "• 개발 도움: '이 코드 리뷰해줘'\n\n"
            "긴급하지 않은 요청은 백로그에 저장되어 나중에 처리됩니다."
        )
        await update.message.reply_text(help_text, parse_mode="Markdown")

    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update.effective_user.id):
            return
        from systems.usage_manager import UsageManager
        usage = UsageManager()
        summary = usage.get_status_summary()
        await update.message.reply_text(summary)

    async def _handle_backlog(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update.effective_user.id):
            return
        from agents.inbox_trage.queue_writer import QueueWriter
        queue = QueueWriter()
        pending = queue.get_pending(limit=20)
        if not pending:
            await update.message.reply_text("📭 백로그가 비어 있습니다.")
            return
        lines = [f"📋 *백로그 ({len(pending)}건)*\n"]
        for i, item in enumerate(pending, 1):
            label = "🔴" if item["priority"] >= 8 else "🟡" if item["priority"] >= 5 else "🟢"
            lines.append(
                f"{i}. {label} `[{item['domain']}]` {item['summary']}\n"
                f"   ID: `{item['id']}` | 우선순위: {item['priority']}/10"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _handle_assets(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update.effective_user.id):
            return
        from agents.finance.asset_manager import AssetManager
        summary = AssetManager().net_worth_summary()
        await update.message.reply_text("💼 *전체 자산 현황*\n\n" + summary, parse_mode="Markdown")

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update.effective_user.id):
            logger.warning(f"Unauthorized access attempt from user {update.effective_user.id}")
            return

        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        text = update.message.text
        logger.info(f"Message from {user_id}: {text[:80]}")

        try:
            await self.router.route(
                message=text,
                chat_id=chat_id,
                user_id=user_id,
                message_id=update.message.message_id,
            )
        except Exception as e:
            logger.error(f"Unhandled error routing message: {e}", exc_info=True)
            await self.error_recovery.handle(e, chat_id=chat_id, context="bot_listener")

    def run(self):
        logger.info("Jarvis bot starting...")
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    BotListener().run()
