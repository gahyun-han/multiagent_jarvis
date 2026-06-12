"""
매월 자동 발송 스크립트 — asset bot으로 전송.
  1) 월별 자산 리포트 (텍스트)
  2) 수입/지출 추이 그래프 (PNG)
  3) 가계부 요약 표 (PNG)
"""
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CHAT_ID = 7952029488


async def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    import os
    token = os.getenv("ASSET_BOT_TOKEN")
    if not token:
        logger.error("ASSET_BOT_TOKEN not set")
        sys.exit(1)

    from systems.telegram_sender import TelegramSender
    from agents.finance.report_generator import generate_monthly_report
    from agents.finance.chart_generator import generate_chart, generate_table_image

    sender = TelegramSender(token=token)

    # ① 월별 자산 리포트
    report = generate_monthly_report()
    ok = await sender.send(CHAT_ID, report)
    logger.info(f"Report sent: {ok}")

    # ② 수입/지출 추이 그래프
    chart = generate_chart(4)
    ok = await sender.send_photo(CHAT_ID, chart, caption="📊 최근 4개월 수입/지출 추이")
    logger.info(f"Chart sent: {ok}")

    # ③ 가계부 요약 표
    table = generate_table_image(4)
    ok = await sender.send_photo(CHAT_ID, table, caption="📋 최근 4개월 가계부 요약")
    logger.info(f"Table sent: {ok}")


if __name__ == "__main__":
    asyncio.run(main())
