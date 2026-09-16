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

def get_controller():
    return MusicController()
