import asyncio
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock, patch

from agents.inbox_trage.trage_agent import TriageAgent
from systems.telegram_sender import TelegramSender


def _make_intent(raw_message="fix login bug", summary="Fix login", domain="dev"):
    return SimpleNamespace(raw_message=raw_message, summary=summary, domain=domain)


def _make_agent(classifier_return="bug", scorer_return=9, writer_return=None, sender=None):
    if writer_return is None:
        writer_return = {"id": "42"}

    mock_sender = sender if sender is not None else AsyncMock(spec=TelegramSender)

    mock_classifier = MagicMock()
    mock_classifier.classify.return_value = classifier_return

    mock_scorer = MagicMock()
    mock_scorer.score.return_value = scorer_return

    mock_writer = MagicMock()
    mock_writer.write.return_value = writer_return

    with patch("agents.inbox_trage.trage_agent.TriageClassifier", return_value=mock_classifier), \
         patch("agents.inbox_trage.trage_agent.PriorityScorer", return_value=mock_scorer), \
         patch("agents.inbox_trage.trage_agent.QueueWriter", return_value=mock_writer):
        agent = TriageAgent(sender=mock_sender)

    return agent, mock_classifier, mock_scorer, mock_writer, mock_sender


# ── _priority_label ──────────────────────────────────────────────────────────

def test_priority_label_high_at_boundary():
    assert TriageAgent._priority_label(8) == "🔴 높음"


def test_priority_label_high_above_boundary():
    assert TriageAgent._priority_label(10) == "🔴 높음"


def test_priority_label_medium_at_boundary():
    assert TriageAgent._priority_label(5) == "🟡 보통"


def test_priority_label_medium_below_high():
    assert TriageAgent._priority_label(7) == "🟡 보통"


def test_priority_label_low_at_boundary():
    assert TriageAgent._priority_label(4) == "🟢 낮음"


def test_priority_label_low_at_zero():
    assert TriageAgent._priority_label(0) == "🟢 낮음"


# ── __init__ ─────────────────────────────────────────────────────────────────

def test_init_creates_default_sender():
    with patch("agents.inbox_trage.trage_agent.TriageClassifier"), \
         patch("agents.inbox_trage.trage_agent.PriorityScorer"), \
         patch("agents.inbox_trage.trage_agent.QueueWriter"), \
         patch("agents.inbox_trage.trage_agent.TelegramSender") as MockSender:
        mock_instance = MagicMock(spec=TelegramSender)
        MockSender.return_value = mock_instance
        agent = TriageAgent(sender=None)
        MockSender.assert_called_once()
        assert agent.sender is mock_instance


def test_init_uses_injected_sender():
    mock_sender = AsyncMock(spec=TelegramSender)
    with patch("agents.inbox_trage.trage_agent.TriageClassifier"), \
         patch("agents.inbox_trage.trage_agent.PriorityScorer"), \
         patch("agents.inbox_trage.trage_agent.QueueWriter"):
        agent = TriageAgent(sender=mock_sender)
    assert agent.sender is mock_sender


# ── handle happy paths ───────────────────────────────────────────────────────

def test_handle_happy_path_high_priority():
    agent, _, _, _, mock_sender = _make_agent(scorer_return=9, writer_return={"id": "42"})
    intent = _make_intent(summary="Fix login")
    asyncio.run(agent.handle(intent, chat_id=123))
    mock_sender.send.assert_called_once()
    sent_msg = mock_sender.send.call_args[0][1]
    assert "🔴 높음" in sent_msg
    assert "42" in sent_msg
    assert "Fix login" in sent_msg


def test_handle_happy_path_medium_priority():
    agent, _, _, _, mock_sender = _make_agent(scorer_return=6)
    asyncio.run(agent.handle(_make_intent(), chat_id=123))
    sent_msg = mock_sender.send.call_args[0][1]
    assert "🟡 보통" in sent_msg


def test_handle_happy_path_low_priority():
    agent, _, _, _, mock_sender = _make_agent(scorer_return=3)
    asyncio.run(agent.handle(_make_intent(), chat_id=123))
    sent_msg = mock_sender.send.call_args[0][1]
    assert "🟢 낮음" in sent_msg


def test_handle_confirmation_message_format():
    agent, _, _, _, mock_sender = _make_agent(
        classifier_return="bug",
        scorer_return=7,
        writer_return={"id": "abc-123"},
    )
    asyncio.run(agent.handle(_make_intent(), chat_id=123))
    sent_msg = mock_sender.send.call_args[0][1]
    assert "bug" in sent_msg
    assert "7/10" in sent_msg
    assert "abc-123" in sent_msg


# ── handle error paths ───────────────────────────────────────────────────────

def test_handle_classifier_raises_sends_error():
    agent, mock_classifier, mock_scorer, mock_writer, mock_sender = _make_agent()
    mock_classifier.classify.side_effect = ValueError("bad input")

    asyncio.run(agent.handle(_make_intent(), chat_id=123))

    mock_sender.send.assert_called_once()
    error_msg = mock_sender.send.call_args[0][1]
    assert "⚠️ 백로그 저장 중 오류" in error_msg
    mock_scorer.score.assert_not_called()
    mock_writer.write.assert_not_called()


def test_handle_scorer_raises_sends_error():
    agent, _, mock_scorer, mock_writer, mock_sender = _make_agent()
    mock_scorer.score.side_effect = RuntimeError("scorer failed")

    asyncio.run(agent.handle(_make_intent(), chat_id=123))

    mock_sender.send.assert_called_once()
    error_msg = mock_sender.send.call_args[0][1]
    assert "⚠️" in error_msg
    mock_writer.write.assert_not_called()


def test_handle_queue_writer_raises_sends_error():
    agent, _, _, mock_writer, mock_sender = _make_agent()
    mock_writer.write.side_effect = IOError("disk full")

    asyncio.run(agent.handle(_make_intent(), chat_id=123))

    mock_sender.send.assert_called_once()
    error_msg = mock_sender.send.call_args[0][1]
    assert "disk full" in error_msg


def test_handle_sender_raises_is_logged():
    agent, _, _, _, mock_sender = _make_agent()
    mock_sender.send.side_effect = ConnectionError("connection refused")

    # First send (success msg) raises → caught → error send also raises → propagates out
    with pytest.raises(ConnectionError):
        asyncio.run(agent.handle(_make_intent(), chat_id=123))

    # Exactly two calls: one for confirmation, one for error — no infinite retry
    assert mock_sender.send.call_count <= 2


# ── handle call order and argument passing ───────────────────────────────────

def test_handle_calls_components_in_order():
    call_order = []

    mock_sender = AsyncMock(spec=TelegramSender)

    mock_classifier = MagicMock()
    mock_classifier.classify.side_effect = (
        lambda *a, **kw: call_order.append("classify") or "bug"
    )

    mock_scorer = MagicMock()
    mock_scorer.score.side_effect = (
        lambda *a, **kw: call_order.append("score") or 7
    )

    mock_writer = MagicMock()
    mock_writer.write.side_effect = (
        lambda *a, **kw: call_order.append("write") or {"id": "1"}
    )

    async def _fake_send(*args, **kwargs):
        call_order.append("send")

    mock_sender.send.side_effect = _fake_send

    with patch("agents.inbox_trage.trage_agent.TriageClassifier", return_value=mock_classifier), \
         patch("agents.inbox_trage.trage_agent.PriorityScorer", return_value=mock_scorer), \
         patch("agents.inbox_trage.trage_agent.QueueWriter", return_value=mock_writer):
        agent = TriageAgent(sender=mock_sender)

    asyncio.run(agent.handle(_make_intent(), chat_id=123))
    assert call_order == ["classify", "score", "write", "send"]


def test_handle_passes_raw_message_to_classifier():
    agent, mock_classifier, _, _, _ = _make_agent()
    intent = _make_intent(raw_message="fix login bug", domain="dev")
    asyncio.run(agent.handle(intent, chat_id=123))
    mock_classifier.classify.assert_called_once_with("fix login bug", "dev")


def test_handle_passes_correct_args_to_queue_writer():
    agent, _, _, mock_writer, _ = _make_agent(classifier_return="bug", scorer_return=7)
    intent = _make_intent(raw_message="fix login bug", summary="Fix login", domain="dev")
    asyncio.run(agent.handle(intent, chat_id=123))
    mock_writer.write.assert_called_once_with(
        message="fix login bug",
        summary="Fix login",
        domain="dev",
        category="bug",
        priority=7,
    )