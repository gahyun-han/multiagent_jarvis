"""
Usage manager — tracks Claude token usage within a rolling 5-hour window.
Detects when the window resets to ~0%, notifies via Telegram, then drains backlog.
"""
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

USAGE_PATH = Path(__file__).resolve().parents[1] / "data" / "token_usage.json"
LOG_PATH = Path(__file__).resolve().parents[1] / "data" / "execution_log.json"

WINDOW_HOURS = 5
DEFAULT_BUDGET = 100_000
RESET_COOLDOWN_HOURS = 4.5       # 활성 모드 드레인 중복 방지 (동일 윈도우 내 1회)
IDLE_DRAIN_COOLDOWN_MINS = 15    # 대기 모드 드레인 재실행 방지 (실패/지연 대비)


class UsageManager:
    def __init__(self):
        self._ensure_files()

    def has_budget(self) -> bool:
        usage = self._load_usage()
        self._evict_old(usage)
        used = sum(e["tokens"] for e in usage["window"])
        budget = usage.get("budget", DEFAULT_BUDGET)
        return used < budget * 0.95

    def record_usage(self, agent: str, tokens_used: int):
        usage = self._load_usage()
        self._evict_old(usage)
        usage["window"].append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "tokens": tokens_used,
        })
        self._save_usage(usage)
        self._append_log(agent, tokens_used)

    def get_status_summary(self) -> str:
        """Returns real Claude Code usage read from session files."""
        try:
            from systems.claude_code_usage import format_usage_message
            usage = self._load_usage()
            output_limit = usage.get("output_token_limit", 88_000)
            return format_usage_message(output_limit, manual_reset_at_ms=self._load_manual_reset_ms(usage))
        except Exception as e:
            logger.warning(f"claude_code_usage unavailable, falling back: {e}")
            usage = self._load_usage()
            self._evict_old(usage)
            used = sum(e["tokens"] for e in usage["window"])
            budget = usage.get("budget", DEFAULT_BUDGET)
            pct = used / budget * 100
            remaining = budget - used
            bar_filled = int(pct / 10)
            bar = "█" * bar_filled + "░" * (10 - bar_filled)
            return (
                f"📊 *Claude 토큰 사용 현황 (5h 윈도우)*\n"
                f"`[{bar}]` {pct:.1f}%\n"
                f"사용: {used:,} / {budget:,} 토큰\n"
                f"잔여: {remaining:,} 토큰"
            )

    async def check_reset_and_drain(self, chat_id: int):
        """
        [대기 모드] api_calls == 0 (세션 없음 → reset_in_min ≈ 300)
          - 백로그 0건: 아무것도 안 함 (타이머 자동 연장)
          - 백로그 ≥ 1건: 새 5h 윈도우 시작 + 드레인 + Telegram 알림

        [활성 모드] api_calls > 0 (실제 세션 존재)
          - reset > 60분 (앞선 4시간): 스킵 — 수동 즉시 요청 용량 확보
          - reset ≤ 60분 (마지막 1시간):
              백로그 있음 → 드레인 + 알림
              백로그 없음 → 쿨다운 기록, 알림 없음 (정상 리셋 완료)
        """
        usage = self._load_usage()

        try:
            import pytz
            from systems.claude_code_usage import get_usage_summary
            from agents.inbox_trage.queue_writer import QueueWriter
            from systems.telegram_sender import TelegramSender

            output_limit = usage.get("output_token_limit", 88_000)
            real = get_usage_summary(output_limit, manual_reset_at_ms=self._load_manual_reset_ms(usage))
            reset_in_min = real["reset_in_minutes"]
            output_pct  = real["output_pct"]
            api_calls   = real.get("api_calls", 0)
            is_idle     = (api_calls == 0)

            logger.debug(
                f"Usage check: idle={is_idle} reset_in={reset_in_min:.1f}m "
                f"pct={output_pct:.1f}% calls={api_calls}"
            )

            # ── 대기 모드 ────────────────────────────────────────────────────
            if is_idle:
                pending = QueueWriter().get_pending(limit=50)
                if not pending:
                    logger.debug("Idle, no backlog — timer drifting")
                    return
                if not self._idle_drain_cooldown_passed(usage):
                    logger.debug("Idle drain cooldown active — skipping")
                    return

                now_utc = datetime.now(timezone.utc)
                kst = pytz.timezone("Asia/Seoul")
                reset_str = (now_utc + timedelta(hours=WINDOW_HOURS)).astimezone(kst).strftime("%H:%M")
                usage["last_idle_drain_at"] = now_utc.isoformat()
                self._save_usage(usage)

                logger.info(f"Idle→Active: starting new 5h window (backlog={len(pending)}, reset≈{reset_str})")
                await TelegramSender().send(
                    chat_id,
                    f"⚡ 대기 중인 백로그 {len(pending)}건으로 새 5시간 윈도우를 시작합니다.\n"
                    f"🔄 리셋 예정: {reset_str}",
                )
                await self._drain_backlog(chat_id)
                return

            # ── 활성 모드 ────────────────────────────────────────────────────
            if reset_in_min > 60:
                logger.debug(f"Active, {reset_in_min:.0f}m left — skip (reserve capacity)")
                return

            if not self._reset_cooldown_passed(usage):
                logger.debug("Active cooldown active — skipping")
                return

            # 마지막 1시간: 잔여 용량 소진 구간
            pending = QueueWriter().get_pending(limit=50)
            usage["last_reset_notified_at"] = datetime.now(timezone.utc).isoformat()
            self._save_usage(usage)

            if pending:
                logger.info(f"Active last hour: draining (reset={reset_in_min:.0f}m, backlog={len(pending)})")
                await self._notify_and_drain(chat_id, reset_in_min, output_pct, output_limit)
            else:
                logger.info(f"Active last hour: silent cycle end (reset={reset_in_min:.0f}m)")

        except Exception as e:
            logger.warning(f"Usage check failed: {e}")

    async def _notify_and_drain(self, chat_id: int, reset_in_min: float, pct: float, budget: int):
        from systems.telegram_sender import TelegramSender
        from agents.inbox_trage.queue_writer import QueueWriter

        sender = TelegramSender()
        queue = QueueWriter()
        pending = queue.get_pending(limit=50)
        pending_count = len(pending)

        reset_str = f"{reset_in_min:.0f}분"
        msg = (
            f"⚡ *백로그 실행 시작*\n"
            f"사용률 {pct:.1f}% — 리셋까지 {reset_str}\n"
        )
        if pending_count > 0:
            msg += f"📋 대기 작업 {pending_count}개 순차 실행"
        else:
            msg += "📋 대기 중인 백로그 없음"

        await sender.send(chat_id, msg)

        if pending_count > 0:
            await self._drain_backlog(chat_id)

    async def _drain_backlog(self, chat_id: int):
        import asyncio
        from agents.inbox_trage.queue_writer import QueueWriter
        from systems.telegram_sender import TelegramSender

        queue = QueueWriter()
        pending = queue.get_pending(limit=2)
        if not pending:
            return
        sender = TelegramSender()
        for item in pending:
            if self.has_budget():
                asyncio.create_task(self._process_backlog_item(item, chat_id, queue, sender))
            else:
                logger.info("Budget exhausted mid-cycle, stopping backlog drain")
                break

    def trigger_backlog_if_ready(self, chat_id: int):
        """Legacy sync entry point kept for compatibility."""
        if not self.has_budget():
            return
        from agents.inbox_trage.queue_writer import QueueWriter
        import asyncio
        from systems.telegram_sender import TelegramSender
        queue = QueueWriter()
        pending = queue.get_pending(limit=2)
        if not pending:
            return
        sender = TelegramSender()
        for item in pending:
            if self.has_budget():
                asyncio.create_task(self._process_backlog_item(item, chat_id, queue, sender))
            else:
                logger.info("Budget exhausted mid-cycle, stopping backlog drain")

    async def _process_backlog_item(self, item: dict, chat_id: int, queue, sender):
        from orchestrator.intent_classifier import Intent
        from orchestrator.router import Router
        intent = Intent(
            domain=item["domain"],
            urgency="immediate",
            confidence=1.0,
            summary=item["summary"],
            raw_message=item["message"],
        )
        router = Router()
        await router._dispatch_immediate(intent, chat_id)
        queue.mark_done(item["id"])

    def set_manual_reset(self, reset_at_iso: str):
        """Store a user-specified reset time (ISO string, UTC)."""
        usage = self._load_usage()
        usage["manual_reset_at"] = reset_at_iso
        self._save_usage(usage)

    def _load_manual_reset_ms(self, usage: dict | None = None) -> int | None:
        if usage is None:
            usage = self._load_usage()
        raw = usage.get("manual_reset_at")
        if not raw:
            return None
        try:
            ts = datetime.fromisoformat(raw)
            ms = int(ts.timestamp() * 1000)
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            return ms if ms > now_ms else None
        except Exception:
            return None

    def _reset_cooldown_passed(self, usage: dict) -> bool:
        last = usage.get("last_reset_notified_at")
        if not last:
            return True
        elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(last)
        return elapsed.total_seconds() > RESET_COOLDOWN_HOURS * 3600

    def _idle_drain_cooldown_passed(self, usage: dict) -> bool:
        last = usage.get("last_idle_drain_at")
        if not last:
            return True
        elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(last)
        return elapsed.total_seconds() > IDLE_DRAIN_COOLDOWN_MINS * 60

    def _evict_old(self, usage: dict):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)
        usage["window"] = [
            e for e in usage["window"]
            if datetime.fromisoformat(e["ts"]) > cutoff
        ]

    def _load_usage(self) -> dict:
        if not USAGE_PATH.exists():
            return {"budget": DEFAULT_BUDGET, "window": []}
        try:
            return json.loads(USAGE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {"budget": DEFAULT_BUDGET, "window": []}

    def _save_usage(self, usage: dict):
        USAGE_PATH.write_text(json.dumps(usage, ensure_ascii=False, indent=2), encoding="utf-8")

    def _append_log(self, agent: str, tokens: int):
        try:
            log = []
            if LOG_PATH.exists():
                log = json.loads(LOG_PATH.read_text(encoding="utf-8"))
            log.append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "agent": agent,
                "tokens": tokens,
            })
            log = log[-1000:]
            LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Log append error: {e}")

    def _ensure_files(self):
        USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not USAGE_PATH.exists():
            self._save_usage({"budget": DEFAULT_BUDGET, "window": []})
