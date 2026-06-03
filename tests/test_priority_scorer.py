import pytest
from unittest.mock import MagicMock, patch

from agents.inbox_trage.priority_scorer import PriorityScorer


@pytest.fixture
def scorer():
    with patch("anthropic.Anthropic"):
        s = PriorityScorer()
    return s


def _make_response(text: str):
    resp = MagicMock()
    resp.content = [MagicMock(text=text)]
    return resp


# ---------------------------------------------------------------------------
# _keyword_score
# ---------------------------------------------------------------------------

def test_keyword_score_no_keywords(scorer):
    assert scorer._keyword_score("buy groceries") == 5


def test_keyword_score_korean_deadline(scorer):
    # '마감' → +3
    assert scorer._keyword_score("마감 있어요") == 8


def test_keyword_score_english_deadline(scorer):
    # 'deadline' → +3
    assert scorer._keyword_score("deadline is tomorrow") == 8


def test_keyword_score_multiple_keywords_clamped(scorer):
    # '마감'+3, '오늘'+2, '중요'+2, 'important'+2, 'deadline'+3 → 5+12=17 → clamped 10
    assert scorer._keyword_score("마감 오늘 중요 important deadline") == 10


def test_keyword_score_case_insensitive(scorer):
    # 'DEADLINE' lowered to 'deadline' → +3
    assert scorer._keyword_score("DEADLINE approaching") == 8


def test_keyword_score_empty_message(scorer):
    assert scorer._keyword_score("") == 5


# ---------------------------------------------------------------------------
# score() – AI path
# ---------------------------------------------------------------------------

def test_score_happy_path(scorer):
    scorer.client.messages.create.return_value = _make_response('{"score": 7, "reason": "보통"}')
    # base=5, ai=7 → (5+7)//2=6
    assert scorer.score("buy groceries", "task") == 6


def test_score_keyword_boost_plus_ai(scorer):
    scorer.client.messages.create.return_value = _make_response('{"score": 9, "reason": "긴급"}')
    # '마감'+3, '내일' (substring of '내일까지')+1 → base=9; (9+9)//2=9
    assert scorer.score("마감 내일까지", "work") == 9


def test_score_result_clamped_to_10(scorer):
    scorer.client.messages.create.return_value = _make_response('{"score": 10, "reason": "매우 긴급"}')
    # '마감'+3, '오늘'+2, '중요'+2 → base=12→10; (10+10)//2=10
    assert scorer.score("마감 오늘 중요", "work") == 10


def test_score_result_clamped_to_1(scorer):
    scorer.client.messages.create.return_value = _make_response('{"score": -5, "reason": "낮음"}')
    # base=5, ai=-5 → (5-5)//2=0 → clamped to 1
    assert scorer.score("", "misc") == 1


def test_score_ai_missing_score_key(scorer):
    scorer.client.messages.create.return_value = _make_response('{"reason": "보통"}')
    # missing 'score' → default 5; base=5 → (5+5)//2=5
    assert scorer.score("review notes", "study") == 5


def test_score_ai_returns_invalid_json(scorer):
    scorer.client.messages.create.return_value = _make_response("sorry, cannot score")
    # json.loads raises → fallback to keyword base; '마감'+3 → base=8
    assert scorer.score("마감 있음", "work") == 8


def test_score_ai_returns_non_integer_score(scorer):
    scorer.client.messages.create.return_value = _make_response('{"score": "high", "reason": "건강"}')
    # int("high") raises → fallback to keyword base=5
    assert scorer.score("call dentist", "health") == 5


def test_score_api_exception(scorer):
    scorer.client.messages.create.side_effect = Exception("API error")
    # '오늘'+2 → base=7; exception → return 7
    assert scorer.score("오늘 할 일", "task") == 7


def test_score_ai_score_boundary_zero(scorer):
    scorer.client.messages.create.return_value = _make_response('{"score": 0}')
    # base=5, ai=0 → (5+0)//2=2 → max(1,2)=2
    assert scorer.score("nothing urgent", "misc") == 2


def test_score_ai_score_boundary_eleven(scorer):
    scorer.client.messages.create.return_value = _make_response('{"score": 11}')
    # base=5 (no keywords in '긴급'), ai=11 → (5+11)//2=8 → min(10,8)=8
    assert scorer.score("긴급", "work") == 8


def test_score_empty_message_with_ai(scorer):
    scorer.client.messages.create.return_value = _make_response('{"score": 3, "reason": "낮음"}')
    # base=5, ai=3 → (5+3)//2=4
    assert scorer.score("", "misc") == 4


def test_score_category_passed_to_ai(scorer):
    scorer.client.messages.create.return_value = _make_response('{"score": 5, "reason": "보통"}')
    scorer.score("check emails", "inbox")
    kwargs = scorer.client.messages.create.call_args.kwargs
    content = kwargs["messages"][0]["content"]
    assert "category: inbox" in content