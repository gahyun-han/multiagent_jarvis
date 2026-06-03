import json
from datetime import date, timedelta
from unittest.mock import patch

from agents.finance.ledger_parser import LedgerParser


def _parser():
    return LedgerParser()


# ---------- parse() ----------

def test_parse_returns_first_entry():
    entries = [
        {"type": "expense", "amount": 5000, "category": "식비", "description": "점심", "date": None},
        {"type": "expense", "amount": 3000, "category": "식비", "description": "커피", "date": None},
    ]
    with patch("agents.finance.ledger_parser.claude_ask", return_value=json.dumps(entries)):
        result = _parser().parse("점심 5000원 커피 3000원")
    assert result == entries[0]


def test_parse_returns_none_when_no_entries():
    with patch("agents.finance.ledger_parser.claude_ask", return_value="[]"):
        result = _parser().parse("hello world")
    assert result is None


# ---------- parse_many() ----------

def test_parse_many_llm_returns_valid_array():
    entry = {"type": "expense", "amount": 5000, "category": "식비", "description": "점심", "date": None}
    with patch("agents.finance.ledger_parser.claude_ask", return_value=json.dumps([entry])):
        result = _parser().parse_many("점심 5000원")
    assert result == [entry]


def test_parse_many_llm_returns_dict_wraps_in_list():
    entry = {"type": "expense", "amount": 5000, "category": "식비", "description": "점심", "date": None}
    with patch("agents.finance.ledger_parser.claude_ask", return_value=json.dumps(entry)):
        result = _parser().parse_many("점심 5000원")
    assert result == [entry]


def test_parse_many_llm_returns_unexpected_type_gives_empty():
    with patch("agents.finance.ledger_parser.claude_ask", return_value='"just a string"'):
        result = _parser().parse_many("some message")
    assert result == []


def test_parse_many_falls_back_on_llm_exception():
    with patch("agents.finance.ledger_parser.claude_ask", side_effect=RuntimeError("API error")):
        result = _parser().parse_many("점심 5000원")
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["amount"] == 5000
    assert result[0]["category"] == "식비"


def test_parse_many_falls_back_on_invalid_json():
    with patch("agents.finance.ledger_parser.claude_ask", return_value="not json"):
        result = _parser().parse_many("점심 5000원")
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["amount"] == 5000


def test_parse_many_empty_llm_array():
    with patch("agents.finance.ledger_parser.claude_ask", return_value="[]"):
        result = _parser().parse_many("some message")
    assert result == []


# ---------- _regex_parse() — basic matching ----------

def test_regex_parse_single_expense():
    result = _parser()._regex_parse("점심 5000원")
    assert len(result) == 1
    assert result[0]["type"] == "expense"
    assert result[0]["amount"] == 5000
    assert result[0]["category"] == "식비"


def test_regex_parse_multiple_items_in_one_message():
    result = _parser()._regex_parse("커피 3000원 택시 8000원")
    assert len(result) == 2
    assert {e["amount"] for e in result} == {3000, 8000}
    assert {e["category"] for e in result} == {"식비", "교통"}


# ---------- _regex_parse() — date hints ----------

def test_regex_parse_date_hint_어제():
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    result = _parser()._regex_parse("어제: (점심 5000원)")
    assert len(result) == 1
    assert result[0]["date"] == yesterday


def test_regex_parse_date_hint_오늘():
    today = date.today().isoformat()
    result = _parser()._regex_parse("오늘: (카페 4500원)")
    assert len(result) == 1
    assert result[0]["date"] == today


def test_regex_parse_date_hint_그제():
    two_days_ago = (date.today() - timedelta(days=2)).isoformat()
    result = _parser()._regex_parse("그제: (버스 1500원)")
    assert len(result) == 1
    assert result[0]["date"] == two_days_ago


def test_regex_parse_multiple_date_segments():
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    today = date.today().isoformat()
    result = _parser()._regex_parse("어제: (밥 6000원) 오늘: (커피 3000원)")
    assert len(result) == 2
    dates = {e["date"] for e in result}
    assert yesterday in dates
    assert today in dates


def test_regex_parse_no_date_prefix_uses_today():
    today = date.today().isoformat()
    result = _parser()._regex_parse("영화 12000원")
    assert len(result) == 1
    assert result[0]["date"] == today


# ---------- _regex_parse() — category mapping ----------

def test_regex_parse_category_교통():
    result = _parser()._regex_parse("지하철 1400원")
    assert len(result) == 1
    assert result[0]["category"] == "교통"


def test_regex_parse_category_쇼핑():
    result = _parser()._regex_parse("마트 용품 25000원")
    assert len(result) >= 1
    assert result[0]["category"] == "쇼핑"


def test_regex_parse_category_문화():
    result = _parser()._regex_parse("영화 14000원")
    assert len(result) == 1
    assert result[0]["category"] == "문화"


def test_regex_parse_category_주거():
    result = _parser()._regex_parse("관리비 50000원")
    assert len(result) == 1
    assert result[0]["category"] == "주거"


def test_regex_parse_category_의료():
    result = _parser()._regex_parse("병원 15000원")
    assert len(result) == 1
    assert result[0]["category"] == "의료"


def test_regex_parse_unknown_category_defaults_to_기타():
    result = _parser()._regex_parse("선물 30000원")
    assert len(result) == 1
    assert result[0]["category"] == "기타"


# ---------- _regex_parse() — edge cases ----------

def test_regex_parse_amount_with_commas():
    result = _parser()._regex_parse("커피 1,500원")
    assert len(result) == 1
    assert result[0]["amount"] == 1500


def test_regex_parse_zero_amount_skipped():
    result = _parser()._regex_parse("테스트 0원")
    assert result == []


def test_regex_parse_no_match_returns_empty():
    result = _parser()._regex_parse("hello world")
    assert result == []


def test_regex_parse_type_always_expense():
    result = _parser()._regex_parse("점심 5000원 커피 3000원")
    assert len(result) > 0
    assert all(e["type"] == "expense" for e in result)


# ---------- format_amount() ----------

def test_format_amount_typical():
    assert LedgerParser.format_amount(5000) == "5,000원"


def test_format_amount_large():
    assert LedgerParser.format_amount(1000000) == "1,000,000원"


def test_format_amount_zero():
    assert LedgerParser.format_amount(0) == "0원"


def test_format_amount_negative():
    assert LedgerParser.format_amount(-5000) == "-5,000원"