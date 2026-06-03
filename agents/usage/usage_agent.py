"""Usage agent — returns current Claude Code usage when asked via Telegram.
Also handles "리셋 HH:MM으로 설정해줘" to manually sync the reset clock.
"""
import re
from datetime import datetime, timedelta, timezone

import pytz

from systems.claude_code_usage import DEFAULT_OUTPUT_LIMIT, get_usage_summary
from systems.usage_manager import UsageManager

KST = pytz.timezone("Asia/Seoul")

# Matches "리셋 23:51로", "리셋 00:04 설정", "reset 23:51"
_RESET_SET_RE = re.compile(r"(?:리셋|reset)\s*(\d{1,2}):(\d{2})", re.IGNORECASE)


class UsageAgent:
    async def handle(self, intent=None) -> str:
        msg = (intent.raw_message if intent else "").strip()

        m = _RESET_SET_RE.search(msg)
        if m:
            return self._set_reset_time(int(m.group(1)), int(m.group(2)))

        mgr = UsageManager()
        manual_ms = mgr._load_manual_reset_ms()
        u = get_usage_summary(DEFAULT_OUTPUT_LIMIT, manual_reset_at_ms=manual_ms)

        reset_min = u["reset_in_minutes"]
        reset_str = f"{reset_min:.0f}분 후" if reset_min < 60 else f"{reset_min / 60:.1f}시간 후"
        manual_tag = " *(수동설정)*" if u.get("is_manual_reset") else ""

        return (
            f"📊 *Claude Code 사용량*\n"
            f"🔢 출력 토큰: {u['output']:,}\n"
            f"📡 API 호출: {u['api_calls']}회\n"
            f"💾 캐시 읽기: {u['cache_read']:,}\n"
            f"🔄 리셋까지: *{reset_str}*{manual_tag}\n"
            f"_리셋 시간 수동설정: '리셋 HH:MM으로 설정해줘'_"
        )

    def _set_reset_time(self, hour: int, minute: int) -> str:
        now_kst = datetime.now(KST)
        reset_kst = now_kst.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if reset_kst <= now_kst:
            reset_kst += timedelta(days=1)

        reset_utc = reset_kst.astimezone(timezone.utc)
        UsageManager().set_manual_reset(reset_utc.isoformat())

        remaining = reset_kst - now_kst
        total_min = int(remaining.total_seconds() / 60)
        h, m = divmod(total_min, 60)
        time_str = f"{h}시간 {m}분" if h else f"{m}분"
        return (
            f"✅ 리셋 시간을 *{hour:02d}:{minute:02d} KST*로 설정했습니다.\n"
            f"약 *{time_str} 후* 리셋 — 1시간 남으면 백로그 자동 처리 시작."
        )
