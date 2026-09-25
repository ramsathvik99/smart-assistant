import sys
import webbrowser
import subprocess
import random
from datetime import datetime

# Self-healing import for yt_dlp
try:
    import yt_dlp
except ImportError:
    yt_dlp = None

def install_missing_package(package_name: str):
    """Attempts to install a missing package for the current interpreter."""
    print(f"[SYSTEM] Attempting to install missing dependency: {package_name}...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
        print(f"[SYSTEM] Successfully installed {package_name}. Please restart the application for changes to take effect.")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to auto-install {package_name}: {e}")
        return False

class MusicController:
    """
    Manages a persistent music playback queue and controls.
    Spotify-like functionality for Nova with Language Awareness.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MusicController, cls).__new__(cls)
            cls._instance.music_queue = []
            cls._instance.current_index = 0
            cls._instance.is_playing = False
        return cls._instance

    def __init__(self):
        if not hasattr(self, 'music_queue'):
            self.music_queue = []
            self.current_index = 0
            self.is_playing = False

    def _ensure_yt_dlp(self):
        """Checks if yt-dlp is available, attempts auto-install if not."""
        global yt_dlp
        if yt_dlp is None:
            if install_missing_package("yt-dlp"):
                try:
                    import yt_dlp
                except ImportError:
                    pass
        return yt_dlp is not None

    def extract_language(self, command: str):
        """Identifies any supported language in the command."""
        command = command.lower()
        languages = ["telugu", "hindi", "tamil", "english", "malayalam", "kannada"]
        for lang in languages:
            if lang in command:
                return lang
        return None

    def extract_song_query(self, command: str):
        """Cleans noise words from the command to isolate the song intent."""
        command = command.lower()
        remove_words = ["play", "song", "songs", "in", "music", "version", "original"]
        for word in remove_words:
            command = command.replace(word, "")
        return command.strip()

    def build_smart_query(self, command: str):
        """Builds a high-precision YouTube query based on language and intent."""
        song = self.extract_song_query(command)
        lang = self.extract_language(command)
        
        if not song:
            return "trending latest songs", None

        if lang:
            return f"{song} {lang} version official song full", lang
        else:
            return f"{song} official song full video", None

    def get_songs(self, query: str, target_lang: str = None):
        """
        Fetches 20 full-length songs. 
        Biases towards recent years and rewards language matches.
        """
        if not self._ensure_yt_dlp():
            return []

        ydl_opts = {
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
            "extract_flat": True,
        }

        current_year = datetime.now().year
        recent_years = [str(current_year), str(current_year-1), str(current_year-2)]
        
        print(f"[DEBUG] Fetching songs for queue (ytsearch20): {query}")
        
        scored_candidates = []

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Add current year to query for freshness biasing if not already present
                search_query = query
                if not any(year in search_query for year in recent_years):
                    search_query += f" {current_year}"

                result = ydl.extract_info(f"ytsearch20:{search_query}", download=False)

                for video in result.get("entries", []):
                    title = video.get("title", "").lower()
                    duration = video.get("duration", 0)
                    upload_date = video.get("upload_date", "")

                    if duration is None or duration < 120 or duration > 300:
                        continue
                    if any(word in title for word in ["short", "teaser", "promo", "clip"]):
                        continue

                    # --- SCORING ---
                    score = 0
                    
                    # 1. Language Match Boost (+10)
                    if target_lang and target_lang in title:
                        score += 10
                    elif target_lang and not any(l in title for l in ["telugu", "hindi", "tamil", "english"]):
                        # Passive boost if no conflicting language is mentioned
                        score += 2

                    # 2. Ideal duration (2.5 - 4.3 min)
                    if 150 <= duration <= 260:
                        score += 5
                    
                    # 3. Quality Keywords
                    if any(w in title for w in ["official", "full", "audio", "original"]):
                        score += 3

                    # 4. Freshness
                    if any(year in title for year in recent_years):
                        score += 2
                    if upload_date and upload_date.startswith(tuple(recent_years)):
                        score += 3

                    scored_candidates.append((score, video.get("url") or video.get("webpage_url")))

        except Exception as e:
            print(f"[ERROR] Failed to fetch songs: {e}")

        if not scored_candidates:
            return []

        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        return [c[1] for c in scored_candidates]

    def play_music(self, raw_command: str):
        """Main entry point: processes command, builds queue, and plays first song."""
        query, target_lang = self.build_smart_query(raw_command)
        
        songs = self.get_songs(query, target_lang)
        if not songs: return False

        # Varied playback: Take top 8 high-scoring songs and shuffle for diversity
        top_pool = songs[:min(len(songs), 8)]
        random.shuffle(top_pool)
        
        self.music_queue = top_pool + songs[min(len(songs), 8):]
        self.current_index = 0
        return self.play_current()

    def play_current(self):
        """Opens current URL in browser."""
        if not self.music_queue: return False
        if 0 <= self.current_index < len(self.music_queue):
            url = self.music_queue[self.current_index]
            if not url.startswith("http"):
                url = f"https://www.youtube.com/watch?v={url}"
            webbrowser.open(url)
            self.is_playing = True
            return True
        return False

    def next_song(self):
        """Skips forward."""
        if not self.music_queue: return "Queue is empty."
        if self.current_index < len(self.music_queue) - 1:
            self.current_index += 1
            self.play_current()
            return f"Playing next ({self.current_index+1}/{len(self.music_queue)})."
        return "End of queue."

    def previous_song(self):
        """Skips back."""
        if not self.music_queue: return "Queue is empty."
        if self.current_index > 0:
            self.current_index -= 1
            self.play_current()
            return f"Playing previous ({self.current_index+1}/{len(self.music_queue)})."
        return "Beginning of queue."

    def toggle_play_pause(self):
        """Dispatches global Windows Media Play/Pause key (Spotify, YouTube, Media players)."""
        try:
            import ctypes
            VK_MEDIA_PLAY_PAUSE = 0xB3
            KEYEVENTF_KEYUP = 0x0002
            ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, KEYEVENTF_KEYUP, 0)
            self.is_playing = not self.is_playing
            return "Toggled playback (Play/Pause)."
        except Exception as e:
            return f"Failed to toggle playback: {e}"

    def media_next(self):
        """Dispatches global Windows Media Next Track key."""
        try:
            import ctypes
            VK_MEDIA_NEXT_TRACK = 0xB0
            KEYEVENTF_KEYUP = 0x0002
            ctypes.windll.user32.keybd_event(VK_MEDIA_NEXT_TRACK, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_MEDIA_NEXT_TRACK, 0, KEYEVENTF_KEYUP, 0)
            return "Skipped to next track."
        except Exception as e:
            return f"Failed to skip track: {e}"

    def media_previous(self):
        """Dispatches global Windows Media Previous Track key."""
        try:
            import ctypes
            VK_MEDIA_PREV_TRACK = 0xB1
            KEYEVENTF_KEYUP = 0x0002
            ctypes.windll.user32.keybd_event(VK_MEDIA_PREV_TRACK, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_MEDIA_PREV_TRACK, 0, KEYEVENTF_KEYUP, 0)
            return "Returned to previous track."
        except Exception as e:
            return f"Failed to return to previous track: {e}"

    def media_stop(self):
        """Dispatches global Windows Media Stop key."""
        try:
            import ctypes
            VK_MEDIA_STOP = 0xB2
            KEYEVENTF_KEYUP = 0x0002
            ctypes.windll.user32.keybd_event(VK_MEDIA_STOP, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_MEDIA_STOP, 0, KEYEVENTF_KEYUP, 0)
            self.is_playing = False
            return "Stopped media playback."
        except Exception as e:
            return f"Failed to stop playback: {e}"

    def volume_up(self, steps: int = 5):
        """Dispatches Windows master volume up key events."""
        try:
            import ctypes
            VK_VOLUME_UP = 0xAF
            KEYEVENTF_KEYUP = 0x0002
            for _ in range(max(1, min(25, steps))):
                ctypes.windll.user32.keybd_event(VK_VOLUME_UP, 0, 0, 0)
                ctypes.windll.user32.keybd_event(VK_VOLUME_UP, 0, KEYEVENTF_KEYUP, 0)
            return f"Turned volume up by {steps} steps."
        except Exception as e:
            return f"Failed to turn volume up: {e}"

    def volume_down(self, steps: int = 5):
        """Dispatches Windows master volume down key events."""
        try:
            import ctypes
            VK_VOLUME_DOWN = 0xAE
            KEYEVENTF_KEYUP = 0x0002
            for _ in range(max(1, min(25, steps))):
                ctypes.windll.user32.keybd_event(VK_VOLUME_DOWN, 0, 0, 0)
                ctypes.windll.user32.keybd_event(VK_VOLUME_DOWN, 0, KEYEVENTF_KEYUP, 0)
            return f"Turned volume down by {steps} steps."
        except Exception as e:
            return f"Failed to turn volume down: {e}"

    def volume_mute(self):
        """Dispatches Windows master volume mute toggle."""
        try:
            import ctypes
            VK_VOLUME_MUTE = 0xAD
            KEYEVENTF_KEYUP = 0x0002
            ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, KEYEVENTF_KEYUP, 0)
            return "Toggled volume mute."
        except Exception as e:
            return f"Failed to toggle mute: {e}"

    def get_queue_status(self):
        """Get the current queue length, active index, and playing state."""
        total = len(self.music_queue)
        curr = self.current_index + 1 if total > 0 else 0
        state = "Playing" if self.is_playing else "Paused/Stopped"
        if total == 0:
            msg = "The music queue is currently empty."
        else:
            msg = f"Queue status: Track {curr} of {total} ({state})."
        return {
            "status": "success",
            "total_tracks": total,
            "queue_length": total,
            "current_track": curr,
            "is_playing": self.is_playing,
            "message": msg
        }

_default_music_controller = MusicController()

def get_controller():
    return _default_music_controller

def get_queue_status():
    return _default_music_controller.get_queue_status()

def media_stop():
    msg = _default_music_controller.media_stop()
    return {"status": "success", "message": msg}

def volume_up(steps: int = 5):
    msg = _default_music_controller.volume_up(steps)
    return {"status": "success", "message": msg}

def volume_down(steps: int = 5):
    msg = _default_music_controller.volume_down(steps)
    return {"status": "success", "message": msg}

def volume_mute():
    msg = _default_music_controller.volume_mute()
    return {"status": "success", "message": msg}
