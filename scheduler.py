"""
Scheduler — runs periodic tasks:
  - Every 5 min: check token budget and drain backlog
  - Daily 08:00: send calendar briefing
"""
import os
import asyncio
import logging
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

CHAT_ID = int(os.getenv("ALLOWED_TELEGRAM_USER_IDS", "0").split(",")[0])


async def check_backlog():
    from systems.usage_manager import UsageManager
    mgr = UsageManager()
    if mgr.has_budget() and CHAT_ID:
        mgr.trigger_backlog_if_ready(CHAT_ID)
        logger.info("Backlog check complete")


async def daily_briefing():
    from agents.calendar.calendar_agent import CalendarAgent
    agent = CalendarAgent()
    if CHAT_ID:
        await agent.daily_briefing(CHAT_ID)
        logger.info("Daily briefing sent")


async def main():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_backlog, "interval", minutes=5, id="backlog_check")
    scheduler.add_job(daily_briefing, "cron", hour=8, minute=0, id="daily_briefing")
    scheduler.start()
    logger.info("Jarvis scheduler started")
    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
