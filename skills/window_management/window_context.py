"""
Active Window & Foreground Application Context
Uses Windows Win32 APIs via ctypes to inspect the user's current focused application,
window title, and capture targeted screenshots of the active window for situational awareness.
"""

from __future__ import annotations

import ctypes
import logging
import os
import re
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

user32 = ctypes.windll.user32 if sys.platform == "win32" else None
kernel32 = ctypes.windll.kernel32 if sys.platform == "win32" else None


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


def get_foreground_window_info() -> Dict[str, Any]:
    """
    Returns metadata about the currently active foreground window:
    - title: Window title string
    - class_name: Executable or window class name
    - pid: Process ID
    - hwnd: Window handle
    - rect: (x, y, w, h)
    - bbox: (left, top, right, bottom)
    """
    if not user32:
        return {"title": "Desktop Environment", "class_name": "unknown", "pid": 0, "hwnd": 0, "rect": (0, 0, 0, 0)}

    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return {"title": "Desktop", "class_name": "Progman", "pid": 0, "hwnd": 0, "rect": (0, 0, 0, 0)}

        length = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if length > 0:
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value.strip()

        class_buff = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buff, 256)
        class_name = class_buff.value.strip()

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = max(0, rect.right - rect.left)
        h = max(0, rect.bottom - rect.top)

        return {
            "title": title or "Untitled Window",
            "class_name": class_name,
            "pid": pid.value,
            "hwnd": hwnd,
            "rect": (rect.left, rect.top, w, h),
            "bbox": (rect.left, rect.top, rect.right, rect.bottom),
        }
    except Exception as exc:
        return {"title": "Error inspecting window", "class_name": "error", "error": str(exc), "rect": (0, 0, 0, 0)}


def capture_active_window_screenshot(output_path: Optional[str] = None) -> Optional[str]:
    """
    Captures a screenshot of the current foreground window.
    Saves to output_path or returns path in data/screenshots/.
    """
    info = get_foreground_window_info()
    bbox = info.get("bbox")

    try:
        from PIL import ImageGrab
        if not output_path:
            from core.semantic_file_naming import get_semantic_file_naming_service
            project_root = Path(__file__).resolve().parent.parent.parent
            out_dir = project_root / "data" / "screenshots"
            out_dir.mkdir(parents=True, exist_ok=True)
            win_title = info.get("title", "")
            desc = f"screenshot {win_title}" if win_title and win_title not in ("Desktop", "Untitled Window", "Desktop Environment") else "active_window_screenshot"
            namer = get_semantic_file_naming_service()
            output_path, _ = namer.resolve_output_path(
                task_description=desc,
                artifact_type="image",
                extension=".jpg",
                output_directory=out_dir,
            )

        rect = info.get("rect", (0, 0, 0, 0))
        if not bbox or rect[2] < 10 or rect[3] < 10:
            img = ImageGrab.grab()
        else:
            img = ImageGrab.grab(bbox=bbox)

        img.save(output_path, format="JPEG", quality=85)
        return output_path
    except Exception as exc:
        logger.warning(f"Active window screenshot failed: {exc}")
        return None


def minimize_active_window() -> bool:
    """Minimizes the currently focused foreground window."""
    if not user32:
        return False
    hwnd = user32.GetForegroundWindow()
    if hwnd:
        user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
        return True
    return False


def restore_active_window(hwnd: Optional[int] = None) -> bool:
    """Restores the active or specified window."""
    if not user32:
        return False
    target = hwnd or user32.GetForegroundWindow()
    if target:
        user32.ShowWindow(target, 9)  # SW_RESTORE
        return True
    return False


def _ocr_image(path: str) -> Optional[str]:
    """OCR a screenshot via pytesseract; returns text or None if unavailable.

    Degrades honestly: pytesseract/tesseract may not be installed, in which
    case the caller relies on the VLM path (primary) instead.
    """
    try:
        import pytesseract
        from PIL import Image
        with Image.open(path) as img:
            text = pytesseract.image_to_string(img)
        return (text or "").strip() or None
    except Exception as exc:
        logger.debug(f"[SCREEN_EVIDENCE] OCR unavailable: {exc}")
        return None


def capture_screen_evidence(scope: str = "window") -> Dict[str, Any]:
    """Capture the minimum evidence needed to explain the current visual context.

    Reuses the existing foreground-window capture; returns screenshot path,
    window metadata, best-effort OCR text, and a timestamp. Never raises —
    each evidence piece degrades to None on failure so a partial capture is
    still usable.

    scope: 'window' -> foreground window (default); 'screen' -> full desktop
    (for overlapping windows / media).
    """
    from datetime import datetime

    info = get_foreground_window_info() or {}
    path: Optional[str] = None

    if scope == "screen":
        try:
            from PIL import ImageGrab
            project_root = Path(__file__).resolve().parent.parent.parent
            out_dir = project_root / "data" / "screenshots"
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            out_path = str(out_dir / f"screen_evidence_{ts}.jpg")
            ImageGrab.grab().save(out_path, format="JPEG", quality=85)
            path = out_path
        except Exception as exc:
            logger.warning(f"[SCREEN_EVIDENCE] Full-screen capture failed: {exc}")
            path = None
        if not path:
            path = capture_active_window_screenshot()
    else:
        path = capture_active_window_screenshot()

    ocr_text = _ocr_image(path) if path else None
    return {
        "screenshot_path": path,
        "window_info": info,
        "ocr_text": ocr_text,
        "scope": scope,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "has_visual": bool(path),
    }


# --------------------------------------------------------------------------- #
# Media evidence (video the user is actually watching)
# --------------------------------------------------------------------------- #

_BROWSER_SUFFIX_RE = re.compile(
    r"\s*-\s*(?:YouTube|Brave|Chrome|Microsoft\s+Edge|Firefox|Google\s+Chrome|"
    r"Opera|Vivaldi|Arc)\s*$",
    re.IGNORECASE,
)
_NOTIFY_COUNT_RE = re.compile(r"^\(\d+\)\s*")

# Titles that identify a site but NOT a specific video. Searching for these
# would resolve an arbitrary clip and present its transcript as if it were what
# the user is watching -- a fabricated observation, so they are refused.
_GENERIC_MEDIA_TITLES = {
    "youtube", "youtube - video", "youtube video", "video", "home", "shorts",
    "youtube shorts", "youtube music", "youtube studio", "subscriptions",
    "watch history", "trending", "browse",
}


def _detect_media_source(window_info: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort identification of the media in the foreground window.

    Uses only the window title (metadata Friday can already read). It never
    claims access to hidden playback state, audio, or a site it cannot reach.
    """
    title = (window_info.get("title") or "").strip()
    low = title.lower()
    result: Dict[str, Any] = {
        "title": title,
        "is_browser": any(b in low for b in (
            "youtube", "brave", "chrome", "edge", "firefox", "opera", "browser",
        )),
        "looks_like_video": False,
        "video_title": None,
        "direct_video_id": None,
    }
    if not title:
        return result

    try:
        from modules.music.youtube_transcript import extract_video_id
        direct = extract_video_id(title)
        if direct:
            result["direct_video_id"] = direct
            result["looks_like_video"] = True
            return result
    except Exception as exc:
        logger.debug(f"[MEDIA_EVIDENCE] direct id extraction failed: {exc}")

    if "youtube" in low:
        result["looks_like_video"] = True
        # Titles stack suffixes ("Title - Artist - YouTube - Brave"); strip them
        # all so the residual text is the searchable video title.
        cleaned = title
        for _ in range(3):
            stripped = _BROWSER_SUFFIX_RE.sub("", cleaned).strip()
            stripped = _NOTIFY_COUNT_RE.sub("", stripped).strip()
            if not stripped or stripped == cleaned:
                break
            cleaned = stripped
        result["video_title"] = None if cleaned.lower().strip(" .-|") in _GENERIC_MEDIA_TITLES \
            or len(cleaned.strip()) < 4 else cleaned
    return result


def _short_error(err: Optional[str]) -> str:
    """Condense a provider exception into a one-line, user-presentable reason.

    Raw library errors (e.g. youtube-transcript-api IP-block reports) can run to
    several paragraphs of README text; embedding that verbatim would swamp the
    prompt and the spoken/UI answer.
    """
    if not err:
        return "unknown error"
    e = " ".join(str(err).split())
    low = e.lower()
    if "blocking requests" in low or "ipblocked" in low or "requestblocked" in low:
        return "YouTube is currently blocking transcript requests from this network."
    if "no transcripts" in low or "transcripts_disabled" in low or "no captions" in low:
        return "This video has no captions or transcript available."
    return e[:180] + ("..." if len(e) > 180 else "")


def capture_media_evidence(window_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Gather genuine evidence about the media the user is watching.

    Evidence, strongest first:
      1. timestamped captions/transcript (YouTube) -- real, time-addressable
         understanding of what is being said/explained;
      2. a resolved source URL / video id;
      3. window metadata (title / application);
      4. nothing visual here on purpose -- the caller's frame screenshot is
         explicitly NOT treated as equivalent to understanding the video.

    Never raises. Records honest ``limitations`` when the source cannot be
    accessed (no captions, unsupported site, resolution or network failure), so
    the caller can state the gap instead of fabricating content.
    """
    from datetime import datetime

    info = dict(window_info or get_foreground_window_info() or {})
    source = _detect_media_source(info)
    limitations: list = []
    segments: list = []
    transcript = ""
    video_id = source.get("direct_video_id")
    source_url = None
    candidates: list = []

    if not video_id and source.get("video_title"):
        try:
            from modules.music.music_controller import get_controller
            from modules.music.youtube_transcript import extract_video_id
            for item in (get_controller().get_songs(source["video_title"]) or []):
                candidate = extract_video_id(str(item))
                if candidate and candidate not in candidates:
                    candidates.append(candidate)
                if len(candidates) >= 5:
                    break
        except Exception as exc:
            logger.debug(f"[MEDIA_EVIDENCE] video resolution failed: {exc}")

    direct_id = source.get("direct_video_id")
    if direct_id and direct_id not in candidates:
        candidates.insert(0, direct_id)

    if candidates:
        from modules.music.youtube_transcript import get_video_transcript
        last_error = None
        for cand in candidates:
            try:
                res = get_video_transcript(cand) or {}
            except Exception as exc:
                logger.debug(f"[MEDIA_EVIDENCE] transcript error for {cand}: {exc}")
                last_error = str(exc)
                continue
            if res.get("success") and res.get("transcript"):
                video_id = cand
                source_url = f"https://www.youtube.com/watch?v={cand}"
                transcript = res.get("transcript") or ""
                segments = res.get("segments") or []
                last_error = None
                break
            last_error = res.get("error") or (
                "no captions available" if res.get("success") else "unknown error"
            )
        if not transcript:
            # Nothing verified: do NOT name a source we could not actually read.
            video_id, source_url = (direct_id, None) if direct_id else (None, None)
            if direct_id:
                source_url = f"https://www.youtube.com/watch?v={direct_id}"
            limitations.append(_short_error(last_error))
    elif not limitations:
        if source.get("is_browser"):
            limitations.append(
                "I can see a browser/media window but can't identify a specific "
                "video or source in it, so I have no captions or transcript to "
                "work from."
            )
        else:
            limitations.append(
                "I can't reach this source's captions, transcript, or audio, so I can "
                "only describe what is visibly on screen -- not everything being said."
            )

    return {
        "kind": "media",
        "window_info": info,
        "source_title": source.get("video_title") or info.get("title"),
        "is_browser_media": bool(source.get("is_browser")),
        "video_id": video_id,
        "source_url": source_url,
        "segments": segments,
        "segment_count": len(segments),
        "transcript": transcript,
        "has_transcript": bool(transcript),
        # Identity used to detect an app/media switch on follow-up questions.
        # Keyed by the WINDOW TITLE first: the same window must produce the same
        # key whether the turn was answered from captions (media) or from the
        # frame (screen), otherwise a follow-up looks like a source switch and
        # continuity is lost. video_id is only a fallback.
        "source_key": (info.get("title") or "").strip() or video_id or None,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "limitations": limitations,
    }

