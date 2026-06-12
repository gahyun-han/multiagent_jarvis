"""
자산관리봇 — 월급/적금/고정지출/대출잔금 수동 설정 전용 봇.

/modifyitem : 항목 선택 후 대화형 입력
/status     : 현재 설정 확인
/cancel     : 대화 취소
"""
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── 데이터 경로 ──────────────────────────────────────────────────────────────
_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "finance"
_FA_PATH = _DATA_DIR / "finance_assets.json"
_ASSETS_PATH = Path(__file__).resolve().parents[1] / "data" / "assets.json"

# ── 대화 상태 ────────────────────────────────────────────────────────────────
(
    MENU,
    AWAIT_SALARY,
    AWAIT_SAVINGS,
    FIXED_MENU,
    AWAIT_FIXED_NAME,
    AWAIT_FIXED_AMOUNT,
    LOAN_SELECT,
    AWAIT_LOAN_AMOUNT,
) = range(8)


# ── finance_assets.json 헬퍼 ─────────────────────────────────────────────────

def _load_fa() -> dict:
    if not _FA_PATH.exists():
        return {"updated_at": "", "fixed": {"salary": 0, "savings": 0, "fixed_expenses": []}}
    try:
        return json.loads(_FA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"updated_at": "", "fixed": {"salary": 0, "savings": 0, "fixed_expenses": []}}


def _save_fa(data: dict) -> None:
    from datetime import date
    data["updated_at"] = date.today().isoformat()
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _FA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_loans() -> list[dict]:
    if not _ASSETS_PATH.exists():
        return []
    try:
        d = json.loads(_ASSETS_PATH.read_text(encoding="utf-8"))
        return d.get("loans", [])
    except Exception:
        return []


def _save_loan_balance(name: str, remaining: int) -> None:
    if not _ASSETS_PATH.exists():
        return
    try:
        d = json.loads(_ASSETS_PATH.read_text(encoding="utf-8"))
        for loan in d.get("loans", []):
            if loan["name"] == name:
                loan["remaining"] = remaining
                break
        _ASSETS_PATH.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error(f"Loan save error: {e}")


def _parse_amount(text: str) -> int | None:
    """'1,200,000' or '1200000' or '120만' → int. 실패 시 None."""
    text = text.strip().replace(",", "").replace(" ", "")
    # '만' 처리
    import re
    m = re.fullmatch(r'(\d+(?:\.\d+)?)만', text)
    if m:
        return int(float(m.group(1)) * 10000)
    if text.isdigit():
        return int(text)
    return None


# ── 공통 헬퍼 ────────────────────────────────────────────────────────────────

def _fmt(amount: int) -> str:
    return f"{amount:,}원"


def _main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 월급 설정", callback_data="edit:salary")],
        [InlineKeyboardButton("💚 적금 납입액", callback_data="edit:savings")],
        [InlineKeyboardButton("🔒 고정지출 관리", callback_data="edit:fixed")],
        [InlineKeyboardButton("🔴 대출 잔금 업데이트", callback_data="edit:loan")],
        [InlineKeyboardButton("❌ 취소", callback_data="edit:cancel")],
    ])


# ── /start ───────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💼 *자산관리봇*\n\n"
        "/modifyitem — 월급/적금/고정지출/대출 설정\n"
        "/status — 현재 설정 확인\n"
        "/cancel — 진행 중인 대화 취소",
        parse_mode="Markdown",
    )


# ── /status ──────────────────────────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fa = _load_fa()
    fixed = fa.get("fixed", {})
    salary = fixed.get("salary", 0)
    savings = fixed.get("savings", 0)
    expenses = fixed.get("fixed_expenses", [])
    loans = _load_loans()

    lines = ["💼 *현재 설정*\n"]
    lines.append(f"💵 월급: {_fmt(salary)}")
    lines.append(f"💚 적금 납입액: {_fmt(savings)}/월")
    if expenses:
        lines.append("\n🔒 고정지출:")
        for e in expenses:
            lines.append(f"  • {e['name']}: {_fmt(e['amount'])}")
        lines.append(f"  소계: {_fmt(sum(e['amount'] for e in expenses))}")
    else:
        lines.append("🔒 고정지출: 없음")
    if loans:
        lines.append("\n🔴 대출:")
        for l in loans:
            lines.append(f"  • {l['name']}: {_fmt(l.get('remaining', 0))}")
    else:
        lines.append("🔴 대출: 없음")

    if fa.get("updated_at"):
        lines.append(f"\n_마지막 수정: {fa['updated_at']}_")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /modifyitem 대화 시작 ─────────────────────────────────────────────────────

async def cmd_modifyitem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "수정할 항목을 선택하세요:",
        reply_markup=_main_menu_keyboard(),
    )
    return MENU


# ── MENU: 인라인 버튼 콜백 ────────────────────────────────────────────────────

async def cb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data.split(":", 1)[1]

    if action == "cancel":
        await query.edit_message_text("❌ 취소되었습니다.")
        return ConversationHandler.END

    if action == "salary":
        fa = _load_fa()
        current = fa.get("fixed", {}).get("salary", 0)
        await query.edit_message_text(
            f"💵 *월급 설정*\n현재: {_fmt(current)}\n\n새 금액을 입력하세요 (예: 3500000 또는 350만)",
            parse_mode="Markdown",
        )
        return AWAIT_SALARY

    if action == "savings":
        fa = _load_fa()
        current = fa.get("fixed", {}).get("savings", 0)
        await query.edit_message_text(
            f"💚 *적금 납입액 설정*\n현재: {_fmt(current)}/월\n\n새 금액을 입력하세요 (예: 500000 또는 50만)",
            parse_mode="Markdown",
        )
        return AWAIT_SAVINGS

    if action == "fixed":
        return await _show_fixed_menu(query, context)

    if action == "loan":
        loans = _load_loans()
        if not loans:
            await query.edit_message_text("🔴 등록된 대출이 없습니다.\nJarvis봇에서 대출 정보를 먼저 추가해주세요.")
            return ConversationHandler.END
        buttons = [
            [InlineKeyboardButton(f"• {l['name']} ({_fmt(l.get('remaining', 0))})",
                                  callback_data=f"loan:{l['name']}")]
            for l in loans
        ]
        buttons.append([InlineKeyboardButton("❌ 취소", callback_data="loan:__cancel__")])
        await query.edit_message_text(
            "🔴 *대출 잔금 업데이트*\n수정할 대출을 선택하세요:",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="Markdown",
        )
        return LOAN_SELECT

    return ConversationHandler.END


# ── 월급 입력 ────────────────────────────────────────────────────────────────

async def recv_salary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    amount = _parse_amount(update.message.text)
    if amount is None:
        await update.message.reply_text("⚠️ 숫자만 입력해주세요. (예: 3500000 또는 350만)")
        return AWAIT_SALARY
    fa = _load_fa()
    fa.setdefault("fixed", {})["salary"] = amount
    _save_fa(fa)
    await update.message.reply_text(f"✅ 월급이 *{_fmt(amount)}*으로 저장되었습니다.", parse_mode="Markdown")
    return ConversationHandler.END


# ── 적금 납입액 입력 ──────────────────────────────────────────────────────────

async def recv_savings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    amount = _parse_amount(update.message.text)
    if amount is None:
        await update.message.reply_text("⚠️ 숫자만 입력해주세요. (예: 500000 또는 50만)")
        return AWAIT_SAVINGS
    fa = _load_fa()
    fa.setdefault("fixed", {})["savings"] = amount
    _save_fa(fa)
    await update.message.reply_text(f"✅ 적금 납입액이 *{_fmt(amount)}/월*으로 저장되었습니다.", parse_mode="Markdown")
    return ConversationHandler.END


# ── 고정지출 서브 메뉴 ────────────────────────────────────────────────────────

async def _show_fixed_menu(query_or_update, context) -> int:
    fa = _load_fa()
    expenses = fa.get("fixed", {}).get("fixed_expenses", [])

    lines = ["🔒 *고정지출 목록*"]
    if expenses:
        for i, e in enumerate(expenses):
            lines.append(f"{i+1}. {e['name']}: {_fmt(e['amount'])}")
        lines.append(f"\n소계: {_fmt(sum(e['amount'] for e in expenses))}")
    else:
        lines.append("_(없음)_")

    buttons = [[InlineKeyboardButton("➕ 항목 추가", callback_data="fixed:add")]]
    if expenses:
        buttons.append([InlineKeyboardButton("🗑 항목 삭제", callback_data="fixed:delete")])
    buttons.append([InlineKeyboardButton("❌ 취소", callback_data="fixed:cancel")])

    keyboard = InlineKeyboardMarkup(buttons)
    if hasattr(query_or_update, 'edit_message_text'):
        await query_or_update.edit_message_text("\n".join(lines), reply_markup=keyboard, parse_mode="Markdown")
    else:
        await query_or_update.message.reply_text("\n".join(lines), reply_markup=keyboard, parse_mode="Markdown")
    return FIXED_MENU


async def cb_fixed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data.split(":", 1)[1]

    if action == "cancel":
        await query.edit_message_text("❌ 취소되었습니다.")
        return ConversationHandler.END

    if action == "add":
        await query.edit_message_text(
            "🔒 *고정지출 추가*\n항목 이름을 입력하세요. (예: 관리비, 넷플릭스)",
            parse_mode="Markdown",
        )
        return AWAIT_FIXED_NAME

    if action == "delete":
        fa = _load_fa()
        expenses = fa.get("fixed", {}).get("fixed_expenses", [])
        buttons = [
            [InlineKeyboardButton(f"🗑 {e['name']} ({_fmt(e['amount'])})",
                                  callback_data=f"fdel:{e['name']}")]
            for e in expenses
        ]
        buttons.append([InlineKeyboardButton("← 뒤로", callback_data="fdel:__back__")])
        await query.edit_message_text(
            "삭제할 항목을 선택하세요:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return FIXED_MENU

    if action.startswith("fdel:") or query.data.startswith("fdel:"):
        pass  # handled by cb_fdel

    return FIXED_MENU


async def cb_fdel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    name = query.data.split(":", 1)[1]

    if name == "__back__":
        return await _show_fixed_menu(query, context)

    fa = _load_fa()
    expenses = fa.get("fixed", {}).get("fixed_expenses", [])
    fa["fixed"]["fixed_expenses"] = [e for e in expenses if e["name"] != name]
    _save_fa(fa)
    await query.edit_message_text(f"🗑 *{name}* 항목이 삭제되었습니다.", parse_mode="Markdown")
    return ConversationHandler.END


# ── 고정지출 이름 입력 ────────────────────────────────────────────────────────

async def recv_fixed_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("⚠️ 이름을 입력해주세요.")
        return AWAIT_FIXED_NAME
    context.user_data["fixed_name"] = name
    await update.message.reply_text(
        f"*{name}*의 금액을 입력하세요. (예: 55000 또는 5만5천)",
        parse_mode="Markdown",
    )
    return AWAIT_FIXED_AMOUNT


# ── 고정지출 금액 입력 ────────────────────────────────────────────────────────

async def recv_fixed_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    amount = _parse_amount(update.message.text)
    if amount is None:
        await update.message.reply_text("⚠️ 숫자만 입력해주세요. (예: 55000 또는 5만5천)")
        return AWAIT_FIXED_AMOUNT

    name = context.user_data.pop("fixed_name", "알 수 없음")
    fa = _load_fa()
    expenses = fa.setdefault("fixed", {}).setdefault("fixed_expenses", [])
    # 이름 중복이면 업데이트
    for e in expenses:
        if e["name"] == name:
            e["amount"] = amount
            break
    else:
        expenses.append({"name": name, "amount": amount})
    _save_fa(fa)

    total = sum(e["amount"] for e in expenses)
    await update.message.reply_text(
        f"✅ *{name}* {_fmt(amount)} 저장 완료\n고정지출 소계: {_fmt(total)}",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ── 대출 선택 콜백 ────────────────────────────────────────────────────────────

async def cb_loan_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    name = query.data.split(":", 1)[1]

    if name == "__cancel__":
        await query.edit_message_text("❌ 취소되었습니다.")
        return ConversationHandler.END

    context.user_data["loan_name"] = name
    loans = _load_loans()
    current = next((l.get("remaining", 0) for l in loans if l["name"] == name), 0)
    await query.edit_message_text(
        f"🔴 *{name}* 잔금 업데이트\n현재: {_fmt(current)}\n\n새 잔금을 입력하세요:",
        parse_mode="Markdown",
    )
    return AWAIT_LOAN_AMOUNT


# ── 대출 잔금 입력 ────────────────────────────────────────────────────────────

async def recv_loan_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    amount = _parse_amount(update.message.text)
    if amount is None:
        await update.message.reply_text("⚠️ 숫자만 입력해주세요. (예: 15000000 또는 1500만)")
        return AWAIT_LOAN_AMOUNT

    name = context.user_data.pop("loan_name", "")
    _save_loan_balance(name, amount)
    await update.message.reply_text(
        f"✅ *{name}* 잔금이 *{_fmt(amount)}*으로 업데이트되었습니다.",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ── /cancel ──────────────────────────────────────────────────────────────────

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ 취소되었습니다.")
    return ConversationHandler.END


# ── 봇 실행 ──────────────────────────────────────────────────────────────────

def run():
    token = os.getenv("ASSET_BOT_TOKEN")
    if not token:
        raise ValueError("ASSET_BOT_TOKEN not set in .env")

    app = Application.builder().token(token).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("modifyitem", cmd_modifyitem)],
        states={
            MENU: [CallbackQueryHandler(cb_menu, pattern=r"^edit:")],
            AWAIT_SALARY: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_salary)],
            AWAIT_SAVINGS: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_savings)],
            FIXED_MENU: [
                CallbackQueryHandler(cb_fixed, pattern=r"^fixed:"),
                CallbackQueryHandler(cb_fdel, pattern=r"^fdel:"),
            ],
            AWAIT_FIXED_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_fixed_name)],
            AWAIT_FIXED_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_fixed_amount)],
            LOAN_SELECT: [CallbackQueryHandler(cb_loan_select, pattern=r"^loan:")],
            AWAIT_LOAN_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, recv_loan_amount)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(conv)

    logger.info("Asset bot starting...")
    app.run_polling()


if __name__ == "__main__":
    run()
