"""
Claude Code runner — calls the `claude` CLI in non-interactive (-p) mode.
Replaces direct Anthropic API calls so all LLM usage goes through
the Claude Pro subscription instead of separate API credits.
"""
import asyncio
import subprocess
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

CLAUDE_BIN = shutil.which("claude") or "/Users/hanga/.npm-global/bin/claude"
_TIMEOUT = 90  # subprocess timeout (seconds) — 이벤트 루프 블로킹 최대 시간


def ask(prompt: str, system: str = "", model: str = "claude-sonnet-4-6",
        max_tokens: int = 2048, no_tools: bool = False) -> str:
    """동기 버전 — 스크립트/테스트용. async 컨텍스트에서는 async_ask() 사용."""
    full_prompt = f"{system}\n\n{prompt}".strip() if system else prompt

    cmd = [CLAUDE_BIN, "-p", full_prompt, "--model", model]
    if no_tools:
        cmd += ["--tools", ""]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            err = result.stderr.strip()
            logger.error(f"claude CLI error (rc={result.returncode}): {err[:200]}")
            raise RuntimeError(f"claude CLI 오류: {err[:200]}")
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"claude CLI 응답 시간 초과 ({_TIMEOUT}s)")
    except FileNotFoundError:
        raise RuntimeError(f"claude CLI를 찾을 수 없습니다: {CLAUDE_BIN}")


async def async_ask(prompt: str, system: str = "", model: str = "claude-sonnet-4-6",
                    max_tokens: int = 2048, no_tools: bool = False) -> str:
    """비동기 버전 — asyncio.to_thread()로 스레드풀 실행, 이벤트 루프 비블로킹.
    bot_listener / agent handle() 내부에서 항상 이 버전 사용."""
    return await asyncio.to_thread(ask, prompt, system, model, max_tokens, no_tools)
