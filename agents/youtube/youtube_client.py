"""
YouTube client — transcript fetch + Gemini summarization.
"""
import os
import re
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_VIDEO_ID_RE = re.compile(
    r'(?:youtu\.be/|youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/))([a-zA-Z0-9_-]{11})'
)

_SUMMARY_PROMPT = """다음은 YouTube 영상의 자막입니다. 핵심 내용을 한국어로 체계적으로 정리해주세요.

## 정리 형식
**개요** (2-3줄 요약)

**주요 내용**
- 핵심 포인트들을 bullet point로

**핵심 인사이트**
- 중요한 인사이트나 결론

---
자막:
{transcript}
"""


def extract_video_id(url: str) -> str | None:
    m = _VIDEO_ID_RE.search(url)
    return m.group(1) if m else None


def fetch_transcript(video_id: str) -> str:
    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()
    for langs in [["ko"], ["en"], ["ko", "en"]]:
        try:
            fetched = api.fetch(video_id, languages=langs)
            return " ".join(s.text for s in fetched)
        except Exception:
            continue
    # 언어 무관하게 첫 번째 자막 시도
    try:
        transcript_list = api.list(video_id)
        fetched = next(iter(transcript_list)).fetch()
        return " ".join(s.text for s in fetched)
    except Exception:
        pass
    raise RuntimeError(f"자막을 가져올 수 없습니다 (video_id={video_id})")


def fetch_video_title(video_id: str) -> str:
    """oembed로 제목만 빠르게 가져오기 (API key 불필요)."""
    try:
        import urllib.request, json
        url = f"https://www.youtube.com/oembed?url=https://youtu.be/{video_id}&format=json"
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read())["title"]
    except Exception:
        return video_id


def summarize_with_gemini(transcript: str, video_url: str, title: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY가 .env에 설정되지 않았습니다.")

    from google import genai
    client = genai.Client(api_key=api_key)

    prompt = _SUMMARY_PROMPT.format(transcript=transcript[:30000])
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    summary = response.text.strip()

    return f"URL: {video_url}\n\n{summary}"


def fetch_and_summarize(url: str) -> tuple[str, str]:
    """YouTube URL → (title, summary_markdown) 반환."""
    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError(f"YouTube URL에서 video ID를 추출할 수 없습니다: {url}")

    logger.info(f"Fetching transcript for {video_id}")
    title = fetch_video_title(video_id)
    transcript = fetch_transcript(video_id)
    logger.info(f"Transcript length: {len(transcript)} chars")

    summary = summarize_with_gemini(transcript, url, title)
    return title, summary
