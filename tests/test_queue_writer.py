import json
import pytest
from datetime import datetime, timezone

import agents.inbox_trage.queue_writer as qw_module
from agents.inbox_trage.queue_writer import QueueWriter


@pytest.fixture(autouse=True)
def isolated_queue(tmp_path, monkeypatch):
    fake_path = tmp_path / "backlog_queue.json"
    monkeypatch.setattr(qw_module, "QUEUE_PATH", fake_path)
    return fake_path


@pytest.fixture
def qw():
    return QueueWriter()


def _kw(**overrides):
    base = dict(message="msg", summary="sum", domain="dom", category="cat", priority=1)
    base.update(overrides)
    return base


def test_write_returns_entry_with_expected_fields(qw):
    entry = qw.write(message="Buy milk", summary="grocery", domain="personal", category="task", priority=5)
    for key in ("id", "created_at", "message", "summary", "domain", "category", "priority", "status"):
        assert key in entry
    assert entry["message"] == "Buy milk"
    assert entry["summary"] == "grocery"
    assert entry["domain"] == "personal"
    assert entry["category"] == "task"
    assert entry["priority"] == 5
    assert entry["status"] == "pending"


def test_write_persists_entry_to_queue_file(qw):
    entry = qw.write(**_kw())
    loaded = qw._load()
    assert any(e["id"] == entry["id"] for e in loaded)


def test_write_id_is_8_chars(qw):
    entry = qw.write(**_kw())
    assert len(entry["id"]) == 8


def test_write_created_at_is_utc_iso(qw):
    entry = qw.write(**_kw())
    dt = datetime.fromisoformat(entry["created_at"])
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0


def test_write_trims_to_100_pending_entries(qw):
    for _ in range(101):
        qw.write(**_kw(priority=1))
    high = qw.write(**_kw(priority=10))
    result = qw.get_pending(limit=200)
    assert len(result) <= 100
    assert any(e["id"] == high["id"] for e in result)


def test_write_does_not_evict_done_entries(isolated_queue, qw):
    done_entries = [
        {
            "id": f"dn{i:06d}",
            "created_at": "2025-01-01T00:00:00+00:00",
            "message": "m", "summary": "s", "domain": "d", "category": "c",
            "priority": 1, "status": "done", "completed_at": "2025-01-01T01:00:00+00:00",
        }
        for i in range(100)
    ]
    isolated_queue.write_text(json.dumps(done_entries), encoding="utf-8")
    p1 = qw.write(**_kw(priority=1))
    p2 = qw.write(**_kw(priority=2))
    queue = qw._load()
    ids = {e["id"] for e in queue}
    assert p1["id"] in ids
    assert p2["id"] in ids
    assert sum(1 for e in queue if e["status"] == "done") == 100


def test_get_pending_returns_only_pending(qw):
    qw.write(**_kw())
    qw.write(**_kw())
    d1 = qw.write(**_kw())
    d2 = qw.write(**_kw())
    qw.mark_done(d1["id"])
    qw.mark_done(d2["id"])
    result = qw.get_pending(limit=100)
    assert len(result) == 2
    assert all(e["status"] == "pending" for e in result)


def test_get_pending_sorted_by_priority_desc(qw):
    qw.write(**_kw(priority=1))
    qw.write(**_kw(priority=5))
    qw.write(**_kw(priority=3))
    result = qw.get_pending(limit=10)
    assert [e["priority"] for e in result] == [5, 3, 1]


def test_get_pending_respects_limit(qw):
    for _ in range(5):
        qw.write(**_kw())
    assert len(qw.get_pending(limit=2)) == 2


def test_get_pending_default_limit_is_10(qw):
    for _ in range(15):
        qw.write(**_kw())
    assert len(qw.get_pending()) == 10


def test_get_pending_empty_queue(qw):
    assert qw.get_pending() == []


def test_mark_done_sets_status_and_completed_at(qw):
    entry = qw.write(**_kw())
    qw.mark_done(entry["id"])
    queue = {e["id"]: e for e in qw._load()}
    updated = queue[entry["id"]]
    assert updated["status"] == "done"
    assert "completed_at" in updated
    datetime.fromisoformat(updated["completed_at"])


def test_mark_done_nonexistent_id_is_noop(qw):
    qw.mark_done("deadbeef")
    assert qw.get_pending() == []


def test_mark_done_only_affects_target_entry(qw):
    e1 = qw.write(**_kw())
    e2 = qw.write(**_kw())
    e3 = qw.write(**_kw())
    qw.mark_done(e2["id"])
    queue = {e["id"]: e for e in qw._load()}
    assert queue[e1["id"]]["status"] == "pending"
    assert queue[e3["id"]]["status"] == "pending"


def test_delete_all_pending_returns_count(qw):
    qw.write(**_kw())
    qw.write(**_kw())
    qw.write(**_kw())
    done_entry = qw.write(**_kw())
    qw.mark_done(done_entry["id"])
    assert qw.delete_all_pending() == 3


def test_delete_all_pending_sets_all_done(qw):
    for _ in range(5):
        qw.write(**_kw())
    qw.delete_all_pending()
    assert qw.get_pending() == []


def test_delete_all_pending_empty_queue(qw):
    assert qw.delete_all_pending() == 0


def test_delete_all_pending_preserves_done_entries(qw):
    done_entry = qw.write(**_kw())
    qw.mark_done(done_entry["id"])
    qw.write(**_kw())
    qw.write(**_kw())
    qw.delete_all_pending()
    queue = qw._load()
    assert len(queue) == 3
    assert all(e["status"] == "done" for e in queue)


def test_delete_by_id_returns_true_for_pending_entry(qw):
    entry = qw.write(**_kw())
    assert qw.delete_by_id(entry["id"]) is True
    queue = {e["id"]: e for e in qw._load()}
    assert queue[entry["id"]]["status"] == "done"


def test_delete_by_id_returns_false_for_done_entry(qw):
    entry = qw.write(**_kw())
    qw.mark_done(entry["id"])
    assert qw.delete_by_id(entry["id"]) is False


def test_delete_by_id_returns_false_for_missing_id(qw):
    assert qw.delete_by_id("notreal") is False


def test_load_returns_empty_list_when_file_missing(isolated_queue, qw):
    assert not isolated_queue.exists()
    assert qw._load() == []


def test_load_returns_empty_list_on_corrupt_json(isolated_queue, qw):
    isolated_queue.write_text("not json {{{", encoding="utf-8")
    assert qw._load() == []


def test_save_and_load_roundtrip_unicode(qw):
    entry = qw.write(message="안녕하세요", summary="こんにちは", domain="d", category="c", priority=1)
    loaded = qw._load()
    found = next(e for e in loaded if e["id"] == entry["id"])
    assert found["message"] == "안녕하세요"
    assert found["summary"] == "こんにちは"


def test_write_multiple_entries_accumulate(qw):
    e1 = qw.write(**_kw())
    e2 = qw.write(**_kw())
    e3 = qw.write(**_kw())
    queue = qw._load()
    assert len(queue) == 3
    assert len({e["id"] for e in queue}) == 3