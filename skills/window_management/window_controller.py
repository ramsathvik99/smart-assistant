"""
Window Management Controller
Provides conversational commands for inspecting active window context and capturing active window screenshots.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)
from .window_context import (
    get_foreground_window_info,
    capture_active_window_screenshot,
    capture_screen_evidence,
    capture_media_evidence,
    minimize_active_window,
    restore_active_window,
)


class WindowController:
    def get_active_window(self) -> dict[str, Any]:
        info = get_foreground_window_info()
        title = info.get("title", "Unknown")
        cls_name = info.get("class_name", "Unknown")
        pid = info.get("pid", 0)

        msg = f"The active window is '{title}' (Process: {cls_name}, PID: {pid})."
        return {
            "success": True,
            "status": "success",
            "info": info,
            "message": msg
        }

    def capture_screenshot(self) -> dict[str, Any]:
        path = capture_active_window_screenshot()
        if path:
            return {
                "success": True,
                "status": "success",
                "file_path": path,
                "message": f"Captured screenshot of active window and saved to {path}."
            }
        return {
            "success": False,
            "status": "error",
            "message": "Failed to capture active window screenshot."
        }

    _SCREEN_UNDERSTAND = (
        "what am i looking at", "what is on my screen", "what's on my screen",
        "what is happening", "what's happening", "what is going on", "what's going on",
        "explain this", "explain what", "explain it", "explain that", "explain the",
        "what does this mean", "why is this", "why is that", "what am i doing",
        "teach me", "i don't understand", "don't understand this", "what's wrong",
        "what is wrong", "what should i", "summarize this", "summarise this",
        "what is this", "what's this", "walk me through", "help me understand",
        "make notes", "quiz me", "revision notes",
        "video", "person explaining", "the speaker", "speaker", "what is playing",
        "in this video", "this video", "this clip", "recording", "webinar", "lecture",
        "animation", "stream",
    )

    # Section questions that reference a point in time in the current media:
    # "what happens at 1:30", "what is said after 2:00", "explain 3 minutes".
    _SECTION_TIME_RE = re.compile(
        r"\b(?:what\s+(?:happens|is\s+said|is\s+happening|comes)|explain|"
        r"tell\s+me\s+(?:what|about))\b.{0,40}?"
        r"\b(?:(?:at|around|after|before|from)\s+)?"
        r"(?:\d{1,2}:\d{2}|\d{1,2}\s*(?:minutes?|mins?))\b",
        re.IGNORECASE,
    )

    def _is_screen_understanding(self, text_low: str) -> bool:
        if any(m in text_low for m in self._SCREEN_UNDERSTAND):
            return True
        # Time-addressed section questions must reach the explain path too,
        # otherwise they silently fall through to plain window metadata.
        return bool(self._SECTION_TIME_RE.search(text_low))

    def _prior_analysis(self):
        """Last stored screen analysis from dialogue context (for follow-ups)."""
        try:
            from extensions.dialogue_state_manager import get_dialogue_manager
            from instance.config import settings
            uid = str(getattr(settings, "CURRENT_USER_ID", None) or 1)
            dm = get_dialogue_manager(uid)
            ctx = dm.current_state.session_context if (dm and dm.current_state) else {}
            return ctx.get("last_screen_analysis") if isinstance(ctx, dict) else None
        except Exception:
            return None

    def _store_analysis(self, record: dict) -> None:
        """Persist a short analysis record for contextual follow-up questions."""
        try:
            from extensions.dialogue_state_manager import get_dialogue_manager
            from instance.config import settings
            uid = str(getattr(settings, "CURRENT_USER_ID", None) or 1)
            dm = get_dialogue_manager(uid)
            if dm and dm.current_state:
                dm.current_state.session_context["last_screen_analysis"] = record
        except Exception:
            pass

    # Explicit time references, so a user can ask about a specific section:
    # "what happens at 1:23", "explain after 2:00", "what is said at 3 minutes".
    _TIME_CLOCK_RE = re.compile(r"\b(?:at|around|after|before|from)\s+(\d{1,2}):(\d{2})\b", re.IGNORECASE)
    _TIME_MIN_RE = re.compile(r"\b(?:at|around|after|before|from)\s+(\d{1,2})\s*(?:minute|minutes|min)\b", re.IGNORECASE)

    def _time_window(self, text_low: str):
        """Translate a time reference into a (start, end) evidence window.

        Returns (None, None) when no time is referenced, so the full timeline is
        used. Directional words shift the window rather than guessing a range.
        """
        seconds = None
        direction = None
        m = self._TIME_CLOCK_RE.search(text_low)
        if m:
            seconds = int(m.group(1)) * 60 + int(m.group(2))
            direction = re.search(r"\b(after|before|from)\b", m.group(0).lower())
            direction = direction.group(1) if direction else "at"
        else:
            m = self._TIME_MIN_RE.search(text_low)
            if m:
                seconds = int(m.group(1)) * 60
                direction = re.search(r"\b(after|before|from)\b", m.group(0).lower())
                direction = direction.group(1) if direction else "at"
        if seconds is None:
            return None, None
        if direction == "after" or direction == "from":
            return float(seconds), float(seconds + 120)
        if direction == "before":
            return float(max(0, seconds - 120)), float(seconds)
        return float(max(0, seconds - 20)), float(seconds + 50)

    def explain_visual(self, user_input: str) -> dict[str, Any]:
        """Explain the current visual context (screen or media) from real evidence.

        Screen: VLM primary (screenshot -> get_vision_completion), then
        OCR/metadata text fallback, then an honest limitation.

        Media: timestamped captions/transcript are the primary evidence -- a
        screenshot of a video player is explicitly NOT treated as understanding
        the video. The frame is attached only as visual context, and the answer
        falls back to transcript-only (still real) before ever settling for the
        frame alone, which is flagged as a limitation.

        Stores a short record so follow-up questions can continue without
        repeating context; the record is invalidated if the user switches to a
        different app/media source. Never fabricates an observation when
        providers fail.
        """
        text_low = user_input.lower()
        is_media = any(k in text_low for k in (
            "video", "person explaining", "speaker", "clip", "stream",
            "lecture", "playing", "webinar", "recording",
        ))
        is_followup = (
            any(k in text_low for k in (
                " that", " this", " it", "again", "more detail", "in more detail", "before",
                "previous", "earlier", "expand", "the second", "the first point",
                "mean", "why is", "why are", "happening", "happened", "teach me",
                "should i", "wrong here", "relate", "quiz me", "make notes",
            ))
            # section questions ("what happens at 1:30") continue the same thread
            or bool(self._SECTION_TIME_RE.search(text_low))
        )

        # Load prior BEFORE choosing the capture scope: a follow-up on a MEDIA
        # turn stays a media turn even when the phrasing itself has no video
        # keyword ("what happens at 1:30"), so captions/timestamps are used
        # instead of settling for the frame alone.
        prior = self._prior_analysis() if is_followup else None
        if prior and prior.get("media"):
            is_media = True

        evidence = capture_screen_evidence(scope="screen" if is_media else "window")
        info = evidence.get("window_info") or {}
        title = info.get("title", "") or ""
        app = info.get("class_name", "") or ""
        ocr = (evidence.get("ocr_text") or "").strip()

        # Genuine media evidence: captions/transcript + timestamps for a video.
        media = None
        if is_media:
            try:
                media = capture_media_evidence(info)
            except Exception as exc:
                logger.warning(f"[SCREEN] media evidence failed: {exc}")
                media = None
        media = media or {}
        limitations = list(media.get("limitations") or [])
        transcript = media.get("transcript") or ""
        segments = media.get("segments") or []
        source_key = media.get("source_key") or (title.strip() or None)

        # Continuity: drop the prior analysis only once the CURRENT window is
        # known, so a real app/media switch never replays a stale answer while
        # staying on the same window keeps the thread (both key on window title).
        if prior and prior.get("source_key") and title.strip() \
                and prior.get("source_key") != title.strip():
            logger.info("[SCREEN] source changed; ignoring stale prior analysis")
            prior = None
        if not transcript and prior and prior.get("media") and prior.get("transcript"):
            transcript = prior.get("transcript") or ""
            segments = prior.get("segments") or []

        if not evidence.get("has_visual") and not ocr and not title and not transcript:
            return {
                "success": False, "status": "error",
                "message": "I couldn't capture anything to analyze — no screen or window evidence is available right now.",
            }

        system_prompt = (
            "You are Friday, a desktop assistant explaining what is currently visible on "
            "the user's screen or in the media they are watching. Base the answer ONLY on "
            "the provided evidence (window metadata, OCR text, caption/transcript cues, "
            "and/or the attached screenshot). Clearly separate what is observable from "
            "inference; never fabricate content, dialogue, audio, off-screen events, or "
            "earlier scenes that are not in the evidence. If evidence is insufficient, say "
            "so honestly. Start with the direct answer, then add useful detail; keep it "
            "concise unless depth was asked, and match the requested shape (summary, "
            "detailed explanation, section focus, or notes)."
        )

        base_lines = [f"Question from the user: {user_input.strip()}"]
        if title:
            base_lines.append(f"Active window title: {title}")
        if app:
            base_lines.append(f"Application/class: {app}")

        # Timestamped caption evidence, windowed to any section the user named.
        timeline = ""
        if transcript:
            try:
                from modules.music.youtube_transcript import segments_to_timeline
                tw_start, tw_end = self._time_window(text_low)
                timeline = segments_to_timeline(segments, start=tw_start, end=tw_end)
            except Exception as exc:
                logger.warning(f"[SCREEN] timeline rendering failed: {exc}")
                timeline = ""
            if not timeline:
                timeline = transcript[:6000]

        if is_media:
            if timeline:
                base_lines += [
                    "",
                    "Caption/transcript cues with timestamps (real, time-addressable):",
                    timeline,
                    "Use these timestamps to locate any section the user asks about. "
                    "Never invent dialogue that is not present in these cues.",
                ]
            else:
                base_lines += [
                    "",
                    "No captions or transcript could be accessed for this media.",
                ]
                base_lines += [f"Limitation: {lim}" for lim in limitations]
                base_lines.append(
                    "State plainly that you cannot access its captions/audio and can only "
                    "describe the visible frame. Do not invent dialogue or narration."
                )

        if prior and prior.get("analysis"):
            base_lines.append(
                f"Your previous answer (for follow-up continuity): {prior['analysis']}"
            )

        prompt = "\n".join(base_lines)
        analysis = None
        source = None

        if is_media and transcript:
            # 1) Real captions + frame together when vision is available.
            if evidence.get("has_visual"):
                try:
                    from extensions.llm_engine import get_llm_engine
                    analysis = get_llm_engine().get_vision_completion(
                        prompt,
                        images=[evidence["screenshot_path"]],
                        system_prompt=system_prompt,
                        timeout=12.0,
                    )
                    if analysis and analysis.strip():
                        analysis = analysis.strip()
                        source = "vision+transcript"
                except Exception as exc:
                    logger.warning(f"[SCREEN] VLM+transcript analysis failed: {exc}")
            # 2) Transcript-only: still genuine media understanding, no vision needed.
            if not analysis:
                try:
                    from extensions.llm_engine import get_llm_engine
                    analysis = get_llm_engine().get_completion(
                        prompt, system_prompt=system_prompt, max_tokens=900,
                        timeout_budget=10.0, task_type="interactive",
                    )
                    if analysis and analysis.strip():
                        analysis = analysis.strip()
                        source = "transcript"
                except Exception as exc:
                    logger.warning(f"[SCREEN] transcript analysis failed: {exc}")
        elif evidence.get("has_visual"):
            # VLM primary for plain screen understanding.
            try:
                from extensions.llm_engine import get_llm_engine
                analysis = get_llm_engine().get_vision_completion(
                    prompt,
                    images=[evidence["screenshot_path"]],
                    system_prompt=system_prompt,
                    timeout=12.0,
                )
                if analysis and analysis.strip():
                    analysis = analysis.strip()
                    source = "vision"
            except Exception as exc:
                logger.warning(f"[SCREEN] VLM analysis failed: {exc}")

        # OCR/metadata text fallback (no vision provider, or VLM failed).
        if not analysis:
            if ocr:
                txt = "\n".join(
                    base_lines + ["", "OCR text extracted from the screen:", ocr[:4000]]
                )
            elif title or app:
                txt = "\n".join(base_lines + [
                    "",
                    "No visual analysis provider is available and no readable text was "
                    "extracted. Using only the window metadata below — do not guess about "
                    "visual details you cannot see.",
                ])
            else:
                txt = None
            if txt:
                try:
                    from extensions.llm_engine import get_llm_engine
                    analysis = get_llm_engine().get_completion(
                        txt, system_prompt=system_prompt, max_tokens=700,
                        timeout_budget=8.0, task_type="interactive",
                    )
                    if analysis and analysis.strip():
                        analysis = analysis.strip()
                        source = "ocr_metadata" if ocr else "metadata"
                except Exception as exc:
                    logger.warning(f"[SCREEN] text analysis failed: {exc}")

        if not analysis:
            # Honest limitation — never fabricate an observation.
            if ocr:
                analysis = (
                    f"I can't run visual analysis right now, but here's the text I read "
                    f"on screen: {ocr[:600]}"
                )
                source = "ocr_only"
            elif title:
                extra = (" " + " ".join(limitations[:2])) if (is_media and limitations) else ""
                analysis = (
                    f"I can't interpret the screen visually right now. The active window "
                    f"is '{title}' (Application: {app or 'unknown'}). No vision provider "
                    f"or readable text was available.{extra}"
                )
                source = "metadata_only"
            else:
                return {
                    "success": False, "status": "error",
                    "message": "I couldn't analyze the screen: no vision provider, OCR, or window metadata was available.",
                }

        # Frame-only media answers must never read as full video understanding.
        if is_media and not transcript and analysis:
            analysis = (
                f"{analysis}\n\n(I couldn't access this video's captions or audio, so the "
                f"above is based only on the visible frame — not everything being said.)"
            )

        record = {
            "question": user_input.strip(),
            "analysis": analysis,
            "source": source,
            "window_title": title,
            "source_key": source_key,
            "screenshot_path": evidence.get("screenshot_path"),
            "captured_at": evidence.get("captured_at"),
            "media": is_media,
            "has_transcript": bool(transcript),
            "transcript": transcript[:10000] if transcript else None,
            "segments": segments[:1200] if segments else None,
            "segment_count": len(segments),
            "limitations": limitations,
        }
        self._store_analysis(record)

        return {
            "success": True,
            "status": "success",
            "message": analysis,
            "analysis": analysis,
            "analysis_source": source,
            "window_info": info,
            "ocr_available": bool(ocr),
            "screenshot_path": evidence.get("screenshot_path"),
            "captured_at": evidence.get("captured_at"),
            "media_source": media.get("source_url"),
            "has_transcript": bool(transcript),
            "segment_count": len(segments),
            "limitations": limitations,
        }

    def get_active_page_title(self) -> dict[str, Any]:
        """Retrieve active page title from active browser session, foreground window, or context."""
        # 1. Check active browser session singleton
        try:
            from modules.browser.browser_controller import get_active_browser_session
            session = get_active_browser_session()
            t = session.get_title()
            if t and t.strip():
                clean_t = t.strip()
                return {
                    "success": True,
                    "status": "success",
                    "title": clean_t,
                    "message": f"The title of the page is '{clean_t}'."
                }
        except Exception:
            pass

        # 2. Check foreground window if it is a browser
        info = get_foreground_window_info()
        win_title = info.get("title", "")
        cls_name = info.get("class_name", "").lower()
        is_browser_win = any(b in cls_name or b in win_title.lower() for b in ["chrome", "edge", "firefox", "brave", "opera", "browser"])
        if win_title and is_browser_win:
            cleaned_title = re.sub(r'\s*-\s*(?:Google\s+Chrome|Microsoft\s+Edge|Mozilla\s+Firefox|Brave|Opera).*$', '', win_title, flags=re.IGNORECASE).strip()
            if cleaned_title and not cleaned_title.lower().startswith("new tab") and cleaned_title.lower() != "browser":
                return {
                    "success": True,
                    "status": "success",
                    "title": cleaned_title,
                    "message": f"The title of the page is '{cleaned_title}'."
                }

        # 3. Check ContextManager for recent browser context or URL artifact
        try:
            from extensions.context_manager import get_manager
            ctx = get_manager()
            act_ctx = ctx.get_active_context()
            last_browser = act_ctx.get("last_browser")
            if last_browser:
                return {
                    "success": True,
                    "status": "success",
                    "title": last_browser.capitalize(),
                    "message": f"The active browser tab is {last_browser.capitalize()}."
                }
            arts = ctx.get_recent_user_artifacts(artifact_type="url", limit=1)
            if arts:
                art = arts[0]
                art_name = art.get("filename") or art.get("url")
                return {
                    "success": True,
                    "status": "success",
                    "title": art_name,
                    "message": f"The active page is '{art_name}'."
                }
        except Exception:
            pass

        # 4. If no active page can be observed, ask a concise clarifying question
        return {
            "success": True,
            "status": "clarification",
            "message": "Which web page or browser tab would you like me to check?",
            "response": "Which web page or browser tab would you like me to check?"
        }

    def get_active_page_summary(self, user_input: str) -> dict[str, Any]:
        """Summarize active page or ask concise clarification if no page is observed."""
        # 1. Active browser session
        try:
            from modules.browser.browser_controller import get_active_browser_session
            session = get_active_browser_session()
            if session.current_url or session.current_title:
                t = session.get_title() or session.current_url
                return {
                    "success": True,
                    "status": "success",
                    "message": f"The active page is '{t}' ({session.current_url or 'browser session'})."
                }
        except Exception:
            pass

        # 2. Foreground browser window
        info = get_foreground_window_info()
        win_title = info.get("title", "")
        cls_name = info.get("class_name", "").lower()
        is_browser_win = any(b in cls_name or b in win_title.lower() for b in ["chrome", "edge", "firefox", "brave", "opera", "browser"])
        if win_title and is_browser_win:
            cleaned_title = re.sub(r'\s*-\s*(?:Google\s+Chrome|Microsoft\s+Edge|Mozilla\s+Firefox|Brave|Opera).*$', '', win_title, flags=re.IGNORECASE).strip()
            if cleaned_title and not cleaned_title.lower().startswith("new tab") and cleaned_title.lower() != "browser":
                return {
                    "success": True,
                    "status": "success",
                    "message": f"The active page is '{cleaned_title}' in {info.get('class_name', 'your browser')}."
                }

        # 3. ContextManager
        try:
            from extensions.context_manager import get_manager
            ctx = get_manager()
            act_ctx = ctx.get_active_context()
            last_browser = act_ctx.get("last_browser")
            if last_browser:
                return {
                    "success": True,
                    "status": "success",
                    "message": f"The currently open website is {last_browser.capitalize()}."
                }
        except Exception:
            pass

        # 4. Fallback: ask concise clarifying question
        return {
            "success": True,
            "status": "clarification",
            "message": "Which web page or browser tab would you like me to check?",
            "response": "Which web page or browser tab would you like me to check?"
        }

    def handle_command(self, user_input: str) -> dict[str, Any]:
        text_low = user_input.lower().strip()

        # Active page title / summary queries
        is_page_title = bool(re.search(r'\b(?:retrevie|retrieve|get|tell\s+me|what(?:\'s|\s+is)|show)\s+(?:the\s+)?(?:page\s+title|title\s+of\s+(?:this|the)\s+page|title\s+of\s+page)\b', text_low)) or text_low in ("page title", "what is the title", "what is the page title", "retrevie the title of the page", "retrieve the title of the page")
        if is_page_title:
            return self.get_active_page_title()

        is_page_summary = bool(re.search(r'\bwhat\s+(?:is\s+)?(?:this|the)\s+page\s+about\b', text_low))
        if is_page_summary:
            return self.get_active_page_summary(user_input)

        if "minimize" in text_low and any(w in text_low for w in ["current window", "active window", "this window"]):
            success = minimize_active_window()
            return {
                "success": success,
                "status": "minimized" if success else "error",
                "message": "Minimized the active window." if success else "Could not minimize active window."
            }

        if "restore" in text_low and any(w in text_low for w in ["current window", "active window", "this window", "window"]):
            success = restore_active_window()
            return {
                "success": success,
                "status": "restored" if success else "error",
                "message": "Restored the window." if success else "Could not restore window."
            }

        is_screenshot = (
            any(w in text_low for w in ["screenshot", "capture", "snap"]) and
            any(w in text_low for w in ["active window", "foreground window", "current window", "window screenshot", "window capture"])
        ) or any(w in text_low for w in ["capture active window", "screenshot active window", "snap active window", "take a screenshot of the active window", "take screenshot of active window"])

        if is_screenshot:
            return self.capture_screenshot()

        if self._is_screen_understanding(text_low):
            return self.explain_visual(user_input)

        return self.get_active_window()


_controller_instance: Optional[WindowController] = None


def get_window_controller() -> WindowController:
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = WindowController()
    return _controller_instance
