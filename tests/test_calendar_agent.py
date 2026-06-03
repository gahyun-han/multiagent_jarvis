import asyncio
from unittest.mock import MagicMock, patch

from agents.calendar.calendar_agent import CalendarAgent


def _intent(msg: str):
    i = MagicMock()
    i.raw_message = msg
    return i


def _make_agent(ask_return: str = "{}"):
    """Return a CalendarAgent whose CalendarStore and claude_ask are mocked."""
    with patch("agents.calendar.calendar_agent.CalendarStore") as MockStore:
        agent = CalendarAgent()
        agent.store = MockStore.return_value
    return agent


# ── handle() routes ────────────────────────────────────────────────────────────

def test_handle_add_action():
    agent = _make_agent()
    agent.store.add_event.return_value = {"id": "abc12345"}
    parsed = {
        "action": "add",
        "title": "팀 미팅",
        "datetime": "2026-06-01T14:00:00",
        "notes": "",
    }
    with patch("agents.calendar.calendar_agent.claude_ask", return_value='{"action":"add","title":"팀 미팅","datetime":"2026-06-01T14:00:00","notes":""}'):
        result = asyncio.run(agent.handle(_intent("팀 미팅 일정 추가")))
    assert "팀 미팅" in result
    assert "abc12345" in result


def test_handle_query_today():
    agent = _make_agent()
    agent.store.get_today.return_value = [
        {"id": "aabb1122", "title": "조깅", "datetime": "2026-06-01T07:00:00"}
    ]
    with patch("agents.calendar.calendar_agent.claude_ask", return_value='{"action":"query","query_type":"today"}'):
        result = asyncio.run(agent.handle(_intent("오늘 일정 알려줘")))
    assert "조깅" in result


def test_handle_query_upcoming():
    agent = _make_agent()
    agent.store.get_upcoming.return_value = []
    with patch("agents.calendar.calendar_agent.claude_ask", return_value='{"action":"query","query_type":"upcoming"}'):
        result = asyncio.run(agent.handle(_intent("다가오는 일정 보여줘")))
    assert "없습니다" in result


def test_handle_query_by_date():
    agent = _make_agent()
    agent.store.get_by_date.return_value = [
        {"id": "ccdd3344", "title": "치과", "datetime": "2026-06-05T10:00:00"}
    ]
    with patch("agents.calendar.calendar_agent.claude_ask", return_value='{"action":"query","query_type":"date","date":"2026-06-05"}'):
        result = asyncio.run(agent.handle(_intent("6월 5일 일정")))
    assert "치과" in result


def test_handle_query_all():
    agent = _make_agent()
    agent.store.get_all.return_value = [
        {"id": "eeff5566", "title": "연간 목표 리뷰", "datetime": "2026-12-31T09:00:00"}
    ]
    with patch("agents.calendar.calendar_agent.claude_ask", return_value='{"action":"query","query_type":"all"}'):
        result = asyncio.run(agent.handle(_intent("전체 일정 보여줘")))
    assert "연간 목표 리뷰" in result


def test_handle_delete_success():
    agent = _make_agent()
    agent.store.delete_event.return_value = True
    with patch("agents.calendar.calendar_agent.claude_ask", return_value='{"action":"delete","entry_id":"abc12345"}'):
        result = asyncio.run(agent.handle(_intent("abc12345 삭제해줘")))
    assert "삭제" in result
    assert "abc12345" in result


def test_handle_delete_not_found():
    agent = _make_agent()
    agent.store.delete_event.return_value = False
    with patch("agents.calendar.calendar_agent.claude_ask", return_value='{"action":"delete","entry_id":"xxxxxxxx"}'):
        result = asyncio.run(agent.handle(_intent("xxxxxxxx 삭제")))
    assert "찾을 수 없습니다" in result


def test_handle_delete_missing_id():
    agent = _make_agent()
    with patch("agents.calendar.calendar_agent.claude_ask", return_value='{"action":"delete","entry_id":""}'):
        result = asyncio.run(agent.handle(_intent("삭제해줘")))
    assert "ID" in result


def test_handle_unknown_falls_back_to_chat():
    agent = _make_agent()
    with patch("agents.calendar.calendar_agent.claude_ask", side_effect=["{'action':'unknown'}", "안녕하세요!"]):
        result = asyncio.run(agent.handle(_intent("안녕")))
    # unknown falls back to a chat reply — just check it returns a non-empty string
    assert isinstance(result, str) and len(result) > 0


# ── _add() direct ──────────────────────────────────────────────────────────────

def test_add_valid_datetime():
    agent = _make_agent()
    agent.store.add_event.return_value = {"id": "zz998877"}
    result = agent._add({"title": "독서", "datetime": "2026-07-04T20:00:00", "notes": "소설"})
    assert "독서" in result
    assert "zz998877" in result


def test_add_invalid_datetime_defaults():
    agent = _make_agent()
    agent.store.add_event.return_value = {"id": "fallback1"}
    result = agent._add({"title": "기본시간", "datetime": "not-a-date", "notes": ""})
    assert "기본시간" in result
    agent.store.add_event.assert_called_once()


def test_add_missing_title_defaults_to_무제():
    agent = _make_agent()
    agent.store.add_event.return_value = {"id": "notitle1"}
    result = agent._add({"datetime": "2026-08-01T09:00:00", "notes": ""})
    assert "무제" in result


# ── _query() direct ────────────────────────────────────────────────────────────

def test_query_today_empty():
    agent = _make_agent()
    agent.store.get_today.return_value = []
    result = agent._query({"query_type": "today"})
    assert "없습니다" in result


def test_query_today_with_events():
    agent = _make_agent()
    agent.store.get_today.return_value = [{"id": "t1", "title": "산책", "datetime": "2026-06-01T07:00:00"}]
    result = agent._query({"query_type": "today"})
    assert "산책" in result


def test_query_date_empty():
    agent = _make_agent()
    agent.store.get_by_date.return_value = []
    result = agent._query({"query_type": "date", "date": "2026-09-01"})
    assert "없습니다" in result


def test_query_all_multiple_events():
    agent = _make_agent()
    agent.store.get_all.return_value = [
        {"id": "a1", "title": "이벤트1", "datetime": "2026-06-10T10:00:00"},
        {"id": "a2", "title": "이벤트2", "datetime": "2026-06-11T11:00:00"},
    ]
    result = agent._query({"query_type": "all"})
    assert "이벤트1" in result
    assert "이벤트2" in result
    assert "2건" in result


def test_query_upcoming_default():
    agent = _make_agent()
    agent.store.get_upcoming.return_value = [{"id": "u1", "title": "회의", "datetime": "2026-06-03T09:00:00"}]
    result = agent._query({"query_type": "upcoming"})
    assert "회의" in result


# ── _delete() direct ───────────────────────────────────────────────────────────

def test_delete_success():
    agent = _make_agent()
    agent.store.delete_event.return_value = True
    result = agent._delete({"entry_id": "abc12345"})
    assert "삭제되었습니다" in result


def test_delete_not_found():
    agent = _make_agent()
    agent.store.delete_event.return_value = False
    result = agent._delete({"entry_id": "notexist"})
    assert "찾을 수 없습니다" in result


def test_delete_no_entry_id():
    agent = _make_agent()
    result = agent._delete({})
    assert "ID" in result
    agent.store.delete_event.assert_not_called()


# ── parse failure graceful fallback ───────────────────────────────────────────

def test_handle_parse_failure_falls_back():
    agent = _make_agent()
    with patch("agents.calendar.calendar_agent.claude_ask", side_effect=["not-valid-json", "도움이 필요하신가요?"]):
        result = asyncio.run(agent.handle(_intent("아무말")))
    assert isinstance(result, str)
