"""
Finance 리포트 시스템 테스트
- sms_parser: 건별/월별총액/파싱실패/저장/월별로드
- report_generator: 리포트 생성, 스냅샷 append, 전월 비교
- finance_agent: 월별 리포트/카드 문자 커맨드 라우팅
"""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── sms_parser ────────────────────────────────────────────────────────────────

def test_parse_sms_individual_approval_shinhan():
    from agents.finance.sms_parser import parse_sms
    text = "신한카드 12,000원 승인 스타벅스 06/12 09:30 잔여한도 2,000,000원"
    result = parse_sms(text)
    assert result["amount"] == 12000
    assert result["card"] == "신한"
    assert result["source"] == "sms"
    assert "스타벅스" in result["merchant"]


def test_parse_sms_individual_amount_no_comma():
    from agents.finance.sms_parser import parse_sms
    result = parse_sms("국민카드 5000원 승인 GS25")
    assert result["amount"] == 5000
    assert result["card"] == "국민"
    assert result["source"] == "sms"


def test_parse_sms_monthly_total():
    from agents.finance.sms_parser import parse_sms
    result = parse_sms("이번달 카드 사용액 345,000원")
    assert result["amount"] == 345000
    assert result["source"] == "monthly_total"
    assert result["merchant"] == "월별합산"


def test_parse_sms_monthly_total_with_month():
    from agents.finance.sms_parser import parse_sms
    result = parse_sms("[신한카드] 5월 이용대금: 1,234,000원")
    assert result["amount"] == 1234000
    assert result["source"] == "monthly_total"


def test_parse_sms_failure_returns_unknown():
    from agents.finance.sms_parser import parse_sms
    result = parse_sms("안녕하세요 고객님")
    assert result["source"] == "unknown"
    assert result["amount"] == 0
    assert "raw" in result


def test_parse_sms_large_amount():
    from agents.finance.sms_parser import parse_sms
    result = parse_sms("삼성카드 1,500,000원 승인 이마트")
    assert result["amount"] == 1500000


def test_save_transaction_creates_file(tmp_path):
    from agents.finance import sms_parser as sms_mod
    original = sms_mod._TRANSACTIONS_PATH
    sms_mod._TRANSACTIONS_PATH = tmp_path / "transactions.json"
    sms_mod._FINANCE_DIR = tmp_path
    try:
        sms_mod.save_transaction({"amount": 1000, "merchant": "test", "card": "신한", "date": "2026-06-12", "source": "sms"})
        data = json.loads((tmp_path / "transactions.json").read_text())
        assert len(data) == 1
        assert data[0]["amount"] == 1000
    finally:
        sms_mod._TRANSACTIONS_PATH = original


def test_save_transaction_appends(tmp_path):
    from agents.finance import sms_parser as sms_mod
    original_path = sms_mod._TRANSACTIONS_PATH
    original_dir = sms_mod._FINANCE_DIR
    sms_mod._TRANSACTIONS_PATH = tmp_path / "transactions.json"
    sms_mod._FINANCE_DIR = tmp_path
    try:
        sms_mod.save_transaction({"amount": 1000, "source": "sms", "date": "2026-06-01", "merchant": "A", "card": "신한"})
        sms_mod.save_transaction({"amount": 2000, "source": "sms", "date": "2026-06-02", "merchant": "B", "card": "국민"})
        data = json.loads((tmp_path / "transactions.json").read_text())
        assert len(data) == 2
    finally:
        sms_mod._TRANSACTIONS_PATH = original_path
        sms_mod._FINANCE_DIR = original_dir


def test_load_transactions_for_month(tmp_path):
    from agents.finance import sms_parser as sms_mod
    original_path = sms_mod._TRANSACTIONS_PATH
    sms_mod._TRANSACTIONS_PATH = tmp_path / "transactions.json"
    data = [
        {"amount": 1000, "source": "sms", "date": "2026-06-05", "merchant": "A", "card": "신한"},
        {"amount": 2000, "source": "sms", "date": "2026-07-01", "merchant": "B", "card": "국민"},
        {"amount": 500, "source": "monthly_total", "date": "2026-06-30", "merchant": "월별합산", "card": "신한"},
        {"amount": 3000, "source": "income", "date": "2026-06-01", "merchant": "성과금", "card": ""},
    ]
    (tmp_path / "transactions.json").write_text(json.dumps(data))
    try:
        result = sms_mod.load_transactions_for_month("2026-06")
        assert len(result) == 1  # monthly_total/income 제외, 7월 제외
        assert result[0]["amount"] == 1000
    finally:
        sms_mod._TRANSACTIONS_PATH = original_path


def test_load_income_for_month(tmp_path):
    from agents.finance import sms_parser as sms_mod
    original_path = sms_mod._TRANSACTIONS_PATH
    sms_mod._TRANSACTIONS_PATH = tmp_path / "transactions.json"
    data = [
        {"amount": 1000, "source": "sms", "date": "2026-06-05", "merchant": "A", "card": "신한"},
        {"amount": 5000, "source": "income", "date": "2026-06-01", "merchant": "성과금", "card": ""},
        {"amount": 3000, "source": "income", "date": "2026-07-01", "merchant": "성과금", "card": ""},
    ]
    (tmp_path / "transactions.json").write_text(json.dumps(data))
    try:
        result = sms_mod.load_income_for_month("2026-06")
        assert len(result) == 1
        assert result[0]["amount"] == 5000
    finally:
        sms_mod._TRANSACTIONS_PATH = original_path


def test_parse_and_save_success(tmp_path):
    from agents.finance import sms_parser as sms_mod
    original_path = sms_mod._TRANSACTIONS_PATH
    original_dir = sms_mod._FINANCE_DIR
    sms_mod._TRANSACTIONS_PATH = tmp_path / "transactions.json"
    sms_mod._FINANCE_DIR = tmp_path
    try:
        parsed, success = sms_mod.parse_and_save("신한카드 5,000원 승인 GS25")
        assert success is True
        assert parsed["amount"] == 5000
    finally:
        sms_mod._TRANSACTIONS_PATH = original_path
        sms_mod._FINANCE_DIR = original_dir


def test_parse_and_save_failure(tmp_path):
    from agents.finance import sms_parser as sms_mod
    original_path = sms_mod._TRANSACTIONS_PATH
    original_dir = sms_mod._FINANCE_DIR
    sms_mod._TRANSACTIONS_PATH = tmp_path / "transactions.json"
    sms_mod._FINANCE_DIR = tmp_path
    try:
        parsed, success = sms_mod.parse_and_save("이건 카드 문자가 아닙니다")
        assert success is False
        assert parsed["source"] == "unknown"
        # 실패해도 저장은 되어야 함
        data = json.loads((tmp_path / "transactions.json").read_text())
        assert len(data) == 1
    finally:
        sms_mod._TRANSACTIONS_PATH = original_path
        sms_mod._FINANCE_DIR = original_dir


# ── report_generator ─────────────────────────────────────────────────────────

_EMPTY_ASSETS = {"accounts": [], "savings": [], "loans": [], "real_estate": [], "stocks": []}


def _patch_rg(tmp_path, rg):
    rg._FINANCE_DIR = tmp_path
    rg._SNAPSHOT_PATH = tmp_path / "monthly_snapshot.json"
    rg._FINANCE_ASSETS_PATH = tmp_path / "finance_assets.json"


def test_generate_monthly_report_contains_sections(tmp_path):
    from agents.finance import report_generator as rg
    _patch_rg(tmp_path, rg)
    with patch("agents.finance.report_generator.AssetManager") as MockAM:
        MockAM.return_value.load.return_value = {
            "accounts": [{"name": "카카오뱅크", "balance": 1000000}],
            "savings": [],
            "loans": [],
            "real_estate": [{"name": "아파트", "value": 500000000}],
            "stocks": [{"name": "삼성전자", "total_value": 8000000}],
        }
        with patch("agents.finance.report_generator.load_transactions_for_month", return_value=[
            {"amount": 50000, "source": "sms", "card": "신한"},
            {"amount": 30000, "source": "sms", "card": "국민"},
        ]):
            with patch("agents.finance.report_generator.load_income_for_month", return_value=[]):
                result = rg.generate_monthly_report("2026-06")

    assert "순자산 현황" in result
    assert "수입/지출 요약" in result
    assert "전월 대비" in result
    assert "2026-06" in result


def test_generate_monthly_report_saves_snapshot(tmp_path):
    from agents.finance import report_generator as rg
    _patch_rg(tmp_path, rg)
    with patch("agents.finance.report_generator.AssetManager") as MockAM:
        MockAM.return_value.load.return_value = _EMPTY_ASSETS
        with patch("agents.finance.report_generator.load_transactions_for_month", return_value=[]):
            with patch("agents.finance.report_generator.load_income_for_month", return_value=[]):
                rg.generate_monthly_report("2026-06")

    data = json.loads((tmp_path / "monthly_snapshot.json").read_text())
    assert len(data) == 1
    assert data[0]["month"] == "2026-06"


def test_generate_report_no_duplicate_snapshot(tmp_path):
    """같은 월 리포트 2번 생성해도 스냅샷은 1개 (덮어쓰기)."""
    from agents.finance import report_generator as rg
    _patch_rg(tmp_path, rg)
    with patch("agents.finance.report_generator.AssetManager") as MockAM:
        MockAM.return_value.load.return_value = _EMPTY_ASSETS
        with patch("agents.finance.report_generator.load_transactions_for_month", return_value=[]):
            with patch("agents.finance.report_generator.load_income_for_month", return_value=[]):
                rg.generate_monthly_report("2026-06")
                rg.generate_monthly_report("2026-06")

    data = json.loads((tmp_path / "monthly_snapshot.json").read_text())
    assert len(data) == 1


def test_generate_report_shows_prev_month_trend(tmp_path):
    """전월 스냅샷이 있으면 트렌드 섹션에 전월 데이터가 표시된다."""
    from agents.finance import report_generator as rg
    _patch_rg(tmp_path, rg)

    prev = [{"month": "2026-05", "net_assets": 100000000, "stock_value": 8000000, "real_estate_value": 0, "card_spend": 0}]
    (tmp_path / "monthly_snapshot.json").write_text(json.dumps(prev))

    with patch("agents.finance.report_generator.AssetManager") as MockAM:
        MockAM.return_value.load.return_value = {
            "accounts": [], "savings": [], "loans": [],
            "real_estate": [{"name": "아파트", "value": 110000000}],
            "stocks": [],
        }
        with patch("agents.finance.report_generator.load_transactions_for_month", return_value=[]):
            with patch("agents.finance.report_generator.load_income_for_month", return_value=[]):
                result = rg.generate_monthly_report("2026-06")

    assert "2026-05" in result
    assert "100,000,000" in result


def test_generate_report_no_prev_snapshot_message(tmp_path):
    """전월 데이터 없으면 안내 문구 출력."""
    from agents.finance import report_generator as rg
    _patch_rg(tmp_path, rg)
    with patch("agents.finance.report_generator.AssetManager") as MockAM:
        MockAM.return_value.load.return_value = _EMPTY_ASSETS
        with patch("agents.finance.report_generator.load_transactions_for_month", return_value=[]):
            with patch("agents.finance.report_generator.load_income_for_month", return_value=[]):
                result = rg.generate_monthly_report("2026-06")
    assert "전월 데이터 없음" in result


def test_report_includes_card_spend_note(tmp_path):
    """카드 지출 항목에 '누락 있을 수 있음' 문구가 포함된다."""
    from agents.finance import report_generator as rg
    _patch_rg(tmp_path, rg)
    with patch("agents.finance.report_generator.AssetManager") as MockAM:
        MockAM.return_value.load.return_value = _EMPTY_ASSETS
        with patch("agents.finance.report_generator.load_transactions_for_month", return_value=[
            {"amount": 10000, "source": "sms", "card": "신한"},
        ]):
            with patch("agents.finance.report_generator.load_income_for_month", return_value=[]):
                result = rg.generate_monthly_report("2026-06")
    assert "누락 있을 수 있음" in result


def test_report_shows_card_breakdown(tmp_path):
    """카드사별 지출 내역이 리포트에 표시된다."""
    from agents.finance import report_generator as rg
    _patch_rg(tmp_path, rg)
    with patch("agents.finance.report_generator.AssetManager") as MockAM:
        MockAM.return_value.load.return_value = _EMPTY_ASSETS
        with patch("agents.finance.report_generator.load_transactions_for_month", return_value=[
            {"amount": 300000, "source": "manual", "card": "삼성카드"},
            {"amount": 100000, "source": "manual", "card": "토스카드"},
        ]):
            with patch("agents.finance.report_generator.load_income_for_month", return_value=[]):
                result = rg.generate_monthly_report("2026-06")
    assert "삼성카드" in result
    assert "300,000" in result
    assert "토스카드" in result


def test_report_shows_extra_income(tmp_path):
    """성과금 등 추가 수입이 리포트에 표시되고 총 수입이 계산된다."""
    from agents.finance import report_generator as rg
    _patch_rg(tmp_path, rg)
    (tmp_path / "finance_assets.json").write_text(json.dumps(
        {"fixed": {"salary": 9800000, "savings": 0, "fixed_expenses": []}}
    ))
    with patch("agents.finance.report_generator.AssetManager") as MockAM:
        MockAM.return_value.load.return_value = _EMPTY_ASSETS
        with patch("agents.finance.report_generator.load_transactions_for_month", return_value=[]):
            with patch("agents.finance.report_generator.load_income_for_month", return_value=[
                {"amount": 6376700, "merchant": "업무성과금(가현)", "source": "income"},
            ]):
                result = rg.generate_monthly_report("2026-06")
    assert "업무성과금(가현)" in result
    assert "총 수입" in result
    assert "16,176,700" in result  # 9,800,000 + 6,376,700


def test_prev_month_helper():
    from agents.finance.report_generator import _prev_month
    assert _prev_month("2026-06") == "2026-05"
    assert _prev_month("2026-01") == "2025-12"
    assert _prev_month("2020-03") == "2020-02"


# ── finance_agent 커맨드 라우팅 ───────────────────────────────────────────────

def _make_intent(raw: str):
    intent = MagicMock()
    intent.raw_message = raw
    intent.chat_id = 0
    return intent


@pytest.mark.asyncio
async def test_finance_agent_routes_monthly_report():
    """'월별 리포트' 키워드가 generate_monthly_report()로 라우팅된다."""
    from agents.finance.finance_agent import FinanceAgent

    intent = _make_intent("월별 리포트 보여줘")
    with patch("agents.finance.finance_agent.generate_monthly_report", return_value="리포트 내용") as mock_report:
        agent = FinanceAgent()
        result = await agent.handle(intent)
    mock_report.assert_called_once()
    assert result == "리포트 내용"


@pytest.mark.asyncio
async def test_finance_agent_routes_asset_status():
    """'자산 현황' 키워드가 generate_monthly_report()로 라우팅된다."""
    from agents.finance.finance_agent import FinanceAgent

    intent = _make_intent("자산 현황 알려줘")
    with patch("agents.finance.finance_agent.generate_monthly_report", return_value="자산 현황") as mock_report:
        agent = FinanceAgent()
        result = await agent.handle(intent)
    mock_report.assert_called_once()


@pytest.mark.asyncio
async def test_finance_agent_routes_card_sms_success():
    """'카드 문자' + 문자 내용이 파싱되고 확인 메시지 반환."""
    from agents.finance.finance_agent import FinanceAgent

    intent = _make_intent("카드 문자 신한카드 12,000원 승인 스타벅스")
    with patch("agents.finance.finance_agent.parse_and_save",
               return_value=({"amount": 12000, "card": "신한", "merchant": "스타벅스", "source": "sms"}, True)):
        agent = FinanceAgent()
        result = await agent.handle(intent)
    assert "기록 완료" in result
    assert "12,000" in result


@pytest.mark.asyncio
async def test_finance_agent_routes_card_sms_failure():
    """카드 문자 파싱 실패 시 사용자 확인 요청 메시지 반환."""
    from agents.finance.finance_agent import FinanceAgent

    intent = _make_intent("카드 문자 이건 알 수 없는 문자")
    with patch("agents.finance.finance_agent.parse_and_save",
               return_value=({"amount": 0, "source": "unknown", "raw": "이건 알 수 없는 문자"}, False)):
        agent = FinanceAgent()
        result = await agent.handle(intent)
    assert "파싱 실패" in result or "확인" in result


@pytest.mark.asyncio
async def test_finance_agent_card_sms_no_content():
    """'카드 문자'만 입력 시 안내 메시지 반환."""
    from agents.finance.finance_agent import FinanceAgent

    intent = _make_intent("카드 문자")
    with patch("agents.finance.finance_agent.parse_and_save") as mock_parse:
        agent = FinanceAgent()
        result = await agent.handle(intent)
    mock_parse.assert_not_called()
    assert "내용을 찾지 못했습니다" in result or "예:" in result


# ── chart_generator ──────────────────────────────────────────────────────────

def test_generate_chart_returns_bytes(tmp_path):
    from agents.finance import chart_generator as cg
    cg._SNAPSHOT_PATH = tmp_path / "monthly_snapshot.json"
    cg._TRANSACTIONS_PATH = tmp_path / "transactions.json"
    cg._FINANCE_ASSETS_PATH = tmp_path / "finance_assets.json"

    snaps = [
        {"month": "2026-05", "net_assets": 100, "stock_value": 0, "real_estate_value": 0, "card_spend": 2000000},
        {"month": "2026-06", "net_assets": 100, "stock_value": 0, "real_estate_value": 0, "card_spend": 1500000},
    ]
    (tmp_path / "monthly_snapshot.json").write_text(json.dumps(snaps))
    (tmp_path / "transactions.json").write_text("[]")
    (tmp_path / "finance_assets.json").write_text(json.dumps(
        {"fixed": {"salary": 9800000, "savings": 200000, "fixed_expenses": []}}
    ))

    result = cg.generate_chart(2)
    assert isinstance(result, bytes)
    assert len(result) > 1000
    assert result[:4] == b'\x89PNG'  # PNG magic bytes


def test_generate_excel_returns_xlsx(tmp_path):
    from agents.finance import chart_generator as cg
    cg._SNAPSHOT_PATH = tmp_path / "monthly_snapshot.json"
    cg._TRANSACTIONS_PATH = tmp_path / "transactions.json"
    cg._FINANCE_ASSETS_PATH = tmp_path / "finance_assets.json"

    snaps = [{"month": "2026-06", "net_assets": 100, "stock_value": 0, "real_estate_value": 0, "card_spend": 500000}]
    (tmp_path / "monthly_snapshot.json").write_text(json.dumps(snaps))
    txs = [
        {"date": "2026-06-01", "amount": 300000, "card": "삼성카드", "source": "manual"},
        {"date": "2026-06-01", "amount": 200000, "card": "토스카드", "source": "manual"},
    ]
    (tmp_path / "transactions.json").write_text(json.dumps(txs))
    (tmp_path / "finance_assets.json").write_text(json.dumps(
        {"fixed": {"salary": 9800000, "savings": 200000, "fixed_expenses": []}}
    ))

    result = cg.generate_excel(1)
    assert isinstance(result, bytes)
    # xlsx magic bytes (PK zip)
    assert result[:2] == b'PK'
