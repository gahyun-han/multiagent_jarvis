import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from agents.finance.ledger_parser import LedgerParser


def test_parse_returns_first_entry():
    parser = LedgerParser()
    entry = {"type": "expense", "amount": 8000, "category": "식비", "description": "점심", "date": None}

    async def _run():
        with patch.object(parser, "parse_many", new=AsyncMock(return_value=[entry])):
            return await parser.parse("점심 8000원")

    assert asyncio.run(_run()) == entry


def test_parse_returns_none_when_empty():
    parser = LedgerParser()

    async def _run():
        with patch.object(parser, "parse_many", new=AsyncMock(return_value=[])):
            return await parser.parse("")

    assert asyncio.run(_run()) is None


def test_parse_many_llm_returns_list():
    parser = LedgerParser()
    raw = '[{"type":"expense","amount":8000,"category":"식비","description":"점심","date":null}]'

    async def _run():
        with patch("agents.finance.ledger_parser.claude_ask", new=AsyncMock(return_value=raw)):
            return await parser.parse_many("점심 8000원")

    result = asyncio.run(_run())
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["type"] == "expense"
    assert result[0]["amount"] == 8000


def test_parse_many_llm_returns_dict_wrapped():
    parser = LedgerParser()
    raw = '{"type":"expense","amount":8000,"category":"식비","description":"점심","date":null}'

    async def _run():
        with patch("agents.finance.ledger_parser.claude_ask", new=AsyncMock(return_value=raw)):
            return await parser.parse_many("점심 8000원")

    result = asyncio.run(_run())
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["type"] == "expense"
    assert result[0]["amount"] == 8000


def test_parse_many_llm_returns_invalid_type():
    parser = LedgerParser()

    async def _run():
        with patch("agents.finance.ledger_parser.claude_ask", new=AsyncMock(return_value='"just a string"')):
            return await parser.parse_many("test")

    assert asyncio.run(_run()) == []


def test_parse_many_llm_returns_empty_array():
    parser = LedgerParser()

    async def _run():
        with patch("agents.finance.ledger_parser.claude_ask", new=AsyncMock(return_value="[]")):
            return await parser.parse_many("test")

    assert asyncio.run(_run()) == []


def test_parse_many_falls_back_on_llm_exception():
    parser = LedgerParser()

    async def _run():
        with patch(
            "agents.finance.ledger_parser.claude_ask",
            new=AsyncMock(side_effect=Exception("API error")),
        ):
            return await parser.parse_many("커피 3000원")

    result = asyncio.run(_run())
    assert len(result) == 1
    assert result[0]["type"] == "expense"
    assert result[0]["amount"] == 3000


def test_parse_many_falls_back_on_invalid_json():
    parser = LedgerParser()

    async def _run():
        with patch("agents.finance.ledger_parser.claude_ask", new=AsyncMock(return_value="not json")):
            return await parser.parse_many("택시 5000원")

    result = asyncio.run(_run())
    assert len(result) == 1
    assert result[0]["amount"] == 5000


def test_parse_many_date_hint_prepended():
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    parser = LedgerParser()
    captured = {}

    async def mock_ask(msg, **kwargs):
        captured["msg"] = msg
        return "[]"

    async def _run():
        with patch("agents.finance.ledger_parser.claude_ask", new=mock_ask):
            return await parser.parse_many("test message")

    asyncio.run(_run())
    assert f"오늘={today}" in captured["msg"]
    assert f"어제={yesterday}" in captured["msg"]


def test_regex_parse_simple_expense():
    parser = LedgerParser()
    today = date.today().isoformat()
    result = parser._regex_parse("점심 8000원")
    assert len(result) == 1
    assert result[0]["type"] == "expense"
    assert result[0]["amount"] == 8000
    assert result[0]["category"] == "식비"
    assert result[0]["date"] == today


def test_regex_parse_amount_with_commas():
    parser = LedgerParser()
    result = parser._regex_parse("카페 1,500원")
    assert len(result) == 1
    assert result[0]["amount"] == 1500


def test_regex_parse_category_식비():
    parser = LedgerParser()
    result = parser._regex_parse("저녁 배달 12000원")
    assert len(result) == 1
    assert result[0]["category"] == "식비"


def test_regex_parse_category_교통():
    parser = LedgerParser()
    result = parser._regex_parse("지하철 1400원")
    assert len(result) == 1
    assert result[0]["category"] == "교통"


def test_regex_parse_category_기타():
    parser = LedgerParser()
    result = parser._regex_parse("선물 25000원")
    assert len(result) == 1
    assert result[0]["category"] == "기타"


def test_regex_parse_date_hint_어제():
    parser = LedgerParser()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    result = parser._regex_parse("어제: (버스 1400원)")
    assert len(result) == 1
    assert result[0]["date"] == yesterday


def test_regex_parse_date_hint_오늘():
    parser = LedgerParser()
    today = date.today().isoformat()
    result = parser._regex_parse("오늘: (점심 9000원)")
    assert len(result) == 1
    assert result[0]["date"] == today


def test_regex_parse_date_hint_그제():
    parser = LedgerParser()
    two_days_ago = (date.today() - timedelta(days=2)).isoformat()
    result = parser._regex_parse("그제: (영화 13000원)")
    assert len(result) == 1
    assert result[0]["date"] == two_days_ago


def test_regex_parse_multiple_items_same_segment():
    parser = LedgerParser()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    result = parser._regex_parse("어제: (아침 5000원 점심 8000원)")
    assert len(result) == 2
    assert all(e["date"] == yesterday for e in result)


def test_regex_parse_multiple_date_segments():
    parser = LedgerParser()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    today = date.today().isoformat()
    result = parser._regex_parse("어제: (택시 6000원) 오늘: (커피 4500원)")
    assert len(result) == 2
    dates = {e["date"] for e in result}
    assert yesterday in dates
    assert today in dates


def test_regex_parse_no_match_returns_empty():
    parser = LedgerParser()
    assert parser._regex_parse("오늘 날씨 좋다") == []


def test_regex_parse_zero_amount_skipped():
    parser = LedgerParser()
    assert parser._regex_parse("테스트 0원") == []


def test_regex_parse_no_date_hint_uses_today():
    parser = LedgerParser()
    today = date.today().isoformat()
    result = parser._regex_parse("치킨 18000원")
    assert len(result) == 1
    assert result[0]["date"] == today


def test_format_amount_thousands():
    assert LedgerParser.format_amount(1500) == "1,500원"


def test_format_amount_millions():
    assert LedgerParser.format_amount(1000000) == "1,000,000원"


def test_format_amount_zero():
    assert LedgerParser.format_amount(0) == "0원"


def test_format_amount_negative():
    assert LedgerParser.format_amount(-5000) == "-5,000원"