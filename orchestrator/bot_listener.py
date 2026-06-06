"""
Telegram bot listener — entry point for all incoming messages.
Receives messages and passes them to the router.
"""
import asyncio
import os
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
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
        self.app.add_handler(CommandHandler("usage", self._handle_status))
        self.app.add_handler(CommandHandler("backlog", self._handle_backlog))
        self.app.add_handler(CommandHandler("assets", self._handle_assets))
        self.app.add_handler(CommandHandler("python", self._handle_python))
        self.app.add_handler(CommandHandler("notebooklm", self._handle_notebooklm))
        self.app.add_handler(CallbackQueryHandler(self._handle_callback))
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
            summary = item["summary"][:80]
            for ch in ["_", "*", "[", "]", "`"]:
                summary = summary.replace(ch, f"\\{ch}")
            lines.append(
                f"{i}. {label} [{item['domain']}] {summary}\n"
                f"   ID: `{item['id']}` | 우선순위: {item['priority']}/10"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _handle_assets(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update.effective_user.id):
            return
        from agents.finance.asset_manager import AssetManager
        summary = AssetManager().net_worth_summary()
        await update.message.reply_text("💼 *전체 자산 현황*\n\n" + summary, parse_mode="Markdown")

    async def _handle_python(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update.effective_user.id):
            return
        from pathlib import Path
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        base = Path.home() / "PycharmProjects"
        if not base.exists():
            await update.message.reply_text("📂 ~/PycharmProjects 디렉토리를 찾을 수 없습니다.")
            return

        projects = sorted(
            d for d in base.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )
        if not projects:
            await update.message.reply_text("📂 Python 프로젝트가 없습니다.")
            return

        buttons = [
            [InlineKeyboardButton(f"🐍 {p.name}", callback_data=f"pyproj:{p.name}")]
            for p in projects
        ]
        keyboard = InlineKeyboardMarkup(buttons)
        await update.message.reply_text(
            f"📂 *~/PycharmProjects 프로젝트 목록* ({len(projects)}개)\n어떤 프로젝트가 궁금하세요?",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

    async def _handle_notebooklm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Zotero 컬렉션 목록을 인라인 버튼으로 보여줌.

        하위 컬렉션이 있는 폴더(Domain/Method/Problem)를 상단에 배치하고,
        나머지 단일 컬렉션은 2열로 하단에 배치한다.
        """
        if not self._is_allowed(update.effective_user.id):
            return
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        await update.message.reply_text("⏳ Zotero 컬렉션 목록 불러오는 중…")
        try:
            folders, leaves = await asyncio.to_thread(self._fetch_nlm_top_cols)
            if not folders and not leaves:
                await update.message.reply_text("⚠️ Zotero 컬렉션을 불러올 수 없습니다.")
                return

            buttons = []
            # 폴더형 컬렉션 (하위 있음) — 1열, 상단
            if folders:
                for key, name in folders:
                    buttons.append([InlineKeyboardButton(f"📂 {name}", callback_data=f"nlm_top:{key}")])

            # 단일 컬렉션 — 2열, 하단
            leaf_btns = [
                InlineKeyboardButton(f"📄 {name}", callback_data=f"nlm_top:{key}")
                for key, name in leaves
            ]
            for i in range(0, len(leaf_btns), 2):
                buttons.append(leaf_btns[i:i + 2])

            keyboard = InlineKeyboardMarkup(buttons)
            total = len(folders) + len(leaves)
            folder_note = f"📂 하위 폴더 있음: {', '.join(n for _, n in folders)}\n" if folders else ""
            await update.message.reply_text(
                f"📓 *NotebookLM 업로드* ({total}개)\n{folder_note}컬렉션을 선택하세요.",
                reply_markup=keyboard,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(f"_handle_notebooklm error: {e}", exc_info=True)
            await update.message.reply_text(f"⚠️ 오류: {e}")

    def _fetch_nlm_top_cols(self) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """Zotero 최상위 컬렉션을 (폴더목록, 단일목록) 으로 분리해 반환.

        폴더: 하위 컬렉션이 1개 이상 있는 컬렉션 (Domain, Method, Problem 등)
        단일: 하위 컬렉션이 없는 컬렉션
        """
        from agents.paper.zotero_client import ZoteroClient
        zc = ZoteroClient()
        if not zc.zot:
            return [], []
        all_cols = zc.zot.everything(zc.zot.collections())
        # 하위 컬렉션을 가진 부모 키 집합
        parent_keys = {
            c["data"]["parentCollection"]
            for c in all_cols
            if c["data"].get("parentCollection", False)
        }
        top = [
            (c["data"]["key"], c["data"]["name"])
            for c in all_cols
            if not c["data"].get("parentCollection", False)
        ]
        folders = sorted(
            [(k, n) for k, n in top if k in parent_keys],
            key=lambda x: x[1].lower(),
        )
        leaves = sorted(
            [(k, n) for k, n in top if k not in parent_keys],
            key=lambda x: x[1].lower(),
        )
        return folders, leaves

    def _fetch_nlm_sub_cols(self, top_key: str) -> list[tuple[str, str]]:
        """특정 최상위 컬렉션의 하위 컬렉션 (key, name) 목록 반환."""
        from agents.paper.zotero_client import ZoteroClient
        zc = ZoteroClient()
        if not zc.zot:
            return []
        all_cols = zc.zot.everything(zc.zot.collections())
        subs = [
            (c["data"]["key"], c["data"]["name"])
            for c in all_cols
            if c["data"].get("parentCollection", "") == top_key
        ]
        return sorted(subs, key=lambda x: x[1].lower())

    def _fetch_col_name(self, col_key: str) -> str:
        """컬렉션 키로 이름 반환."""
        from agents.paper.zotero_client import ZoteroClient
        zc = ZoteroClient()
        if not zc.zot:
            return col_key
        all_cols = zc.zot.everything(zc.zot.collections())
        for c in all_cols:
            if c["data"]["key"] == col_key:
                return c["data"]["name"]
        return col_key

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """인라인 버튼 콜백 처리."""
        query = update.callback_query
        await query.answer()

        if not self._is_allowed(query.from_user.id):
            return

        try:
            parts = query.data.split(":", 1)
            action = parts[0]
            payload = parts[1] if len(parts) > 1 else ""
            chat_id = query.message.chat_id

            if action == "pyproj":
                await query.edit_message_reply_markup(reply_markup=None)
                await self._send_project_info(chat_id, payload)
                return

            if action == "nlm_top":
                await self._handle_nlm_top(query, payload, chat_id)
                return

            if action == "nlm_page":
                # payload: "{parent_key}:{offset}"
                p_key, _, offset_str = payload.rpartition(":")
                await self._handle_nlm_page(query, p_key, int(offset_str), chat_id)
                return

            if action == "nlm_upload":
                await query.edit_message_reply_markup(reply_markup=None)
                await self._handle_nlm_upload(chat_id, payload)
                return

            await query.edit_message_reply_markup(reply_markup=None)  # 버튼 제거
            await self.router.handle_callback(action, payload, chat_id)
        except Exception as e:
            logger.error(f"Callback error: {e}", exc_info=True)

    _NLM_PAGE_SIZE = 20  # 한 페이지에 보여줄 하위 컬렉션 수

    async def _handle_nlm_top(self, query, top_key: str, chat_id: int):
        """최상위 컬렉션 클릭 → 하위 컬렉션 목록(첫 페이지) 또는 바로 업로드."""
        top_name = await asyncio.to_thread(self._fetch_col_name, top_key)
        subs = await asyncio.to_thread(self._fetch_nlm_sub_cols, top_key)

        if not subs:
            await query.edit_message_reply_markup(reply_markup=None)
            await self._handle_nlm_upload(chat_id, top_key)
            return

        await self._render_sub_page(query, top_key, top_name, subs, offset=0)

    async def _handle_nlm_page(self, query, top_key: str, offset: int, chat_id: int):
        """하위 컬렉션 페이지 이동."""
        top_name = await asyncio.to_thread(self._fetch_col_name, top_key)
        subs = await asyncio.to_thread(self._fetch_nlm_sub_cols, top_key)
        await self._render_sub_page(query, top_key, top_name, subs, offset)

    async def _render_sub_page(self, query, top_key: str, top_name: str,
                                subs: list, offset: int):
        """하위 컬렉션 목록을 페이지 단위로 렌더링."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        page_size = self._NLM_PAGE_SIZE
        page_subs = subs[offset:offset + page_size]
        total = len(subs)
        page_num = offset // page_size + 1
        total_pages = (total + page_size - 1) // page_size

        buttons = [
            [InlineKeyboardButton(f"📂 전체 업로드 ({top_name}, {total}개)",
                                  callback_data=f"nlm_upload:{top_key}")]
        ]
        for sub_key, sub_name in page_subs:
            buttons.append([
                InlineKeyboardButton(f"└ {sub_name[:42]}", callback_data=f"nlm_upload:{sub_key}")
            ])

        # 페이지 이동 버튼
        nav = []
        if offset > 0:
            nav.append(InlineKeyboardButton("◀ 이전", callback_data=f"nlm_page:{top_key}:{offset - page_size}"))
        if offset + page_size < total:
            nav.append(InlineKeyboardButton("다음 ▶", callback_data=f"nlm_page:{top_key}:{offset + page_size}"))
        if nav:
            buttons.append(nav)

        keyboard = InlineKeyboardMarkup(buttons)
        await query.edit_message_text(
            f"📁 {top_name} — 하위 컬렉션 선택 ({page_num}/{total_pages}페이지, 총 {total}개)",
            reply_markup=keyboard,
        )

    async def _handle_nlm_upload(self, chat_id: int, col_key: str):
        """선택한 컬렉션을 NotebookLM에 백그라운드 업로드."""
        from agents.paper.paper_agent import PaperAgent
        agent = PaperAgent()
        await self.app.bot.send_message(
            chat_id=chat_id,
            text="📓 NotebookLM 업로드를 백그라운드에서 시작합니다…",
        )
        asyncio.create_task(agent.upload_collection_by_key(col_key, chat_id))

    async def _send_project_info(self, chat_id: int, project_name: str):
        """프로젝트 상세 정보(파일 목록, 최근 실행 이력)를 Telegram으로 전송."""
        from pathlib import Path
        import subprocess, json

        proj_dir = Path.home() / "PycharmProjects" / project_name
        if not proj_dir.exists():
            await self.app.bot.send_message(chat_id=chat_id, text=f"❌ 프로젝트를 찾을 수 없습니다: {project_name}")
            return

        # 최상위 .py 파일 목록
        py_files = sorted(f.name for f in proj_dir.iterdir() if f.suffix == ".py" and f.is_file())
        has_venv = (proj_dir / ".venv").exists()
        has_req = (proj_dir / "requirements.txt").exists()

        # 최근 수정 파일
        all_py = sorted(
            [f for f in proj_dir.rglob("*.py") if ".venv" not in str(f) and "__pycache__" not in str(f)],
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        recent_file = all_py[0].name if all_py else "-"

        # git 최근 커밋 (있으면)
        git_log = ""
        try:
            result = subprocess.run(
                ["git", "-C", str(proj_dir), "log", "--oneline", "-3"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                git_log = "\n".join(f"  `{line}`" for line in result.stdout.strip().splitlines())
        except Exception:
            pass

        lines = [
            f"🐍 *{project_name}*",
            f"📁 경로: `~/PycharmProjects/{project_name}`",
            f"",
            f"📄 최상위 py 파일: {', '.join(py_files) or '-'}",
            f"🕐 최근 수정: `{recent_file}`",
            f"{'✅ venv 있음' if has_venv else '❌ venv 없음'} | {'✅ requirements.txt' if has_req else '❌ requirements.txt 없음'}",
        ]
        if git_log:
            lines += [f"", f"📝 최근 커밋:", git_log]

        await self.app.bot.send_message(
            chat_id=chat_id,
            text="\n".join(lines),
            parse_mode="Markdown",
        )

    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_allowed(update.effective_user.id):
            logger.warning(f"Unauthorized access attempt from user {update.effective_user.id}")
            return

        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        text = update.message.text
        logger.info(f"Message from {user_id}: {text[:80]}")

        await update.message.reply_text("⏳ 처리 중...")

        try:
            await asyncio.wait_for(
                self.router.route(
                    message=text,
                    chat_id=chat_id,
                    user_id=user_id,
                    message_id=update.message.message_id,
                ),
                timeout=95,
            )
        except asyncio.TimeoutError as e:
            logger.error(f"Handler timeout for message: {text[:80]}")
            await self.error_recovery.handle(
                RuntimeError("응답 시간 초과 (95s)"),
                chat_id=chat_id,
                context="handler_timeout",
            )
        except Exception as e:
            logger.error(f"Unhandled error routing message: {e}", exc_info=True)
            await self.error_recovery.handle(e, chat_id=chat_id, context="bot_listener")

    def run(self):
        logger.info("Jarvis bot starting...")
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    BotListener().run()
