import sys
import time
import webbrowser
import subprocess
import random
from datetime import datetime

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

try:
    import yt_dlp
except ImportError:
    yt_dlp = None
    print(f"[DEBUG] yt-dlp import failed. Current Python: {sys.executable}")
    # Attempt one-time self-healing installation
    if install_missing_package("yt-dlp"):
        try:
            import yt_dlp
        except ImportError:
            pass

def build_music_query(text: str) -> str:
    """
    Generates intelligent, natural YouTube queries based on user intent.
    """
    text = text.lower().strip()
    
    if "trending" in text:
        return "trending songs"
    elif "latest" in text:
        return f"{text} songs"
    elif "telugu" in text:
        return "latest telugu songs"
    elif "hindi" in text:
        return "latest hindi songs"
    elif "english" in text:
        return "latest english songs"
    elif "hits" in text:
        return "top hits songs"
    elif "song" in text or "songs" in text:
        return text
    else:
        return f"{text} song"

def play_youtube(query: str):
    """
    Finds a recent, full-length video on YouTube and opens it directly using yt-dlp.
    Filters: Duration > 2 mins, No Shorts/Teasers.
    Selection: Random from top 20 results.
    """
    if not yt_dlp:
        print("[ERROR] yt-dlp is not installed. Continuous playback disabled.")
        return False

    print(f"[DEBUG] Searching YouTube via yt-dlp (ytsearch20): {query}")
    
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": True,
    }

    current_year = datetime.now().year

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Search for up to 20 results to pick a random good choice
            result = ydl.extract_info(f"ytsearch20:{query}", download=False)

            if "entries" not in result or not result["entries"]:
                print("[ERROR] No videos found")
                return False

            valid_videos = []

            for entry in result["entries"]:
                title = entry.get("title", "").lower()
                duration = entry.get("duration", 0)
                upload_date = entry.get("upload_date", "")

                # 1. Date Filter: Only last 2 years
                if upload_date:
                    try:
                        year = int(upload_date[:4])
                        if year < current_year - 2:
                            continue
                    except ValueError:
                        pass # If we can't parse date, we might still consider it based on duration
                
                # 2. Duration Filter: Skip short videos (< 2 minutes)
                if duration and duration < 120:
                    continue
                
                # 3. Content Filter: Skip teasers/promos/shorts
                if any(word in title for word in ["short", "teaser", "promo", "clip"]):
                    continue
                
                # 4. Success Case: Store as a valid candidate
                valid_videos.append(entry)

            if not valid_videos:
                print("[ERROR] No recent full-length songs found in candidates")
                # Fallback to the first entry if it's not a short (ignoring date if no other options)
                for entry in result["entries"]:
                    if (entry.get("duration") or 0) >= 120:
                        valid_videos.append(entry)
                        break

            if valid_videos:
                # 5. Randomized Selection from valid candidates
                selected = random.choice(valid_videos)
                video_url = selected.get("url") or selected.get("webpage_url")
                
                if video_url:
                    # If it's just a video ID, prefix it
                    if not video_url.startswith("http"):
                        video_url = f"https://www.youtube.com/watch?v={video_url}"
                        
                    print(f"[DEBUG] Randomly Playing Recent Selection: {video_url} (Title: {selected.get('title')})")
                    webbrowser.open(video_url)
                    return True
                
    except Exception as e:
        print(f"[ERROR] yt-dlp extraction failed: {e}")
    
    print("[ERROR] No suitable video found after filtering")
    return False

from modules.music.music_controller import get_controller

def handle_play_command(text: str) -> str:
    """
    Handles music playback by delegating to the language-aware music_controller.
    """
    from modules.music.music_controller import get_controller
    controller = get_controller()
    
    # Process "next" or "previous" directly
    if "next" in text.lower():
        return controller.next_song()
    elif "previous" in text.lower() or "prev" in text.lower():
        return controller.previous_song()
    
    success = controller.play_music(text)
    
    if success:
        return f"Starting a personalized music queue for your request."
    else:
        return f"Sorry, I couldn't find a high-quality selection for that music request."
