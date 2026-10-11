"""
Browser Environment Adapter
Specialized observer for web browsers (Chrome, Brave, Edge, Firefox, Opera, etc.).
Extracts active website, domain, page type, tab title, URL, and rich web entity states
(including deep YouTube video, channel, video_id, and playback context).
"""

from __future__ import annotations

import logging
import re
import time
import urllib.parse
from typing import Any, Dict, Optional, Tuple

from core.environment.adapters.base_adapter import BaseEnvironmentAdapter
from core.environment.models import EnvironmentState
from core.environment.ui_tree import (
    try_get_browser_cdp_info,
    try_get_browser_url,
)

logger = logging.getLogger(__name__)


class BrowserEnvironmentAdapter(BaseEnvironmentAdapter):
    """
    Adapter for web browser applications.
    Extracts deep context for YouTube, web documents, web mail, developer sites,
    and arbitrary web destinations.
    """

    name = "browser"
    app_category = "browser"

    BROWSER_NAMES = {
        "chrome", "google chrome", "brave", "brave browser", "msedge",
        "edge", "microsoft edge", "firefox", "mozilla firefox", "opera",
        "vivaldi", "arc", "chromium"
    }

    def can_handle(self, app_name: str, window_info: Dict[str, Any]) -> bool:
        clean_app = (app_name or "").lower().strip()
        cls_name = (window_info.get("class_name") or "").lower()
        title = (window_info.get("title") or "").lower()

        if any(b in clean_app for b in self.BROWSER_NAMES):
            return True
        if any(b in cls_name for b in ("chrome", "brave", "edge", "firefox", "opera")):
            return True
        if any(f" - {b}" in title for b in ("google chrome", "brave", "microsoft\u200b edge", "firefox")):
            return True
        return False

    def extract_state(self, window_info: Dict[str, Any], hierarchy_level: int = 1) -> Optional[EnvironmentState]:
        title = (window_info.get("title") or "").strip()
        cls_name = window_info.get("class_name", "")
        pid = window_info.get("pid", 0)
        hwnd = window_info.get("hwnd", 0)

        # Detect browser flavor
        browser_name = "browser"
        t_low = title.lower()
        c_low = cls_name.lower()
        if "brave" in t_low or "brave" in c_low:
            browser_name = "brave"
        elif "edge" in t_low or "msedge" in c_low:
            browser_name = "edge"
        elif "firefox" in t_low or "firefox" in c_low:
            browser_name = "firefox"
        elif "chrome" in t_low or "chrome" in c_low:
            browser_name = "chrome"
        elif "opera" in t_low or "opera" in c_low:
            browser_name = "opera"

        # Check if caller already provided rich URL or metadata in window_info
        detected_url: Optional[str] = window_info.get("url")
        source_tier = "integration"

        # Tier 1 & 2: Query CDP and UIAutomation if not already in window_info
        if not detected_url and hierarchy_level <= 2:
            try:
                # 1. CDP inspection
                cdp = try_get_browser_cdp_info(title_hint=title)
                if cdp and cdp.get("url"):
                    detected_url = cdp["url"]
                    source_tier = "api"
                elif hwnd:
                    # 2. UIAutomation / Win32 address inspection
                    detected_url = try_get_browser_url(hwnd, browser_name, title_hint=title)
                    if detected_url:
                        source_tier = "accessibility"
            except Exception as exc:
                logger.debug("[BROWSER_ADAPTER] Rich URL inspection exception: %s", exc)

        # Clean browser name suffix from title
        clean_title = title
        clean_title = re.sub(
            r'\s*-\s*(?:Google\s+Chrome|Brave|Microsoft\s+Edge|Mozilla\s+Firefox|Opera|Vivaldi|Arc)$',
            '', clean_title, flags=re.IGNORECASE
        ).strip()
        clean_title = re.sub(r'^\(\d+\)\s*', '', clean_title).strip()  # strip notification counter e.g. "(1) "

        # Parse domain from URL if available
        domain: Optional[str] = None
        if detected_url:
            try:
                parsed_u = urllib.parse.urlparse(detected_url)
                domain = parsed_u.netloc.lower()
                if domain.startswith("www."):
                    domain = domain[4:]
            except Exception:
                pass

        entities: Dict[str, Any] = {
            "browser": browser_name,
            "raw_title": title,
            "page_title": clean_title,
        }
        if detected_url:
            entities["url"] = detected_url
        if domain:
            entities["domain"] = domain

        # ── 1. YouTube Deep Context ──────────────────────────────────────────
        is_youtube = (
            "youtube" in t_low
            or (domain and "youtube.com" in domain)
            or (detected_url and "youtube.com" in detected_url.lower())
        )

        if is_youtube:
            entities["website"] = "YouTube"
            entities["platform"] = "YouTube"
            entities["domain"] = domain or "youtube.com"

            # Parse video page title
            m_yt = re.match(r'^(.*?)(?:\s*-\s*YouTube)$', clean_title, re.IGNORECASE)
            video_title_cand = m_yt.group(1).strip() if m_yt else clean_title

            # Parse video_id from URL
            video_id: Optional[str] = window_info.get("video_id")
            if not video_id and detected_url:
                m_vid = re.search(r'[?&]v=([a-zA-Z0-9_-]{11})', detected_url)
                if m_vid:
                    video_id = m_vid.group(1)
                elif "youtu.be/" in detected_url:
                    m_ytbe = re.search(r'youtu\.be/([a-zA-Z0-9_-]{11})', detected_url)
                    if m_ytbe:
                        video_id = m_ytbe.group(1)
                elif "/shorts/" in detected_url:
                    m_sh = re.search(r'/shorts/([a-zA-Z0-9_-]{11})', detected_url)
                    if m_sh:
                        video_id = m_sh.group(1)

            # Parse playback_position
            playback_position = window_info.get("playback_position")
            if not playback_position and detected_url:
                m_t = re.search(r'[?&]t=([0-9a-zA-Z]+)', detected_url)
                if m_t:
                    playback_position = m_t.group(1)

            # Playback state
            playback_state = window_info.get("playback_state")
            if not playback_state:
                if "paused" in t_low:
                    playback_state = "paused"
                elif "playing" in t_low:
                    playback_state = "playing"

            # Channel extraction
            channel = window_info.get("channel")

            if video_title_cand.lower() in ("youtube", "home", ""):
                entities["page_type"] = "home"
                entities["video_title"] = None
                entities["video_id"] = None
                entities["channel"] = channel
                entities["current_page"] = detected_url or "https://www.youtube.com/"
                entities["playback_state"] = None
                entities["playback_position"] = None
                content_ctx = f"Browsing YouTube Home in {browser_name.capitalize()}"
            elif "search" in video_title_cand.lower() or "results" in video_title_cand.lower():
                entities["page_type"] = "search"
                entities["video_title"] = None
                entities["video_id"] = None
                entities["channel"] = channel
                entities["search_query"] = video_title_cand
                entities["current_page"] = detected_url or "https://www.youtube.com/results"
                entities["playback_state"] = None
                entities["playback_position"] = None
                content_ctx = f"Searching on YouTube for '{video_title_cand}' in {browser_name.capitalize()}"
            else:
                entities["page_type"] = "video_page"
                entities["video_title"] = video_title_cand
                entities["video_id"] = video_id
                # Check for channel in title if format "<Video> - <Channel>"
                if not channel and " - " in video_title_cand:
                    parts = video_title_cand.split(" - ")
                    if len(parts) >= 2:
                        entities["video_title"] = parts[0].strip()
                        channel = parts[-1].strip()
                entities["channel"] = channel
                entities["playback_state"] = playback_state
                entities["playback_position"] = playback_position
                entities["current_page"] = detected_url or (
                    f"https://www.youtube.com/watch?v={video_id}" if video_id else "https://www.youtube.com/watch"
                )

                channel_str = f" by {channel}" if channel else ""
                content_ctx = f"Watching '{entities['video_title']}'{channel_str} on YouTube ({browser_name.capitalize()})"

            if not entities.get("url"):
                entities["url"] = entities["current_page"]

            return EnvironmentState(
                timestamp=time.time(),
                application=browser_name,
                window_title=title,
                window_hwnd=hwnd,
                window_pid=pid,
                process_name=f"{browser_name}.exe",
                app_category="browser",
                active_entities=entities,
                content_context=content_ctx,
                visible_text=clean_title,
                user_action_summary="Viewing YouTube",
                source_tier=source_tier,
                metadata={"website": "YouTube", "browser": browser_name, "video_id": video_id},
            )

        # ── 2. Google Docs / Workspace ───────────────────────────────────────
        if "google docs" in t_low or (detected_url and "docs.google.com/document" in detected_url):
            doc_name = re.sub(r'\s*-\s*Google\s+Docs$', '', clean_title, flags=re.IGNORECASE).strip()
            entities["website"] = "Google Docs"
            entities["domain"] = domain or "docs.google.com"
            entities["document_name"] = doc_name
            entities["doc_type"] = "document"
            entities["page_type"] = "document"
            entities["url"] = detected_url or "https://docs.google.com/document"
            return EnvironmentState(
                timestamp=time.time(),
                application=browser_name,
                window_title=title,
                window_hwnd=hwnd,
                window_pid=pid,
                process_name=f"{browser_name}.exe",
                app_category="browser",
                active_entities=entities,
                content_context=f"Editing document '{doc_name}' in Google Docs",
                visible_text=clean_title,
                source_tier=source_tier,
                metadata={"website": "Google Docs"},
            )

        # ── 3. GitHub ────────────────────────────────────────────────────────
        if "github" in t_low or (detected_url and "github.com" in detected_url):
            entities["website"] = "GitHub"
            entities["domain"] = domain or "github.com"
            repo_info = re.sub(r'\s*·\s*GitHub$', '', clean_title, flags=re.IGNORECASE).strip()
            repo_info = re.sub(r'\s*-\s*GitHub$', '', repo_info, flags=re.IGNORECASE).strip()
            entities["repository_context"] = repo_info
            entities["page_type"] = "code_repository"
            entities["url"] = detected_url or f"https://github.com/{repo_info}"
            return EnvironmentState(
                timestamp=time.time(),
                application=browser_name,
                window_title=title,
                window_hwnd=hwnd,
                window_pid=pid,
                process_name=f"{browser_name}.exe",
                app_category="browser",
                active_entities=entities,
                content_context=f"Browsing GitHub repository '{repo_info}'",
                visible_text=clean_title,
                source_tier=source_tier,
                metadata={"website": "GitHub"},
            )

        # ── 4. Gmail ─────────────────────────────────────────────────────────
        if "gmail" in t_low or (detected_url and "mail.google.com" in detected_url):
            entities["website"] = "Gmail"
            entities["domain"] = domain or "mail.google.com"
            mail_subject = re.sub(r'\s*-\s*Gmail$', '', clean_title, flags=re.IGNORECASE).strip()
            entities["mail_context"] = mail_subject
            entities["page_type"] = "web_mail"
            entities["url"] = detected_url or "https://mail.google.com"
            return EnvironmentState(
                timestamp=time.time(),
                application=browser_name,
                window_title=title,
                window_hwnd=hwnd,
                window_pid=pid,
                process_name=f"{browser_name}.exe",
                app_category="browser",
                active_entities=entities,
                content_context=f"Viewing Gmail: '{mail_subject}'",
                visible_text=clean_title,
                source_tier=source_tier,
                metadata={"website": "Gmail"},
            )

        # ── 5. Search Engines (Google, Bing, DuckDuckGo) ─────────────────────
        if "google search" in t_low or (detected_url and ("google.com/search" in detected_url or "bing.com/search" in detected_url)):
            search_query = re.sub(r'\s*-\s*Google\s+Search$', '', clean_title, flags=re.IGNORECASE).strip()
            entities["website"] = "Google Search"
            entities["domain"] = domain or "google.com"
            entities["search_query"] = search_query
            entities["page_type"] = "search_results"
            entities["url"] = detected_url or f"https://www.google.com/search?q={urllib.parse.quote(search_query)}"
            return EnvironmentState(
                timestamp=time.time(),
                application=browser_name,
                window_title=title,
                window_hwnd=hwnd,
                window_pid=pid,
                process_name=f"{browser_name}.exe",
                app_category="browser",
                active_entities=entities,
                content_context=f"Browsing '{clean_title}' in {browser_name.capitalize()}",
                visible_text=clean_title,
                source_tier=source_tier,
                metadata={"website": "Google Search"},
            )

        # ── 6. General Web Page ──────────────────────────────────────────────
        entities["website"] = clean_title.split(" - ")[-1].strip() if " - " in clean_title else "Web Page"
        entities["domain"] = domain or (f"{entities['website'].lower().replace(' ', '')}.com" if entities["website"] != "Web Page" else "web")
        entities["page_type"] = "article" if any(w in t_low for w in ("blog", "article", "post", "news")) else "general"
        entities["url"] = detected_url or (f"https://{entities['domain']}" if domain else "https://web")
        content_ctx = f"Browsing '{clean_title}' in {browser_name.capitalize()}"

        return EnvironmentState(
            timestamp=time.time(),
            application=browser_name,
            window_title=title,
            window_hwnd=hwnd,
            window_pid=pid,
            process_name=f"{browser_name}.exe",
            app_category="browser",
            active_entities=entities,
            content_context=content_ctx,
            visible_text=clean_title,
            source_tier=source_tier,
            metadata={"browser": browser_name, "domain": entities["domain"]},
        )

    def detect_action(
        self,
        before: EnvironmentState,
        after: EnvironmentState,
    ) -> Tuple[str, str, str]:
        # Application switch
        if before.application != after.application:
            return (
                "APP_SWITCH",
                f"Switched to {after.application.capitalize()}",
                f"Switched from {before.application} to {after.application}",
            )

        b_web = before.get_entity("website", "")
        a_web = after.get_entity("website", "")
        b_vid = before.get_entity("video_title")
        a_vid = after.get_entity("video_title")
        b_id = before.get_entity("video_id")
        a_id = after.get_entity("video_id")

        # YouTube video transitions
        if a_web == "YouTube" and b_web == "YouTube":
            if (a_vid and b_vid and a_vid != b_vid) or (a_id and b_id and a_id != b_id):
                return (
                    "VIDEO_CHANGE",
                    f"Clicked video '{a_vid}'",
                    f"YouTube: switched video from '{b_vid}' to '{a_vid}'",
                )
            if a_vid and not b_vid:
                return (
                    "VIDEO_START",
                    f"Started watching '{a_vid}'",
                    f"YouTube: started watching video '{a_vid}'",
                )
            b_play = before.get_entity("playback_state")
            a_play = after.get_entity("playback_state")
            if a_play and b_play and a_play != b_play:
                return (
                    "PLAYBACK_STATE_CHANGE",
                    f"Playback state changed to {a_play}",
                    f"YouTube: playback state changed to {a_play}",
                )

        # Tab or site switch
        if a_web != b_web or before.get_entity("domain") != after.get_entity("domain"):
            return (
                "TAB_SWITCH",
                f"Switched website to {a_web or after.get_entity('domain', 'new site')}",
                f"Switched browser tab from {b_web or 'previous site'} to {a_web}",
            )

        # Page navigation within same site
        if before.get_entity("url") != after.get_entity("url") or before.window_title != after.window_title:
            return (
                "PAGE_NAVIGATION",
                f"Navigated to '{after.get_entity('page_title', after.window_title)}'",
                f"Navigated to '{after.window_title}'",
            )

        return ("NO_CHANGE", "No change", "Browser state remained stable")
