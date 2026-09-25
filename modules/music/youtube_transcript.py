"""
YouTube Transcript & Video Summarizer for Nova Smart Assistant.
Extracts subtitles/transcripts and generates concise summaries with key takeaways.
"""

import re
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def extract_video_id(url_or_text: str) -> Optional[str]:
    """
    Extract 11-character YouTube video ID from various URL patterns or text.
    """
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'(?:embed\/)([0-9A-Za-z_-]{11})',
        r'(?:youtu\.be\/)([0-9A-Za-z_-]{11})',
        r'^([0-9A-Za-z_-]{11})$'
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_text)
        if match:
            return match.group(1)
    return None


def get_video_transcript(video_id: str) -> Dict[str, Any]:
    """
    Fetch subtitle text for a given YouTube video ID.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        
        # Try fetching English or auto-generated transcripts
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)
        
        # Attempt to find manual English, then generated English, then first available
        try:
            transcript = transcript_list.find_transcript(['en', 'en-US', 'en-GB'])
        except Exception:
            transcript = transcript_list.find_generated_transcript(['en', 'en-US', 'en-GB'])
            
        data = transcript.fetch()
        text_list = []
        for entry in data:
            if hasattr(entry, 'text'):
                text_list.append(str(entry.text))
            elif isinstance(entry, dict) and 'text' in entry:
                text_list.append(str(entry['text']))
        full_text = " ".join(text_list)
        
        return {
            "success": True,
            "video_id": video_id,
            "transcript": full_text,
            "char_count": len(full_text)
        }
    except Exception as e:
        logger.warning(f"[YOUTUBE] Failed to get transcript for {video_id}: {e}")
        return {
            "success": False,
            "video_id": video_id,
            "transcript": "",
            "error": str(e)
        }


def summarize_youtube_video(url_or_query: str) -> Dict[str, Any]:
    """
    Extract transcript for a YouTube video and generate a concise AI summary.
    """
    video_id = extract_video_id(url_or_query)
    
    if not video_id:
        # If user passed a query instead of URL, search for the video first
        try:
            from modules.music.music_controller import get_controller
            ctrl = get_controller()
            songs = ctrl.get_songs(url_or_query)
            if songs:
                first_url = songs[0]
                video_id = extract_video_id(first_url)
        except Exception as e:
            logger.error(f"[YOUTUBE] Video search failed: {e}")

    if not video_id:
        return {
            "success": False,
            "message": "Could not identify a valid YouTube video to summarize."
        }

    trans_res = get_video_transcript(video_id)
    if not trans_res["success"] or not trans_res["transcript"]:
        return {
            "success": False,
            "video_id": video_id,
            "message": f"Could not retrieve captions/transcript for this video ({trans_res.get('error', 'No captions')})."
        }

    transcript_text = trans_res["transcript"]
    # Limit transcript length to fit prompt context comfortably (first ~8000 chars)
    truncated_transcript = transcript_text[:8000]

    # Summarize with LLMEngine
    summary = None
    try:
        from core.llm_engine import LLMEngine
        engine = LLMEngine()
        prompt = (
            f"Here is the transcript of a YouTube video:\n\n{truncated_transcript}\n\n"
            "Please provide a clear, concise summary in 3-4 bullet points capturing the main ideas "
            "and key takeaways of the video."
        )
        summary = engine.generate_response(prompt)
    except Exception as e:
        logger.warning(f"[YOUTUBE] LLM summarization error: {e}")

    if not summary:
        # Fallback heuristic summary
        sentences = [s.strip() for s in transcript_text.split('.') if len(s.strip()) > 30]
        summary = "• " + "\n• ".join(sentences[:3]) + "."

    return {
        "success": True,
        "video_id": video_id,
        "video_url": f"https://www.youtube.com/watch?v={video_id}",
        "summary": summary,
        "message": f"Here is the summary of the video:\n\n{summary}"
    }
