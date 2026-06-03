"""
FixAgent — natural language fix requests applied directly to source files.
Flow:
  1. Parse file path + fix description from the message
  2. Read the source file
  3. Ask Claude to produce the fixed source (full file, fenced)
  4. Write the fixed file back
  5. If the file is inside the Jarvis project, run autotest to verify
"""
import re
import logging
from pathlib import Path

from systems.claude_runner import async_ask as claude_ask

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HOME = Path.home()

# Candidate base directories for path resolution (in priority order)
_SEARCH_BASES = [
    HOME / "PycharmProjects",
    HOME / "Desktop" / "claude",
    PROJECT_ROOT,
    HOME,
]

_FIX_SYSTEM = """
You are a senior Python developer. The user wants a specific change applied to the source file below.

Rules:
- Apply ONLY what is described. Do not refactor anything else.
- Return the COMPLETE fixed file wrapped in exactly one ```python ... ``` fence.
- Nothing before or after the fence.
""".strip()


class FixAgent:
    async def handle(self, intent) -> str:
        message = intent.raw_message
        target, description = self._parse(message)

        if target is None:
            return (
                "⚠️ 수정할 파일 경로를 포함해 주세요.\n"
                "예: `TrendNotifier/main.py 중복 제거해줘`"
            )

        if not target.exists():
            return f"⚠️ 파일을 찾을 수 없습니다: {target}"

        source = target.read_text(encoding="utf-8")
        logger.info(f"FixAgent: {target} / '{description[:60]}'")

        prompt = (
            f"File: {target}\n\n"
            f"Fix request: {description}\n\n"
            f"Source:\n```python\n{source}\n```"
        )

        try:
            raw = await claude_ask(prompt, system=_FIX_SYSTEM, max_tokens=4096, no_tools=True)
            fixed = self._strip_fence(raw)
        except Exception as e:
            return f"⚠️ Claude 수정 실패: {e}"

        if not fixed or fixed.strip() == source.strip():
            return "⚠️ 변경사항이 없습니다. 요청 내용을 더 구체적으로 작성해 주세요."

        target.write_text(fixed, encoding="utf-8")
        result_lines = [f"✅ *{target.name}* 수정 완료\n📁 `{target}`"]

        # Jarvis 내부 파일이면 autotest로 검증
        try:
            rel = target.relative_to(PROJECT_ROOT)
            result_lines.append("\n🧪 autotest 검증 중...")
            from agents.dev.autotest_agent import AutoTestAgent
            test_result = await AutoTestAgent(max_rounds=2).run(target)
            result_lines.append(test_result)
        except ValueError:
            pass  # 외부 프로젝트 파일 — autotest 생략

        return "\n".join(result_lines)

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _parse(self, message: str) -> tuple[Path | None, str]:
        """메시지에서 (파일경로, 수정설명) 추출."""
        # 패턴 우선순위:
        # 1. ~/PycharmProjects/Foo/bar.py  or  /absolute/path/file.py
        # 2. Foo/bar.py  (base directory 탐색)
        # 3. agents/foo/bar.py  (Jarvis 상대경로)

        patterns = [
            r"(~/[\w/\-\.]+\.py)",            # ~/PycharmProjects/...
            r"(/[\w/\-\.]+\.py)",             # /absolute/path/...
            r"([\w\-]+(?:/[\w\-\.]+)+\.py)",  # Foo/bar/baz.py (다단계 경로)
        ]

        for pat in patterns:
            m = re.search(pat, message)
            if not m:
                continue
            raw_path = m.group(1)
            description = (message[:m.start()] + message[m.end():]).strip()
            resolved = self._resolve(raw_path)
            if resolved:
                return resolved, description or message

        return None, message

    def _resolve(self, raw: str) -> Path | None:
        """경로 문자열을 실제 Path로 변환. 없으면 None."""
        # ~ 확장
        if raw.startswith("~"):
            p = Path(raw).expanduser()
            return p if p.exists() else None

        # 절대경로
        if raw.startswith("/"):
            p = Path(raw)
            return p if p.exists() else None

        # 상대경로 — 기본 디렉토리에서 탐색
        for base in _SEARCH_BASES:
            p = base / raw
            if p.exists():
                return p

        return None

    @staticmethod
    def _strip_fence(text: str) -> str:
        text = text.strip()
        for opener in ("```python\n", "```\n"):
            start = text.find(opener)
            if start != -1:
                code_start = start + len(opener)
                end = text.rfind("\n```")
                if end > code_start:
                    return text[code_start:end].strip()
        return text
