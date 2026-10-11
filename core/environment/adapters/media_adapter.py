"""
Media Player Environment Adapter
Specialized observer for music and media players (Spotify, VLC, Windows Media Player, iTunes).
Extracts active song/track, artist, media player, and playback status.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, Optional, Tuple

from core.environment.adapters.base_adapter import BaseEnvironmentAdapter
from core.environment.models import EnvironmentState


class MediaEnvironmentAdapter(BaseEnvironmentAdapter):
    """
    Adapter for media and audio playback applications.
    Extracts current song, artist, and playback context.
    """

    name = "media"
    app_category = "media"

    MEDIA_APPS = {
        "spotify", "vlc", "wmplayer", "itunes", "groove", "musicbee", "aimp"
    }

    def can_handle(self, app_name: str, window_info: Dict[str, Any]) -> bool:
        clean_app = (app_name or "").lower().strip()
        cls_name = (window_info.get("class_name") or "").lower()
        title = (window_info.get("title") or "").lower()

        if any(m in clean_app for m in self.MEDIA_APPS):
            return True
        if any(m in cls_name for m in ("spotify", "vlc")):
            return True
        if any(m in title for m in ("spotify", "vlc media player", "windows media player", "itunes")):
            return True
        return False

    def extract_state(self, window_info: Dict[str, Any], hierarchy_level: int = 1) -> Optional[EnvironmentState]:
        title = (window_info.get("title") or "").strip()
        cls_name = window_info.get("class_name", "")
        pid = window_info.get("pid", 0)
        hwnd = window_info.get("hwnd", 0)
        t_low = title.lower()

        player = "spotify" if "spotify" in t_low or "spotify" in cls_name.lower() else "vlc" if "vlc" in t_low else "media_player"

        entities: Dict[str, Any] = {
            "player": player,
            "raw_title": title,
        }

        # ── Spotify ───────────────────────────────────────────────────────────
        if player == "spotify":
            # Spotify title format when playing: "<Artist> – <Song>" or "<Artist> - <Song>"
            # When paused/idle: "Spotify Free", "Spotify Premium", "Spotify"
            if title.lower() in ("spotify", "spotify free", "spotify premium", ""):
                entities["is_playing"] = False
                entities["song"] = None
                entities["artist"] = None
                content_ctx = "Spotify is open (idle or paused)"
            else:
                entities["is_playing"] = True
                sep = " – " if " – " in title else " - " if " - " in title else None
                if sep:
                    parts = title.split(sep, 1)
                    entities["artist"] = parts[0].strip()
                    entities["song"] = parts[1].strip()
                    content_ctx = f"Listening to '{entities['song']}' by {entities['artist']} on Spotify"
                else:
                    entities["song"] = title
                    entities["artist"] = None
                    content_ctx = f"Listening to '{title}' on Spotify"

        # ── VLC Media Player ──────────────────────────────────────────────────
        elif player == "vlc":
            clean_title = re.sub(r'\s*-\s*VLC\s+media\s+player$', '', title, flags=re.IGNORECASE).strip()
            if clean_title.lower() in ("vlc media player", ""):
                entities["is_playing"] = False
                content_ctx = "VLC media player is open (idle)"
            else:
                entities["is_playing"] = True
                entities["media_title"] = clean_title
                content_ctx = f"Playing '{clean_title}' in VLC media player"

        else:
            clean_title = re.sub(r'\s*-\s*(?:Windows\s+Media\s+Player|iTunes)$', '', title, flags=re.IGNORECASE).strip()
            entities["media_title"] = clean_title
            content_ctx = f"Playing media '{clean_title}' in {player.capitalize()}"

        return EnvironmentState(
            timestamp=time.time(),
            application=player,
            window_title=title,
            window_hwnd=hwnd,
            window_pid=pid,
            process_name=f"{player}.exe",
            app_category="media",
            active_entities=entities,
            content_context=content_ctx,
            visible_text=title,
            user_action_summary=f"Listening to media on {player.capitalize()}",
            source_tier="integration",
            metadata={"player": player},
        )

    def detect_action(
        self,
        before: EnvironmentState,
        after: EnvironmentState,
    ) -> Tuple[str, str, str]:
        if before.application != after.application:
            return (
                "APP_SWITCH",
                f"Switched to {after.application.capitalize()}",
                f"Switched from {before.application} to {after.application}",
            )

        b_song = before.get_entity("song") or before.get_entity("media_title")
        a_song = after.get_entity("song") or after.get_entity("media_title")

        if a_song and b_song and a_song != b_song:
            return (
                "MEDIA_TRACK_CHANGE",
                f"Changed track to '{a_song}'",
                f"Media: switched track from '{b_song}' to '{a_song}'",
            )

        if a_song and not b_song:
            return (
                "MEDIA_PLAY",
                f"Started playing '{a_song}'",
                f"Media: started playing '{a_song}'",
            )

        return ("NO_CHANGE", "No change", "Media playback remained stable")
