"""
YouTube agent — detects YouTube URL, summarizes via Gemini, saves to Obsidian.
"""
import asyncio
import logging
import re

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r'https?://(?:www\.)?(?:youtube\.com|youtu\.be)/\S+')


class YouTubeAgent:
    async def handle(self, intent) -> str:
        msg = intent.raw_message
        url_match = _URL_RE.search(msg)
        if not url_match:
            return "⚠️ YouTube URL을 포함해 주세요.\n예: `https://youtu.be/xxxxx 요약해줘`"

        url = url_match.group().rstrip(".,)")
        chat_id = getattr(intent, "chat_id", 0)

        asyncio.create_task(self._bg_summarize(url, chat_id))
        return "📺 YouTube 영상 요약을 시작합니다. 자막 길이에 따라 30초~1분 소요됩니다."

    async def _bg_summarize(self, url: str, chat_id: int):
        from agents.youtube.youtube_client import fetch_and_summarize
        from agents.paper.obsidian_client import ObsidianClient
        from systems.telegram_sender import TelegramSender

        sender = TelegramSender()
        try:
            title, summary = await asyncio.to_thread(fetch_and_summarize, url)

            obs = ObsidianClient()
            path = await asyncio.to_thread(obs.add_note, summary, title, "YouTube")
            rel = path.relative_to(obs.vault_path)

            if chat_id:
                await sender.send_plain(chat_id, f"✅ 요약 완료: {title}\n📝 저장: {rel}")
                await sender.send_chunks(chat_id, summary, chunk_size=3800)
        except Exception as e:
            logger.error(f"YouTubeAgent error: {e}", exc_info=True)
            if chat_id:
                await sender.send_plain(chat_id, f"⚠️ YouTube 요약 실패: {e}")
