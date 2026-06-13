"""
TriageAgent — _strip_backlog_trigger 파싱 및 저장 메시지 검증
"""
import pytest
from agents.inbox_trage.trage_agent import _strip_backlog_trigger


class TestStripBacklogTrigger:
    def test_arrow_trigger_removed(self):
        msg = "보조축 추가해서 함께 그려줘.\n->백로그 추가해줘"
        assert _strip_backlog_trigger(msg) == "보조축 추가해서 함께 그려줘."

    def test_arrow_with_space_removed(self):
        msg = "논문 읽어야지\n-> 백로그에 추가해줘"
        assert _strip_backlog_trigger(msg) == "논문 읽어야지"

    def test_inline_trigger_removed(self):
        msg = "강화학습 공부해야지 백로그에 넣어줘"
        assert _strip_backlog_trigger(msg) == "강화학습 공부해야지"

    def test_trigger_without_arrow_removed(self):
        msg = "코드 리팩토링 백로그 저장해줘"
        assert _strip_backlog_trigger(msg) == "코드 리팩토링"

    def test_backlog_ro_pattern(self):
        msg = "일정 정리 백로그로 넣어줘"
        assert _strip_backlog_trigger(msg) == "일정 정리"

    def test_naeun_chuori(self):
        msg = "데이터 분석 나중에 처리해줘"
        assert _strip_backlog_trigger(msg) == "데이터 분석"

    def test_naeun_suhaeng(self):
        msg = "리포트 작성 나중에 수행해줘"
        assert _strip_backlog_trigger(msg) == "리포트 작성"

    def test_no_trigger_unchanged(self):
        msg = "오늘 날씨 알려줘"
        assert _strip_backlog_trigger(msg) == "오늘 날씨 알려줘"

    def test_only_trigger_returns_original(self):
        """트리거만 있는 경우 원본 반환 (빈 문자열 방지)."""
        msg = "백로그에 추가해줘"
        assert _strip_backlog_trigger(msg) == "백로그에 추가해줘"

    def test_multiline_real_case(self):
        """실제 발생한 케이스."""
        msg = (
            "Jarvis, AssetManager_hangabot에 최근 수입/지출 추이 그래프를 보내주고있는데, "
            "순자산이 매달 어떻게달라지는지도 보조축 추가해서 함께 그려줘.\n->백로그 추가해줘"
        )
        result = _strip_backlog_trigger(msg)
        assert "백로그" not in result
        assert "보조축 추가해서 함께 그려줘." in result

    def test_whitespace_stripped(self):
        msg = "할 일 정리   백로그에 저장해"
        result = _strip_backlog_trigger(msg)
        assert result == "할 일 정리"
