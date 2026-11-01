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
        segments = []
        for entry in data:
            if hasattr(entry, "text"):
                txt = str(entry.text)
                start = getattr(entry, "start", None)
                dur = getattr(entry, "duration", None)
            elif isinstance(entry, dict) and "text" in entry:
                txt = str(entry["text"])
                start = entry.get("start")
                dur = entry.get("duration")
            else:
                continue
            text_list.append(txt)
            segments.append({
                "text": txt,
                "start": float(start) if start is not None else None,
                "duration": float(dur) if dur is not None else None,
            })
        full_text = " ".join(text_list)
        
        return {
            "success": True,
            "video_id": video_id,
            "transcript": full_text,
            # Timestamped caption cues -- the real, time-addressable media
            # evidence. `transcript` above is a flat string; these preserve each
            # cue's `start`, so a user can ask about a specific section.
            "segments": segments,
            "segment_count": len(segments),
            "duration_seconds": (
                round((segments[-1]["start"] + (segments[-1]["duration"] or 0.0)), 1)
                if segments and segments[-1].get("start") is not None else None
            ),
            "char_count": len(full_text)
        }
    except Exception as e:
        logger.warning(f"[YOUTUBE] Failed to get transcript for {video_id}: {e}")
        return {
            "success": False,
            "video_id": video_id,
            "transcript": "",
            "segments": [],
            "segment_count": 0,
            "error": str(e)
        }


def format_timestamp(seconds: Optional[float]) -> str:
    """Render seconds as ``H:MM:SS`` / ``M:SS`` for a readable timeline."""
    try:
        total = int(max(0, float(seconds or 0)))
    except (TypeError, ValueError):
        return "0:00"
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def segments_to_timeline(
    segments: Optional[list],
    start: Optional[float] = None,
    end: Optional[float] = None,
    max_chars: int = 6000,
) -> str:
    """Render caption cues as ``[M:SS] text`` lines.

    ``start``/``end`` window the timeline to a section the user asked about
    ("what happens at 1:23"). Returns "" when no timestamped cues exist, so the
    caller can honestly report that no transcript evidence is available rather
    than inventing one.
    """
    if not segments:
        return ""
    lines, used = [], 0
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        seg_start = seg.get("start")
        if seg_start is None:
            continue
        if start is not None and seg_start < float(start) - 0.5:
            continue
        if end is not None and seg_start > float(end) + 0.5:
            break
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        line = f"[{format_timestamp(seg_start)}] {text}"
        if used + len(line) + 1 > max_chars:
            lines.append("... (timeline truncated)")
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


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
        from extensions.llm_engine import LLMEngine
        engine = LLMEngine()
        prompt = (
            f"Here is the transcript of a YouTube video:\n\n{truncated_transcript}\n\n"
            "Please provide a clear, concise summary in 3-4 bullet points capturing the main ideas "
            "and key takeaways of the video."
        )
        summary = engine.get_completion(prompt)
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
