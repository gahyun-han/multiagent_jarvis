import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path

import agents.calendar.calendar_store as cs_module
from agents.calendar.calendar_store import CalendarStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    store_path = tmp_path / "calendar.json"
    monkeypatch.setattr(cs_module, "STORE_PATH", store_path)
    return CalendarStore()


def test_add_returns_entry_with_expected_fields(store):
    entry = store.add("Meeting", "2026-06-01T10:00:00", notes="bring laptop")
    assert {"id", "title", "datetime", "notes", "created_at"} <= set(entry.keys())
    assert len(entry["id"]) == 8
    assert entry["title"] == "Meeting"
    assert entry["datetime"] == "2026-06-01T10:00:00"
    assert entry["notes"] == "bring laptop"


def test_add_persists_to_store(store):
    store.add("Lunch", "2026-06-01T12:00:00")
    assert any(e["title"] == "Lunch" for e in store.get_all())


def test_add_empty_notes_defaults_to_empty_string(store):
    entry = store.add("Call", "2026-06-02T09:00:00")
    assert entry["notes"] == ""


def test_add_multiple_entries_accumulate(store):
    store.add("Entry1", "2026-06-01T08:00:00")
    store.add("Entry2", "2026-06-01T09:00:00")
    store.add("Entry3", "2026-06-01T10:00:00")
    all_entries = store.get_all()
    titles = [e["title"] for e in all_entries]
    assert len(all_entries) == 3
    assert "Entry1" in titles
    assert "Entry2" in titles
    assert "Entry3" in titles


def test_delete_existing_entry_returns_true(store):
    entry = store.add("ToDelete", "2026-06-01T10:00:00")
    result = store.delete(entry["id"])
    assert result is True
    assert not any(e["id"] == entry["id"] for e in store.get_all())


def test_delete_nonexistent_id_returns_false(store):
    store.add("Keeper", "2026-06-01T10:00:00")
    initial_count = len(store.get_all())
    result = store.delete("nosuchid")
    assert result is False
    assert len(store.get_all()) == initial_count


def test_delete_removes_only_targeted_entry(store):
    e1 = store.add("First", "2026-06-01T10:00:00")
    e2 = store.add("Second", "2026-06-01T11:00:00")
    store.delete(e1["id"])
    remaining = store.get_all()
    assert len(remaining) == 1
    assert remaining[0]["id"] == e2["id"]


def test_get_all_empty_store(store):
    assert store.get_all() == []


def test_get_today_returns_todays_entries_only(store):
    from datetime import date
    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    store.add("Today", f"{today}T10:00:00")
    store.add("Tomorrow", f"{tomorrow}T10:00:00")
    result = store.get_today()
    assert len(result) == 1
    assert result[0]["title"] == "Today"


def test_get_today_no_matching_entries(store):
    store.add("OldEvent", "2020-01-01T10:00:00")
    assert store.get_today() == []


def test_get_upcoming_default_7_days(store):
    now = datetime.now()
    store.add("Soon", (now + timedelta(days=1)).isoformat())
    store.add("Week", (now + timedelta(days=5)).isoformat())
    store.add("Far", (now + timedelta(days=10)).isoformat())
    result = store.get_upcoming()
    titles = [e["title"] for e in result]
    assert "Soon" in titles
    assert "Week" in titles
    assert "Far" not in titles
    assert result[0]["title"] == "Soon"
    assert result[1]["title"] == "Week"


def test_get_upcoming_excludes_past_entries(store):
    now = datetime.now()
    store.add("Past", (now - timedelta(days=1)).isoformat())
    store.add("Future", (now + timedelta(days=1)).isoformat())
    result = store.get_upcoming()
    titles = [e["title"] for e in result]
    assert "Future" in titles
    assert "Past" not in titles


def test_get_upcoming_custom_days_window(store):
    now = datetime.now()
    store.add("Short", (now + timedelta(hours=12)).isoformat())
    store.add("Long", (now + timedelta(hours=25)).isoformat())
    result = store.get_upcoming(days=1)
    titles = [e["title"] for e in result]
    assert "Short" in titles
    assert "Long" not in titles


def test_get_upcoming_skips_invalid_datetime_entries(store):
    now = datetime.now()
    store.add("BadDate", "not-a-date")
    store.add("GoodDate", (now + timedelta(hours=1)).isoformat())
    result = store.get_upcoming()
    titles = [e["title"] for e in result]
    assert "GoodDate" in titles
    assert "BadDate" not in titles


def test_get_by_date_returns_matching_entries(store):
    store.add("Morning", "2026-06-15T09:00:00")
    store.add("Afternoon", "2026-06-15T15:00:00")
    store.add("Other", "2026-06-20T10:00:00")
    result = store.get_by_date("2026-06-15")
    assert len(result) == 2
    titles = [e["title"] for e in result]
    assert "Morning" in titles
    assert "Afternoon" in titles


def test_get_by_date_no_match_returns_empty(store):
    store.add("SomeEvent", "2026-06-01T10:00:00")
    assert store.get_by_date("2099-01-01") == []


def test_format_entry_valid_iso_datetime():
    entry = {
        "id": "abcd1234",
        "title": "Demo",
        "datetime": "2026-06-01T14:30:00",
        "notes": "prep",
    }
    result = CalendarStore.format_entry(entry)
    assert "06/01 14:30" in result
    assert "*Demo*" in result
    assert "prep" in result
    assert "`abcd1234`" in result
    assert "—" in result


def test_format_entry_no_notes_omits_notes_section():
    entry = {
        "id": "abcd1234",
        "title": "NoNotes",
        "datetime": "2026-06-01T10:00:00",
        "notes": "",
    }
    result = CalendarStore.format_entry(entry)
    assert "—" not in result


def test_format_entry_invalid_datetime_falls_back():
    entry = {
        "id": "abcd1234",
        "title": "Test",
        "datetime": "bad-value",
        "notes": "",
    }
    result = CalendarStore.format_entry(entry)
    assert "bad-value" in result


def test_format_list_non_empty():
    entries = [
        {"id": "aaaa1111", "title": "A", "datetime": "2026-06-01T09:00:00", "notes": ""},
        {"id": "bbbb2222", "title": "B", "datetime": "2026-06-01T10:00:00", "notes": ""},
    ]
    result = CalendarStore().format_list(entries)
    lines = result.split("\n")
    assert len(lines) == 2


def test_format_list_empty_returns_korean_message():
    result = CalendarStore().format_list([])
    assert result == "등록된 일정이 없습니다."


def test_load_missing_file_returns_empty_list(tmp_path, monkeypatch):
    monkeypatch.setattr(cs_module, "STORE_PATH", tmp_path / "nonexistent.json")
    assert CalendarStore()._load() == []


def test_load_corrupted_json_returns_empty_list(tmp_path, monkeypatch):
    bad_file = tmp_path / "calendar.json"
    bad_file.write_text("{broken json", encoding="utf-8")
    monkeypatch.setattr(cs_module, "STORE_PATH", bad_file)
    assert CalendarStore()._load() == []


def test_save_and_load_round_trip(tmp_path, monkeypatch):
    store_path = tmp_path / "calendar.json"
    monkeypatch.setattr(cs_module, "STORE_PATH", store_path)
    s = CalendarStore()
    entries = [{"id": "한글id", "title": "회의", "datetime": "2026-06-01T10:00:00", "notes": "노트"}]
    s._save(entries)
    loaded = s._load()
    assert loaded == entries
    assert loaded[0]["title"] == "회의"
    assert loaded[0]["notes"] == "노트"


def test_id_uniqueness_across_adds(store):
    ids = [store.add(f"Entry{i}", "2026-06-01T10:00:00")["id"] for i in range(100)]
    assert len(set(ids)) == 100


def test_get_upcoming_boundary_exactly_now(tmp_path, monkeypatch):
    store_path = tmp_path / "calendar.json"
    monkeypatch.setattr(cs_module, "STORE_PATH", store_path)

    fixed_now = datetime(2026, 6, 1, 10, 0, 0)

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(cs_module, "datetime", FakeDatetime)

    s = CalendarStore()
    s.add("Boundary", fixed_now.isoformat())
    result = s.get_upcoming(days=7)
    assert any(e["title"] == "Boundary" for e in result)