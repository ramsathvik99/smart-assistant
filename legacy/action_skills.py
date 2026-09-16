import os
import time
import webbrowser
import subprocess
import requests
import datetime
from zoneinfo import ZoneInfo

# Import recommendation skills
try:
    from skills.music_recommendation import recommend_music as music_recommend
    from skills.movie_recommendation import recommend_movie as movie_recommend
    from skills.life_recommendation import life_recommendation as life_recommend
    RECOMMENDATION_SKILLS_AVAILABLE = True
except ImportError as e:
    print(f"[RECOMMENDATION SKILLS] Import failed: {e}")
    RECOMMENDATION_SKILLS_AVAILABLE = False
    
    # Fallback functions
    def music_recommend(context=None, genre_or_mood=None):
        return "Music recommendation system is not available."
    
    def movie_recommend(context=None, genre_or_mood=None):
        return "Movie recommendation system is not available."
    
    def life_recommend(context=None, specific_need=None):
        return "Life recommendation system is not available."

# Lazy import wrapper for joke to avoid top-level TTS/Playsound imports hanging
def get_random_joke_wrapper():
    try:
        import communication.responses as cr
        return cr.get_random_joke()
    except (ImportError, Exception):
        return "I don't have a joke right now."

# ======================================================
# RECOMMENDATION SKILL FUNCTIONS
# ======================================================
def recommend_music_skill(genre_or_mood=None):
    """Music recommendation skill with context awareness"""
    if not RECOMMENDATION_SKILLS_AVAILABLE:
        return "Music recommendation system is not available."
    
    # Build context from available information
    context = {
        'time': datetime.now(ZoneInfo("Asia/Kolkata")).hour,
        'current_app': '',  # Could be enhanced with active window detection
        'mood': '',  # Could be enhanced with mood detection,
        'command': f"recommend music {genre_or_mood}" if genre_or_mood else "recommend music"
    }
    
    return music_recommend(context, genre_or_mood)

def recommend_movie_skill(genre_or_mood=None):
    """Movie recommendation skill with context awareness"""
    if not RECOMMENDATION_SKILLS_AVAILABLE:
        return "Movie recommendation system is not available."
    
    # Build context from available information
    context = {
        'time': datetime.now(ZoneInfo("Asia/Kolkata")).hour,
        'current_app': '',
        'mood': '',
        'command': f"recommend movie {genre_or_mood}" if genre_or_mood else "recommend movie"
    }
    
    return movie_recommend(context, genre_or_mood)

def recommend_life_skill(specific_need=None):
    """Life recommendation skill with behavioral analysis"""
    if not RECOMMENDATION_SKILLS_AVAILABLE:
        return "Life recommendation system is not available."
    
    # Build context from available information
    context = {
        'time': datetime.now(ZoneInfo("Asia/Kolkata")).hour,
        'current_app': '',
        'idle_time': 0,  # Could be enhanced with idle detection
        'mood': '',
        'command': f"life advice {specific_need}" if specific_need else "life advice"
    }
    
    return life_recommend(context, specific_need)

# ======================================================
# CORE SKILL FUNCTIONS (Return Strings)
# ======================================================

def open_browser(url_or_query="https://google.com"):
    """Opens a browser and returns a status string."""
    import webbrowser
    import urllib.parse
    
    query = str(url_or_query).lower()
    
    # 🚨 SEARCH LOGIC (Part 1 - Default Web Search)
    # ✅ ONLY trigger search if explicit phrase exists
    if "search for" in query:
        # extract ONLY after 'search for'
        search_part = query.split("search for", 1)[1].strip()

        # ❌ if nothing after → DO NOT SEARCH
        if not search_part:
            webbrowser.open("https://www.google.com")
            return "Opening Google."

        encoded = urllib.parse.quote(search_part)
        url = f"https://www.google.com/search?q={encoded}"
        webbrowser.open(url)
        return f"Searching Google for {search_part}."

    try:
        webbrowser.open(url_or_query)
        return f"Opening {url_or_query}."
    except Exception as e:
        return f"Failed to open browser: {e}"

def get_time():
    """Returns current time string."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    return f"The current time is {now.strftime('%I:%M %p')}."

def get_date():
    """Returns current date string."""
    today = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%A, %B %d, %Y")
    return f"Today is {today}."

def play_music_browser():
    """Opens YouTube Music."""
    webbrowser.open("https://music.youtube.com")
    return "Opening YouTube Music."

def shutdown_system():
    return "I cannot execute shutdown from this specific module yet, but I would if I could."

def restart_system():
    return "I cannot execute restart from this specific module yet."

def lock_system():
    try:
        import ctypes
        ctypes.windll.user32.LockWorkStation()
        return "System locked."
    except Exception as e:
        return f"Could not lock system: {e}"

def take_screenshot():
    try:
        import pyautogui
        timestamp = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"screenshot_{timestamp}.png"
        save_path = os.path.join(os.path.expanduser("~"), "Pictures", filename)
        pyautogui.screenshot(save_path)
        return f"Screenshot saved to Pictures folder."
    except ImportError:
        return "PyAutoGUI is not installed, cannot take screenshot."
    except Exception as e:
        return f"Screenshot failed: {e}"

def search_web_skill(query=None):
    if not query:
        return "What should I search for?"
    url = f"https://www.google.com/search?q={query}"
    webbrowser.open(url)
    return f"Searching Google for {query}."

def open_youtube(query=None):
    if query:
        url = f"https://www.youtube.com/results?search_query={query}"
        webbrowser.open(url)
        return f"Searching YouTube for {query}."
    webbrowser.open("https://youtube.com")
    return "Opening YouTube."

# ======================================================
# DISPATCHER MAP
# ======================================================
ACTION_SKILL_MAP = {
    "open_browser": open_browser,
    "time": get_time,
    "date": get_date,
    "play_music": play_music_browser,
    "joke": get_random_joke_wrapper,
    "shutdown": shutdown_system,
    "restart": restart_system,
    "lock": lock_system,
    "screenshot": take_screenshot,
    "search": search_web_skill,
    "youtube": open_youtube,
    "google": lambda: open_browser("https://google.com"),
    "recommend_music": recommend_music_skill,
    "recommend_movie": recommend_movie_skill,
    "recommend_life": recommend_life_skill,
}

def handle_command(intent_or_text, **kwargs):
    """
    Dispatcher: Routes intent OR raw text to skill function.
    Returns: String (response to be spoken)
    """
    text = intent_or_text.lower().strip()
    
    # 1. Direct Intent Match
    if text in ACTION_SKILL_MAP:
        return ACTION_SKILL_MAP[text](**kwargs)

    # 2. Keyphrase Matching (Text-based dispatch)
    if "time" in text and ("current" in text or "what" in text or "tell" in text):
        return get_time()
    
    if "date" in text and ("current" in text or "what" in text or "today" in text):
        return get_date()
        
    if "joke" in text or "funny" in text:
        return get_random_joke_wrapper()
        
    if "screenshot" in text:
        return take_screenshot()
        
    if "lock" in text and "system" in text:
        return lock_system()

    # Recommendation Skills
    if any(phrase in text for phrase in ["recommend music", "suggest music", "music recommendation", "what music"]):
        # Extract genre or mood if specified
        genre_or_mood = None
        for genre in ["pop", "rock", "hip-hop", "electronic", "classical", "jazz", "lofi"]:
            if genre in text:
                genre_or_mood = genre
                break
        for mood in ["happy", "sad", "energetic", "relaxed", "focused"]:
            if mood in text:
                genre_or_mood = mood
                break
        return recommend_music_skill(genre_or_mood)
    
    if any(phrase in text for phrase in ["suggest a movie", "recommend movie", "what should i watch", "movie recommendation"]):
        # Extract genre if specified
        genre_or_mood = None
        for genre in ["action", "comedy", "drama", "thriller", "scifi", "romance", "horror", "marvel"]:
            if genre in text:
                genre_or_mood = genre
                break
        return recommend_movie_skill(genre_or_mood)
    
    if any(phrase in text for phrase in ["life advice", "suggest something", "what should i do", "recommendation", "life recommendation"]):
        # Extract specific need if specified
        specific_need = None
        if "stress" in text or "overwhelmed" in text:
            specific_need = "stress"
        elif "productivity" in text or "focus" in text:
            specific_need = "productivity"
        elif "break" in text:
            specific_need = "break"
        return recommend_life_skill(specific_need)
    
    # Holistic Guidance Skills - Multi-dimensional recommendations
    if any(phrase in text for phrase in ["what should i study", "what to study", "after inter", "after intermediate", "study after inter"]):
        context = {
            'command': text,
            'time': datetime.now(ZoneInfo("Asia/Kolkata")).hour,
            'current_app': '',
            'mood': '',
            'specific_need': 'education'
        }
        return recommend_life_skill(None)  # Will trigger holistic guidance
    
    if any(phrase in text for phrase in ["what should i learn", "what to learn", "learn now", "what should i learn now"]):
        context = {
            'command': text,
            'time': datetime.now(ZoneInfo("Asia/Kolkata")).hour,
            'current_app': '',
            'mood': '',
            'specific_need': 'learning'
        }
        return recommend_life_skill(None)  # Will trigger holistic guidance
    
    if any(phrase in text for phrase in ["what should i do to stay healthy", "stay healthy", "be healthy", "healthy tips"]):
        context = {
            'command': text,
            'time': datetime.now(ZoneInfo("Asia/Kolkata")).hour,
            'current_app': '',
            'mood': '',
            'specific_need': 'health'
        }
        return recommend_life_skill(None)  # Will trigger holistic guidance
    
    if any(phrase in text for phrase in ["what should i do in life", "purpose of life", "life purpose", "what to do in life"]):
        context = {
            'command': text,
            'time': datetime.now(ZoneInfo("Asia/Kolkata")).hour,
            'current_app': '',
            'mood': '',
            'specific_need': 'life_purpose'
        }
        return recommend_life_skill(None)  # Will trigger holistic guidance
    
    if any(phrase in text for phrase in ["what should i do", "what to do", "guide me", "need guidance"]):
        context = {
            'command': text,
            'time': datetime.now(ZoneInfo("Asia/Kolkata")).hour,
            'current_app': '',
            'mood': '',
            'specific_need': 'general'
        }
        return recommend_life_skill(None)  # Will trigger holistic guidance

    if "youtube" in text:
        query = text.replace("open youtube", "").replace("search youtube", "").replace("search for", "").strip()
        return open_youtube(query if query else None)

    if "google" in text:
        return open_browser("https://google.com")

    # Search Fallback
    if "search" in text:
         query = text.replace("search for", "").replace("search", "").strip()
         return search_web_skill(query if query else None)

    # Fallback for "open browser"
    if "browser" in text:
        return open_browser()

    # If no match, return None to let other processors handle it
    return None
