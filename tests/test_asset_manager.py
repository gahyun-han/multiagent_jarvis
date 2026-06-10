import json
import unittest.mock
from pathlib import Path

import pytest

from agents.finance.asset_manager import AssetManager, _EMPTY
import agents.finance.asset_manager as asset_manager_module


def _patch_path(p):
    return unittest.mock.patch.object(asset_manager_module, "ASSET_PATH", p)


# ── load() ──────────────────────────────────────────────────────────────────

def test_load_returns_empty_when_file_missing(tmp_path):
    missing = tmp_path / "assets.json"
    with _patch_path(missing):
        result = AssetManager().load()
    assert result == {"accounts": [], "savings": [], "loans": [], "real_estate": [], "stocks": []}


def test_load_returns_full_structure(tmp_path):
    asset_file = tmp_path / "assets.json"
    data = {
        "accounts": [{"name": "신한", "balance": 1000}],
        "savings": [{"name": "청약", "balance": 2000}],
        "loans": [{"name": "주담대", "remaining": 500}],
        "real_estate": [{"name": "아파트", "value": 9000}],
    }
    asset_file.write_text(json.dumps(data), encoding="utf-8")
    with _patch_path(asset_file):
        result = AssetManager().load()
    assert result["accounts"] == data["accounts"]
    assert result["savings"] == data["savings"]
    assert result["loans"] == data["loans"]
    assert result["real_estate"] == data["real_estate"]


def test_load_migrates_legacy_list_format(tmp_path):
    asset_file = tmp_path / "assets.json"
    legacy = [{"name": "국민", "balance": 500}]
    asset_file.write_text(json.dumps(legacy), encoding="utf-8")
    with _patch_path(asset_file):
        result = AssetManager().load()
    assert result["accounts"] == legacy
    assert result["savings"] == []
    assert result["loans"] == []
    assert result["real_estate"] == []


def test_load_fills_missing_keys_with_empty_lists(tmp_path):
    asset_file = tmp_path / "assets.json"
    asset_file.write_text(json.dumps({"accounts": [{"name": "X", "balance": 1}]}), encoding="utf-8")
    with _patch_path(asset_file):
        result = AssetManager().load()
    assert result["savings"] == []
    assert result["loans"] == []
    assert result["real_estate"] == []


def test_load_returns_empty_on_invalid_json(tmp_path):
    asset_file = tmp_path / "assets.json"
    asset_file.write_text("not json", encoding="utf-8")
    with _patch_path(asset_file):
        result = AssetManager().load()
    assert result == {"accounts": [], "savings": [], "loans": [], "real_estate": [], "stocks": []}


def test_load_returns_empty_on_read_permission_error():
    mock_path = unittest.mock.MagicMock(spec=Path)
    mock_path.exists.return_value = True
    mock_path.read_text.side_effect = PermissionError("Permission denied")
    with _patch_path(mock_path):
        result = AssetManager().load()
    assert result == {"accounts": [], "savings": [], "loans": [], "real_estate": [], "stocks": []}


# ── save() ───────────────────────────────────────────────────────────────────

def test_save_writes_utf8_json(tmp_path):
    asset_file = tmp_path / "assets.json"
    data = {"accounts": [{"name": "국민은행", "balance": 100}]}
    with _patch_path(asset_file):
        AssetManager().save(data)
    raw = asset_file.read_text(encoding="utf-8")
    assert "국민은행" in raw
    assert json.loads(raw) == data


def test_save_overwrites_existing_file(tmp_path):
    asset_file = tmp_path / "assets.json"
    asset_file.write_text(json.dumps({"accounts": [{"name": "old", "balance": 1}]}), encoding="utf-8")
    new_data = {"accounts": [{"name": "new", "balance": 999}]}
    with _patch_path(asset_file):
        AssetManager().save(new_data)
    assert json.loads(asset_file.read_text(encoding="utf-8")) == new_data


# ── upsert() ─────────────────────────────────────────────────────────────────

def test_upsert_adds_new_item_to_empty_category(tmp_path):
    asset_file = tmp_path / "assets.json"
    with _patch_path(asset_file):
        AssetManager().upsert("savings", [{"name": "청약저축", "balance": 50000}])
        result = AssetManager().load()
    assert any(item["name"] == "청약저축" for item in result["savings"])


def test_upsert_updates_existing_item_by_name(tmp_path):
    asset_file = tmp_path / "assets.json"
    initial = {
        "accounts": [{"name": "카카오뱅크", "balance": 100}],
        "savings": [], "loans": [], "real_estate": [],
    }
    asset_file.write_text(json.dumps(initial), encoding="utf-8")
    with _patch_path(asset_file):
        AssetManager().upsert("accounts", [{"name": "카카오뱅크", "balance": 200}])
        result = AssetManager().load()
    accounts = result["accounts"]
    assert len(accounts) == 1
    assert accounts[0]["balance"] == 200


def test_upsert_preserves_other_categories(tmp_path):
    asset_file = tmp_path / "assets.json"
    initial = {
        "accounts": [],
        "savings": [{"name": "청약", "balance": 100}],
        "loans": [{"name": "주담대", "remaining": 1000}],
        "real_estate": [],
    }
    asset_file.write_text(json.dumps(initial), encoding="utf-8")
    with _patch_path(asset_file):
        AssetManager().upsert("accounts", [{"name": "신한", "balance": 500}])
        result = AssetManager().load()
    assert result["savings"] == initial["savings"]
    assert result["loans"] == initial["loans"]


def test_upsert_adds_multiple_items_at_once(tmp_path):
    asset_file = tmp_path / "assets.json"
    with _patch_path(asset_file):
        AssetManager().upsert("accounts", [{"name": "A", "balance": 1}, {"name": "B", "balance": 2}])
        result = AssetManager().load()
    names = [item["name"] for item in result["accounts"]]
    assert "A" in names
    assert "B" in names


# ── net_worth_summary() ───────────────────────────────────────────────────────

def test_net_worth_summary_no_data_returns_placeholder(tmp_path):
    missing = tmp_path / "assets.json"
    with _patch_path(missing):
        result = AssetManager().net_worth_summary()
    assert result == "등록된 자산 정보가 없습니다."


def test_net_worth_summary_accounts_only(tmp_path):
    asset_file = tmp_path / "assets.json"
    data = {
        "accounts": [{"name": "신한", "balance": 1000000}],
        "savings": [], "loans": [], "real_estate": [],
    }
    asset_file.write_text(json.dumps(data), encoding="utf-8")
    with _patch_path(asset_file):
        result = AssetManager().net_worth_summary()
    assert "통장/계좌" in result
    assert "1,000,000원" in result
    assert "총 자산" in result
    assert "총 부채" not in result


def test_net_worth_summary_loans_shown_and_net_computed(tmp_path):
    asset_file = tmp_path / "assets.json"
    data = {
        "accounts": [{"name": "신한", "balance": 2000000}],
        "savings": [],
        "loans": [{"name": "카카오대출", "remaining": 500000}],
        "real_estate": [],
    }
    asset_file.write_text(json.dumps(data), encoding="utf-8")
    with _patch_path(asset_file):
        result = AssetManager().net_worth_summary()
    assert "2,000,000원" in result
    assert "500,000원" in result
    assert "총 부채" in result
    assert "1,500,000원" in result


def test_net_worth_summary_savings_optional_fields_absent(tmp_path):
    asset_file = tmp_path / "assets.json"
    data = {
        "accounts": [],
        "savings": [{"name": "청약", "balance": 300000}],
        "loans": [], "real_estate": [],
    }
    asset_file.write_text(json.dumps(data), encoding="utf-8")
    with _patch_path(asset_file):
        result = AssetManager().net_worth_summary()
    assert "청약: 300,000원" in result
    savings_lines = [ln for ln in result.splitlines() if "청약" in ln and "적금" not in ln]
    assert len(savings_lines) == 1
    assert "%" not in savings_lines[0]
    assert "만기" not in savings_lines[0]
    assert "월" not in savings_lines[0]


def test_net_worth_summary_savings_all_optional_fields_present(tmp_path):
    asset_file = tmp_path / "assets.json"
    data = {
        "accounts": [],
        "savings": [{
            "name": "정기적금", "balance": 500000,
            "interest_rate": 3.5, "monthly": 100000, "maturity_date": "2027-01-01",
        }],
        "loans": [], "real_estate": [],
    }
    asset_file.write_text(json.dumps(data), encoding="utf-8")
    with _patch_path(asset_file):
        result = AssetManager().net_worth_summary()
    assert "(3.5%)" in result
    assert "월 100,000원" in result
    assert "만기: 2027-01-01" in result


def test_net_worth_summary_loans_optional_fields_absent(tmp_path):
    asset_file = tmp_path / "assets.json"
    data = {
        "accounts": [],
        "savings": [],
        "loans": [{"name": "주택담보", "remaining": 50000000}],
        "real_estate": [],
    }
    asset_file.write_text(json.dumps(data), encoding="utf-8")
    with _patch_path(asset_file):
        result = AssetManager().net_worth_summary()
    assert "50,000,000원" in result
    loan_lines = [ln for ln in result.splitlines() if "주택담보" in ln]
    assert len(loan_lines) == 1
    assert "%" not in loan_lines[0]
    assert "월상환" not in loan_lines[0]
    assert "만기" not in loan_lines[0]


def test_net_worth_summary_real_estate_with_address(tmp_path):
    asset_file = tmp_path / "assets.json"
    data = {
        "accounts": [], "savings": [], "loans": [],
        "real_estate": [{"name": "아파트", "value": 500000000, "address": "서울 강남구"}],
    }
    asset_file.write_text(json.dumps(data), encoding="utf-8")
    with _patch_path(asset_file):
        result = AssetManager().net_worth_summary()
    assert "(서울 강남구)" in result


def test_net_worth_summary_real_estate_without_address(tmp_path):
    asset_file = tmp_path / "assets.json"
    data = {
        "accounts": [], "savings": [], "loans": [],
        "real_estate": [{"name": "오피스텔", "value": 200000000}],
    }
    asset_file.write_text(json.dumps(data), encoding="utf-8")
    with _patch_path(asset_file):
        result = AssetManager().net_worth_summary()
    re_lines = [ln for ln in result.splitlines() if "오피스텔" in ln]
    assert len(re_lines) == 1
    assert "오피스텔: 200,000,000원" in re_lines[0]
    assert "(" not in re_lines[0]


def test_net_worth_summary_zero_balance_items_included(tmp_path):
    asset_file = tmp_path / "assets.json"
    data = {
        "accounts": [{"name": "비상금통장", "balance": 0}],
        "savings": [], "loans": [], "real_estate": [],
    }
    asset_file.write_text(json.dumps(data), encoding="utf-8")
    with _patch_path(asset_file):
        result = AssetManager().net_worth_summary()
    assert "비상금통장" in result
    assert "0원" in result


# ── edge cases ───────────────────────────────────────────────────────────────

def test_upsert_unknown_category_creates_key(tmp_path):
    asset_file = tmp_path / "assets.json"
    with _patch_path(asset_file):
        AssetManager().upsert("crypto", [{"name": "BTC", "balance": 1}])
        result = AssetManager().load()
    assert "crypto" in result
    assert any(item["name"] == "BTC" for item in result["crypto"])


def test_load_does_not_mutate_empty_sentinel(tmp_path):
    missing = tmp_path / "assets.json"
    with _patch_path(missing):
        result1 = AssetManager().load()
        result2 = AssetManager().load()
    assert result1 is not result2
    # Rebinding a key on one returned dict must not affect the other or _EMPTY
    result1["accounts"] = [{"name": "injected"}]
    assert result2["accounts"] == []
    assert _EMPTY["accounts"] == []