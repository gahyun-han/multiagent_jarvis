"""
ObsidianClient read/search 메서드 + PaperAgent 읽기/검색 핸들러 테스트.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.paper.obsidian_client import ObsidianClient
from agents.paper.paper_agent import (
    _parse_obs_read_ref,
    _parse_obs_search,
    PaperAgent,
    _OBS_SEND_KWS,
    _OBS_SEARCH_KWS,
)


# ── ObsidianClient.read_note ──────────────────────────────────────────────────

def test_read_note_returns_full_content(tmp_path):
    content = "# 연구계획\n\n## 목표\n자기학습 에이전트 연구"
    md = tmp_path / "연구계획.md"
    md.write_text(content, encoding="utf-8")
    obs = ObsidianClient.__new__(ObsidianClient)
    obs.vault_path = tmp_path
    assert obs.read_note(md) == content


# ── ObsidianClient.search_in_note ─────────────────────────────────────────────

def test_search_in_note_returns_matching_paragraphs(tmp_path):
    md = tmp_path / "note.md"
    md.write_text(
        "## 도입부\n\n자기학습 에이전트는 강화학습 기반이다.\n\n## 관련 없는 섹션\n\n전혀 다른 내용.",
        encoding="utf-8",
    )
    obs = ObsidianClient.__new__(ObsidianClient)
    obs.vault_path = tmp_path
    results = obs.search_in_note(md, "자기학습 에이전트")
    assert len(results) == 1
    assert "자기학습" in results[0]


def test_search_in_note_empty_query_returns_empty(tmp_path):
    md = tmp_path / "note.md"
    md.write_text("내용", encoding="utf-8")
    obs = ObsidianClient.__new__(ObsidianClient)
    obs.vault_path = tmp_path
    assert obs.search_in_note(md, "") == []


def test_search_in_note_no_match_returns_empty(tmp_path):
    md = tmp_path / "note.md"
    md.write_text("전혀 무관한 내용\n\n다른 내용", encoding="utf-8")
    obs = ObsidianClient.__new__(ObsidianClient)
    obs.vault_path = tmp_path
    assert obs.search_in_note(md, "존재하지않는키워드") == []


def test_search_in_note_multiple_matches(tmp_path):
    md = tmp_path / "note.md"
    md.write_text(
        "Dreaming 첫 번째 언급\n\nDreaming 두 번째 언급\n\n관련없음",
        encoding="utf-8",
    )
    obs = ObsidianClient.__new__(ObsidianClient)
    obs.vault_path = tmp_path
    results = obs.search_in_note(md, "Dreaming")
    assert len(results) == 2


# ── ObsidianClient.search_vault ──────────────────────────────────────────────

def test_search_vault_finds_matching_files(tmp_path):
    (tmp_path / "a.md").write_text("transformer 기반 모델\n\n다른 내용", encoding="utf-8")
    (tmp_path / "b.md").write_text("전혀 관계없음", encoding="utf-8")
    obs = ObsidianClient.__new__(ObsidianClient)
    obs.vault_path = tmp_path
    results = obs.search_vault("transformer")
    assert len(results) == 1
    assert results[0]["filename"] == "a"


def test_search_vault_empty_vault_returns_empty(tmp_path):
    obs = ObsidianClient.__new__(ObsidianClient)
    obs.vault_path = tmp_path
    assert obs.search_vault("anything") == []


def test_search_vault_respects_max_results(tmp_path):
    for i in range(5):
        (tmp_path / f"note{i}.md").write_text("target keyword here", encoding="utf-8")
    obs = ObsidianClient.__new__(ObsidianClient)
    obs.vault_path = tmp_path
    results = obs.search_vault("target", max_results=3)
    assert len(results) == 3


def test_search_vault_sections_capped_at_five(tmp_path):
    paragraphs = "\n\n".join(f"keyword 단락{i}" for i in range(10))
    (tmp_path / "big.md").write_text(paragraphs, encoding="utf-8")
    obs = ObsidianClient.__new__(ObsidianClient)
    obs.vault_path = tmp_path
    results = obs.search_vault("keyword")
    assert len(results[0]["sections"]) <= 5


# ── _parse_obs_read_ref ───────────────────────────────────────────────────────

def test_parse_read_ref_from_md_extension():
    assert _parse_obs_read_ref("연구계획.md 내용 보내줘") == "연구계획"


def test_parse_read_ref_from_obsidian_pattern():
    assert _parse_obs_read_ref("옵시디언 연구계획 내용 보내줘") == "연구계획"


def test_parse_read_ref_returns_none_when_no_file():
    assert _parse_obs_read_ref("옵시디언 내용 보내줘") is None


# ── _parse_obs_search ─────────────────────────────────────────────────────────

def test_parse_search_file_with_md_extension():
    file_ref, query = _parse_obs_search("연구계획.md에서 자기학습 에이전트 찾아줘")
    assert file_ref == "연구계획"
    assert "자기학습" in query


def test_parse_search_vault_wide_content_exists():
    file_ref, query = _parse_obs_search("자기학습 에이전트에 대한 내용 있어?")
    assert file_ref is None
    assert "자기학습" in query


def test_parse_search_vault_wide_from_obsidian():
    file_ref, query = _parse_obs_search("옵시디언에서 dreaming 찾아줘")
    assert file_ref is None
    assert "dreaming" in query.lower()


# ── _OBS_SEND_KWS / _OBS_SEARCH_KWS 키워드 커버리지 ─────────────────────────

def test_send_kws_cover_common_phrases():
    msg = "옵시디언 연구계획 내용 보내줘"
    assert any(kw in msg for kw in _OBS_SEND_KWS)


def test_search_kws_cover_file_search():
    msg = "연구계획.md에서 dreaming 찾아줘"
    assert any(kw in msg for kw in _OBS_SEARCH_KWS)


def test_search_kws_cover_vault_exists():
    msg = "자기학습 에이전트에 대한 내용 있어?"
    assert any(kw in msg for kw in _OBS_SEARCH_KWS)


# ── PaperAgent._handle_obsidian_read ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_obsidian_read_returns_content_when_short(tmp_path):
    content = "# 연구계획\n\n짧은 내용"
    md = tmp_path / "연구계획.md"
    md.write_text(content, encoding="utf-8")

    agent = PaperAgent.__new__(PaperAgent)
    mock_obs = MagicMock()
    mock_obs.find_note.return_value = md
    mock_obs.read_note.return_value = content
    mock_obs.vault_path = tmp_path

    with patch("agents.paper.obsidian_client.ObsidianClient", return_value=mock_obs):
        result = await agent._handle_obsidian_read("연구계획.md 내용 보내줘", chat_id=123)

    assert result is not None
    assert "연구계획" in result


@pytest.mark.asyncio
async def test_handle_obsidian_read_sends_chunks_when_long(tmp_path):
    long_content = "x" * 5000
    md = tmp_path / "big.md"
    md.write_text(long_content, encoding="utf-8")

    agent = PaperAgent.__new__(PaperAgent)
    mock_obs = MagicMock()
    mock_obs.find_note.return_value = md
    mock_obs.read_note.return_value = long_content
    mock_obs.vault_path = tmp_path

    mock_sender = AsyncMock()
    mock_sender.send_chunks = AsyncMock(return_value=True)

    with patch("agents.paper.obsidian_client.ObsidianClient", return_value=mock_obs):
        with patch("systems.telegram_sender.TelegramSender", return_value=mock_sender):
            result = await agent._handle_obsidian_read("big.md 내용 보내줘", chat_id=123)

    assert result is None
    mock_sender.send_chunks.assert_called_once()


@pytest.mark.asyncio
async def test_handle_obsidian_read_no_file_ref():
    agent = PaperAgent.__new__(PaperAgent)
    result = await agent._handle_obsidian_read("내용 보내줘", chat_id=0)
    assert "파일명" in result


@pytest.mark.asyncio
async def test_handle_obsidian_read_file_not_found(tmp_path):
    agent = PaperAgent.__new__(PaperAgent)
    mock_obs = MagicMock()
    mock_obs.find_note.return_value = None
    mock_obs.vault_path = tmp_path

    with patch("agents.paper.obsidian_client.ObsidianClient", return_value=mock_obs):
        result = await agent._handle_obsidian_read("없는파일.md 내용 보내줘", chat_id=0)

    assert "찾지 못했습니다" in result


# ── PaperAgent._handle_obsidian_search ───────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_obsidian_search_in_file(tmp_path):
    md = tmp_path / "연구계획.md"
    md.write_text("자기학습 에이전트 연구\n\n다른 내용", encoding="utf-8")

    agent = PaperAgent.__new__(PaperAgent)
    mock_obs = MagicMock()
    mock_obs.find_note.return_value = md
    mock_obs.search_in_note.return_value = ["자기학습 에이전트 연구"]
    mock_obs.vault_path = tmp_path

    with patch("agents.paper.obsidian_client.ObsidianClient", return_value=mock_obs):
        result = await agent._handle_obsidian_search("연구계획.md에서 자기학습 에이전트 찾아줘")

    assert "자기학습" in result
    assert "검색결과" in result


@pytest.mark.asyncio
async def test_handle_obsidian_search_vault_wide(tmp_path):
    agent = PaperAgent.__new__(PaperAgent)
    mock_obs = MagicMock()
    mock_obs.search_vault.return_value = [
        {"filename": "연구계획", "rel_path": "연구계획.md", "sections": ["dreaming 관련 단락"]},
    ]
    mock_obs.vault_path = tmp_path

    with patch("agents.paper.obsidian_client.ObsidianClient", return_value=mock_obs):
        result = await agent._handle_obsidian_search("dreaming에 대한 내용 있어?")

    assert "dreaming" in result.lower() or "Dreaming" in result
    assert "연구계획" in result


@pytest.mark.asyncio
async def test_handle_obsidian_search_no_results(tmp_path):
    agent = PaperAgent.__new__(PaperAgent)
    mock_obs = MagicMock()
    mock_obs.search_vault.return_value = []
    mock_obs.vault_path = tmp_path

    with patch("agents.paper.obsidian_client.ObsidianClient", return_value=mock_obs):
        result = await agent._handle_obsidian_search("존재하지않는키워드에 대한 내용 있어?")

    assert "찾지 못했습니다" in result
