import os
import logging
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agents.paper.zotero_client import ZoteroClient
from agents.paper.obsidian_client import ObsidianClient


@pytest.fixture(autouse=True)
def clear_zotero_env(monkeypatch):
    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    monkeypatch.delenv("ZOTERO_USER_ID", raising=False)
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)


def _make_item(title="Paper", creators=None, date="2023-06",
               abstract="Abstract text", key="KEY1", url="http://example.com"):
    if creators is None:
        creators = [{"lastName": "Smith", "firstName": "John"}]
    return {
        "data": {
            "title": title,
            "creators": creators,
            "date": date,
            "abstractNote": abstract,
            "key": key,
            "url": url,
        }
    }


def _make_client_with_mock_zot(monkeypatch):
    monkeypatch.setenv("ZOTERO_API_KEY", "key")
    monkeypatch.setenv("ZOTERO_USER_ID", "123")
    mock_zot = MagicMock()
    with patch("agents.paper.zotero_client.zotero.Zotero", return_value=mock_zot):
        client = ZoteroClient()
    return client, mock_zot


# --- __init__ ---

def test_init_with_valid_credentials(monkeypatch):
    monkeypatch.setenv("ZOTERO_API_KEY", "key")
    monkeypatch.setenv("ZOTERO_USER_ID", "123")
    with patch("agents.paper.zotero_client.zotero.Zotero", return_value=MagicMock()):
        client = ZoteroClient()
    assert client.zot is not None


def test_init_missing_api_key(monkeypatch, caplog):
    monkeypatch.setenv("ZOTERO_USER_ID", "123")
    with caplog.at_level(logging.WARNING, logger="agents.paper.zotero_client"):
        client = ZoteroClient()
    assert client.zot is None
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_init_missing_user_id(monkeypatch, caplog):
    monkeypatch.setenv("ZOTERO_API_KEY", "key")
    with caplog.at_level(logging.WARNING, logger="agents.paper.zotero_client"):
        client = ZoteroClient()
    assert client.zot is None
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_init_no_credentials():
    client = ZoteroClient()
    assert client.zot is None


def test_init_custom_vault_path(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "/home/user/vault")
    client = ZoteroClient()
    assert client.vault_path == Path("/home/user/vault")


def test_init_default_vault_path():
    client = ZoteroClient()
    assert client.vault_path == Path("")


# --- get_recent_papers ---

def test_get_recent_papers_happy_path(monkeypatch):
    client, mock_zot = _make_client_with_mock_zot(monkeypatch)
    mock_zot.top.return_value = [_make_item("Paper 1"), _make_item("Paper 2")]

    result = client.get_recent_papers()

    assert len(result) == 2
    assert result[0]["title"] == "Paper 1"
    assert result[1]["title"] == "Paper 2"
    for r in result:
        assert set(r.keys()) == {"title", "authors", "year", "abstract", "key", "url"}


def test_get_recent_papers_no_credentials():
    client = ZoteroClient()
    assert client.get_recent_papers() == []


def test_get_recent_papers_api_exception(monkeypatch, caplog):
    client, mock_zot = _make_client_with_mock_zot(monkeypatch)
    mock_zot.top.side_effect = Exception("network error")

    with caplog.at_level(logging.ERROR, logger="agents.paper.zotero_client"):
        result = client.get_recent_papers()

    assert result == []
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_get_recent_papers_default_limit(monkeypatch):
    client, mock_zot = _make_client_with_mock_zot(monkeypatch)
    mock_zot.top.return_value = []

    client.get_recent_papers()

    assert mock_zot.top.call_args.kwargs["limit"] == 20


def test_get_recent_papers_custom_limit(monkeypatch):
    client, mock_zot = _make_client_with_mock_zot(monkeypatch)
    mock_zot.top.return_value = []

    client.get_recent_papers(limit=5)

    assert mock_zot.top.call_args.kwargs["limit"] == 5


# --- search_papers ---

def test_search_papers_happy_path(monkeypatch):
    client, mock_zot = _make_client_with_mock_zot(monkeypatch)
    mock_zot.items.return_value = [_make_item("Transformer 1"), _make_item("Transformer 2")]

    result = client.search_papers("transformer")

    assert len(result) == 2
    assert result[0]["title"] == "Transformer 1"
    assert result[1]["title"] == "Transformer 2"


def test_search_papers_no_credentials():
    client = ZoteroClient()
    assert client.search_papers("ml") == []


def test_search_papers_api_exception(monkeypatch, caplog):
    client, mock_zot = _make_client_with_mock_zot(monkeypatch)
    mock_zot.items.side_effect = Exception("API error")

    with caplog.at_level(logging.ERROR, logger="agents.paper.zotero_client"):
        result = client.search_papers("query")

    assert result == []
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_search_papers_empty_query(monkeypatch):
    client, mock_zot = _make_client_with_mock_zot(monkeypatch)
    mock_zot.items.return_value = []

    client.search_papers("")

    assert mock_zot.items.call_args.kwargs["q"] == ""


# --- get_obsidian_notes ---

def test_get_obsidian_notes_happy_path(tmp_path):
    papers = tmp_path / "papers"
    papers.mkdir()
    content = "a" * 100
    (papers / "note.md").write_text(content, encoding="utf-8")

    client = ZoteroClient()
    client.vault_path = tmp_path

    notes = client.get_obsidian_notes()

    assert len(notes) == 1
    assert notes[0]["filename"] == "note.md"
    assert notes[0]["content"] == content


def test_get_obsidian_notes_subfolder_missing(tmp_path):
    client = ZoteroClient()
    client.vault_path = tmp_path

    notes = client.get_obsidian_notes()

    assert notes == []


def test_get_obsidian_notes_default_subfolder(tmp_path):
    papers = tmp_path / "papers"
    papers.mkdir()
    (papers / "default.md").write_text("some content", encoding="utf-8")

    client = ZoteroClient()
    client.vault_path = tmp_path

    notes = client.get_obsidian_notes()

    assert len(notes) == 1
    assert notes[0]["filename"] == "default.md"


def test_get_obsidian_notes_custom_subfolder(tmp_path):
    research = tmp_path / "research"
    research.mkdir()
    (research / "study.md").write_text("study content", encoding="utf-8")

    client = ZoteroClient()
    client.vault_path = tmp_path

    notes = client.get_obsidian_notes(subfolder="research")

    assert len(notes) == 1
    assert notes[0]["filename"] == "study.md"
    assert notes[0]["content"] == "study content"


def test_get_obsidian_notes_content_truncated_at_2000(tmp_path):
    papers = tmp_path / "papers"
    papers.mkdir()
    (papers / "long.md").write_text("x" * 5000, encoding="utf-8")

    client = ZoteroClient()
    client.vault_path = tmp_path

    notes = client.get_obsidian_notes()

    assert len(notes[0]["content"]) == 2000


def test_get_obsidian_notes_recursive_glob(tmp_path):
    subdir = tmp_path / "papers" / "subdir"
    subdir.mkdir(parents=True)
    (subdir / "deep.md").write_text("deep content", encoding="utf-8")

    client = ZoteroClient()
    client.vault_path = tmp_path

    notes = client.get_obsidian_notes()

    assert any(n["filename"] == "deep.md" for n in notes)


def test_get_obsidian_notes_non_md_files_ignored(tmp_path):
    papers = tmp_path / "papers"
    papers.mkdir()
    (papers / "note.txt").write_text("text content", encoding="utf-8")
    (papers / "paper.pdf").write_bytes(b"%PDF data")

    client = ZoteroClient()
    client.vault_path = tmp_path

    notes = client.get_obsidian_notes()

    assert notes == []


def test_get_obsidian_notes_unreadable_file_skipped(tmp_path):
    papers = tmp_path / "papers"
    papers.mkdir()
    (papers / "good.md").write_text("good content", encoding="utf-8")
    (papers / "bad.md").write_bytes(b"\xff\xfe\x80\x81\x82")

    client = ZoteroClient()
    client.vault_path = tmp_path

    notes = client.get_obsidian_notes()

    assert len(notes) == 1
    assert notes[0]["filename"] == "good.md"


# --- _parse_item ---

def test_parse_item_full_data():
    item = {
        "data": {
            "title": "Test Paper",
            "creators": [
                {"lastName": "Smith", "firstName": "John"},
                {"lastName": "Doe", "firstName": "Jane"},
            ],
            "date": "2023-06",
            "abstractNote": "This is an abstract.",
            "key": "ABC123",
            "url": "http://example.com",
        }
    }
    result = ZoteroClient._parse_item(item)
    assert result["title"] == "Test Paper"
    assert "Smith" in result["authors"]
    assert "Doe" in result["authors"]
    assert result["year"] == "2023"
    assert result["abstract"] == "This is an abstract."
    assert result["key"] == "ABC123"
    assert result["url"] == "http://example.com"


def test_parse_item_missing_data_key():
    result = ZoteroClient._parse_item({})
    assert result == {
        "title": "Unknown",
        "authors": "",
        "year": "",
        "abstract": "",
        "key": "",
        "url": "",
    }


def test_parse_item_no_creators():
    item = {"data": {"creators": []}}
    result = ZoteroClient._parse_item(item)
    assert result["authors"] == ""


def test_parse_item_more_than_three_creators():
    creators = [{"lastName": f"Last{i}", "firstName": f"First{i}"} for i in range(5)]
    item = {"data": {"creators": creators}}
    result = ZoteroClient._parse_item(item)
    names = [n.strip() for n in result["authors"].split(",")]
    assert len(names) == 3


def test_parse_item_creator_missing_first_name():
    item = {"data": {"creators": [{"lastName": "Smith"}]}}
    result = ZoteroClient._parse_item(item)
    assert result["authors"] == "Smith"


def test_parse_item_missing_title():
    item = {"data": {}}
    result = ZoteroClient._parse_item(item)
    assert result["title"] == "Unknown"


def test_parse_item_date_shorter_than_four_chars():
    item = {"data": {"date": "20"}}
    result = ZoteroClient._parse_item(item)
    assert result["year"] == "20"


def test_parse_item_empty_date():
    item = {"data": {"date": ""}}
    result = ZoteroClient._parse_item(item)
    assert result["year"] == ""


def test_parse_item_abstract_truncated_at_500():
    item = {"data": {"abstractNote": "a" * 1000}}
    result = ZoteroClient._parse_item(item)
    assert len(result["abstract"]) == 500