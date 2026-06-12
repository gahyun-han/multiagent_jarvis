"""
자산관리봇 테스트
- _parse_amount: 다양한 금액 표현 파싱
- _load_fa / _save_fa: finance_assets.json 읽기/쓰기
- _load_loans / _save_loan_balance: assets.json 대출 처리
- recv_salary / recv_savings / recv_fixed_name/amount / recv_loan_amount: 대화 상태 핸들러
- cmd_status: 현재 설정 포맷 검증
"""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── _parse_amount ─────────────────────────────────────────────────────────────

def test_parse_amount_plain_int():
    from bots.asset_bot import _parse_amount
    assert _parse_amount("3500000") == 3500000


def test_parse_amount_with_commas():
    from bots.asset_bot import _parse_amount
    assert _parse_amount("3,500,000") == 3500000


def test_parse_amount_man():
    from bots.asset_bot import _parse_amount
    assert _parse_amount("350만") == 3500000


def test_parse_amount_decimal_man():
    from bots.asset_bot import _parse_amount
    assert _parse_amount("5.5만") == 55000


def test_parse_amount_invalid():
    from bots.asset_bot import _parse_amount
    assert _parse_amount("삼백오십만원") is None
    assert _parse_amount("abc") is None


def test_parse_amount_zero():
    from bots.asset_bot import _parse_amount
    assert _parse_amount("0") == 0


# ── _load_fa / _save_fa ───────────────────────────────────────────────────────

def test_load_fa_missing_file(tmp_path):
    import bots.asset_bot as ab
    orig = ab._FA_PATH
    ab._FA_PATH = tmp_path / "finance_assets.json"
    try:
        result = ab._load_fa()
        assert result["fixed"]["salary"] == 0
        assert result["fixed"]["savings"] == 0
        assert result["fixed"]["fixed_expenses"] == []
    finally:
        ab._FA_PATH = orig


def test_save_and_load_fa(tmp_path):
    import bots.asset_bot as ab
    orig_path = ab._FA_PATH
    orig_dir = ab._DATA_DIR
    ab._FA_PATH = tmp_path / "finance_assets.json"
    ab._DATA_DIR = tmp_path
    try:
        data = {"updated_at": "", "fixed": {"salary": 4000000, "savings": 300000, "fixed_expenses": []}}
        ab._save_fa(data)
        loaded = ab._load_fa()
        assert loaded["fixed"]["salary"] == 4000000
        assert loaded["updated_at"] != ""  # 날짜 자동 기록
    finally:
        ab._FA_PATH = orig_path
        ab._DATA_DIR = orig_dir


def test_save_fa_updates_updated_at(tmp_path):
    import bots.asset_bot as ab
    from datetime import date
    orig_path = ab._FA_PATH
    orig_dir = ab._DATA_DIR
    ab._FA_PATH = tmp_path / "finance_assets.json"
    ab._DATA_DIR = tmp_path
    try:
        ab._save_fa({"fixed": {"salary": 0, "savings": 0, "fixed_expenses": []}})
        saved = json.loads((tmp_path / "finance_assets.json").read_text())
        assert saved["updated_at"] == date.today().isoformat()
    finally:
        ab._FA_PATH = orig_path
        ab._DATA_DIR = orig_dir


# ── _load_loans / _save_loan_balance ─────────────────────────────────────────

def test_load_loans_missing_file(tmp_path):
    import bots.asset_bot as ab
    orig = ab._ASSETS_PATH
    ab._ASSETS_PATH = tmp_path / "assets.json"
    try:
        assert ab._load_loans() == []
    finally:
        ab._ASSETS_PATH = orig


def test_load_loans(tmp_path):
    import bots.asset_bot as ab
    orig = ab._ASSETS_PATH
    ab._ASSETS_PATH = tmp_path / "assets.json"
    (tmp_path / "assets.json").write_text(json.dumps({
        "loans": [{"name": "전세대출", "remaining": 50000000}]
    }))
    try:
        loans = ab._load_loans()
        assert len(loans) == 1
        assert loans[0]["name"] == "전세대출"
    finally:
        ab._ASSETS_PATH = orig


def test_save_loan_balance(tmp_path):
    import bots.asset_bot as ab
    orig = ab._ASSETS_PATH
    ab._ASSETS_PATH = tmp_path / "assets.json"
    (tmp_path / "assets.json").write_text(json.dumps({
        "loans": [{"name": "전세대출", "remaining": 50000000}]
    }))
    try:
        ab._save_loan_balance("전세대출", 45000000)
        data = json.loads((tmp_path / "assets.json").read_text())
        assert data["loans"][0]["remaining"] == 45000000
    finally:
        ab._ASSETS_PATH = orig


# ── 대화 핸들러 ───────────────────────────────────────────────────────────────

def _make_update_with_text(text: str):
    update = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _make_context(user_data=None):
    ctx = MagicMock()
    ctx.user_data = user_data or {}
    return ctx


@pytest.mark.asyncio
async def test_recv_salary_saves_and_ends(tmp_path):
    import bots.asset_bot as ab
    from telegram.ext import ConversationHandler
    orig_path, orig_dir = ab._FA_PATH, ab._DATA_DIR
    ab._FA_PATH = tmp_path / "fa.json"
    ab._DATA_DIR = tmp_path
    try:
        update = _make_update_with_text("350만")
        ctx = _make_context()
        result = await ab.recv_salary(update, ctx)
        assert result == ConversationHandler.END
        loaded = ab._load_fa()
        assert loaded["fixed"]["salary"] == 3500000
        update.message.reply_text.assert_called_once()
        assert "3,500,000" in update.message.reply_text.call_args.args[0]
    finally:
        ab._FA_PATH = orig_path
        ab._DATA_DIR = orig_dir


@pytest.mark.asyncio
async def test_recv_salary_invalid_stays_in_state(tmp_path):
    import bots.asset_bot as ab
    update = _make_update_with_text("삼백오십만")
    ctx = _make_context()
    result = await ab.recv_salary(update, ctx)
    assert result == ab.AWAIT_SALARY


@pytest.mark.asyncio
async def test_recv_savings_saves(tmp_path):
    import bots.asset_bot as ab
    from telegram.ext import ConversationHandler
    orig_path, orig_dir = ab._FA_PATH, ab._DATA_DIR
    ab._FA_PATH = tmp_path / "fa.json"
    ab._DATA_DIR = tmp_path
    try:
        update = _make_update_with_text("500000")
        ctx = _make_context()
        result = await ab.recv_savings(update, ctx)
        assert result == ConversationHandler.END
        assert ab._load_fa()["fixed"]["savings"] == 500000
    finally:
        ab._FA_PATH = orig_path
        ab._DATA_DIR = orig_dir


@pytest.mark.asyncio
async def test_recv_fixed_name_stores_in_user_data():
    import bots.asset_bot as ab
    update = _make_update_with_text("관리비")
    ctx = _make_context()
    result = await ab.recv_fixed_name(update, ctx)
    assert result == ab.AWAIT_FIXED_AMOUNT
    assert ctx.user_data["fixed_name"] == "관리비"


@pytest.mark.asyncio
async def test_recv_fixed_amount_adds_expense(tmp_path):
    import bots.asset_bot as ab
    from telegram.ext import ConversationHandler
    orig_path, orig_dir = ab._FA_PATH, ab._DATA_DIR
    ab._FA_PATH = tmp_path / "fa.json"
    ab._DATA_DIR = tmp_path
    try:
        update = _make_update_with_text("55000")
        ctx = _make_context({"fixed_name": "관리비"})
        result = await ab.recv_fixed_amount(update, ctx)
        assert result == ConversationHandler.END
        expenses = ab._load_fa()["fixed"]["fixed_expenses"]
        assert len(expenses) == 1
        assert expenses[0]["name"] == "관리비"
        assert expenses[0]["amount"] == 55000
    finally:
        ab._FA_PATH = orig_path
        ab._DATA_DIR = orig_dir


@pytest.mark.asyncio
async def test_recv_fixed_amount_updates_existing(tmp_path):
    """같은 이름 항목은 금액 업데이트."""
    import bots.asset_bot as ab
    from telegram.ext import ConversationHandler
    orig_path, orig_dir = ab._FA_PATH, ab._DATA_DIR
    ab._FA_PATH = tmp_path / "fa.json"
    ab._DATA_DIR = tmp_path
    data = {"updated_at": "", "fixed": {"salary": 0, "savings": 0, "fixed_expenses": [{"name": "관리비", "amount": 50000}]}}
    ab._save_fa(data)
    try:
        update = _make_update_with_text("60000")
        ctx = _make_context({"fixed_name": "관리비"})
        await ab.recv_fixed_amount(update, ctx)
        expenses = ab._load_fa()["fixed"]["fixed_expenses"]
        assert len(expenses) == 1  # 중복 없음
        assert expenses[0]["amount"] == 60000
    finally:
        ab._FA_PATH = orig_path
        ab._DATA_DIR = orig_dir


@pytest.mark.asyncio
async def test_recv_loan_amount_updates(tmp_path):
    import bots.asset_bot as ab
    from telegram.ext import ConversationHandler
    orig = ab._ASSETS_PATH
    ab._ASSETS_PATH = tmp_path / "assets.json"
    (tmp_path / "assets.json").write_text(json.dumps({
        "loans": [{"name": "전세대출", "remaining": 50000000}]
    }))
    try:
        update = _make_update_with_text("4500만")
        ctx = _make_context({"loan_name": "전세대출"})
        result = await ab.recv_loan_amount(update, ctx)
        assert result == ConversationHandler.END
        data = json.loads((tmp_path / "assets.json").read_text())
        assert data["loans"][0]["remaining"] == 45000000
    finally:
        ab._ASSETS_PATH = orig


# ── cmd_status ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cmd_status_shows_all_sections(tmp_path):
    import bots.asset_bot as ab
    orig_path, orig_dir = ab._FA_PATH, ab._DATA_DIR
    orig_assets = ab._ASSETS_PATH
    ab._FA_PATH = tmp_path / "fa.json"
    ab._DATA_DIR = tmp_path
    ab._ASSETS_PATH = tmp_path / "assets.json"

    fa_data = {
        "updated_at": "2026-06-12",
        "fixed": {
            "salary": 4000000,
            "savings": 300000,
            "fixed_expenses": [{"name": "관리비", "amount": 55000}],
        },
    }
    ab._save_fa(fa_data)
    (tmp_path / "assets.json").write_text(json.dumps({
        "loans": [{"name": "전세대출", "remaining": 50000000}]
    }))

    try:
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        ctx = MagicMock()
        await ab.cmd_status(update, ctx)

        text = update.message.reply_text.call_args.args[0]
        assert "4,000,000" in text
        assert "300,000" in text
        assert "관리비" in text
        assert "전세대출" in text
    finally:
        ab._FA_PATH = orig_path
        ab._DATA_DIR = orig_dir
        ab._ASSETS_PATH = orig_assets
