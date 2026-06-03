"""
One-shot test: read real Claude Code usage and send to Telegram.
Run: python3 test_usage_telegram.py
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

async def main():
    from systems.claude_code_usage import format_usage_message, get_usage_summary
    from systems.telegram_sender import TelegramSender

    chat_id = int(os.getenv("ALLOWED_TELEGRAM_USER_IDS", "0").split(",")[0])
    sender = TelegramSender()

    u = get_usage_summary()
    msg = format_usage_message()

    # Append note about limit calibration
    msg += (
        "\n\n⚙️ _출력 토큰 한도는 기본값 88,000으로 설정됨_\n"
        "_실제 한도와 다르면 알려주세요 (Max 구독 기준으로 조정해드릴게요)_"
    )

    print("Sending to Telegram...")
    print(msg)
    ok = await sender.send(chat_id, msg)
    print("Sent:", ok)

if __name__ == "__main__":
    asyncio.run(main())
