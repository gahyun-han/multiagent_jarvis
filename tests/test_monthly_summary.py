import json
import pytest
from pathlib import Path

import agents.finance.monthly_summary as ms
from agents.finance.monthly_summary import (
    _load_ledger,
    _entry_month,
    _bar,
    _fmt,
    _today_str,
    get_monthly_summary,
    get_monthly_graph,
    get_category_detail,
)


def _write_ledger(tmp_path, entries):
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps(entries), encoding="utf-8")
    return p


# ── _load_ledger ───────────────────────────────────────────────────────────

def test_load_ledger_file_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(ms, "LEDGER_PATH", tmp_path / "nonexistent.json")
    assert _load_ledger() == []


def test_load_ledger_valid_json(monkeypatch, tmp_path):
    data = [{"date": "2026-05-01", "type": "income", "amount": 1000}]
    p = _write_ledger(tmp_path, data)
    monkeypatch.setattr(ms, "LEDGER_PATH", p)
    result = _load_ledger()
    assert len(result) == 1
    assert result[0]["amount"] == 1000


def test_load_ledger_invalid_json(monkeypatch, tmp_path):
    p = tmp_path / "ledger.json"
    p.write_text("{broken json", encoding="utf-8")
    monkeypatch.setattr(ms, "LEDGER_PATH", p)
    assert _load_ledger() == []


# ── _entry_month ───────────────────────────────────────────────────────────

def test_entry_month_valid_date():
    assert _entry_month({"date": "2026-03-15"}) == "2026-03"


def test_entry_month_missing_date_key():
    assert _entry_month({}) == _today_str()


def test_entry_month_short_date_string():
    assert _entry_month({"date": "2026-0"}) == _today_str()


# ── _bar ───────────────────────────────────────────────────────────────────

def test_bar_normal():
    assert _bar(6, 12, 12) == "██████░░░░░░"


def test_bar_max_value_zero():
    assert _bar(0, 0, 12) == "░░░░░░░░░░░░"


def test_bar_full():
    assert _bar(12, 12, 12) == "████████████"


def test_bar_zero_value():
    assert _bar(0, 100, 12) == "░░░░░░░░░░░░"


# ── _fmt ───────────────────────────────────────────────────────────────────

def test_fmt_millions():
    assert _fmt(2_500_000) == "2.5M"


def test_fmt_ten_thousands():
    assert _fmt(35_000) == "3만"


def test_fmt_small_amount():
    assert _fmt(9_999) == "9,999"


def test_fmt_exactly_ten_thousand():
    assert _fmt(10_000) == "1만"


# ── get_monthly_summary ────────────────────────────────────────────────────

def test_get_monthly_summary_no_data(monkeypatch, tmp_path):
    data = [
        {"date": "2026-05-01", "type": "income", "amount": 100_000,
         "category": "수입", "description": "salary"},
    ]
    p = _write_ledger(tmp_path, data)
    monkeypatch.setattr(ms, "LEDGER_PATH", p)
    result = get_monthly_summary("2026-01")
    assert "2026-01" in result
    assert "데이터가 없습니다" in result


def test_get_monthly_summary_happy_path(monkeypatch, tmp_path):
    data = [
        {"date": "2026-05-01", "type": "income", "amount": 3_000_000,
         "category": "수입", "description": "salary"},
        {"date": "2026-05-05", "type": "expense", "amount": 50_000,
         "category": "식비", "description": "lunch"},
        {"date": "2026-05-10", "type": "expense", "amount": 30_000,
         "category": "교통", "description": "bus"},
    ]
    p = _write_ledger(tmp_path, data)
    monkeypatch.setattr(ms, "LEDGER_PATH", p)
    result = get_monthly_summary("2026-05")
    assert "수입" in result
    assert "지출" in result
    assert "잔여" in result
    assert "식비" in result
    assert "교통" in result
    assert "█" in result


def test_get_monthly_summary_default_month(monkeypatch, tmp_path):
    current = _today_str()
    data = [
        {"date": f"{current}-01", "type": "income", "amount": 200_000,
         "category": "수입", "description": "test"},
    ]
    p = _write_ledger(tmp_path, data)
    monkeypatch.setattr(ms, "LEDGER_PATH", p)
    result = get_monthly_summary()
    assert current in result


def test_get_monthly_summary_negative_balance(monkeypatch, tmp_path):
    data = [
        {"date": "2026-05-01", "type": "income", "amount": 100_000,
         "category": "수입", "description": "income"},
        {"date": "2026-05-02", "type": "expense", "amount": 200_000,
         "category": "기타", "description": "expense"},
    ]
    p = _write_ledger(tmp_path, data)
    monkeypatch.setattr(ms, "LEDGER_PATH", p)
    result = get_monthly_summary("2026-05")
    assert "🔴" in result
    assert "-100,000" in result


def test_get_monthly_summary_positive_balance(monkeypatch, tmp_path):
    data = [
        {"date": "2026-05-01", "type": "income", "amount": 300_000,
         "category": "수입", "description": "income"},
        {"date": "2026-05-02", "type": "expense", "amount": 100_000,
         "category": "기타", "description": "expense"},
    ]
    p = _write_ledger(tmp_path, data)
    monkeypatch.setattr(ms, "LEDGER_PATH", p)
    result = get_monthly_summary("2026-05")
    assert "✅" in result
    assert "200,000" in result


def test_get_monthly_summary_missing_category_defaults_to_기타(monkeypatch, tmp_path):
    data = [
        {"date": "2026-05-10", "type": "expense", "amount": 5_000,
         "description": "mystery"},
    ]
    p = _write_ledger(tmp_path, data)
    monkeypatch.setattr(ms, "LEDGER_PATH", p)
    result = get_monthly_summary("2026-05")
    assert "기타" in result


def test_get_monthly_summary_only_income_no_expense(monkeypatch, tmp_path):
    data = [
        {"date": "2026-05-01", "type": "income", "amount": 500_000,
         "category": "수입", "description": "salary"},
    ]
    p = _write_ledger(tmp_path, data)
    monkeypatch.setattr(ms, "LEDGER_PATH", p)
    result = get_monthly_summary("2026-05")
    assert "500,000" in result
    assert "식비" not in result
    assert "교통" not in result
    assert "쇼핑" not in result


def test_get_monthly_summary_empty_ledger(monkeypatch, tmp_path):
    monkeypatch.setattr(ms, "LEDGER_PATH", tmp_path / "nonexistent.json")
    result = get_monthly_summary("2026-05")
    assert "데이터가 없습니다" in result


# ── get_monthly_graph ──────────────────────────────────────────────────────

def test_get_monthly_graph_empty_ledger(monkeypatch, tmp_path):
    monkeypatch.setattr(ms, "LEDGER_PATH", tmp_path / "nonexistent.json")
    result = get_monthly_graph(3)
    assert "데이터가 없습니다" in result


def test_get_monthly_graph_happy_path(monkeypatch, tmp_path):
    data = [
        {"date": "2026-03-01", "type": "income", "amount": 200_000, "description": "a"},
        {"date": "2026-03-05", "type": "expense", "amount": 50_000,
         "category": "식비", "description": "b"},
        {"date": "2026-04-01", "type": "income", "amount": 210_000, "description": "c"},
        {"date": "2026-04-05", "type": "expense", "amount": 60_000,
         "category": "교통", "description": "d"},
        {"date": "2026-05-01", "type": "income", "amount": 220_000, "description": "e"},
        {"date": "2026-05-05", "type": "expense", "amount": 70_000,
         "category": "기타", "description": "f"},
    ]
    p = _write_ledger(tmp_path, data)
    monkeypatch.setattr(ms, "LEDGER_PATH", p)
    result = get_monthly_graph(3)
    assert "2026-03" in result
    assert "2026-04" in result
    assert "2026-05" in result
    assert "💰" in result
    assert "💸" in result


def test_get_monthly_graph_fewer_months_than_requested(monkeypatch, tmp_path):
    data = [
        {"date": "2026-05-01", "type": "income", "amount": 100_000, "description": "a"},
        {"date": "2026-05-02", "type": "expense", "amount": 50_000,
         "category": "기타", "description": "b"},
    ]
    p = _write_ledger(tmp_path, data)
    monkeypatch.setattr(ms, "LEDGER_PATH", p)
    result = get_monthly_graph(3)
    assert "2026-05" in result
    assert "1개월" in result


def test_get_monthly_graph_single_month(monkeypatch, tmp_path):
    data = [
        {"date": "2026-03-01", "type": "income", "amount": 200_000, "description": "a"},
        {"date": "2026-04-01", "type": "income", "amount": 210_000, "description": "b"},
        {"date": "2026-05-01", "type": "income", "amount": 220_000, "description": "c"},
    ]
    p = _write_ledger(tmp_path, data)
    monkeypatch.setattr(ms, "LEDGER_PATH", p)
    result = get_monthly_graph(1)
    assert "2026-05" in result
    assert "2026-03" not in result
    assert "2026-04" not in result


def test_get_monthly_graph_chronological_order(monkeypatch, tmp_path):
    data = [
        {"date": "2026-03-01", "type": "income", "amount": 100_000, "description": "a"},
        {"date": "2026-05-01", "type": "income", "amount": 120_000, "description": "b"},
    ]
    p = _write_ledger(tmp_path, data)
    monkeypatch.setattr(ms, "LEDGER_PATH", p)
    result = get_monthly_graph(2)
    assert result.index("2026-03") < result.index("2026-05")


# ── get_category_detail ────────────────────────────────────────────────────

def test_get_category_detail_no_data(monkeypatch, tmp_path):
    data = [
        {"date": "2026-05-01", "type": "expense", "amount": 10_000,
         "category": "교통", "description": "bus"},
    ]
    p = _write_ledger(tmp_path, data)
    monkeypatch.setattr(ms, "LEDGER_PATH", p)
    result = get_category_detail("식비", "2026-01")
    assert "2026-01" in result
    assert "식비" in result
    assert "항목이 없습니다" in result


def test_get_category_detail_happy_path(monkeypatch, tmp_path):
    data = [
        {"date": "2026-05-20", "type": "expense", "amount": 20_000,
         "category": "식비", "description": "dinner"},
        {"date": "2026-05-01", "type": "expense", "amount": 10_000,
         "category": "식비", "description": "lunch"},
    ]
    p = _write_ledger(tmp_path, data)
    monkeypatch.setattr(ms, "LEDGER_PATH", p)
    result = get_category_detail("식비", "2026-05")
    assert "30,000" in result
    assert "dinner" in result
    assert "lunch" in result


def test_get_category_detail_default_month(monkeypatch, tmp_path):
    current = _today_str()
    data = [
        {"date": f"{current}-15", "type": "expense", "amount": 15_000,
         "category": "교통", "description": "taxi"},
    ]
    p = _write_ledger(tmp_path, data)
    monkeypatch.setattr(ms, "LEDGER_PATH", p)
    result = get_category_detail("교통")
    assert current in result


def test_get_category_detail_excludes_income_entries(monkeypatch, tmp_path):
    data = [
        {"date": "2026-05-01", "type": "income", "amount": 50_000,
         "category": "식비", "description": "bonus"},
    ]
    p = _write_ledger(tmp_path, data)
    monkeypatch.setattr(ms, "LEDGER_PATH", p)
    result = get_category_detail("식비", "2026-05")
    assert "항목이 없습니다" in result


def test_get_category_detail_sorted_newest_first(monkeypatch, tmp_path):
    data = [
        {"date": "2026-05-01", "type": "expense", "amount": 10_000,
         "category": "식비", "description": "early"},
        {"date": "2026-05-20", "type": "expense", "amount": 20_000,
         "category": "식비", "description": "late"},
    ]
    p = _write_ledger(tmp_path, data)
    monkeypatch.setattr(ms, "LEDGER_PATH", p)
    result = get_category_detail("식비", "2026-05")
    assert result.index("2026-05-20") < result.index("2026-05-01")


def test_get_category_detail_entry_missing_date(monkeypatch, tmp_path):
    data = [
        {"type": "expense", "amount": 8_000, "category": "식비",
         "description": "nodateitem"},
    ]
    p = _write_ledger(tmp_path, data)
    monkeypatch.setattr(ms, "LEDGER_PATH", p)
    result = get_category_detail("식비", _today_str())
    assert "nodateitem" in result