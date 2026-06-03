"""
Scheduler — runs periodic tasks:
  - Every 3 min (all day): check backlog trigger condition
    Trigger: 리셋까지 ≤ 60분 → 백로그 실행 + Telegram 보고
  - Daily 08:00: send calendar briefing
"""
import os
import asyncio
import logging
import pytz
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

CHAT_ID = int(os.getenv("ALLOWED_TELEGRAM_USER_IDS", "0").split(",")[0])
KST = pytz.timezone("Asia/Seoul")


async def check_backlog():
    """Detect usage reset and drain backlog; notify on reset."""
    from systems.usage_manager import UsageManager
    if not CHAT_ID:
        return
    mgr = UsageManager()
    await mgr.check_reset_and_drain(CHAT_ID)
    logger.info("Backlog check complete")


async def daily_briefing():
    from agents.calendar.calendar_agent import CalendarAgent
    agent = CalendarAgent()
    if CHAT_ID:
        await agent.daily_briefing(CHAT_ID)
        logger.info("Daily briefing sent")


async def main():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler(timezone=KST)

    # Every 3 min: check trigger condition (reset ≤ 60min AND usage < 50%)
    scheduler.add_job(
        check_backlog, "interval", minutes=3,
        id="backlog_check",
    )
    # Daily briefing at 08:00 KST
    scheduler.add_job(
        daily_briefing, "cron",
        hour=8, minute=0,
        id="daily_briefing",
    )

    scheduler.start()
    logger.info("Jarvis scheduler started — trigger: reset≤60min AND usage<50%")
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
