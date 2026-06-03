import json
import pytest
from datetime import date
from pathlib import Path
import agents.finance.savings_tracker as savings_tracker_module
from agents.finance.savings_tracker import SavingsTracker


@pytest.fixture(autouse=True)
def redirect_savings_path(tmp_path, monkeypatch):
    fake_path = tmp_path / "savings.json"
    monkeypatch.setattr(savings_tracker_module, "SAVINGS_PATH", fake_path)
    return fake_path


def test_load_returns_defaults_when_file_missing(redirect_savings_path):
    tracker = SavingsTracker()
    result = tracker.load()
    assert result == {"accounts": [], "loans": [], "last_updated": None}


def test_load_returns_parsed_data_when_file_exists(redirect_savings_path):
    payload = {
        "accounts": [{"name": "ISA", "balance": 1000000}],
        "loans": [],
        "last_updated": "2026-01-01",
    }
    redirect_savings_path.write_text(json.dumps(payload), encoding="utf-8")
    tracker = SavingsTracker()
    result = tracker.load()
    assert result["accounts"][0]["name"] == "ISA"
    assert result["accounts"][0]["balance"] == 1000000
    assert result["last_updated"] == "2026-01-01"
    assert result["loans"] == []


def test_load_returns_defaults_on_invalid_json(redirect_savings_path):
    redirect_savings_path.write_text("not json", encoding="utf-8")
    tracker = SavingsTracker()
    result = tracker.load()
    assert result == {"accounts": [], "loans": [], "last_updated": None}


def test_add_account_happy_path(redirect_savings_path):
    tracker = SavingsTracker()
    tracker.add_account("청약", 5000000, monthly=300000, maturity_date="2027-12-31")
    data = json.loads(redirect_savings_path.read_text(encoding="utf-8"))
    assert len(data["accounts"]) == 1
    acc = data["accounts"][0]
    assert acc["name"] == "청약"
    assert acc["balance"] == 5000000
    assert acc["monthly_contribution"] == 300000
    assert acc["maturity_date"] == "2027-12-31"
    assert data["last_updated"] == date.today().isoformat()


def test_add_account_defaults_monthly_to_zero(redirect_savings_path):
    tracker = SavingsTracker()
    tracker.add_account("비상금", 1000000)
    data = json.loads(redirect_savings_path.read_text(encoding="utf-8"))
    assert data["accounts"][0]["monthly_contribution"] == 0


def test_add_account_defaults_maturity_date_to_none(redirect_savings_path):
    tracker = SavingsTracker()
    tracker.add_account("파킹통장", 200000)
    data = json.loads(redirect_savings_path.read_text(encoding="utf-8"))
    assert data["accounts"][0]["maturity_date"] is None


def test_add_account_multiple_appends(redirect_savings_path):
    tracker = SavingsTracker()
    tracker.add_account("첫번째", 100000)
    tracker.add_account("두번째", 200000)
    data = json.loads(redirect_savings_path.read_text(encoding="utf-8"))
    assert len(data["accounts"]) == 2
    assert data["accounts"][0]["name"] == "첫번째"
    assert data["accounts"][1]["name"] == "두번째"


def test_add_account_updates_last_updated(redirect_savings_path):
    tracker = SavingsTracker()
    tracker.add_account("CMA", 500000)
    data = json.loads(redirect_savings_path.read_text(encoding="utf-8"))
    assert data["last_updated"] == date.today().isoformat()


def test_get_summary_no_data(redirect_savings_path):
    tracker = SavingsTracker()
    result = tracker.get_summary()
    assert result == "등록된 저축/대출 정보가 없습니다."


def test_get_summary_no_data_empty_lists(redirect_savings_path):
    redirect_savings_path.write_text(
        json.dumps({"accounts": [], "loans": [], "last_updated": None}),
        encoding="utf-8",
    )
    tracker = SavingsTracker()
    result = tracker.get_summary()
    assert result == "등록된 저축/대출 정보가 없습니다."


def test_get_summary_accounts_only(redirect_savings_path):
    data = {
        "accounts": [
            {"name": "A", "balance": 1000000, "maturity_date": None},
            {"name": "B", "balance": 500000, "maturity_date": None},
        ],
        "loans": [],
        "last_updated": "2026-01-01",
    }
    redirect_savings_path.write_text(json.dumps(data), encoding="utf-8")
    tracker = SavingsTracker()
    result = tracker.get_summary()
    assert "1,000,000원" in result
    assert "500,000원" in result
    assert "총합: 1,500,000원" in result
    assert "대출 현황" not in result


def test_get_summary_includes_maturity_date_when_present(redirect_savings_path):
    data = {
        "accounts": [
            {"name": "정기적금", "balance": 2000000, "maturity_date": "2028-06-30"},
            {"name": "파킹통장", "balance": 300000, "maturity_date": None},
        ],
        "loans": [],
        "last_updated": "2026-01-01",
    }
    redirect_savings_path.write_text(json.dumps(data), encoding="utf-8")
    tracker = SavingsTracker()
    result = tracker.get_summary()
    lines = result.splitlines()
    account_lines = [l for l in lines if "정기적금" in l or "파킹통장" in l]
    assert any("(만기: 2028-06-30)" in l for l in account_lines if "정기적금" in l)
    assert all("(만기:" not in l for l in account_lines if "파킹통장" in l)


def test_get_summary_loans_section(redirect_savings_path):
    data = {
        "accounts": [{"name": "저축", "balance": 1000000, "maturity_date": None}],
        "loans": [{"name": "신용대출", "remaining": 3000000}],
        "last_updated": "2026-01-01",
    }
    redirect_savings_path.write_text(json.dumps(data), encoding="utf-8")
    tracker = SavingsTracker()
    result = tracker.get_summary()
    assert "대출 현황" in result
    assert "3,000,000원" in result
    assert "신용대출" in result


def test_get_summary_loan_missing_remaining_defaults_to_zero(redirect_savings_path):
    data = {
        "accounts": [{"name": "저축", "balance": 100000, "maturity_date": None}],
        "loans": [{"name": "학자금"}],
        "last_updated": "2026-01-01",
    }
    redirect_savings_path.write_text(json.dumps(data), encoding="utf-8")
    tracker = SavingsTracker()
    result = tracker.get_summary()
    assert "0원" in result


def test_get_summary_zero_balance_account(redirect_savings_path):
    data = {
        "accounts": [{"name": "빈통장", "balance": 0, "maturity_date": None}],
        "loans": [],
        "last_updated": "2026-01-01",
    }
    redirect_savings_path.write_text(json.dumps(data), encoding="utf-8")
    tracker = SavingsTracker()
    result = tracker.get_summary()
    assert "0원" in result
    assert "총합: 0원" in result


def test_get_summary_large_balance_formatting(redirect_savings_path):
    data = {
        "accounts": [{"name": "연금", "balance": 100000000, "maturity_date": None}],
        "loans": [],
        "last_updated": "2026-01-01",
    }
    redirect_savings_path.write_text(json.dumps(data), encoding="utf-8")
    tracker = SavingsTracker()
    result = tracker.get_summary()
    assert "100,000,000원" in result


def test_save_writes_valid_json_file(redirect_savings_path):
    data = {
        "accounts": [{"name": "한글계좌", "balance": 1000}],
        "loans": [],
        "last_updated": "2026-05-31",
    }
    tracker = SavingsTracker()
    tracker._save(data)
    assert redirect_savings_path.exists()
    raw = redirect_savings_path.read_text(encoding="utf-8")
    loaded = json.loads(raw)
    assert loaded == data
    assert "한글계좌" in raw