"""
Smart Assistant — Audio-Only Music Controller with Intelligent Volume Ducking
Provides headless audio playback (VLC via python-vlc), YouTube stream resolution (yt-dlp),
automatic queue progression, and Alexa-style intelligent volume ducking coordinated
with voice activity detection (VAD), assistant command recognition, and TTS response lifecycle.
"""

from __future__ import annotations

import sys
import subprocess
import random
import time
import threading
import re
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable, Tuple
import shutil

# Self-healing import for yt_dlp
try:
    import yt_dlp
except ImportError:
    yt_dlp = None

# Self-healing import for python-vlc
try:
    import vlc
except (ImportError, Exception):
    vlc = None


def install_missing_package(package_name: str) -> bool:
    """Attempts to install a missing package for the current interpreter."""
    print(f"[SYSTEM] Attempting to install missing dependency: {package_name}...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
        print(f"[SYSTEM] Successfully installed {package_name}.")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to auto-install {package_name}: {e}")
        return False


def _safe_str(text: Any) -> str:
    """Sanitizes text for safe terminal display on Windows (cp1252/utf-8)."""
    if text is None:
        return ""
    return str(text).encode("ascii", errors="replace").decode("ascii")


class CallableBool(int):
    """
    Boolean integer subclass that is also callable for backward compatibility.
    Supports both `if ctrl.is_playing:` and `if ctrl.is_playing():`.
    """
    def __call__(self) -> bool:
        return bool(int(self))

    def __bool__(self) -> bool:
        return bool(int(self))

    def __repr__(self) -> str:
        return "True" if self else "False"


class MusicPlaybackState:
    """Conceptual playback and ducking states."""
    NORMAL_PLAYBACK = "NORMAL_PLAYBACK"
    SPEECH_DETECTED = "SPEECH_DETECTED"
    COMMAND_PROCESSING = "COMMAND_PROCESSING"
    ASSISTANT_SPEAKING = "ASSISTANT_SPEAKING"
    RESTORING_VOLUME = "RESTORING_VOLUME"
    USER_PAUSED = "USER_PAUSED"
    USER_STOPPED = "USER_STOPPED"


class TrackItem(str):
    """
    Subclass of str that behaves as a string URL for backward compatibility,
    while holding rich metadata (title, duration, stream URL, expiry, codec, format,
    artist, upload_date, view_count, is_trending, playback_status).
    """
    def __new__(
        cls,
        url: str,
        title: Optional[str] = None,
        duration: Optional[int] = None,
        stream_url: Optional[str] = None,
        expires_at: Optional[float] = None,
        format_id: Optional[str] = None,
        acodec: Optional[str] = None,
        user_agent: Optional[str] = None,
        source: Optional[str] = "youtube",
        artist: Optional[str] = None,
        upload_date: Optional[str] = None,
        view_count: Optional[int] = None,
        is_trending: bool = False,
        trend_score: float = 0.0,
        playback_status: str = "pending"
    ):
        s = super(TrackItem, cls).__new__(cls, url)
        s.url = url
        s.title = title or "YouTube Track"
        s.duration = int(duration or 0)
        s.stream_url = stream_url
        s.expires_at = float(expires_at or 0.0)
        s.format_id = format_id
        s.acodec = acodec
        s.user_agent = user_agent
        s.source = source or "youtube"
        s.artist = artist
        s.upload_date = upload_date
        s.view_count = int(view_count) if view_count is not None else None
        s.is_trending = bool(is_trending)
        s.trend_score = float(trend_score or 0.0)
        s.playback_status = playback_status or "pending"
        return s

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "duration": self.duration,
            "artist": self.artist,
            "upload_date": self.upload_date,
            "view_count": self.view_count,
            "is_trending": self.is_trending,
            "trend_score": self.trend_score,
            "playback_status": self.playback_status,
            "source": self.source
        }

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str):
            return getattr(self, key)
        return super().__getitem__(key)



class BaseAudioPlayer:
    """Abstract interface for audio playback engines."""
    def play(self, stream_url: str, volume: int = 70, user_agent: Optional[str] = None) -> bool:
        raise NotImplementedError

    def get_diagnostics(self) -> Dict[str, Any]:
        return {}

    def pause(self) -> None:
        raise NotImplementedError

    def resume(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def set_volume(self, volume: int) -> None:
        raise NotImplementedError

    def get_volume(self) -> int:
        raise NotImplementedError

    def get_time(self) -> int:
        """Returns current playback position in milliseconds."""
        raise NotImplementedError

    def get_length(self) -> int:
        """Returns total track duration in milliseconds."""
        raise NotImplementedError

    def set_time(self, ms: int) -> bool:
        raise NotImplementedError

    def is_playing(self) -> bool:
        raise NotImplementedError

    def get_state(self) -> str:
        raise NotImplementedError

    def set_end_callback(self, cb: Optional[Callable[[], None]]) -> None:
        raise NotImplementedError

    def release(self) -> None:
        pass


class MockAudioPlayer(BaseAudioPlayer):
    """Deterministic in-memory player for unit testing and fallback."""
    def __init__(self):
        self._playing = False
        self._paused = False
        self._volume = 70
        self._time_ms = 0
        self._length_ms = 240000  # 4 minutes default
        self._stream_url = ""
        self._end_callback = None
        self._start_mono = 0.0
        self._time_to_first_audio_ms = 15.0
        self._selected_device_desc = "Mock Audio Output"
        self._last_error = None

    def play(self, stream_url: str, volume: int = 70, user_agent: Optional[str] = None) -> bool:
        self._stream_url = stream_url
        self._volume = max(0, min(100, int(volume)))
        self._playing = True
        self._paused = False
        self._start_mono = time.monotonic()
        self._time_ms = 0
        self._time_to_first_audio_ms = 15.0
        return True

    def pause(self) -> None:
        if self._playing:
            self._time_ms = self.get_time()
            self._playing = False
            self._paused = True

    def resume(self) -> None:
        if self._paused or not self._playing:
            self._playing = True
            self._paused = False
            self._start_mono = time.monotonic() - (self._time_ms / 1000.0)

    def stop(self) -> None:
        self._playing = False
        self._paused = False
        self._time_ms = 0

    def set_volume(self, volume: int) -> None:
        self._volume = max(0, min(100, int(volume)))

    def get_volume(self) -> int:
        return self._volume

    def get_time(self) -> int:
        if self._playing:
            elapsed = int((time.monotonic() - self._start_mono) * 1000)
            return min(self._length_ms, self._time_ms + elapsed)
        return self._time_ms

    def get_length(self) -> int:
        return self._length_ms

    def set_time(self, ms: int) -> bool:
        self._time_ms = max(0, min(self._length_ms, ms))
        if self._playing:
            self._start_mono = time.monotonic() - (self._time_ms / 1000.0)
        return True

    def is_playing(self) -> bool:
        return self._playing

    def get_state(self) -> str:
        if self._playing:
            return "playing"
        if self._paused:
            return "paused"
        return "stopped"

    def set_end_callback(self, cb: Optional[Callable[[], None]]) -> None:
        self._end_callback = cb

    def simulate_end_reached(self) -> None:
        """Helper for tests to simulate end of track."""
        self.stop()
        if self._end_callback:
            self._end_callback()

    def get_diagnostics(self) -> Dict[str, Any]:
        return {
            "backend": "MockAudioPlayer",
            "state": self.get_state(),
            "is_playing": self.is_playing(),
            "volume": self.get_volume(),
            "time_ms": self.get_time(),
            "length_ms": self.get_length(),
            "time_to_first_audio_ms": self._time_to_first_audio_ms,
            "selected_device": self._selected_device_desc,
            "available_devices": ["Mock Audio Output"],
            "last_error": self._last_error
        }


class VLCAudioPlayer(BaseAudioPlayer):
    """
    Dedicated headless audio player wrapping python-vlc.
    Plays direct audio streams through Windows WASAPI (mmdevice) without opening a browser or video window.
    """
    def __init__(self, preferred_device: Optional[str] = None):
        if vlc is None:
            raise RuntimeError("VLC python bindings not available.")
        # Explicitly configure Windows Multimedia Device (WASAPI) audio output
        self._instance = vlc.Instance("--no-video", "--quiet", "--aout=mmdevice")
        if self._instance is None:
            raise RuntimeError("Failed to create VLC Instance.")
        self._player = self._instance.media_player_new()
        if self._player is None:
            raise RuntimeError("Failed to create VLC MediaPlayer.")

        self._volume = 70
        self._stream_url = ""
        self._end_callback: Optional[Callable[[], None]] = None
        self._playback_start_mono: float = 0.0
        self._last_playback_time_ms: int = 0
        self._time_to_first_audio_ms: Optional[float] = None
        self._selected_device_desc: str = "Default"
        self._last_error: Optional[str] = None

        # Configure audio output device
        self.configure_output_device(preferred_device)

        # Attach EndReached event
        self._event_manager = self._player.event_manager()
        self._event_manager.event_attach(
            vlc.EventType.MediaPlayerEndReached,
            self._on_end_reached_event
        )

    def _get_available_devices(self) -> List[Tuple[str, str]]:
        devices: List[Tuple[str, str]] = []
        try:
            cur = self._instance.audio_output_device_list_get("mmdevice")
            if not cur:
                cur = self._player.audio_output_device_enum()
            while cur:
                dev_id = cur.contents.device.decode('utf-8', errors='ignore') if cur.contents.device else ''
                desc = cur.contents.description.decode('utf-8', errors='ignore') if cur.contents.description else ''
                devices.append((dev_id, desc))
                cur = cur.contents.next
        except Exception as e:
            print(f"[VLC PLAYER] Could not enumerate audio output devices: {e}")
        return devices

    def configure_output_device(self, preferred_name_or_id: Optional[str] = None) -> bool:
        """
        Configures the VLC audio output device using the Windows WASAPI mmdevice module.
        Falls back safely to system default if preferred device is unavailable.
        """
        devices = self._get_available_devices()
        pref = (preferred_name_or_id or "").strip()

        if not pref:
            try:
                self._player.audio_output_device_set("mmdevice", "")
                self._selected_device_desc = "Default (System Output)"
                return True
            except Exception:
                return False

        pref_lower = pref.lower()
        matched_id: Optional[str] = None
        matched_desc: Optional[str] = None

        for dev_id, desc in devices:
            if pref_lower == dev_id.lower() or pref_lower in desc.lower():
                matched_id = dev_id
                matched_desc = desc
                break

        if matched_id is not None:
            try:
                self._player.audio_output_device_set("mmdevice", matched_id)
                self._selected_device_desc = matched_desc or matched_id
                print(f"[VLC PLAYER] Configured output device: {self._selected_device_desc}")
                return True
            except Exception as e:
                print(f"[VLC PLAYER] Failed to set audio device '{matched_desc}': {e}")

        # Fallback to default
        print(f"[VLC PLAYER] Preferred device '{pref}' not found. Falling back to default Windows output.")
        try:
            self._player.audio_output_device_set("mmdevice", "")
            self._selected_device_desc = "Default (Fallback)"
        except Exception:
            pass
        return False

    def _on_end_reached_event(self, event):
        elapsed = time.monotonic() - getattr(self, "_playback_start_mono", 0.0)
        last_t = getattr(self, "_last_playback_time_ms", 0)
        # Guard against spurious EndReached caused by HTTP 403 or decode abort within first 2.5 seconds
        if elapsed < 2.5 and last_t < 1000:
            self._last_error = "Spurious MediaPlayerEndReached event (early abort / connection failure)."
            return

        if self._end_callback:
            # Dispatch in background thread so VLC event loop is not blocked
            threading.Thread(target=self._end_callback, daemon=True).start()

    def play(self, stream_url: str, volume: int = 70, user_agent: Optional[str] = None) -> bool:
        try:
            self._last_error = None
            self._time_to_first_audio_ms = None
            self._last_playback_time_ms = 0
            self._stream_url = stream_url

            media = self._instance.media_new(stream_url)
            if user_agent:
                media.add_option(f":http-user-agent={user_agent}")
            media.add_option(":http-referrer=https://www.youtube.com/")
            self._player.set_media(media)

            self.set_volume(volume)

            res = self._player.play()
            if res != 0:
                self._last_error = f"LibVLC play() returned error code {res}"
                return False

            self._playback_start_mono = time.monotonic()

            # Startup confirmation loop: poll for up to 3.5s to verify audio progression
            confirmed = False
            for _ in range(35):
                time.sleep(0.1)
                st = self._player.get_state()
                cur_time = self._player.get_time()

                if st in (vlc.State.Error, vlc.State.Ended):
                    self._last_error = f"VLC entered {st} during stream buffering (possible HTTP 403 or decode failure)"
                    self._player.stop()
                    return False

                if self._player.is_playing() and cur_time > 0:
                    self._time_to_first_audio_ms = (time.monotonic() - self._playback_start_mono) * 1000.0
                    self._last_playback_time_ms = cur_time
                    confirmed = True
                    break

            if not confirmed:
                if self._player.is_playing():
                    self._time_to_first_audio_ms = (time.monotonic() - self._playback_start_mono) * 1000.0
                    self._last_playback_time_ms = max(0, self._player.get_time())
                    confirmed = True
                else:
                    st = self._player.get_state()
                    self._last_error = f"VLC playback startup timed out after 3.5s (State: {st})"
                    self._player.stop()
                    return False

            return True
        except Exception as e:
            self._last_error = f"Exception during VLC play: {e}"
            print(f"[VLC PLAYER] Error starting playback: {e}")
            return False

    def pause(self) -> None:
        try:
            if self._player.is_playing():
                self._player.pause()
        except Exception:
            pass

    def resume(self) -> None:
        try:
            state = self._player.get_state()
            if state == vlc.State.Paused:
                self._player.play()
            elif state in (vlc.State.Stopped, vlc.State.NothingSpecial):
                self._player.play()
        except Exception:
            pass

    def stop(self) -> None:
        try:
            self._player.stop()
        except Exception:
            pass

    def set_volume(self, volume: int) -> None:
        clean_vol = max(0, min(100, int(volume)))
        self._volume = clean_vol
        try:
            self._player.audio_set_volume(clean_vol)
            if self._player.audio_get_mute():
                self._player.audio_set_mute(False)
        except Exception:
            pass

    def get_volume(self) -> int:
        try:
            cur = self._player.audio_get_volume()
            if cur >= 0:
                self._volume = cur
        except Exception:
            pass
        return self._volume

    def get_time(self) -> int:
        try:
            t = self._player.get_time()
            if t > 0:
                self._last_playback_time_ms = t
            return max(0, t) if t >= 0 else 0
        except Exception:
            return 0

    def get_length(self) -> int:
        try:
            l = self._player.get_length()
            return max(0, l) if l >= 0 else 0
        except Exception:
            return 0

    def set_time(self, ms: int) -> bool:
        try:
            return self._player.set_time(max(0, int(ms))) == 0
        except Exception:
            return False

    def is_playing(self) -> bool:
        try:
            return bool(self._player.is_playing())
        except Exception:
            return False

    def get_state(self) -> str:
        try:
            st = self._player.get_state()
            if st == vlc.State.Playing:
                return "playing"
            if st == vlc.State.Paused:
                return "paused"
            if st == vlc.State.Stopped:
                return "stopped"
            if st == vlc.State.Ended:
                return "ended"
            if st == vlc.State.Error:
                return "error"
        except Exception:
            pass
        return "stopped"

    def set_end_callback(self, cb: Optional[Callable[[], None]]) -> None:
        self._end_callback = cb

    def get_diagnostics(self) -> Dict[str, Any]:
        devs = [d[1] for d in self._get_available_devices()]
        return {
            "backend": "VLCAudioPlayer",
            "state": self.get_state(),
            "is_playing": self.is_playing(),
            "volume": self.get_volume(),
            "time_ms": self.get_time(),
            "length_ms": self.get_length(),
            "time_to_first_audio_ms": round(self._time_to_first_audio_ms, 1) if self._time_to_first_audio_ms else None,
            "selected_device": self._selected_device_desc,
            "available_devices": devs,
            "last_error": self._last_error
        }

    def release(self) -> None:
        try:
            self._player.stop()
            self._player.release()
            self._instance.release()
        except Exception:
            pass


class MusicSessionState:
    """
    Canonical session state tracking active constraints, queue position,
    search history, era preference, and trend verification status across playback turns.
    """
    def __init__(self):
        self.requested_language: Optional[str] = None
        self.requested_artist: Optional[str] = None
        self.requested_genre: Optional[str] = None
        self.requested_mood: Optional[str] = None
        self.exact_song_requested: Optional[str] = None
        self.is_specific_song: bool = False
        self.era_preference: str = "latest"  # "latest", "trending", "old", "retro", "90s"
        self.allow_older: bool = False
        self.trend_only: bool = False
        self.trend_verification_limited: bool = False
        self.user_query_raw: str = ""
        self.clean_search_query: str = ""
        self.active_session: bool = False
        self.search_attempts: int = 0
        self.rejected_candidates: List[Dict[str, Any]] = []

    def to_dict(self, ctrl: Optional[Any] = None) -> Dict[str, Any]:
        curr_track = ctrl.get_current_track() if ctrl else None
        return {
            "requested_language": self.requested_language,
            "requested_artist": self.requested_artist,
            "requested_genre": self.requested_genre,
            "requested_mood": self.requested_mood,
            "is_specific_song": self.is_specific_song,
            "exact_song_requested": self.exact_song_requested,
            "era_preference": self.era_preference,
            "allow_older": self.allow_older,
            "trend_only": self.trend_only,
            "trend_verification_limited": self.trend_verification_limited,
            "active_session": self.active_session,
            "clean_search_query": self.clean_search_query,
            "search_attempts": self.search_attempts,
            "rejected_count": len(self.rejected_candidates),
            "current_track": getattr(curr_track, "title", None) if curr_track else None,
            "queue_position": (ctrl.current_index + 1) if ctrl and ctrl.music_queue else 0,
            "queue_length": len(ctrl.music_queue) if ctrl else 0,
            "user_volume": getattr(ctrl, "_user_volume", 70) if ctrl else 70,
            "effective_volume": int(getattr(ctrl, "_effective_volume", 70)) if ctrl else 70,
            "is_ducked": getattr(ctrl, "_is_ducked", False) if ctrl else False,
            "playback_status": ctrl.playback_state if ctrl else "USER_STOPPED"
        }


class ParsedMusicCommand:
    """Represents a deterministically parsed music utterance."""
    def __init__(
        self,
        raw_text: str,
        is_transport: bool = False,
        transport_action: Optional[str] = None,
        is_video_requested: bool = False,
        language: Optional[str] = None,
        artist: Optional[str] = None,
        genre: Optional[str] = None,
        exact_song_title: Optional[str] = None,
        clean_query: str = "",
        era_preference: str = "latest",
        allow_older: bool = False,
        is_trending_requested: bool = False
    ):
        self.raw_text = raw_text
        self.is_transport = is_transport
        self.transport_action = transport_action
        self.is_video_requested = is_video_requested
        self.language = language
        self.artist = artist
        self.genre = genre
        self.exact_song_title = exact_song_title
        self.clean_query = clean_query
        self.era_preference = era_preference
        self.allow_older = allow_older
        self.is_trending_requested = is_trending_requested


class MusicCommandParser:
    """
    Deterministic music-command parser that extracts language, artist,
    exact song title, genre/mood constraints, era/recency preferences, and transport actions
    without contaminating search queries with wake words or assistant names.
    """
    KNOWN_LANGUAGES = [
        "telugu", "hindi", "tamil", "english", "punjabi", "kannada",
        "malayalam", "bengali", "marathi", "gujarati", "bhojpuri"
    ]
    GENRES_MOODS = [
        "romantic", "romance", "melody", "love", "sad", "emotional",
        "heartbreak", "party", "dance", "club", "dj", "fast beat",
        "mass", "folk", "classical", "carnatic", "hindustani",
        "devotional", "bhakti", "lo-fi", "lofi", "chill", "pop", "rock"
    ]
    KNOWN_ARTISTS = [
        "sid sriram", "arijit singh", "anirudh", "spb", "s.p. balasubrahmanyam",
        "k.s. chithra", "chithra", "shreya ghoshal", "devi sri prasad", "dsp",
        "thaman", "thaman s", "keeravani", "m.m. keeravani", "anurag kulkarni",
        "ram miriyala", "mangli", "armaan malik", "taylor swift", "ed sheeran",
        "justin bieber", "neha kakkar", "atif aslam", "kumar sanu", "sonu nigam",
        "badshah", "honey singh", "kk", "alka yagnik", "ar rahman", "yuvan shankar raja",
        "harris jayaraj", "mickey j meyer", "ghantasala", "susheela", "janaki",
        "allu arjun", "mahesh babu", "prabhas", "ntr", "ram charan"
    ]
    CLASSIC_ARTISTS = [
        "ghantasala", "susheela", "janaki", "s.p. balasubrahmanyam", "spb",
        "lata mangeshkar", "kishore kumar", "mohammed rafi", "mukesh", "rd burman",
        "kumar sanu", "alka yagnik", "udit narayan"
    ]

    def parse(self, text: str, session: Optional[MusicSessionState] = None) -> ParsedMusicCommand:
        if not text:
            return ParsedMusicCommand("", is_transport=True, transport_action="queue_status")

        raw_low = text.lower().strip().rstrip(".?!,")

        # 1. Strip wake-word and assistant name variations (including ASR errors)
        clean = re.sub(
            r'^(?:(?:hey|ok|hi)\s+)?(?:friday|friay|fridy|trevon|assistant|nova|computer)[,\s]*',
            '',
            raw_low
        )
        clean = re.sub(
            r'[,\s]+(?:friday|friay|fridy|trevon|assistant|nova|computer)$',
            '',
            clean
        )
        clean = clean.strip()

        # Remove leading polite phrases
        clean = re.sub(r'^(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?|please\s+|kindly\s+)+', '', clean).strip()

        # 2. Check Transport Commands (High Precedence)
        # Stop
        if re.search(r'^(?:stop\s+(?:playing\s+)?(?:the\s+)?(?:songs?|music|audio|tracks?|playback|singing)|stop\s+(?:playing|singing)(?:\s+(?:the\s+)?(?:songs?|music|audio|tracks?))?|stop\s+everything|stop\s+all|stop)$', clean):
            return ParsedMusicCommand(text, is_transport=True, transport_action="stop")
        # Pause
        if re.search(r'^(?:pause\s+(?:the\s+)?(?:music|songs?|audio|tracks?|playback)|pause)$', clean):
            return ParsedMusicCommand(text, is_transport=True, transport_action="pause")
        # Resume
        if re.search(r'^(?:resume\s+(?:the\s+)?(?:music|songs?|audio|tracks?|playback)|unpause(?:\s+(?:the\s+)?(?:music|songs?|audio|tracks?|playback))?|resume)$', clean):
            return ParsedMusicCommand(text, is_transport=True, transport_action="resume")
        # Next / Skip (supports "play next", "play next song", "next song", "next track", "skip", "next")
        if re.search(r'^(?:(?:play\s+)?next(?:\s+(?:songs?|tracks?))?|skip\s+(?:this\s+)?(?:songs?|tracks?)?)$', clean):
            return ParsedMusicCommand(text, is_transport=True, transport_action="next")
        # Previous / Back (supports "play previous", "play prev", "previous song", "go back", "prev")
        if re.search(r'^(?:(?:play\s+)?(?:previous|prev)(?:\s+(?:songs?|tracks?))?|go\s+back(?:\s+to\s+previous\s+song)?)$', clean):
            return ParsedMusicCommand(text, is_transport=True, transport_action="previous")
        # Status / What's playing
        if re.search(r'^(?:what\s+(?:song\s+is\s+this|song\s+is\s+playing|is\s+playing|is\s+this\s+song)|what\'s\s+playing|current\s+song|queue\s+status|show\s+queue|what\s+song)$', clean):
            return ParsedMusicCommand(text, is_transport=True, transport_action="queue_status")
        # Volume
        if re.search(r'^(?:turn\s+(?:it\s+)?up|volume\s+up|louder|raise\s+(?:the\s+)?volume)$', clean):
            return ParsedMusicCommand(text, is_transport=True, transport_action="volume_up")
        if re.search(r'^(?:turn\s+(?:it\s+)?down|volume\s+down|quieter|lower\s+(?:the\s+)?volume)$', clean):
            return ParsedMusicCommand(text, is_transport=True, transport_action="volume_down")
        if re.search(r'^(?:mute(?:\s+(?:the\s+)?music)?|unmute(?:\s+(?:the\s+)?music)?)$', clean):
            return ParsedMusicCommand(text, is_transport=True, transport_action="volume_mute")

        # 3. Check Video Request
        is_video = bool(re.search(
            r'\b(?:video\s+songs?|music\s+videos?|watch\s+(?:the\s+)?videos?|show\s+(?:the\s+)?(?:music\s+)?videos?|video\s+version)\b',
            clean
        ))

        # 4. Check Era / Recency / Trending Preferences
        is_old = bool(re.search(
            r'\b(?:old|classic|classics|retro|evergreen|golden|vintage|nostalgic|purane|patha)\b',
            clean
        ) or re.search(r'\b(?:90s?|80s?|70s?|60s?|19\d{2}s?)\b', clean))

        is_trending = bool(re.search(
            r'\b(?:trending|top\s+trending|current\s+trends?|viral|top\s+charts?|chart\s+toppers?)\b',
            clean
        ))

        is_latest = bool(re.search(
            r'\b(?:latest|new|recent|newly\s+released|fresh)\b',
            clean
        ))

        if is_old:
            era_preference = "old"
            allow_older = True
        elif is_trending:
            era_preference = "trending"
            allow_older = False
        elif is_latest:
            era_preference = "latest"
            allow_older = False
        else:
            # Default music selection policy:
            # "Play songs", "Play Telugu songs" default to recent, currently trending individual songs
            era_preference = "latest"
            allow_older = False

        # 5. Extract Language
        lang = None
        for l in self.KNOWN_LANGUAGES:
            if re.search(r'\b' + l + r'\b', clean):
                lang = l
                break

        # If no explicit language specified in command, inherit from active session constraint
        if not lang and session and session.active_session and session.requested_language:
            lang = session.requested_language

        # 6. Extract Artist
        artist = None
        m_artist = re.search(r'\b(?:by|of|singer|artist)\s+([a-zA-Z\s]+?)(?:\s+songs?|\s+tracks?|$)', clean)
        if m_artist:
            cand_artist = m_artist.group(1).strip()
            if cand_artist not in self.KNOWN_LANGUAGES and cand_artist not in self.GENRES_MOODS:
                artist = cand_artist.title()
        if not artist:
            for a in self.KNOWN_ARTISTS:
                if re.search(r'\b' + re.escape(a) + r'\b', clean):
                    artist = a.title()
                    break

        if artist and any(artist.lower() == ca.lower() for ca in self.CLASSIC_ARTISTS):
            allow_older = True

        # 7. Extract Genre / Mood
        genre = None
        for g in self.GENRES_MOODS:
            if re.search(r'\b' + g + r'\b', clean):
                genre = g
                break

        # 8. Exact Song vs General Playlist
        rem_text = re.sub(r'^(?:i\s+want\s+to\s+listen\s+to|let(\'s|\s+us)\s+listen\s+to|put\s+on|play\s+me|play\s+some|play)\s+', '', clean).strip()

        GENERIC_PLAYLIST_MODIFIERS = r'(?:the|some|any|all|telugu|hindi|tamil|english|punjabi|kannada|malayalam|bengali|bhojpuri|romantic|sad|party|dance|rock|pop|classical|devotional|latest|new|recent|trending|viral|old|classic|retro|evergreen|golden|90s|80s|70s|top|hit|hits)'
        is_generic_playlist = bool(re.search(
            r'^(?:' + GENERIC_PLAYLIST_MODIFIERS + r'\s+)*(?:songs?|music|tracks?|hits?|playlist)$',
            rem_text
        ))
        if re.search(r'\bsongs\b', rem_text) and not re.search(r'\bvideo\s+song\b', rem_text):
            tokens_before = re.sub(r'\b' + GENERIC_PLAYLIST_MODIFIERS + r'\b', '', rem_text)
            tokens_before = re.sub(r'\bsongs?\b', '', tokens_before).strip()
            if not tokens_before:
                is_generic_playlist = True

        # If the remaining text only consists of generic keywords, it's a playlist request
        clean_rem_tokens = re.sub(r'\b(?:the|some|latest|trending|new|recent|old|classic|retro|evergreen|songs?|music|tracks?|hits?|playlist|top)\b', '', rem_text).strip()
        if lang:
            clean_rem_tokens = re.sub(r'\b' + lang + r'\b', '', clean_rem_tokens).strip()
        if genre:
            clean_rem_tokens = re.sub(r'\b' + genre + r'\b', '', clean_rem_tokens).strip()

        if not clean_rem_tokens:
            is_generic_playlist = True

        exact_song = None
        if not is_generic_playlist:
            s_title = rem_text
            s_title = re.sub(r'\b(?:video\s+songs?|music\s+videos?|videos?)\b', '', s_title)
            if lang:
                s_title = re.sub(r'\b' + lang + r'\b', '', s_title)
            if genre:
                s_title = re.sub(r'\b' + genre + r'\b', '', s_title)
            if artist:
                s_title = re.sub(r'\b(?:by\s+)?' + re.escape(artist.lower()) + r'\b', '', s_title)
            s_title = re.sub(r'\b(?:the\s+)?(?:latest|trending|new|recent|old|classic|retro|evergreen)\b', '', s_title)
            s_title = re.sub(r'\b(?:song|track|audio|official)\b', '', s_title).strip()
            if s_title and len(s_title) > 1:
                exact_song = s_title.title()
                # A specific-song request should still play that song even if it is old
                allow_older = True

        # 9. Clean Query Construction
        query_parts = []
        if exact_song:
            query_parts.append(exact_song)
        if artist and (not exact_song or artist.lower() not in exact_song.lower()):
            query_parts.append(artist)
        if genre and (not exact_song or genre.lower() not in exact_song.lower()):
            query_parts.append(genre)
        if lang:
            query_parts.append(lang.capitalize())

        if is_video:
            query_parts.append("official music video")
        elif exact_song:
            query_parts.append("official song full audio")
        elif era_preference == "trending":
            query_parts.append("trending hit songs official audio")
        elif era_preference == "old":
            query_parts.append("classic old songs audio")
        else:
            query_parts.append("latest hit songs official audio")

        clean_query = " ".join(query_parts)

        return ParsedMusicCommand(
            raw_text=text,
            is_transport=False,
            transport_action="play",
            is_video_requested=is_video,
            language=lang,
            artist=artist,
            genre=genre,
            exact_song_title=exact_song,
            clean_query=clean_query,
            era_preference=era_preference,
            allow_older=allow_older,
            is_trending_requested=is_trending
        )


class LanguageValidator:
    """
    Validates candidates using metadata, scripts, dedicated channels,
    known works, and negative disqualifiers to strictly enforce language constraints.
    """
    LANGUAGE_SCRIPTS = {
        "telugu": r'[\u0C00-\u0C7F]',
        "hindi": r'[\u0900-\u097F]',
        "tamil": r'[\u0B80-\u0BFF]',
        "punjabi": r'[\u0A00-\u0A7F]',
        "kannada": r'[\u0C80-\u0CFF]',
        "malayalam": r'[\u0D00-\u0D7F]',
        "bengali": r'[\u0980-\u09FF]',
        "gujarati": r'[\u0A80-\u0AFF]'
    }

    LANGUAGE_CHANNELS = {
        "telugu": [
            "aditya music", "saregama telugu", "tips telugu", "t-series telugu",
            "lahari music", "mango music", "madhura audio", "sony music south",
            "zee music south", "geetha arts", "mythri movie makers", "shreyas media",
            "haarikahassinecreations", "aditya dev", "annapurna studios"
        ],
        "hindi": [
            "t-series", "zee music company", "sony music india", "yrf",
            "tips official", "saregama music", "t-series classics"
        ],
        "tamil": [
            "think music india", "divo movies", "sony music south", "saregama tamil",
            "lahari music | tamil", "wunderbar films"
        ],
        "punjabi": [
            "speed records", "white hill music", "geet mp3", "t-series apna punjab"
        ],
        "kannada": [
            "anand audio", "saregama kannada", "lahari music | kannada", "aakash audio"
        ],
        "malayalam": [
            "muzik247", "saregama malayalam", "satyam audios", "goodwill entertainments"
        ],
        "english": [
            "vevo", "warner records", "atlantic records", "interscope records",
            "columbia records", "republic records", "rca records"
        ]
    }

    LANGUAGE_KNOWN_ARTISTS = {
        "telugu": [
            "sid sriram", "spb", "s.p. balasubrahmanyam", "k.s. chithra", "chithra",
            "anurag kulkarni", "ram miriyala", "mangli", "devi sri prasad", "dsp",
            "thaman", "thaman s", "keeravaani", "m.m. keeravani", "mickey j meyer",
            "ghantasala", "susheela", "janaki", "mano", "karthik", "haricharan",
            "hema chandra", "geetha madhuri", "sunitha", "allu arjun", "mahesh babu",
            "prabhas", "ntr", "ram charan", "chiranjeevi", "balakrishna", "venkatesh",
            "nagarjuna", "nani"
        ],
        "hindi": [
            "arijit singh", "neha kakkar", "atif aslam", "shreya ghoshal", "kumar sanu",
            "udit narayan", "sonu nigam", "jubin nautiyal", "badshah", "honey singh",
            "kk", "alka yagnik", "mohit chauhan", "sunidhi chauhan", "vishal mishra",
            "darshan raval", "lata mangeshkar", "kishore kumar", "mohammed rafi",
            "mukesh", "rd burman", "pritam", "mithoon"
        ],
        "tamil": [
            "anirudh", "ar rahman", "yuvan shankar raja", "harris jayaraj", "dhanush",
            "ilaiyaraaja", "vijay", "ajith", "suriya", "sivakarthikeyan", "kamal haasan"
        ],
        "punjabi": [
            "diljit dosanjh", "sidhu moose wala", "ap dhillon", "karan aujla",
            "guru randhawa", "harrdy sandhu", "ammy virk", "b praak", "jassi gill"
        ],
        "english": [
            "taylor swift", "ed sheeran", "justin bieber", "adele", "bruno mars",
            "the weeknd", "drake", "eminem", "billie eilish", "coldplay",
            "imagine dragons", "dua lipa", "post malone", "maroon 5", "rihanna",
            "katy perry", "shawn mendes", "ariana grande", "charlie puth", "selena gomez"
        ]
    }

    EXCLUSIVE_ARTISTS = {
        "telugu": [
            "allu arjun", "mahesh babu", "prabhas", "ram charan", "chiranjeevi",
            "balakrishna", "ram miriyala", "mangli", "mickey j meyer", "ghantasala"
        ],
        "hindi": [
            "lata mangeshkar", "kishore kumar", "mohammed rafi", "mukesh", "rd burman",
            "pritam", "mithoon", "jubin nautiyal", "darshan raval"
        ],
        "tamil": [
            "dhanush", "ilaiyaraaja", "vijay", "ajith", "sivakarthikeyan"
        ],
        "punjabi": [
            "sidhu moose wala", "ap dhillon", "karan aujla", "ammy virk", "b praak"
        ]
    }

    KNOWN_MOVIES_AND_SONGS = {
        "telugu": [
            "ala vaikunthapurramuloo", "pushpa", "rrr", "sarileru neekevvaru", "devara",
            "kalki", "guntur kaaram", "hanuman", "salaar", "geetha govindam",
            "rangasthalam", "arjun reddy", "bahubali", "magadheera", "atharintiki daaredi",
            "srimanthudu", "butta bomma", "samajavaragamana", "ramuloo ramulaa", "o antava",
            "srivalli", "chuttamalle", "fear song", "kurchi madathapetti"
        ],
        "hindi": [
            "aashiqui", "aashiqui 2", "animal", "jawan", "pathaan", "brahmastra",
            "shershaah", "kabir singh", "kalank", "kesariya", "tum hi ho",
            "apna bana le", "channa mereya", "raataan lambiyan", "shayad", "chaleya",
            "satranga", "pehle bhi main"
        ],
        "tamil": [
            "leo", "jailer", "vikram", "master", "kaithi", "ponniyin selvan",
            "rowdy baby", "enjoy enjaami", "arabic kuthu", "naa ready"
        ]
    }

    @classmethod
    def validate_candidate(
        cls,
        candidate: Dict[str, Any],
        target_lang: Optional[str] = None,
        artist: Optional[str] = None,
        exact_title: Optional[str] = None,
        genre: Optional[str] = None
    ) -> Tuple[bool, str, int]:
        title = candidate.get("title", "")
        channel = candidate.get("channel") or candidate.get("uploader") or ""
        desc = candidate.get("description") or ""
        tags = candidate.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]

        title_low = title.lower()
        ch_low = channel.lower()
        full_text = f"{title_low} {ch_low} {desc.lower()} {' '.join(tags).lower()}"

        # 1. Exact Title Verification
        if exact_title:
            clean_exact = re.sub(r'[^a-zA-Z0-9\s]', '', exact_title).lower().strip()
            clean_title = re.sub(r'[^a-zA-Z0-9\s]', '', title).lower()
            req_words = clean_exact.split()
            if not all(w in clean_title for w in req_words):
                return False, f"Title does not contain requested song '{exact_title}'", 0

        # If no language constraint specified, accept if exact title matches
        if not target_lang:
            return True, "No language constraint specified", 50

        target_lang = target_lang.lower().strip()

        # 2. Strict Negative Disqualification
        other_languages = [l for l in ["telugu", "hindi", "tamil", "punjabi", "kannada", "malayalam", "bengali", "bhojpuri"] if l != target_lang]

        if target_lang != "english":
            for other_l in other_languages:
                # Disqualify if title explicitly declares other language and NOT target_lang
                if re.search(r'\b' + other_l + r'\b', title_low) and not re.search(r'\b' + target_lang + r'\b', title_low):
                    return False, f"Title explicitly declares other language '{other_l}' without '{target_lang}'", -100

            # Disqualify non-target scripts (e.g. Devanagari when Telugu requested)
            for other_l, script_pat in cls.LANGUAGE_SCRIPTS.items():
                if other_l != target_lang and re.search(script_pat, title):
                    if not (target_lang in cls.LANGUAGE_SCRIPTS and re.search(cls.LANGUAGE_SCRIPTS[target_lang], title)) and target_lang not in title_low:
                        return False, f"Title contains non-target script ({other_l})", -100

            # Disqualify exclusive artists of other languages
            for other_l, excl_arts in cls.EXCLUSIVE_ARTISTS.items():
                if other_l != target_lang:
                    for excl_a in excl_arts:
                        if excl_a in title_low and target_lang not in title_low and target_lang not in ch_low:
                            return False, f"Artist '{excl_a}' is exclusively associated with '{other_l}'", -80
        else:
            # English target: disqualify any Indian regional language token
            for regional in ["telugu", "hindi", "tamil", "punjabi", "kannada", "malayalam", "bollywood", "tollywood", "kollywood"]:
                if re.search(r'\b' + regional + r'\b', title_low):
                    return False, f"English track request cannot contain regional tag '{regional}'", -100

        # 3. Positive Evidence Scoring
        score = 0
        evidence_parts = []

        # Target language mentioned in title (+50)
        if re.search(r'\b' + target_lang + r'\b', title_low):
            score += 50
            evidence_parts.append(f"title has '{target_lang}'")

        # Target language mentioned in channel (+40)
        if re.search(r'\b' + target_lang + r'\b', ch_low):
            score += 40
            evidence_parts.append(f"channel has '{target_lang}'")

        # Target script in title (+50)
        if target_lang in cls.LANGUAGE_SCRIPTS and re.search(cls.LANGUAGE_SCRIPTS[target_lang], title):
            score += 50
            evidence_parts.append(f"has {target_lang} script")

        # Known channel match (+40)
        if target_lang in cls.LANGUAGE_CHANNELS:
            for ch in cls.LANGUAGE_CHANNELS[target_lang]:
                if ch in ch_low:
                    score += 40
                    evidence_parts.append(f"known channel '{ch}'")
                    break

        # Known artist match (+30)
        if target_lang in cls.LANGUAGE_KNOWN_ARTISTS:
            for art in cls.LANGUAGE_KNOWN_ARTISTS[target_lang]:
                if art in full_text:
                    score += 30
                    evidence_parts.append(f"known artist '{art}'")
                    break

        # Known movie or song match (+35)
        if target_lang in cls.KNOWN_MOVIES_AND_SONGS:
            for m_or_s in cls.KNOWN_MOVIES_AND_SONGS[target_lang]:
                if m_or_s in full_text:
                    score += 35
                    evidence_parts.append(f"known work '{m_or_s}'")
                    break

        # For English: western pop artists (+50)
        if target_lang == "english":
            for eng_art in cls.LANGUAGE_KNOWN_ARTISTS["english"]:
                if eng_art in full_text:
                    score += 50
                    evidence_parts.append(f"known English artist '{eng_art}'")
                    break
            if not re.search(r'[\u0900-\u0D7F]', title) and any(k in full_text for k in ["vevo", "official video", "official audio", "records"]):
                score += 30
                evidence_parts.append("western label/vevo")

        # Artist constraint check: if user explicitly asked for artist
        if artist:
            clean_art = artist.lower().strip()
            if clean_art not in full_text:
                return False, f"Candidate does not match requested artist '{artist}'", 0
            score += 30
            evidence_parts.append(f"matches requested artist '{artist}'")

        # Genre boost / match
        if genre:
            clean_g = genre.lower().strip()
            if clean_g in full_text:
                score += 20
                evidence_parts.append(f"matches genre '{genre}'")

        if score >= 30:
            return True, f"Verified {target_lang} ({', '.join(evidence_parts)})", score
        else:
            return False, f"Insufficient evidence for {target_lang} (Score: {score} < 30)", score


def _canonical_song_key(title: str) -> str:
    """Extracts a canonical key for song title to deduplicate alternate uploads."""
    t = (title or "").lower()
    t = re.sub(r'\[.*?\]|\(.*?\)', '', t)
    t = re.sub(r'\b(?:official|video|audio|song|songs|lyric|lyrical|lyrics|full|hd|4k|remastered|promo|track|tracks|original)\b', '', t)
    t = re.sub(r'[\-–—|:/\\]', ' ', t)
    words = [w for w in re.split(r'\s+', t) if w and (len(w) > 1 or w.isalnum())]
    return " ".join(words[:4]) if words else t.strip()


class CandidateValidator:
    """
    Validates candidates enforcing:
      1. Strict language verification (delegated to LanguageValidator)
      2. Individual-song requirement (rejecting compilations, jukeboxes, full albums, non-stop mixes, and >11 min tracks)
      3. Recency & era policy (rejecting older tracks and 90s/evergreen compilations unless explicitly permitted)
      4. Credible trending evidence verification (requiring view counts / platform chart signals, not title clickbait)
    """
    COMPILATION_PATTERNS = [
        r'\b(?:audio\s+|video\s+|mega\s+)?jukebox\b',
        r'\bnon[\s\-_]?stop\b',
        r'\bnonstop\b',
        r'\ball\s+songs\b',
        r'\ball\s+(?:audio|video)\s+songs\b',
        r'\bfull\s+album\b',
        r'\bcomplete\s+album\b',
        r'\b(?:original\s+soundtrack|ost)\s+album\b',
        r'\bmashup\b',
        r'\bmash\s+up\b',
        r'\bmegamix\b',
        r'\bmega\s+mix\b',
        r'\bremix\s+collection\b',
        r'\bevergreen\s+(?:hits?|songs?|collection)\b',
        r'\bgolden\s+(?:hits?|classics?|songs?)\b',
        r'\bclassic\s+hits?\b',
        r'\bretro\s+hits?\b',
        r'\b(?:90s?|80s?|70s?|2000s?)\s+(?:hits?|collection|songs?)\b',
        r'\b(?:hit\s+)?songs?\s+collection\b',
        r'\baudio\s+collection\b',
        r'\bgreatest\s+hits\b',
        r'\bsuper\s+hit\s+songs\b',
        r'\bback\s+to\s+back\b',
        r'\bb2b\b',
        r'\b\d+\s*hours?\s+(?:mix|collection|songs)\b',
        r'\bhour\s+mix\b',
        r'\bcontinuous\s+mix\b',
        r'\bparty\s+mix\b',
        r'\bdj\s+mix\s+non[\s\-_]?stop\b',
        r'\bcompilation\b',
        r'\btop\s+(?:10|20|50|100)\s+songs\b'
    ]

    OLDER_ERA_PATTERNS = [
        r'\b(?:90s?|80s?|70s?|60s?|19\d{2}s?)\b',
        r'\b(?:evergreen|retro|golden\s+era|vintage|nostalgia|nostalgic|old\s+classics?)\b',
        r'\b(?:purane\s+gane|patha\s+paatalu)\b'
    ]

    KNOWN_BLOCKBUSTERS = [
        "chuttamalle", "fear song", "kurchi madathapetti", "tauba tauba", "kesariya",
        "chaleya", "samajavaragamana", "butta bomma", "ramuloo ramulaa", "o antava",
        "srivalli", "arabic kuthu", "naa ready", "illuminati", "kaavaalaa", "dheera dheera",
        "pehle bhi main", "satranga", "apna bana le"
    ]

    @classmethod
    def validate_candidate(
        cls,
        candidate: Dict[str, Any],
        target_lang: Optional[str] = None,
        artist: Optional[str] = None,
        exact_title: Optional[str] = None,
        genre: Optional[str] = None,
        allow_older: bool = False,
        era_preference: str = "latest",
        trend_only: bool = False,
        recency_window_months: int = 18,
        current_year: int = 2026
    ) -> Tuple[bool, str, int]:
        title = candidate.get("title", "")
        duration = candidate.get("duration", 0) or 0
        upload_date = str(candidate.get("upload_date") or "")
        view_count = candidate.get("view_count")
        channel = candidate.get("channel") or candidate.get("uploader") or ""
        desc = candidate.get("description") or ""
        tags = candidate.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]

        title_low = title.lower()
        full_text = f"{title_low} {channel.lower()} {desc.lower()} {' '.join(tags).lower()}"

        # 1. Enforce strict language constraint
        is_lang_valid, lang_reason, lang_score = LanguageValidator.validate_candidate(
            candidate,
            target_lang=target_lang,
            artist=artist,
            exact_title=exact_title,
            genre=genre
        )
        if not is_lang_valid:
            return False, lang_reason, lang_score

        # Check if classical piece / symphony / concert
        is_classical = any(k in full_text for k in ["symphony", "classical", "philharmonic", "orchestra", "concerto", "sonata", "concert"]) or (genre and any(k in str(genre).lower() for k in ["classical", "symphony"]))

        # 2. Enforce Individual Tracks Only (Reject Compilations / Jukeboxes / Non-stop Mixes)
        if not exact_title and not is_classical:
            if duration and duration > 660:
                return False, f"Rejected compilation/jukebox: duration {duration}s exceeds 11 minutes", -100

            for pat in cls.COMPILATION_PATTERNS:
                if re.search(pat, title_low) or re.search(pat, full_text):
                    return False, "Rejected compilation/jukebox/mix track for individual song playlist", -100
        elif is_classical:
            for pat in [r'\b(?:audio\s+|video\s+|mega\s+)?jukebox\b', r'\bnon[\s\-_]?stop\b', r'\bmegamix\b', r'\bmashup\b']:
                if re.search(pat, title_low) or re.search(pat, full_text):
                    return False, "Rejected jukebox/mix for classical work", -100

        # 3. Enforce Recency and Era Policy
        if not exact_title and not allow_older:
            for pat in cls.OLDER_ERA_PATTERNS:
                if re.search(pat, title_low):
                    return False, "Older track rejected by default recency policy (use 'play old songs' to allow older tracks)", -80

            if upload_date and len(upload_date) >= 4 and upload_date[:4].isdigit():
                u_year = int(upload_date[:4])
                # Older releases (e.g. <= 2023 in 2026) rejected by default unless explicit old request
                if u_year <= (current_year - 3):
                    # Check if verified current viral blockbuster
                    is_viral_exception = any(k in full_text for k in cls.KNOWN_BLOCKBUSTERS) and (view_count is not None and view_count >= 10_000_000)
                    if not is_viral_exception:
                        return False, f"Track released in {u_year} rejected by default recency policy", -80

        # 4. Release Recency & Current Popularity / Trending Verification
        is_recent = False
        if upload_date and len(upload_date) >= 4 and upload_date[:4].isdigit():
            u_year = int(upload_date[:4])
            if u_year in (current_year, current_year - 1):  # 2026 or 2025
                is_recent = True
        elif any(str(y) in title_low for y in (current_year, current_year - 1)):
            is_recent = True
        else:
            # Assume recent if no past decade indicated
            is_recent = not any(re.search(r'\b19\d{2}\b|\b20[0-1]\d\b|\b202[0-3]\b', title_low) for _ in [1])

        # Credible current popularity signals (views, chart presence, verified blockbusters)
        has_popularity_evidence = False
        if view_count is not None and view_count >= 500_000:
            has_popularity_evidence = True
        elif candidate.get("is_chart_track"):
            has_popularity_evidence = True
        elif any(k in full_text for k in cls.KNOWN_BLOCKBUSTERS):
            has_popularity_evidence = True

        # Trending rule:
        # A 2025 song with verified popularity qualifies in 2026.
        # A 2026 song without credible popularity is NOT automatically labelled trending.
        # Title clickbait containing "trending", "viral", etc. is NOT sufficient evidence alone.
        is_trending = has_popularity_evidence and is_recent

        # Trending-only requests: reject tracks that lack credible trending evidence
        if trend_only and not is_trending:
            return False, "Candidate lacks credible current popularity/trend evidence for trending request", 0

        # Candidate Scoring
        final_score = lang_score
        if duration and 120 <= duration <= 360:
            final_score += 15
        elif duration and 60 <= duration <= 600:
            final_score += 5

        if is_recent:
            final_score += 15
        if is_trending:
            final_score += 20
        elif has_popularity_evidence:
            final_score += 10

        if any(w in title_low for w in ["official audio", "official lyric", "official video", "full audio"]):
            final_score += 10

        # Save metadata on candidate dictionary for rich TrackItem construction
        candidate["is_trending"] = is_trending
        candidate["is_recent"] = is_recent
        candidate["has_popularity_evidence"] = has_popularity_evidence
        candidate["trend_score"] = float(final_score)

        return True, f"Accepted individual song (Score: {final_score})", final_score


class MusicController:
    """
    Manages persistent music playback, stream extraction, and Alexa-style
    intelligent audio ducking coordinated with speech activity and TTS.
    """
    _instance: Optional[MusicController] = None
    _singleton_lock = threading.Lock()

    def __new__(cls) -> MusicController:
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = super(MusicController, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        self._lock = threading.RLock()
        self.music_queue: List[TrackItem] = []
        self.current_index: int = 0
        self._internal_is_playing: bool = False

        # Load configurations from settings or sensible defaults
        try:
            from instance.config import settings as cfg
            self._backend_pref = getattr(cfg, "MUSIC_AUDIO_BACKEND", "vlc")
            self._preferred_device = getattr(cfg, "MUSIC_AUDIO_DEVICE", "")
            self._user_volume: int = int(getattr(cfg, "MUSIC_DEFAULT_VOLUME", 70))
            self._ducking_target: float = float(getattr(cfg, "MUSIC_DUCKING_TARGET", 0.20))
            self._duck_attack_ms: int = int(getattr(cfg, "MUSIC_DUCK_ATTACK_MS", 250))
            self._restore_duration_ms: int = int(getattr(cfg, "MUSIC_RESTORE_DURATION_MS", 600))
        except Exception:
            self._backend_pref = "vlc"
            self._preferred_device = ""
            self._user_volume = 70
            self._ducking_target = 0.20
            self._duck_attack_ms = 250
            self._restore_duration_ms = 600

        self._effective_volume: float = float(self._user_volume)
        self._is_ducked: bool = False
        self._explicit_change_during_ducking: bool = False
        self._conceptual_state: str = MusicPlaybackState.USER_STOPPED

        # Fade thread synchronization
        self._fade_generation: int = 0
        self._fade_lock = threading.Lock()
        self._transition_token: int = 0

        # Initialize playback engine with device configuration
        self._audio_engine: BaseAudioPlayer = self._create_audio_engine(self._backend_pref, self._preferred_device)
        self._audio_engine.set_end_callback(self._on_track_end_reached)

        # Hook into voice lifecycle
        self._hook_voice_lifecycle()

        # Canonical session state, parser, and candidate validator
        self.session: MusicSessionState = MusicSessionState()
        self.parser: MusicCommandParser = MusicCommandParser()
        self.candidate_validator: CandidateValidator = CandidateValidator()
        self.language_validator: LanguageValidator = LanguageValidator()
        self.validator: CandidateValidator = self.candidate_validator
        self.last_status_message: Optional[str] = None

        self._initialized = True
        print(f"[MUSIC CONTROLLER] Initialized (Audio Backend: {type(self._audio_engine).__name__}, Vol: {self._user_volume}%)")

    def reset_session(self) -> None:
        """Resets the active music session state."""
        with self._lock:
            self.session = MusicSessionState()
            self.last_status_message = None

    def _create_audio_engine(self, backend_pref: str, preferred_device: str = "") -> BaseAudioPlayer:
        """Create appropriate audio player backend."""
        if backend_pref.lower() == "vlc" and vlc is not None:
            try:
                return VLCAudioPlayer(preferred_device=preferred_device)
            except Exception as e:
                print(f"[MUSIC CONTROLLER] VLC initialization failed ({e}). Falling back to mock player.")
                return MockAudioPlayer()
        return MockAudioPlayer()

    def set_audio_engine(self, engine: BaseAudioPlayer) -> None:
        """Allow injecting custom/mock audio engine for testing."""
        with self._lock:
            if self._audio_engine:
                try:
                    self._audio_engine.stop()
                except Exception:
                    pass
            self._audio_engine = engine
            self._audio_engine.set_end_callback(self._on_track_end_reached)

    def _hook_voice_lifecycle(self) -> None:
        """Register state listener with VoiceLifecycleManager."""
        try:
            from core.voice_lifecycle import get_voice_lifecycle
            vl = get_voice_lifecycle()
            vl.register_state_listener(self._on_voice_state_changed)
        except Exception as e:
            print(f"[MUSIC CONTROLLER] Could not hook voice lifecycle: {e}")

    # ── State Properties ───────────────────────────────────────────────────────
    @property
    def is_playing(self) -> CallableBool:
        if self._audio_engine:
            return CallableBool(1 if self._audio_engine.is_playing() else 0)
        return CallableBool(1 if self._internal_is_playing else 0)

    @is_playing.setter
    def is_playing(self, val: bool) -> None:
        self._internal_is_playing = bool(val)

    @property
    def playback_state(self) -> str:
        return self._conceptual_state

    def is_active(self) -> bool:
        """Returns True if music is actively playing or currently ducked."""
        if self._conceptual_state in (MusicPlaybackState.USER_PAUSED, MusicPlaybackState.USER_STOPPED):
            return False
        return self.is_playing or self._is_ducked

    # ── Voice Lifecycle Callback (Ducking Coordination) ────────────────────────
    def _on_voice_state_changed(self, state: str, message: str) -> None:
        """
        Coordinates intelligent volume ducking with assistant lifecycle:
          - 'listening'  -> Speech detected: lower volume smoothly without pausing.
          - 'processing' -> Utterance ending, recognition in progress: keep ducked.
          - 'speaking'   -> Assistant TTS speaking: keep ducked.
          - 'idle'       -> Interaction completed: restore volume smoothly.
          - 'error'      -> Speech error / noise: restore volume smoothly.
        """
        # If user explicitly paused or stopped, do not react to ambient voice
        if self._conceptual_state in (MusicPlaybackState.USER_PAUSED, MusicPlaybackState.USER_STOPPED):
            return

        # Only duck/restore if music is playing or ducked
        if not self.is_playing and not self._is_ducked:
            return

        if state == "listening":
            self._conceptual_state = MusicPlaybackState.SPEECH_DETECTED
            self.duck_volume()
        elif state == "processing":
            if self._is_ducked:
                self._conceptual_state = MusicPlaybackState.COMMAND_PROCESSING
        elif state == "speaking":
            if self._is_ducked:
                self._conceptual_state = MusicPlaybackState.ASSISTANT_SPEAKING
        elif state in ("idle", "error"):
            if self._is_ducked:
                self.restore_volume()

    # ── Volume Ducking & Smooth Fading ─────────────────────────────────────────
    def duck_volume(self) -> None:
        """Smoothly ducks music volume without pausing playback."""
        with self._lock:
            if self._is_ducked:
                return
            if not self.is_playing:
                return
            self._is_ducked = True
            self._explicit_change_during_ducking = False
            duck_target = max(5, int(self._user_volume * self._ducking_target))
            self._fade_volume(duck_target, duration_ms=self._duck_attack_ms)

    def restore_volume(self) -> None:
        """Smoothly restores music volume back to latest user-selected volume."""
        with self._lock:
            if not self._is_ducked:
                return
            self._is_ducked = False
            self._conceptual_state = MusicPlaybackState.RESTORING_VOLUME
            target_vol = self._user_volume
            self._fade_volume(target_vol, duration_ms=self._restore_duration_ms)

    def _fade_volume(self, target_volume: int, duration_ms: int) -> None:
        """Smoothly interpolates volume in a background thread."""
        clean_target = max(0, min(100, int(target_volume)))
        with self._fade_lock:
            self._fade_generation += 1
            gen = self._fade_generation

        def _worker():
            start_vol = self._effective_volume
            step_ms = 25
            steps = max(1, int(duration_ms / step_ms))
            delta = (clean_target - start_vol) / float(steps)

            for step in range(1, steps + 1):
                time.sleep(step_ms / 1000.0)
                with self._fade_lock:
                    if self._fade_generation != gen:
                        return  # Superseded by newer volume change or duck/restore
                cur_vol = start_vol + delta * step
                self._effective_volume = cur_vol
                self._audio_engine.set_volume(int(round(cur_vol)))

            self._effective_volume = float(clean_target)
            self._audio_engine.set_volume(clean_target)
            with self._lock:
                if not self._is_ducked and self.is_playing:
                    self._conceptual_state = MusicPlaybackState.NORMAL_PLAYBACK

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    # ── Incidental Speech Detection ────────────────────────────────────────────
    def is_addressed_to_assistant(self, text: str) -> bool:
        """
        Distinguishes speech addressed to the assistant from incidental chatter.
        Evaluates wake word, assistant name, explicit PTT, media commands, and system queries.
        """
        if not text or not text.strip():
            return False

        clean = text.lower().strip()

        # 1. Check if Push-to-Talk was held
        try:
            from legacy.sst import is_ptt_held
            if is_ptt_held():
                return True
        except Exception:
            pass

        # 2. Check for assistant name or configured wake words
        try:
            from core.unified_command_router import contains_assistant_name
            if contains_assistant_name(clean):
                return True
        except Exception:
            pass

        # Check explicit naming tokens
        words = re.findall(r'\b\w+\b', clean)
        common_names = {"friday", "friay", "fridy", "trevon", "assistant", "nova", "alexa", "siri", "computer"}
        if any(w in common_names for w in words):
            return True

        # 3. Explicit Music & Playback Commands
        media_keywords = [
            "pause", "resume", "stop", "unpause", "play", "skip", "next song",
            "next track", "previous song", "prev track", "replay", "louder",
            "quieter", "mute", "unmute", "turn it up", "turn it down",
            "turn up", "turn down", "set volume", "lower volume", "raise volume",
            "what song", "what's playing", "current song", "stop playing songs",
            "stop playing", "stop music", "pause music", "resume music"
        ]
        for kw in media_keywords:
            if re.search(r'\b' + re.escape(kw) + r'\b', clean):
                return True

        # 4. Explicit system command prefixes
        system_prefixes = (
            "what is", "what's", "when is", "where is", "who is", "how do", "how is",
            "set a", "set reminder", "set alarm", "set timer", "remind me",
            "open", "close", "launch", "tell me", "calculate", "search for",
            "create", "read my notes", "take a note"
        )
        if any(clean.startswith(prefix) for prefix in system_prefixes):
            return True

        return False

    # ── Query & Language Extraction ───────────────────────────────────────────
    def _ensure_yt_dlp(self) -> bool:
        global yt_dlp
        if yt_dlp is None:
            if install_missing_package("yt-dlp"):
                try:
                    import yt_dlp
                except ImportError:
                    pass
        return yt_dlp is not None

    def extract_language(self, command: str) -> Optional[str]:
        parsed = self.parser.parse(command, self.session)
        return parsed.language

    def extract_song_query(self, command: str) -> str:
        parsed = self.parser.parse(command, self.session)
        return parsed.exact_song_title or parsed.clean_query

    def build_smart_query(self, command: str) -> Tuple[str, Optional[str]]:
        parsed = self.parser.parse(command, self.session)
        return parsed.clean_query, parsed.language

    def _get_flat_ydl_opts(self) -> Dict[str, Any]:
        """Provides yt-dlp search options with supported JS runtime and player clients."""
        opts: Dict[str, Any] = {
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
            "extract_flat": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web"]
                }
            }
        }
        if shutil.which("node"):
            opts["js_runtimes"] = {"node": {}}
        return opts

    def _get_ydl_opts(self) -> Dict[str, Any]:
        """Provides yt-dlp resolution options requesting direct playable audio streams."""
        opts: Dict[str, Any] = {
            "format": "bestaudio/best",
            "quiet": True,
            "noplaylist": True,
            "skip_download": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web"]
                }
            }
        }
        if shutil.which("node"):
            opts["js_runtimes"] = {"node": {}}
        return opts

    def get_songs(
        self,
        query: str,
        target_lang: Optional[str] = None,
        artist: Optional[str] = None,
        exact_title: Optional[str] = None,
        genre: Optional[str] = None,
        allow_older: bool = False,
        era_preference: str = "latest",
        trend_only: bool = False
    ) -> List[TrackItem]:
        """
        Fetches full-length individual songs matching query and strictly validates candidates
        against target language, artist, exact title, genre, individual-song, recency, and trending constraints.
        Discards compilations, jukeboxes, non-stop mixes, teasers, and unverified candidates.
        Performs canonical song title deduplication to avoid duplicate uploads.
        """
        if not self._ensure_yt_dlp():
            return []

        ydl_opts = self._get_flat_ydl_opts()

        current_year = datetime.now().year
        recent_years = [str(current_year), str(current_year - 1)]

        safe_q = _safe_str(query)
        print(f"[MUSIC SEARCH] Fetching candidate tracks: '{safe_q}' (Lang: {target_lang}, Exact: {exact_title}, Era: {era_preference})")
        best_by_canonical_key: Dict[str, Tuple[int, TrackItem]] = {}
        trending_verified_count = 0

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                search_query = query
                # Only append recency context if not exact title and not already specified
                if not exact_title and era_preference == "latest" and not any(year in search_query for year in recent_years):
                    search_query += f" {current_year}"

                result = ydl.extract_info(f"ytsearch30:{search_query}", download=False)

                for video in result.get("entries", []):
                    title = video.get("title", "")
                    title_lower = title.lower()
                    duration = video.get("duration", 0) or 0
                    upload_date = str(video.get("upload_date") or "")
                    view_count = video.get("view_count")

                    # 1. Filter out teasers/promos or clips under 30s
                    if duration is not None and duration < 30:
                        continue
                    if any(w in title_lower for w in ["teaser", "promo", "short clip"]):
                        continue

                    # 2. Strict Candidate Validation
                    cand_dict = {
                        "title": title,
                        "channel": video.get("channel") or video.get("uploader") or "",
                        "description": video.get("description") or "",
                        "tags": video.get("tags") or [],
                        "duration": duration,
                        "upload_date": upload_date,
                        "view_count": view_count
                    }
                    effective_genre = genre or ("classical" if any(w in query.lower() for w in ["classical", "symphony"]) else None)
                    is_valid, reason, val_score = self.validator.validate_candidate(
                        cand_dict,
                        target_lang=target_lang,
                        artist=artist,
                        exact_title=exact_title,
                        genre=effective_genre,
                        allow_older=allow_older,
                        era_preference=era_preference,
                        trend_only=trend_only,
                        current_year=current_year
                    )

                    safe_title = _safe_str(title)
                    if not is_valid:
                        if hasattr(self, "session") and self.session:
                            self.session.rejected_candidates.append({
                                "title": safe_title,
                                "reason": reason
                            })
                        print(f"[MUSIC VALIDATOR] Rejected '{safe_title}': {reason}")
                        continue

                    print(f"[MUSIC VALIDATOR] Accepted '{safe_title}': {reason}")

                    # 3. Rich Candidate Item Construction
                    url = video.get("url") or video.get("webpage_url")
                    if url and not url.startswith("http"):
                        url = f"https://www.youtube.com/watch?v={url}"

                    is_tr = bool(cand_dict.get("is_trending", False))
                    if is_tr:
                        trending_verified_count += 1

                    item = TrackItem(
                        url,
                        title=title or "YouTube Track",
                        duration=duration or 0,
                        artist=cand_dict.get("channel") or artist,
                        upload_date=upload_date,
                        view_count=view_count,
                        is_trending=is_tr,
                        trend_score=float(cand_dict.get("trend_score", val_score)),
                        playback_status="pending"
                    )

                    # 4. Deduplication by Canonical Song Key
                    canonical_key = _canonical_song_key(title)
                    if canonical_key not in best_by_canonical_key or val_score > best_by_canonical_key[canonical_key][0]:
                        best_by_canonical_key[canonical_key] = (val_score, item)

        except Exception as e:
            print(f"[ERROR] Failed to fetch songs: {e}")

        # Check trend verification status
        if trend_only and trending_verified_count == 0:
            if hasattr(self, "session") and self.session:
                self.session.trend_verification_limited = True
            print("[MUSIC] Note: Reliable current trend verification was limited for candidates.")

        if not best_by_canonical_key:
            safe_l = _safe_str(target_lang or "requested")
            print(f"[MUSIC SEARCH] Zero valid candidates passed verification for {safe_l} songs.")
            return []

        scored_candidates = sorted(best_by_canonical_key.values(), key=lambda x: x[0], reverse=True)
        return [c[1] for c in scored_candidates]

    def _resolve_stream_url(self, track: TrackItem) -> Optional[str]:
        """
        Extracts playable direct audio stream using yt-dlp incrementally.
        Caches stream URL and auto-refreshes if expired.
        Extracts format_id, audio codec, and client User-Agent.
        """
        if not self._ensure_yt_dlp():
            return None

        now = time.time()
        # If already resolved and has >60 seconds validity, reuse
        if track.stream_url and track.expires_at > (now + 60):
            return track.stream_url

        url = str(track)
        ydl_opts = self._get_ydl_opts()

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                stream_url = info.get("url")
                format_id = info.get("format_id")
                acodec = info.get("acodec")
                http_headers = info.get("http_headers", {})
                user_agent = http_headers.get("User-Agent")

                # Validate audio stream availability; inspect formats if main url lacks audio
                if (not stream_url or acodec == "none") and "formats" in info:
                    audio_formats = [
                        f for f in info["formats"]
                        if f.get("acodec") != "none" and f.get("url")
                    ]
                    if audio_formats:
                        audio_formats.sort(
                            key=lambda x: (
                                0 if x.get("url", "").endswith(".m3u8") else 1,
                                x.get("abr") or x.get("tbr") or 0
                            ),
                            reverse=True
                        )
                        best_f = audio_formats[0]
                        stream_url = best_f.get("url")
                        format_id = best_f.get("format_id")
                        acodec = best_f.get("acodec")
                        if not user_agent and best_f.get("http_headers"):
                            user_agent = best_f["http_headers"].get("User-Agent")

                if stream_url:
                    track.stream_url = stream_url
                    track.format_id = str(format_id or "")
                    track.acodec = str(acodec or "")
                    track.user_agent = user_agent
                    expires_at = now + 3600.0  # default 1 hour
                    m = re.search(r'[?&]expire=(\d+)', stream_url)
                    if m:
                        try:
                            expires_at = float(m.group(1))
                        except Exception:
                            pass
                    track.expires_at = expires_at
                    if not track.title or track.title == "YouTube Track":
                        track.title = info.get("title", track.title)
                    if not track.duration:
                        track.duration = info.get("duration", track.duration)
                    return stream_url
                else:
                    safe_title = _safe_str(getattr(track, 'title', 'Current Track'))
                    print(f"[MUSIC DIAGNOSTIC] No playable audio format returned for '{safe_title}'.")
        except Exception as e:
            safe_title = _safe_str(getattr(track, 'title', 'Current Track'))
            print(f"[MUSIC DIAGNOSTIC] Stream resolution error for '{safe_title}': {e}")

        return None

    # ── Playback Controls ──────────────────────────────────────────────────────
    def play_music(self, raw_command: str) -> bool:
        """
        Main entry point for music requests and transport commands.
        Parses command deterministically, enforces language/queue constraints,
        and routes transport actions without triggering web searches.
        """
        cmd = self.parser.parse(raw_command, self.session)
        print(f"[MUSIC ROUTER] Parsed input: '{raw_command}' -> Action: {cmd.transport_action} | IsTransport: {cmd.is_transport} | Video: {cmd.is_video_requested}")

        # 1. Handle Transport Commands Immediately (Never search YouTube)
        if cmd.is_transport:
            if cmd.transport_action == "stop":
                self.media_stop()
                self.last_status_message = "Stopped media playback."
                return True
            elif cmd.transport_action in ("pause", "resume"):
                self.last_status_message = self.toggle_play_pause()
                return True
            elif cmd.transport_action in ("next", "skip"):
                self.last_status_message = self.next_song()
                return True
            elif cmd.transport_action in ("previous", "prev"):
                self.last_status_message = self.previous_song()
                return True
            elif cmd.transport_action == "queue_status":
                st = self.get_queue_status()
                self.last_status_message = st.get("message")
                return True
            elif cmd.transport_action == "volume_up":
                self.last_status_message = self.volume_up()
                return True
            elif cmd.transport_action == "volume_down":
                self.last_status_message = self.volume_down()
                return True
            elif cmd.transport_action == "volume_mute":
                self.last_status_message = self.volume_mute()
                return True

        # 2. Handle Video Request (Audio-only is default; video only when explicitly requested)
        if cmd.is_video_requested:
            return self.play_video(raw_command)

        # 3. Update Canonical Session State
        # Hard language constraint: explicit language overrides; otherwise active constraint preserved
        if cmd.language:
            self.session.requested_language = cmd.language
        if cmd.artist:
            self.session.requested_artist = cmd.artist
        elif not self.session.active_session:
            self.session.requested_artist = None

        if cmd.genre:
            self.session.requested_genre = cmd.genre
        elif not self.session.active_session:
            self.session.requested_genre = None

        self.session.exact_song_requested = cmd.exact_song_title
        self.session.is_specific_song = bool(cmd.exact_song_title)
        self.session.era_preference = cmd.era_preference
        self.session.allow_older = cmd.allow_older
        self.session.trend_only = cmd.is_trending_requested
        self.session.trend_verification_limited = False
        self.session.user_query_raw = raw_command
        self.session.clean_search_query = cmd.clean_query
        self.session.search_attempts += 1
        self.session.rejected_candidates = []

        print(f"[MUSIC SESSION] Active Constraints: Lang={self.session.requested_language} | Artist={self.session.requested_artist} | Genre={self.session.requested_genre} | Exact={self.session.exact_song_requested} | Era={self.session.era_preference} | AllowOlder={self.session.allow_older}")
        print(f"[MUSIC SEARCH] Executing query: '{cmd.clean_query}'")

        # 4. Fetch and Validate Candidates
        songs = self.get_songs(
            cmd.clean_query,
            target_lang=self.session.requested_language,
            artist=self.session.requested_artist,
            exact_title=self.session.exact_song_requested,
            genre=self.session.requested_genre,
            allow_older=self.session.allow_older,
            era_preference=self.session.era_preference,
            trend_only=self.session.trend_only
        )

        if not songs:
            lang_str = self.session.requested_language.capitalize() if self.session.requested_language else ""
            if lang_str:
                self.last_status_message = f"Could not find any verified {lang_str} songs matching your request."
            elif self.session.exact_song_requested:
                self.last_status_message = f"Could not find verified song '{self.session.exact_song_requested}'."
            else:
                self.last_status_message = f"Could not find verified songs for '{raw_command}'."
            print(f"[MUSIC] {self.last_status_message}")
            return False

        # 5. Build Queue
        if self.session.is_specific_song:
            # Exact song request: Keep the exact match at the front! Do not shuffle away!
            self.music_queue = songs[:20]
        else:
            # Playlist session: build queue of 10-20 tracks with gentle shuffle of top pool
            top_pool = songs[:min(len(songs), 6)]
            random.shuffle(top_pool)
            self.music_queue = (top_pool + songs[min(len(songs), 6):])[:20]

        self.current_index = 0
        self.session.active_session = True

        res = self.play_current()
        if res:
            base_msg = f"Playing '{self.get_current_track_title()}'."
            if self.session.trend_verification_limited:
                base_msg += " (Note: trend verification is limited due to available metadata)"
            self.last_status_message = base_msg
        else:
            self.last_status_message = "Failed to start music playback."
        return res

    def play_video(self, raw_command: str) -> bool:
        """
        Opens a video interface in the default browser ONLY when explicitly requested.
        Stops background audio playback to avoid audio collision.
        """
        import urllib.parse
        import webbrowser

        cmd = self.parser.parse(raw_command, self.session)
        clean_q = cmd.clean_query or raw_command

        # Stop active audio engine
        self.media_stop()

        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(clean_q)}"
        safe_q = _safe_str(clean_q)
        print(f"[MUSIC VIDEO] Opening video interface for explicit request: '{safe_q}'")
        try:
            webbrowser.open(url)
            self.last_status_message = f"Opened video for '{safe_q}'."
            return True
        except Exception as e:
            print(f"[MUSIC VIDEO] Failed to open browser: {e}")
            self.last_status_message = f"Failed to open video for '{safe_q}'."
            return False

    def play_current(self) -> bool:
        """Plays the current track in the queue using dedicated audio-only playback with startup verification."""
        with self._lock:
            if not self.music_queue:
                return False
            if not (0 <= self.current_index < len(self.music_queue)):
                return False

            raw_item = self.music_queue[self.current_index]
            if not isinstance(raw_item, TrackItem):
                url_str = str(raw_item)
                if not url_str.startswith("http"):
                    url_str = f"https://www.youtube.com/watch?v={url_str}"
                track = TrackItem(url_str, title=getattr(raw_item, 'title', 'Current Track'))
                self.music_queue[self.current_index] = track
            else:
                track = raw_item

            safe_title = _safe_str(getattr(track, 'title', 'Current Track'))

            try:
                stream_url = self._resolve_stream_url(track)
            except Exception as e:
                print(f"[MUSIC DIAGNOSTIC] Stream resolution exception for '{safe_title}': {e}")
                stream_url = None

            if not stream_url:
                print(f"[MUSIC DIAGNOSTIC] Stream URL could not be resolved for '{safe_title}'. Skipping to next track.")
                if self.current_index < len(self.music_queue) - 1:
                    self.current_index += 1
                    return self.play_current()
                return False

            # Check voice state to avoid blasting audio if assistant is already interacting
            try:
                from core.voice_lifecycle import get_voice_lifecycle
                vl = get_voice_lifecycle()
                cur_voice_state = vl.get_state()
            except Exception:
                cur_voice_state = "idle"

            if cur_voice_state in ("listening", "processing", "speaking"):
                self._is_ducked = True
                target_vol = max(5, int(self._user_volume * self._ducking_target))
                self._conceptual_state = (
                    MusicPlaybackState.ASSISTANT_SPEAKING if cur_voice_state == "speaking"
                    else MusicPlaybackState.SPEECH_DETECTED
                )
            else:
                target_vol = int(round(self._effective_volume if self._is_ducked else self._user_volume))

            ua = getattr(track, 'user_agent', None)
            success = self._audio_engine.play(stream_url, volume=target_vol, user_agent=ua)
            if success:
                self._internal_is_playing = True
                if not self._is_ducked:
                    self._conceptual_state = MusicPlaybackState.NORMAL_PLAYBACK

                diag = getattr(self._audio_engine, 'get_diagnostics', lambda: {})()
                dev_desc = diag.get('selected_device', 'Default')
                ttfa = diag.get('time_to_first_audio_ms')
                ttfa_str = f"{ttfa:.1f}" if ttfa is not None else "N/A"
                fmt = getattr(track, 'format_id', 'unknown') or 'unknown'
                codec = getattr(track, 'acodec', 'unknown') or 'unknown'

                print(f"[MUSIC] Audio playback started: '{safe_title}' (Vol: {target_vol}%)")
                print(f"[MUSIC DIAGNOSTIC] Codec: {codec} | Format: {fmt} | Output: {dev_desc} | Vol: {target_vol}% | TTFA: {ttfa_str}ms")

                # Record telemetry timestamps
                try:
                    from core.latency_instrumentation import get_current_tracker
                    tracker = get_current_tracker()
                    tracker.record("tts_playback_start_timestamp")
                    if ttfa is not None:
                        tracker.record("tts_first_audio_timestamp", time.monotonic() - (float(ttfa) / 1000.0))
                except Exception:
                    pass

                return True
            else:
                diag = getattr(self._audio_engine, 'get_diagnostics', lambda: {})()
                err_reason = diag.get('last_error', 'Audio engine failed to verify stream playback')
                print(f"[MUSIC DIAGNOSTIC] Playback failed for '{safe_title}'. Reason: {err_reason}")
                self._internal_is_playing = False
                self._conceptual_state = MusicPlaybackState.USER_STOPPED

                if self.current_index < len(self.music_queue) - 1:
                    print(f"[MUSIC] Attempting next track in queue...")
                    self.current_index += 1
                    return self.play_current()
                return False

    def search_and_play(self, query: str) -> str:
        """Searches and immediately plays song, returning status message."""
        success = self.play_music(f"play {query}")
        if success:
            title = self.get_current_track_title()
            return f"Playing '{title}'."
        return self.last_status_message or f"Could not find or play '{query}'."

    def toggle_play_pause(self) -> str:
        """Toggles between play and pause."""
        with self._lock:
            if self.is_playing:
                self._audio_engine.pause()
                self._internal_is_playing = False
                self._conceptual_state = MusicPlaybackState.USER_PAUSED
                return "Paused media playback."
            else:
                if not self.music_queue:
                    return "Queue is empty."
                self._audio_engine.resume()
                self._internal_is_playing = True
                self._conceptual_state = MusicPlaybackState.NORMAL_PLAYBACK
                return "Resumed media playback."

    def media_stop(self) -> str:
        """Stops media playback, deactivates active session, cancels any pending transitions, and clears queue."""
        with self._lock:
            self._transition_token = getattr(self, "_transition_token", 0) + 1
            self._audio_engine.stop()
            self._internal_is_playing = False
            self._is_ducked = False
            self._conceptual_state = MusicPlaybackState.USER_STOPPED
            self.music_queue.clear()
            self.current_index = 0
            if hasattr(self, "session") and self.session:
                self.session.active_session = False
            self.last_status_message = "Stopped media playback."
            return "Stopped media playback."

    def _replenish_queue(self) -> None:
        """
        Replenishes queue with 10-15 more tracks while strictly maintaining
        active session constraints (language, artist, genre, era preference, trending).
        """
        if not self.session or not self.session.active_session:
            return

        lang = self.session.requested_language
        artist = self.session.requested_artist
        genre = self.session.requested_genre
        allow_older = getattr(self.session, "allow_older", False)
        era_preference = getattr(self.session, "era_preference", "latest")
        trend_only = getattr(self.session, "trend_only", False)

        parts = []
        if artist:
            parts.append(artist)
        if genre:
            parts.append(genre)
        if lang:
            parts.append(lang.capitalize())
        if era_preference in ("old", "retro", "90s"):
            parts.append(f"{era_preference} hits")
        elif trend_only:
            parts.append("trending songs")
        else:
            parts.append("latest songs")
        parts.append("hit audio")
        rep_query = " ".join(parts)

        print(f"[MUSIC QUEUE] Replenishing queue with active session constraints: '{rep_query}' (Lang: {lang}, Era: {era_preference})")
        new_tracks = self.get_songs(
            rep_query,
            target_lang=lang,
            artist=artist,
            genre=genre,
            allow_older=allow_older,
            era_preference=era_preference,
            trend_only=trend_only
        )

        existing_urls = {str(t) for t in self.music_queue}
        existing_keys = {_canonical_song_key(getattr(t, 'title', '')) for t in self.music_queue}

        added = 0
        for track in new_tracks:
            t_url = str(track)
            c_key = _canonical_song_key(getattr(track, 'title', ''))
            if t_url not in existing_urls and c_key not in existing_keys:
                self.music_queue.append(track)
                existing_urls.add(t_url)
                existing_keys.add(c_key)
                added += 1
                if len(self.music_queue) >= 20:
                    break

        print(f"[MUSIC QUEUE] Replenishment complete: added {added} tracks. Queue now has {len(self.music_queue)} tracks.")

    def next_song(self) -> str:
        """Skips forward to next song, replenishing if queue is running low."""
        with self._lock:
            if not self.music_queue:
                return "Queue is empty."

            # If fewer than 3 tracks remain, replenish while preserving session constraints
            if len(self.music_queue) - (self.current_index + 1) < 3 and self.session and self.session.active_session:
                self._replenish_queue()

            if self.current_index < len(self.music_queue) - 1:
                self.current_index += 1
                success = self.play_current()
                if success:
                    return f"Playing next ({self.current_index + 1}/{len(self.music_queue)}): '{self.get_current_track_title()}'."
                else:
                    return "Failed to play next track in queue."
            return "End of queue."

    def previous_song(self) -> str:
        """Skips back to previous song."""
        with self._lock:
            if not self.music_queue:
                return "Queue is empty."
            if self.current_index > 0:
                self.current_index -= 1
                success = self.play_current()
                if success:
                    return f"Playing previous ({self.current_index + 1}/{len(self.music_queue)}): '{self.get_current_track_title()}'."
                else:
                    return "Failed to play previous track in queue."
            return "Beginning of queue."

    def media_next(self) -> str:
        return self.next_song()

    def media_previous(self) -> str:
        return self.previous_song()

    def _on_track_end_reached(self) -> None:
        """Automatic end-of-track progression preserving session constraints."""
        with self._lock:
            if self._conceptual_state == MusicPlaybackState.USER_STOPPED or not self._internal_is_playing or not self.music_queue:
                return

            current_token = getattr(self, "_transition_token", 0)

            # Replenish if low
            if len(self.music_queue) - (self.current_index + 1) < 3 and self.session and self.session.active_session:
                self._replenish_queue()

            if self._conceptual_state == MusicPlaybackState.USER_STOPPED or not self._internal_is_playing:
                return
            if current_token != getattr(self, "_transition_token", 0):
                return

            if self.current_index < len(self.music_queue) - 1:
                print("[MUSIC] Track completed. Auto-advancing to next song.")
                self.current_index += 1
                self.play_current()
            else:
                print("[MUSIC] Queue completed.")
                self._internal_is_playing = False
                self._conceptual_state = MusicPlaybackState.USER_STOPPED

    # ── Volume Controls ────────────────────────────────────────────────────────
    def set_volume(self, level: int) -> str:
        """
        Sets user-selected volume (0-100).
        If ducking is active, updates user volume, keeps song ducked at new relative level,
        and ensures restoration restores to the new user-selected volume.
        """
        with self._lock:
            clean_level = max(0, min(100, int(level)))
            self._user_volume = clean_level
            if self._is_ducked:
                self._explicit_change_during_ducking = True
                ducked_vol = max(5, int(clean_level * self._ducking_target))
                self._effective_volume = float(ducked_vol)
                self._audio_engine.set_volume(ducked_vol)
                return f"Set music volume to {clean_level}% (temporarily ducked to {ducked_vol}%)."
            else:
                self._effective_volume = float(clean_level)
                self._audio_engine.set_volume(clean_level)
                return f"Set music volume to {clean_level}%."

    def get_volume(self) -> int:
        return self._user_volume

    def volume_up(self, steps: int = 5) -> str:
        delta = max(1, min(25, steps)) * 2
        new_vol = min(100, self._user_volume + delta)
        self.set_volume(new_vol)
        return f"Turned volume up to {self._user_volume}%."

    def volume_down(self, steps: int = 5) -> str:
        delta = max(1, min(25, steps)) * 2
        new_vol = max(0, self._user_volume - delta)
        self.set_volume(new_vol)
        return f"Turned volume down to {self._user_volume}%."

    def volume_mute(self) -> str:
        with self._lock:
            cur = self._audio_engine.get_volume()
            if cur > 0:
                self._audio_engine.set_volume(0)
                return "Muted music playback."
            else:
                target = max(10, self._user_volume)
                self._audio_engine.set_volume(target)
                return f"Unmuted music playback (Volume: {target}%)."

    def seek(self, seconds: float) -> str:
        """Seek to position in seconds."""
        with self._lock:
            ms = int(seconds * 1000)
            if self._audio_engine.set_time(ms):
                return f"Seeked to {int(seconds)}s."
            return "Seeking not supported for current stream."

    # ── Status & Metadata ──────────────────────────────────────────────────────
    def get_current_track_title(self) -> str:
        if self.music_queue and 0 <= self.current_index < len(self.music_queue):
            item = self.music_queue[self.current_index]
            if hasattr(item, "title") and item.title:
                return item.title
            if isinstance(item, dict) and item.get("title"):
                return item["title"]
            return str(item)
        return "Unknown Track"

    def get_current_track(self) -> Optional[TrackItem]:
        """Returns the currently active TrackItem or None."""
        if self.music_queue and 0 <= self.current_index < len(self.music_queue):
            return self.music_queue[self.current_index]
        return None

    def get_diagnostics(self) -> Dict[str, Any]:
        """Provides rich structured playback telemetry, session constraints, and diagnostics."""
        diag = getattr(self._audio_engine, "get_diagnostics", lambda: {})()
        curr_track = self.get_current_track()
        pos_ms = self._audio_engine.get_time()
        ttfa = diag.get("time_to_first_audio_ms")
        sess_dict = self.session.to_dict(self) if hasattr(self, "session") and self.session else {}

        return {
            "track_title": getattr(curr_track, "title", "None"),
            "source": getattr(curr_track, "source", "youtube"),
            "format_id": getattr(curr_track, "format_id", "N/A"),
            "audio_codec": getattr(curr_track, "acodec", "N/A"),
            "stream_resolved": bool(getattr(curr_track, "stream_url", None)),
            "player_backend": type(self._audio_engine).__name__,
            "media_assigned": bool(getattr(self._audio_engine, "_stream_url", None)),
            "player_state": self._audio_engine.get_state(),
            "is_playing": bool(self.is_playing),
            "playback_position_ms": pos_ms,
            "position_advancing": bool(self.is_playing and pos_ms > 0),
            "time_to_first_audio_ms": ttfa,
            "selected_output_device": diag.get("selected_device", "Default"),
            "available_output_devices": diag.get("available_devices", []),
            "effective_volume": int(self._effective_volume),
            "user_volume": self._user_volume,
            "is_ducked": self._is_ducked,
            "conceptual_state": self._conceptual_state,
            "last_error": diag.get("last_error", None),
            "session": sess_dict,
            "parsed_constraints": {
                "language": getattr(self.session, "requested_language", None) if hasattr(self, "session") else None,
                "artist": getattr(self.session, "requested_artist", None) if hasattr(self, "session") else None,
                "genre": getattr(self.session, "requested_genre", None) if hasattr(self, "session") else None,
                "era_preference": getattr(self.session, "era_preference", "latest") if hasattr(self, "session") else "latest",
                "allow_older": getattr(self.session, "allow_older", False) if hasattr(self, "session") else False,
                "trend_only": getattr(self.session, "trend_only", False) if hasattr(self, "session") else False,
                "trend_verification_limited": getattr(self.session, "trend_verification_limited", False) if hasattr(self, "session") else False,
                "is_specific_song": getattr(self.session, "is_specific_song", False) if hasattr(self, "session") else False,
                "exact_song": getattr(self.session, "exact_song_requested", None) if hasattr(self, "session") else None,
                "clean_query": getattr(self.session, "clean_search_query", "") if hasattr(self, "session") else ""
            },
            "recent_rejections": getattr(self.session, "rejected_candidates", [])[-5:] if hasattr(self, "session") else [],
            "physical_audibility_verified": False,
            "audibility_note": "Audio stream decoded and progressing through Windows WASAPI output device; physical acoustic audibility depends on hardware speaker power/volume."
        }

    def get_queue_status(self) -> Dict[str, Any]:
        """Get complete queue metadata, detailed tracks list, and playback state."""
        total = len(self.music_queue)
        curr = self.current_index + 1 if total > 0 else 0
        state = "Playing" if self.is_playing else ("Paused" if self._conceptual_state == MusicPlaybackState.USER_PAUSED else "Stopped")
        title = self.get_current_track_title() if total > 0 else "None"
        if total == 0:
            msg = "The music queue is currently empty."
        else:
            msg = f"Queue status: Track {curr} of {total} - '{title}' ({state}, Volume: {self._user_volume}%)."

        tracks_summary = []
        for idx, t in enumerate(self.music_queue):
            status = "playing" if (self.is_playing and idx == self.current_index) else ("current" if idx == self.current_index else getattr(t, "playback_status", "pending"))
            tracks_summary.append({
                "index": idx + 1,
                "title": getattr(t, "title", str(t)),
                "artist": getattr(t, "artist", None),
                "duration": getattr(t, "duration", 0),
                "upload_date": getattr(t, "upload_date", ""),
                "view_count": getattr(t, "view_count", None),
                "is_trending": getattr(t, "is_trending", False),
                "trend_score": getattr(t, "trend_score", 0.0),
                "playback_status": status
            })

        return {
            "status": "success",
            "total_tracks": total,
            "queue_length": total,
            "current_track": curr,
            "current_title": title,
            "is_playing": bool(self.is_playing),
            "user_volume": self._user_volume,
            "effective_volume": int(self._effective_volume),
            "is_ducked": self._is_ducked,
            "conceptual_state": self._conceptual_state,
            "tracks": tracks_summary,
            "message": msg
        }


# Singleton accessor
_default_music_controller = MusicController()


def get_controller() -> MusicController:
    return _default_music_controller


def get_queue_status() -> Dict[str, Any]:
    return _default_music_controller.get_queue_status()


def get_playback_diagnostics() -> Dict[str, Any]:
    return _default_music_controller.get_diagnostics()


def media_stop() -> Dict[str, Any]:
    msg = _default_music_controller.media_stop()
    return {"status": "success", "message": msg}


def volume_up(steps: int = 5) -> Dict[str, Any]:
    msg = _default_music_controller.volume_up(steps)
    return {"status": "success", "message": msg}


def volume_down(steps: int = 5) -> Dict[str, Any]:
    msg = _default_music_controller.volume_down(steps)
    return {"status": "success", "message": msg}


def volume_mute() -> Dict[str, Any]:
    msg = _default_music_controller.volume_mute()
    return {"status": "success", "message": msg}


def set_volume(level: int) -> Dict[str, Any]:
    msg = _default_music_controller.set_volume(level)
    return {"status": "success", "message": msg}


def play_music(raw_command: str = "") -> bool:
    return _default_music_controller.play_music(raw_command or "trending latest songs")


def play_video(raw_command: str = "") -> bool:
    return _default_music_controller.play_video(raw_command)
