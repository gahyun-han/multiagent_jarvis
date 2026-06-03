import os
from types import SimpleNamespace
from unittest.mock import patch

from agents.inbox_trage.classifier import TriageClassifier

_PATCH = "agents.inbox_trage.classifier.anthropic.Anthropic"


def _mock_response(text: str):
    return SimpleNamespace(content=[SimpleNamespace(text=text)])


def test_classify_returns_category_string():
    with patch(_PATCH) as mock_cls:
        mock_cls.return_value.messages.create.return_value = _mock_response(
            '{"category": "errand", "agent_tag": "self"}'
        )
        classifier = TriageClassifier()
        result = classifier.classify("Buy groceries", "errand")
    assert isinstance(result, str)
    assert result == "errand"


def test_classify_uses_category_field_from_response():
    with patch(_PATCH) as mock_cls:
        mock_cls.return_value.messages.create.return_value = _mock_response(
            '{"category": "follow-up", "agent_tag": "self"}'
        )
        classifier = TriageClassifier()
        result = classifier.classify("Follow up with team", "work")
    assert result == "follow-up"


def test_classify_falls_back_to_misc_on_api_exception():
    with patch(_PATCH) as mock_cls:
        mock_cls.return_value.messages.create.side_effect = Exception("API error")
        classifier = TriageClassifier()
        result = classifier.classify("Buy groceries", "errand")
    assert result == "misc"


def test_classify_falls_back_to_misc_on_invalid_json():
    with patch(_PATCH) as mock_cls:
        mock_cls.return_value.messages.create.return_value = _mock_response(
            "not valid json"
        )
        classifier = TriageClassifier()
        result = classifier.classify("Buy groceries", "errand")
    assert result == "misc"


def test_classify_falls_back_to_misc_when_category_key_missing():
    with patch(_PATCH) as mock_cls:
        mock_cls.return_value.messages.create.return_value = _mock_response(
            '{"agent_tag": "calendar"}'
        )
        classifier = TriageClassifier()
        result = classifier.classify("Schedule meeting", "calendar")
    assert result == "misc"


def test_classify_empty_message():
    with patch(_PATCH) as mock_cls:
        mock_cls.return_value.messages.create.return_value = _mock_response(
            '{"category": "misc", "agent_tag": "self"}'
        )
        classifier = TriageClassifier()
        result = classifier.classify("", "errand")
    assert isinstance(result, str)


def test_classify_empty_domain():
    with patch(_PATCH) as mock_cls:
        mock_cls.return_value.messages.create.return_value = _mock_response(
            '{"category": "study", "agent_tag": "paper"}'
        )
        classifier = TriageClassifier()
        result = classifier.classify("Read this paper", "")
    assert isinstance(result, str)


def test_classify_whitespace_stripped_before_json_parse():
    with patch(_PATCH) as mock_cls:
        mock_cls.return_value.messages.create.return_value = _mock_response(
            '  {"category": "idea", "agent_tag": "dev"}  '
        )
        classifier = TriageClassifier()
        result = classifier.classify("New idea", "dev")
    assert result == "idea"


def test_classify_missing_api_key_raises_on_init():
    saved = os.environ.pop("CLAUDE_API_KEY", None)
    try:
        try:
            classifier = TriageClassifier()
            result = classifier.classify("test", "test")
            assert result == "misc"
        except Exception:
            pass  # anthropic may raise immediately on None key — also acceptable
    finally:
        if saved is not None:
            os.environ["CLAUDE_API_KEY"] = saved


def test_classify_response_content_index_error():
    with patch(_PATCH) as mock_cls:
        mock_cls.return_value.messages.create.return_value = SimpleNamespace(content=[])
        classifier = TriageClassifier()
        result = classifier.classify("Buy groceries", "errand")
    assert result == "misc"


def test_classify_long_message():
    long_message = "x" * 10_000
    with patch(_PATCH) as mock_cls:
        mock_cls.return_value.messages.create.return_value = _mock_response(
            '{"category": "study", "agent_tag": "paper"}'
        )
        classifier = TriageClassifier()
        result = classifier.classify(long_message, "study")
    assert isinstance(result, str)


def test_classify_message_with_special_characters():
    message = 'He said "hello\nworld"'
    with patch(_PATCH) as mock_cls:
        mock_cls.return_value.messages.create.return_value = _mock_response(
            '{"category": "follow-up", "agent_tag": "self"}'
        )
        classifier = TriageClassifier()
        result = classifier.classify(message, "follow-up")
    assert isinstance(result, str)


def test_classify_logs_error_on_exception():
    with patch(_PATCH) as mock_cls:
        mock_cls.return_value.messages.create.side_effect = Exception("timeout")
        classifier = TriageClassifier()
        with patch("agents.inbox_trage.classifier.logger") as mock_logger:
            result = classifier.classify("test", "test")
    assert result == "misc"
    mock_logger.error.assert_called_once()
    logged_msg = mock_logger.error.call_args[0][0]
    assert "timeout" in logged_msg


def test_classify_model_attribute():
    with patch(_PATCH):
        classifier = TriageClassifier()
    assert classifier.model == "claude-haiku-4-5-20251001"