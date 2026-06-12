"""
"TOPIC 알아봐주고 + 옵시디언에 FILE.md에 추가" 복합 요청 처리 테스트
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.paper.paper_agent import _parse_obs_request, _RESEARCH_SAVE_RE


# ── _parse_obs_request 패턴 A' 테스트 ─────────────────────────────────────────

def test_parse_obs_md_at_start():
    """기존 패턴 A: 문장 시작이 파일명.md"""
    file_ref, content = _parse_obs_request("연구계획.md에 테스트 내용 추가해줘")
    assert file_ref == "연구계획"
    assert "테스트 내용" in content


def test_parse_obs_md_in_middle():
    """패턴 A': 옵시디언에 파일명.md에 — .md가 중간에 있는 경우"""
    file_ref, content = _parse_obs_request("옵시디언에 연구계획.md에 새로운 내용 추가해줘")
    assert file_ref == "연구계획"
    assert "새로운 내용" in content


def test_parse_obs_md_no_content_returns_none():
    """file_ref 없는 일반 저장"""
    file_ref, content = _parse_obs_request("옵시디언에 오늘 배운 내용 저장해줘")
    assert file_ref is None
    assert "오늘 배운 내용" in content


def test_parse_obs_geogi_pattern():
    """패턴 B: '거기에' 패턴"""
    file_ref, content = _parse_obs_request("옵시디언에 연구노트 거기에 실험 결과 추가해줘")
    assert file_ref == "연구노트"
    assert "실험 결과" in content


# ── _RESEARCH_SAVE_RE 정규식 테스트 ──────────────────────────────────────────

def test_research_save_regex_basic():
    msg = "자기학습 에이전트(Dreaming)에 대해서 알아봐주고, 옵시디언에 연구계획.md에 내용 추가해줘."
    m = _RESEARCH_SAVE_RE.search(msg)
    assert m is not None
    assert "자기학습 에이전트" in m.group(1)
    assert "연구계획.md" in m.group(2)


def test_research_save_regex_variant_keywords():
    for kw in ["알아보고", "조사해주고", "찾아봐주고"]:
        msg = f"강화학습에 대해서 {kw} 옵시디언에 메모.md에 추가해줘"
        m = _RESEARCH_SAVE_RE.search(msg)
        assert m is not None, f"keyword '{kw}' not matched"


def test_research_save_regex_no_match_plain_save():
    """단순 저장 요청은 매칭 안 됨"""
    msg = "옵시디언에 연구계획.md에 내용 추가해줘"
    m = _RESEARCH_SAVE_RE.search(msg)
    assert m is None


# ── _handle_research_and_save 통합 테스트 ────────────────────────────────────

def _make_intent(raw: str):
    intent = MagicMock()
    intent.raw_message = raw
    intent.chat_id = 0
    return intent


@pytest.mark.asyncio
async def test_handle_finds_existing_file_and_appends():
    """기존 연구계획.md 파일을 찾아 내용 추가."""
    from agents.paper.paper_agent import PaperAgent

    intent = _make_intent(
        "자기학습 에이전트(Dreaming)에 대해서 알아봐주고, 옵시디언에 연구계획.md에 내용 추가해줘."
    )
    fake_path = Path("/vault/연구계획.md")

    with patch("agents.paper.paper_agent.ZoteroClient"):
        agent = PaperAgent()
        with patch("agents.paper.paper_agent.claude_ask", new=AsyncMock(return_value="Dreaming 에이전트 조사 결과...")):
            with patch("agents.paper.obsidian_client.ObsidianClient") as MockObs:
                obs_inst = MockObs.return_value
                obs_inst.vault_path = Path("/vault")
                obs_inst.find_note = MagicMock(return_value=fake_path)
                obs_inst.append_to_note = MagicMock(return_value=fake_path)
                result = await agent.handle(intent)

    assert "자기학습 에이전트" in result
    assert "조사 완료" in result
    assert "연구계획" in result
    obs_inst.append_to_note.assert_called_once()


@pytest.mark.asyncio
async def test_handle_creates_new_file_when_not_found():
    """연구계획.md를 못 찾으면 새 파일 생성."""
    from agents.paper.paper_agent import PaperAgent

    intent = _make_intent(
        "RAG에 대해서 알아봐주고, 옵시디언에 연구노트.md에 내용 추가해줘."
    )
    fake_path = Path("/vault/Inbox/RAG.md")

    with patch("agents.paper.paper_agent.ZoteroClient"):
        agent = PaperAgent()
        with patch("agents.paper.paper_agent.claude_ask", new=AsyncMock(return_value="RAG 조사 결과...")):
            with patch("agents.paper.obsidian_client.ObsidianClient") as MockObs:
                obs_inst = MockObs.return_value
                obs_inst.vault_path = Path("/vault")
                obs_inst.find_note = MagicMock(return_value=None)
                obs_inst.add_note = MagicMock(return_value=fake_path)
                result = await agent.handle(intent)

    assert "조사 완료" in result
    obs_inst.add_note.assert_called_once()


@pytest.mark.asyncio
async def test_plain_obsidian_write_still_works():
    """기존 단순 Obsidian 저장은 그대로 동작."""
    from agents.paper.paper_agent import PaperAgent

    intent = _make_intent("옵시디언에 오늘 회의 내용 저장해줘")
    fake_path = Path("/vault/Inbox/오늘 회의 내용.md")

    with patch("agents.paper.paper_agent.ZoteroClient"):
        agent = PaperAgent()
        with patch("agents.paper.obsidian_client.ObsidianClient") as MockObs:
            obs_inst = MockObs.return_value
            obs_inst.vault_path = Path("/vault")
            obs_inst.find_note = MagicMock(return_value=None)
            obs_inst.add_note = MagicMock(return_value=fake_path)
            result = await agent.handle(intent)

    assert "Obsidian" in result
    obs_inst.add_note.assert_called_once()
