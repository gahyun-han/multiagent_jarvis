"""Quick test: send current Claude Code usage to Telegram."""
import asyncio, os
from dotenv import load_dotenv
load_dotenv()

async def main():
    from systems.claude_code_usage import get_usage_summary
    from systems.telegram_sender import TelegramSender

    chat_id = int(os.getenv("ALLOWED_TELEGRAM_USER_IDS", "0").split(",")[0])
    u = get_usage_summary()

    reset_min = u["reset_in_minutes"]
    reset_str = f"{reset_min:.0f}분 후" if reset_min < 60 else f"{reset_min/60:.1f}시간 후"

    msg = (
        f"📊 *Claude Code 사용량 현황*\n"
        f"_(구독: Pro · 5h 롤링 윈도우)_\n\n"
        f"🔢 출력 토큰: {u['output']:,}\n"
        f"📥 입력 토큰: {u['input']:,}\n"
        f"💾 캐시 읽기: {u['cache_read']:,}\n"
        f"📡 API 호출: {u['api_calls']}회\n\n"
        f"🔄 리셋까지: *{reset_str}*\n\n"
        f"⚠️ _Pro 플랜 토큰 한도는 Anthropic 비공개_\n"
        f"_`/usage` 화면의 % 값 알려주시면 한도 역산해드릴게요_"
    )

    ok = await TelegramSender().send(chat_id, msg)
    print("Sent:", ok)
    print(msg)

asyncio.run(main())
