"""
AutoTest agent — full test loop:
  1. Read target file → ask Claude to list test cases
  2. Generate pytest code
  3. Write to tests/ and run pytest
  4. If failures → ask Claude to fix the source file
  5. Repeat until all pass or max_rounds reached
"""
import os
import re
import subprocess
import logging
from pathlib import Path

from systems.claude_runner import async_ask as claude_ask

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = PROJECT_ROOT / "tests"
TESTS_DIR.mkdir(exist_ok=True)

_PLAN_SYSTEM = """
You are a QA engineer. Read the following Python module and output a JSON list of test cases.
Each item: {"name": "test_<snake_case>", "description": "one line", "inputs": "brief", "expected": "brief"}
Cover: happy path, edge cases, error handling.
Output ONLY the JSON array, no markdown fences.
""".strip()

_WRITE_SYSTEM = """
You are a pytest expert. Given the test plan and the source code, write complete pytest code.
Rules:
- One function per test case from the plan.
- Use only stdlib + the project's own modules (no external mocking libs).
- PYTHONPATH includes the project root — import directly (e.g. `from agents.finance.ledger_parser import LedgerParser`).
- Do not use asyncio for sync methods. For async methods use `import asyncio; asyncio.run(...)`.
- CRITICAL: Output the test file wrapped in exactly one ```python ... ``` fence. Nothing before or after the fence.
""".strip()

_FIX_SYSTEM = """
You are a senior Python developer. Tests failed. Fix the SOURCE FILE (not the tests).
CRITICAL: Return the fixed source file wrapped in exactly one ```python ... ``` fence. Nothing before or after the fence.
""".strip()


class AutoTestAgent:
    def __init__(self, max_rounds: int = 3):
        self.max_rounds = max_rounds

    # ------------------------------------------------------------------ #
    #  Public entry points                                                 #
    # ------------------------------------------------------------------ #

    async def handle(self, intent=None) -> str:
        msg = intent.raw_message if intent else ""
        path_match = re.search(r"(agents/\S+\.py|systems/\S+\.py)", msg)
        if not path_match:
            return "⚠️ 테스트할 파일 경로를 포함해 주세요.\n예: `autotest agents/finance/ledger_parser.py`"
        return await self.run(PROJECT_ROOT / path_match.group(1))

    async def run(self, target_path: Path) -> str:
        target_path = Path(target_path)
        if not target_path.is_absolute():
            target_path = PROJECT_ROOT / target_path
        if not target_path.exists():
            return f"⚠️ 파일 없음: {target_path}"

        source = target_path.read_text(encoding="utf-8")
        rel = str(target_path.relative_to(PROJECT_ROOT))
        logger.info(f"AutoTest starting: {rel}")

        # Step 1 — plan
        plan = await self._plan(source, rel)
        logger.info(f"Test plan: {len(plan)} cases")

        # Step 2 — write initial test file
        test_path = TESTS_DIR / f"test_{target_path.stem}.py"
        try:
            test_code = await self._write_tests(source, plan, rel)
        except Exception as e:
            return f"⚠️ 테스트 코드 생성 실패: {e}"
        test_path.write_text(test_code, encoding="utf-8")

        summary_lines = [f"🧪 *AutoTest: {rel}*", f"📋 테스트 케이스 {len(plan)}개"]

        for round_no in range(1, self.max_rounds + 1):
            passed, failed, output = self._run_pytest(test_path)
            total = passed + failed
            logger.info(f"Round {round_no}: {passed}/{total} passed")

            if failed == 0:
                summary_lines.append(f"✅ Round {round_no}: {passed}/{total} 전체 통과!")
                break

            summary_lines.append(f"🔴 Round {round_no}: {passed}/{total} 통과, {failed}개 실패")

            if round_no == self.max_rounds:
                summary_lines.append("⛔ 최대 라운드 도달. 수동 확인 필요.")
                summary_lines.append(f"```\n{output[-800:]}\n```")
                break

            try:
                fixed_source = await self._fix_source(source, test_code, output, rel)
            except Exception as e:
                summary_lines.append(f"  ⚠️ 자동 수정 불가: {e}")
                break

            if fixed_source and fixed_source.strip() != source.strip():
                target_path.write_text(fixed_source, encoding="utf-8")
                source = fixed_source
                summary_lines.append("  🔧 소스 수정 후 재시도...")
            else:
                summary_lines.append("  ⚠️ 변경사항 없음. 수동 확인 필요.")
                break

        return "\n".join(summary_lines)

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    async def _plan(self, source: str, filename: str) -> list[dict]:
        prompt = f"File: {filename}\n\n```python\n{source}\n```"
        try:
            raw = await claude_ask(prompt, system=_PLAN_SYSTEM)
            raw = self._strip_fence(raw)
            import json
            return json.loads(raw)
        except Exception as e:
            logger.error(f"Plan failed: {e}")
            return [{"name": "test_basic", "description": "basic smoke test",
                     "inputs": "—", "expected": "no exception"}]

    async def _write_tests(self, source: str, plan: list[dict], filename: str) -> str:
        import json
        prompt = (
            f"File: {filename}\n\n"
            f"Source:\n```python\n{source}\n```\n\n"
            f"Test plan:\n{json.dumps(plan, ensure_ascii=False, indent=2)}"
        )
        # no_tools: prevent Claude from writing files directly
        raw = await claude_ask(prompt, system=_WRITE_SYSTEM, max_tokens=2048, no_tools=True)
        return self._strip_fence(raw)

    async def _fix_source(self, source: str, test_code: str, failure_output: str, filename: str) -> str:
        prompt = (
            f"Source file ({filename}):\n```python\n{source}\n```\n\n"
            f"Tests:\n```python\n{test_code}\n```\n\n"
            f"Failure output:\n```\n{failure_output[-1500:]}\n```\n\n"
            f"Fix the source file."
        )
        # no_tools: must return code as text, not write to disk
        raw = await claude_ask(prompt, system=_FIX_SYSTEM, max_tokens=2048, no_tools=True)
        return self._strip_fence(raw)

    def _run_pytest(self, test_path: Path) -> tuple[int, int, str]:
        result = subprocess.run(
            ["/Users/hanga/venv/bin/pytest", str(test_path), "-v", "--tb=short", "--no-header"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
            timeout=60,
        )
        output = result.stdout + result.stderr
        passed = len(re.findall(r" PASSED", output))
        failed = len(re.findall(r" FAILED| ERROR", output))
        return passed, failed, output

    @staticmethod
    def _strip_fence(text: str) -> str:
        """Extract code from ```python ... ``` fence, using rfind for the closing fence
        so that ``` inside string literals don't prematurely terminate extraction."""
        text = text.strip()
        # Locate opening fence
        for opener in ("```python\n", "```\n"):
            start = text.find(opener)
            if start != -1:
                code_start = start + len(opener)
                # Use rfind so ``` inside the code body doesn't close prematurely
                end = text.rfind("\n```")
                if end > code_start:
                    return text[code_start:end].strip()
        # No fence — return as-is
        return text
