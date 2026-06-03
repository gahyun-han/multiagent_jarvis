"""
Claude Code Usage Reader
Reads actual Claude token usage from ~/.claude session files.
- history.jsonl: maps sessionId → start timestamp
- projects/<project>/<session>.jsonl: token counts per API call

Calculates usage within a rolling 5-hour window to match /usage output.
"""
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

CLAUDE_DIR = Path.home() / ".claude"
HISTORY_FILE = CLAUDE_DIR / "history.jsonl"
WINDOW_HOURS = 5

# Output tokens are the primary rate-limited resource on Max subscriptions
# Configurable cap — Claude Max ~88K output tokens / 5h (adjust if needed)
DEFAULT_OUTPUT_LIMIT = 88_000


def _load_history() -> list[dict]:
    """Returns list of {sessionId, timestamp_ms, project}."""
    if not HISTORY_FILE.exists():
        return []
    results = []
    for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line.strip())
            if "sessionId" in d and "timestamp" in d:
                results.append(d)
        except Exception:
            pass
    return results


def _session_start_map(cutoff_ms: int) -> dict[str, dict]:
    """
    Returns {sessionId: {start_ms, project}} for sessions that started
    within the 5-hour window.
    """
    history = _load_history()
    seen: dict[str, dict] = {}
    for entry in history:
        sid = entry["sessionId"]
        ts = entry["timestamp"]
        if ts < cutoff_ms:
            continue
        if sid not in seen or ts < seen[sid]["start_ms"]:
            seen[sid] = {
                "start_ms": ts,
                "project": entry.get("project", ""),
            }
    return seen


def _project_dir_for(project_path: str) -> Path | None:
    """Map project path to .claude/projects/<slug>."""
    slug = project_path.replace("/", "-").lstrip("-")
    candidate = CLAUDE_DIR / "projects" / f"-{slug}"
    if candidate.exists():
        return candidate
    # Also try without leading dash
    candidate2 = CLAUDE_DIR / "projects" / slug
    if candidate2.exists():
        return candidate2
    return None


def _read_session_tokens(project_dir: Path, session_id: str) -> dict:
    """Parse token usage from a single session JSONL file."""
    f = project_dir / f"{session_id}.jsonl"
    if not f.exists():
        return {}
    tokens = {
        "input": 0,
        "output": 0,
        "cache_write": 0,
        "cache_read": 0,
        "cost_usd": 0.0,
        "api_calls": 0,
    }
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line.strip())
            tokens["cost_usd"] += d.get("costUSD") or 0
            usage = d.get("message", {}).get("usage", {})
            if usage and d.get("message", {}).get("role") == "assistant":
                tokens["input"] += usage.get("input_tokens", 0)
                tokens["output"] += usage.get("output_tokens", 0)
                tokens["cache_write"] += usage.get("cache_creation_input_tokens", 0)
                tokens["cache_read"] += usage.get("cache_read_input_tokens", 0)
                tokens["api_calls"] += 1
        except Exception:
            pass
    return tokens


def get_usage_summary(
    output_limit: int = DEFAULT_OUTPUT_LIMIT,
    manual_reset_at_ms: int | None = None,
) -> dict:
    """
    Returns usage dict for the last 5 hours:
    {
      output_tokens, input_tokens, cache_write, cache_read, api_calls,
      output_limit, output_pct, reset_in_minutes, oldest_session_start_ms,
      is_manual_reset
    }

    manual_reset_at_ms: epoch-ms override for reset time (from user-set Telegram command).
    If provided and in the future, it takes priority over the auto-detected reset time.
    """
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    cutoff_ms = now_ms - WINDOW_HOURS * 3600 * 1000

    sessions = _session_start_map(cutoff_ms)

    totals = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0,
              "api_calls": 0, "cost_usd": 0.0}
    oldest_start_ms = now_ms

    for sid, info in sessions.items():
        proj_dir = _project_dir_for(info["project"])
        if proj_dir is None:
            continue
        toks = _read_session_tokens(proj_dir, sid)
        if not toks:
            continue
        for k in ("input", "output", "cache_write", "cache_read", "api_calls"):
            totals[k] += toks.get(k, 0)
        totals["cost_usd"] += toks.get("cost_usd", 0)
        if info["start_ms"] < oldest_start_ms:
            oldest_start_ms = info["start_ms"]

    auto_reset_ms = oldest_start_ms + WINDOW_HOURS * 3600 * 1000
    use_manual = bool(manual_reset_at_ms and manual_reset_at_ms > now_ms)
    reset_ms = manual_reset_at_ms if use_manual else auto_reset_ms

    reset_in_min = max(0, (reset_ms - now_ms) / 60_000)
    pct = totals["output"] / output_limit * 100 if output_limit else 0

    return {
        **totals,
        "output_limit": output_limit,
        "output_pct": round(pct, 1),
        "reset_in_minutes": round(reset_in_min, 1),
        "oldest_session_start_ms": oldest_start_ms,
        "is_manual_reset": use_manual,
    }


def format_usage_message(limit: int = DEFAULT_OUTPUT_LIMIT, manual_reset_at_ms: int | None = None) -> str:
    u = get_usage_summary(limit, manual_reset_at_ms=manual_reset_at_ms)
    pct = u["output_pct"]
    bar_filled = min(10, round(pct / 10))
    bar = "█" * bar_filled + "░" * (10 - bar_filled)

    reset_min = u["reset_in_minutes"]
    if reset_min >= 60:
        reset_str = f"{reset_min/60:.1f}시간 후"
    else:
        reset_str = f"{reset_min:.0f}분 후"
    manual_tag = " *(수동설정)*" if u.get("is_manual_reset") else ""

    return (
        f"📊 *Claude Code 사용량 (5h 윈도우)*\n"
        f"`[{bar}]` {pct:.1f}%\n"
        f"출력: {u['output']:,} / {limit:,} 토큰\n"
        f"입력: {u['input']:,}  캐시읽기: {u['cache_read']:,}\n"
        f"API 호출 수: {u['api_calls']}회\n"
        f"🔄 리셋까지: {reset_str}{manual_tag}"
    )
