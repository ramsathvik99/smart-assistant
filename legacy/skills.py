# ======================================================
# IMPORTS
# ======================================================

import os
import re
import io
import time
import json
import base64
import random
import urllib.parse
import datetime
import threading
import subprocess
import platform
from pathlib import Path

import webbrowser
import requests
import pyautogui
import feedparser
import wikipedia
import simpleaudio as sa
import winsound

# VLC manually disabled per user request
vlc = None
VLC_AVAILABLE = False
# try:
#     import vlc
#     VLC_AVAILABLE = True
# except (ImportError, Exception) as e:
#     print(f"[VLC] VLC not available: {e}")
#     vlc = None
#     VLC_AVAILABLE = False

from deep_translator import GoogleTranslator

from legacy.tts import speak
from instance.config import settings as CONFIG

from legacy.memory_manager import (
    add_note_db, get_notes_with_ids_db,
    delete_note_db, clear_notes_db, update_note_db,
    pin_note_db, unpin_note_db, mark_note_done_db,
    search_notes_db, get_pinned_notes_db, get_done_notes_db
)

from zoneinfo import ZoneInfo          # built-in timezone
import geopy
from geopy.geocoders import Nominatim  # to convert country → timezone

# Import timezonefinder with error handling
try:
    from timezonefinder import TimezoneFinder
except ImportError:
    TimezoneFinder = None

import os, sys

# ======================================================
# DEVICE COMMAND INTERCEPTOR
# ======================================================

# Global pending action for confirmation flow
pending_action = None

def is_device_command(text):
    """Check if input is a device command that should be handled locally"""
    import re
    
    text = text.lower().strip()
    
    patterns = [
        r'^create\s+folder',
        r'^delete\s+folder',
        r'^open\s+(?:file\s+)?[^\s]+(?:\s+[^\s]+)*\.(?:pdf|txt|doc|docx|jpg|png|mp4|mp3|csv|xlsx|pptx)',
        r'^rename\s+.+',
        r'^move\s+.+',
        r'^launch\s+.+',
        r'^shutdown',
        r'^restart'
    ]
    
    for pattern in patterns:
        if re.search(pattern, text):
            return True
    
    return False

def extract_folder_name(text):
    """Extract folder name from command text"""
    import re
    
    # Find the folder name without converting to lowercase first
    match = re.search(r'folder\s+(?:named\s+)?(.+)', text, re.IGNORECASE)
    
    if match:
        return match.group(1).strip()
    
    return None

def find_file(filename):
    """Find file on desktop using OneDrive-aware path"""
    import os
    from modules.system_controller.folder_manager import get_desktop_path
    
    desktop = get_desktop_path()
    
    for root, dirs, files in os.walk(desktop):
        for file in files:
            if file.lower() == filename.lower():
                return os.path.join(root, file)
    
    return None

def handle_device_command(text):
    """Parse and execute device commands locally"""
    global pending_action
    
    print("[DEVICE ROUTER] Processing:", text)
    
    try:
        # Import system controller
        from modules.system_controller.action_executor import execute_action
        
        query_lower = text.lower().strip()
        
        # Handle confirmation for pending actions
        if pending_action and query_lower in ["yes", "confirm", "do it"]:
            print("[DEVICE ROUTER] Executing confirmed action")
            # Execute with confirmation flag
            from modules.system_controller.action_executor import execute_action
            result = execute_action(pending_action, confirm=True)
            pending_action = None
            
            if result["success"]:
                return result["message"]
            else:
                return f"Action failed: {result['message']}"
        
        # System control intent detection
        if query_lower.startswith('create folder'):
            folder_name = extract_folder_name(query_lower)
            if folder_name:
                action_data = {
                    "action": "create_folder",
                    "name": folder_name,
                    "location": "desktop"
                }
                result = execute_action(action_data)
                if result["success"]:
                    return result["message"]
                else:
                    return f"Failed to create folder: {result['message']}"
            else:
                return "Please specify a folder name."
        
        elif query_lower.startswith('delete folder'):
            folder_name = extract_folder_name(query_lower)
            if folder_name:
                action_data = {
                    "action": "delete_folder",
                    "name": folder_name,
                    "location": "desktop"
                }
                
                print("[DEVICE ROUTER] Deleting folder:", folder_name)
                
                result = execute_action(action_data)
                
                if not result["success"] and ("requires explicit confirmation" in result["message"] or "CONFIRMATION_REQUIRED" in result["message"]):
                    pending_action = action_data
                    return "Are you sure you want to delete this folder? Say yes to confirm."
                elif result["success"]:
                    return result["message"]
                else:
                    return f"Failed to delete folder: {result['message']}"
            else:
                return "Please specify a folder name."
        
        elif query_lower.startswith('open '):
            # Extract filename from command
            words = query_lower.split()
            if len(words) > 1:
                # Handle "open file filename" and "open filename"
                if words[1] == 'file' and len(words) > 2:
                    filename = " ".join(words[2:])
                else:
                    filename = " ".join(words[1:])
                
                print("[DEVICE ROUTER] Searching for file:", filename)
                
                path = find_file(filename)
                print("[DEVICE ROUTER] Found path:", path)
                
                if path:
                    import os
                    os.startfile(path)
                    return f"Opened {filename}"
                else:
                    return f"{filename} not found on Desktop."
            else:
                return "Please specify a file name."
        
        elif query_lower.startswith('launch '):
            app_name = query_lower.replace('launch ', '').strip()
            if app_name:
                action_data = {
                    "action": "launch_app",
                    "app": app_name
                }
                result = execute_action(action_data)
                if result["success"]:
                    return result["message"]
                else:
                    return f"Failed to launch {app_name}: {result['message']}"
            else:
                return "Please specify an app name."
        
        elif query_lower in ['shutdown', 'restart']:
            action_data = {
                "action": "system_action",
                "action_type": query_lower
            }
            result = execute_action(action_data)
            if result["success"]:
                return result["message"]
            else:
                return f"Failed to {query_lower}: {result['message']}"
        
        print("[DEVICE ROUTER] No matching command pattern found")
        return "Device command not recognized."
        
    except ImportError as e:
        print(f"[DEVICE ROUTER] Import Error: {e}")
        return "Device controller not available."
    except Exception as e:
        print(f"[DEVICE ROUTER] Unexpected Error: {e}")
        return f"Device command error: {str(e)}"

def resource_path(relative):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative)
    return os.path.abspath(relative)

# Path to bundled VLC folder

# Try mobile screenshots
try:
    from plyer import screenshot as plyer_screenshot
except Exception:
    plyer_screenshot = None


# ======================================================
# TIME & DATE
# ======================================================
# Replace your existing tell_time() and tell_date() with this hardened version

import datetime
from zoneinfo import ZoneInfo
from legacy.tts import speak

# optional imports for location -> timezone lookup
try:
    from geopy.geocoders import Nominatim
    from timezonefinder import TimezoneFinder   # note: package name is 'timezonefinder'
    GEO_OK = True
except Exception as _:
    Nominatim = None
    TimezoneFinder = None
    GEO_OK = False

def tell_time(location=None):
    """
    Returns current system time in a clean, consistent format.
    Ignores location (local system only).
    """

    try:
        import datetime

        # Get SYSTEM time (no timezone conversion)
        now = datetime.datetime.now()

        # Debug (optional)
        print(f"[TIME DEBUG] Raw system time: {now}")

        # Format time properly
        time_str = now.strftime("%I:%M %p")  # e.g., 07:45 PM

        # Remove leading zero (optional for natural speech)
        if time_str.startswith("0"):
            time_str = time_str[1:]

        msg = f"The current time is {time_str}."

        # Speak + return (important for NOVA)
        speak(msg)
        return msg

    except Exception as e:
        print("[tell_time ERROR]", e)

        error_msg = "Sorry, I couldn't fetch the time."
        speak(error_msg)
        return error_msg

def tell_date(location=None):
    """
    Speak today's date (local) or date in the given location if possible.
    """
    try:
        if not location:
            today = datetime.datetime.now().strftime("%A, %B %d, %Y")
            msg = f"Today is {today}."
            speak(msg)
            return msg

        if not GEO_OK:
            today = datetime.datetime.now().strftime("%A, %B %d, %Y")
            msg = f"I couldn't lookup that location, but today is {today}."
            speak(msg)
            return msg

        geolocator = Nominatim(user_agent="assistant_date_app", timeout=8)
        if TimezoneFinder is None:
            speak("Sorry, timezone lookup is not available.")
            return
        tf = TimezoneFinder()

        place = geolocator.geocode(location)
        if not place:
            speak(f"Sorry, I couldn't find the location named {location}.")
            return

        timezone_str = tf.timezone_at(lat=place.latitude, lng=place.longitude)
        if not timezone_str:
            speak(f"Sorry, I couldn't determine the timezone for {location}.")
            return

        now_tz = datetime.datetime.now(ZoneInfo(timezone_str))
        date_str = now_tz.strftime("%A, %B %d, %Y")
        msg = f"Today in {place.address.split(',')[0]} is {date_str}."
        speak(msg)
        return msg

    except Exception as e:
        print("[tell_date error]", e)
        speak("Sorry, I couldn't fetch the date right now.")



# ======================================================
# TIMER
# ======================================================

def set_timer(text):
    text = text.lower()
    seconds = 0

    if "hour" in text:
        seconds += int(re.search(r"(\d+)\s*hour", text).group(1)) * 3600

    if "minute" in text:
        seconds += int(re.search(r"(\d+)\s*minute", text).group(1)) * 60

    if "second" in text:
        seconds += int(re.search(r"(\d+)\s*second", text).group(1))

    if seconds <= 0:
        return "I couldn't understand the timer duration."

    def alert():
        winsound.Beep(1800, 700)
        speak("Your timer is done.")

    threading.Timer(seconds, alert).start()
    speak("Timer set.")
    return "Timer set."

# ======================================================
# HELPERS
# ======================================================

def natural_time_to_seconds(text):
    text = text.lower()
    seconds = 0

    h = re.search(r"(\d+)\s*hour", text)
    m = re.search(r"(\d+)\s*minute", text)
    s = re.search(r"(\d+)\s*second", text)

    if h: seconds += int(h.group(1)) * 3600
    if m: seconds += int(m.group(1)) * 60
    if s: seconds += int(s.group(1))

    return seconds


def alarm_beep():
    for _ in range(3):
        winsound.Beep(1800, 800)


# ======================================================
# ALARM
# ======================================================

def set_alarm(text):
    text = text.lower().strip()

    # CASE 1: Timer format
    duration = natural_time_to_seconds(text)
    if duration > 0:
        msg = f"Alarm set for {duration} seconds from now."
        speak(msg)
        threading.Timer(duration, lambda: (alarm_beep(), speak("Your alarm is ringing!"))).start()
        return msg

    # CASE 2: Clock format
    match = re.match(r"(\d{1,2}):(\d{2})(\s*[ap]m)?", text)
    if not match:
        speak("I didn't understand the alarm time.")
        return

    hour = int(match.group(1))
    minute = int(match.group(2))
    ampm = match.group(3)

    if ampm:
        ampm = ampm.strip()
        if "pm" in ampm and hour != 12:
            hour += 12
        if "am" in ampm and hour == 12:
            hour = 0

    now = datetime.datetime.now()
    alarm = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if alarm < now:
        alarm += datetime.timedelta(days=1)

    delay = (alarm - now).total_seconds()

    msg = f"Alarm set for {alarm.strftime('%I:%M %p')}."
    speak(msg)
    threading.Timer(delay, lambda: (alarm_beep(), speak("Wake up! Your alarm is ringing!"))).start()
    return msg


# ======================================================
# MATH SOLVER
# ======================================================

def solve_math(text):
    try:
        text = text.lower()

        for w in ["what is", "calculate", "equals", "the result of", "result of", "answer"]:
            text = text.replace(w, "")

        # Word → symbol conversion
        replace_map = {
            "plus": "+", "add": "+",
            "minus": "-", "subtract": "-",
            "times": "*", "multiplied by": "*", "multiply": "*",
            "divide": "/", "divided by": "/",
        }
        for k, v in replace_map.items():
            text = text.replace(k, v)

        # Fix symbols
        text = re.sub(r'(?<=\d)\s*[xX×]\s*(?=\d)', '*', text)

        expr = re.sub(r'[^0-9+\-*/(). ]', '', text).strip()

        if not expr:
            speak("Sorry, I couldn't calculate that.")
            return

        result = eval(expr)
        msg = f"The result is {result}."
        speak(msg)
        return msg

    except Exception:
        speak("Sorry, I couldn’t calculate that.")
        return None


# ======================================================
# CURRENCY CONVERSION
# ======================================================

def convert_currency(amount, src, dest):
    try:
        currency_map = {
            "dollar": "USD", "dollars": "USD", "usd": "USD", "$": "USD",
            "rupee": "INR", "rupees": "INR", "inr": "INR", "rs": "INR", "₹": "INR",
            "euro": "EUR", "euros": "EUR", "eur": "EUR", "€": "EUR",
            "pound": "GBP", "pounds": "GBP", "gbp": "GBP", "£": "GBP",
            "yen": "JPY", "jpy": "JPY", "¥": "JPY",
            "yuan": "CNY", "cny": "CNY", "rmb": "CNY",
            "cad": "CAD", "aud": "AUD", "chf": "CHF", "sgd": "SGD", "nzd": "NZD"
        }
        
        src_code = currency_map.get(str(src).lower().strip(), str(src).upper().strip())
        dest_code = currency_map.get(str(dest).lower().strip(), str(dest).upper().strip())

        url = f"https://api.exchangerate-api.com/v4/latest/{src_code}"
        data = requests.get(url, timeout=5).json()

        rate = data.get("rates", {}).get(dest_code)
        if not rate:
            speak("I couldn't find the currency conversion rate for those currencies.")
            return "Currency rate not found."

        result = round(amount * rate, 2)
        msg = f"{amount} {src_code} equals {result} {dest_code}."
        speak(msg)
        return msg
    except Exception as e:
        print(f"[Currency Error] {e}")
        speak("Currency conversion failed.")
        return "Currency conversion failed."


# ======================================================
# UNIT CONVERSION
# ======================================================

def convert_units(value, unit_from, unit_to):
    uf_raw = str(unit_from).lower().strip()
    ut_raw = str(unit_to).lower().strip()

    word_map = {
        "metre": "m", "meters": "m", "meter": "m", "kilometre": "km", "kilometer": "km", "kilometers": "km",
        "centimeter": "cm", "centimeters": "cm", "millimeter": "mm", "millimeters": "mm",
        "liter": "l", "liters": "l", "litre": "l", "litres": "l", "milliliter": "ml", "milliliters": "ml",
        "seconds": "s", "second": "s", "minutes": "min", "minute": "min",
        "hours": "hr", "hour": "hr",
        "kilogram": "kg", "kilograms": "kg", "gram": "g", "grams": "g", "milligram": "mg", "milligrams": "mg",
        "pound": "lb", "pounds": "lb", "ounce": "oz", "ounces": "oz",
        "foot": "ft", "feet": "ft", "inch": "inch", "inches": "inch", "yard": "yard", "yards": "yard", "mile": "mile", "miles": "mile",
        "kilometers per hour": "kmph", "km/h": "kmph",
        "meters per second": "mps", "m/s": "mps",
    }

    unit_from = word_map.get(uf_raw, word_map.get(uf_raw.rstrip("s"), uf_raw))
    unit_to = word_map.get(ut_raw, word_map.get(ut_raw.rstrip("s"), ut_raw))

    unit_map = {
        # Length
        "km": 1000, "m": 1, "cm": 0.01, "mm": 0.001,
        "inch": 0.0254, "ft": 0.3048, "yard": 0.9144, "mile": 1609.34,

        # Weight
        "kg": 1, "g": 0.001, "mg": 1e-6,
        "lb": 0.453592, "oz": 0.0283495,

        # Volume
        "l": 1, "ml": 0.001, "cup": 0.236588,

        # Time
        "s": 1, "min": 60, "hr": 3600,

        # Speed (base = m/s)
        "mps": 1,
        "kmph": 1000/3600,
        "mph": 1609.34/3600,
    }

    # Temperature
    if unit_from in ["c", "celsius"] and unit_to in ["f", "fahrenheit"]:
        result = round((value * 9/5) + 32, 2)
        msg = f"{value}°C equals {result}°F."
        speak(msg)
        return msg

    if unit_from in ["f", "fahrenheit"] and unit_to in ["c", "celsius"]:
        result = round((value - 32) * 5/9, 2)
        msg = f"{value}°F equals {result}°C."
        speak(msg)
        return msg

    if unit_from not in unit_map or unit_to not in unit_map:
        speak("Sorry, I cannot convert those units yet.")
        return "Conversion not supported."

    base = value * unit_map[unit_from]
    result = round(base / unit_map[unit_to], 4)

    msg = f"{value} {unit_from} equals {result} {unit_to}."
    speak(msg)
    return msg


# ======================================================
# SCREENSHOTS
# ======================================================
def get_device_screenshot_folder():
    downloads = Path(os.environ["USERPROFILE"]) / "Downloads"
    folder = downloads / "AssistantScreenshots"
    folder.mkdir(parents=True, exist_ok=True)
    return folder



def take_screenshot():
    folder = get_device_screenshot_folder()

    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    filepath = folder / f"screenshot_{timestamp}.png"

    # Debug lines — VERY IMPORTANT
    print("[Debug] Screenshot folder:", folder)
    print("[Debug] Full path:", filepath)

    try:
        saved = False
        if pyautogui:
            try:
                img = pyautogui.screenshot()
                img.save(str(filepath))
                saved = True
                print("[Debug] Screenshot saved successfully with pyautogui!")
            except Exception as e:
                print(f"[Screenshot Debug] pyautogui failed: {e}")

        if not saved:
            try:
                from PIL import ImageGrab
                img = ImageGrab.grab()
                img.save(str(filepath))
                saved = True
                print("[Debug] Screenshot saved with PIL ImageGrab!")
            except Exception as e:
                print(f"[Screenshot Debug] PIL ImageGrab failed: {e}")

        if not saved and plyer_screenshot:
            try:
                plyer_screenshot(filename=str(filepath))
                saved = True
                print("[Debug] Screenshot saved using plyer!")
            except Exception as e:
                print(f"[Screenshot Debug] plyer failed: {e}")

        if saved and filepath.exists() and filepath.stat().st_size > 0:
            msg = f"Screenshot saved successfully at {filepath.name}."
            speak(msg)
            return msg
        else:
            speak("Sorry, I couldn't take the screenshot.")
            return False

    except Exception as e:
        speak("Sorry, I couldn't take the screenshot.")
        print("[Screenshot Error]", e)
        return False


def lock_system():
    speak("Locking the system now.")
    try:
        import ctypes
        ctypes.windll.user32.LockWorkStation()
    except ImportError:
        # Fallback for systems without ctypes
        import subprocess
        subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=False)
    return "System locked."


# ======================================================
# WEATHER
# ======================================================

def get_weather(location):
    api_key = "d29b7232620736a06c781aaea43a14c5"
    if not api_key:
        speak("Weather service not configured.")
        return

    STATES = {
        # only keeping for readability — unchanged
        "andhra pradesh": (15.9129, 79.74),
        "telangana": (17.1232, 79.2088),
        "tamil nadu": (11.1271, 78.6569),
        "karnataka": (15.3173, 75.7139),
        "maharashtra": (19.7515, 75.7139),
        "kerala": (10.8505, 76.2711),
        "gujarat": (22.2587, 71.1924),
        "west bengal": (22.9868, 87.8550),
        "uttar pradesh": (26.8467, 80.9462),
        "rajasthan": (27.0238, 74.2179),
        "bihar": (25.0961, 85.3131),
        "punjab": (31.1471, 75.3412),
        "haryana": (29.0588, 76.0856),
        "madhya pradesh": (22.9734, 78.6569),
        "odisha": (20.9517, 85.0985),
        "jharkhand": (23.6102, 85.2799),
        "assam": (26.2006, 92.9376),
        "chhattisgarh": (21.2787, 81.8661),
        "himachal pradesh": (31.1048, 77.1734),
        "delhi": (28.6139, 77.2090),
        "jammu and kashmir": (33.7782, 76.5762),
    }

    if not location:
        location = "Delhi"
    
    location = str(location).lower().strip()
    if not location:
        location = "delhi"

    try:
        if location in STATES:
            lat, lon = STATES[location]
            url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units=metric"
            place = location.title()
        else:
            place = location.title()
            url = f"https://api.openweathermap.org/data/2.5/weather?q={place}&appid={api_key}&units=metric"

        response = requests.get(url, timeout=10).json()

        if response.get("cod") != 200:
            speak(f"I couldn't find the weather for {place}.")
            return f"I couldn't find the weather for {place}."

        temp = response["main"]["temp"]
        feels = response["main"]["feels_like"]
        desc = response["weather"][0]["description"].capitalize()
        humidity = response["main"]["humidity"]

        msg = (f"The weather in {place} is {desc}. "
              f"Temperature: {temp}°C, feels like {feels}. "
              f"Humidity: {humidity}%.")
        speak(msg)
        return msg

    except Exception as e:
        speak("Sorry, I couldn't fetch the weather right now.")
        print("[Weather Error]", e)
        return "Sorry, I couldn't fetch the weather right now."


# ======================================================
# NEWS FETCHER
# ======================================================

def get_news(location="India"):
    location = re.sub(r"[^a-zA-Z\s]", "", location or "").strip()
    query = urllib.parse.quote_plus(location)

    url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"

    speak(f"Fetching the latest news for {location}...")

    try:
        feed = feedparser.parse(url)

        if not feed.entries:
            speak(f"No news found for {location}.")
            return

        speak(f"Top headlines for {location}:")
        headlines = []
        for i, entry in enumerate(feed.entries[:5], 1):
            h = f"Headline {i}: {entry.title}"
            headlines.append(h)
            speak(h)
            time.sleep(0.4)
        return f"Top headlines for {location}: " + " ".join(headlines)

    except Exception as e:
        speak("Sorry, I couldn’t fetch the news.")
        print("[News Error]", e)


# ======================================================
# AI QUERYING
# ======================================================

# Lazy-loaded LLMEngine singleton for ask_ai()
_ask_ai_engine = None

def _get_ask_ai_engine():
    """Return shared LLMEngine instance (imported lazily to avoid circular imports)."""
    global _ask_ai_engine
    if _ask_ai_engine is None:
        from extensions.llm_engine import LLMEngine
        _ask_ai_engine = LLMEngine()
    return _ask_ai_engine



def ask_ai(query):
    # ======================================================
    # PRIORITY DEVICE COMMAND ROUTING
    # ======================================================
    
    # Check if this is a device command first (highest priority)
    if is_device_command(query):
        print("[DEVICE ROUTER] Priority routing activated")
        result = handle_device_command(query)
        print(f"[DEVICE ROUTER] Returning result: {result}")
        return result
    
    print("[AI ROUTER] Not a device command, proceeding to LLM")

    # ======================================================
    # LIVE WEB RETRIEVAL INTEGRATION - Check for live data needs
    # ======================================================
    try:
        from extensions.live_global.router import is_live_query
        from extensions.live_global.live_pipeline import live_search_pipeline
        
        if is_live_query(query):
            try:
                # Get live context
                live_context = live_search_pipeline(query, max_sources=2)
                
                if live_context and live_context.get("success"):
                    # Build enhanced prompt with live context
                    enhanced_query = f"""Context: {live_context['context']}

User Question: {query}

Based on the live context above, provide a concise and helpful answer. If the context doesn't fully answer the question, say so clearly."""
                    
                    # Process with enhanced query
                    query = enhanced_query
            except Exception as e:
                print(f"[Live Retrieval Error] {e}")
                # Continue with normal pipeline if live retrieval fails
    except ImportError:
        # Live retrieval not available, continue normally
        pass

    # ======================================================
    # LLM QUERY — via central LLMEngine (provider/fallback handled there)
    # BEFORE: direct Groq HTTP call → direct DeepSeek HTTP call
    # AFTER:  LLMEngine.get_completion() → configured provider → fallback chain
    # ======================================================
    system_prompt = (
        f"You are {CONFIG.get_assistant_name() or 'an intelligent assistant'}, a smart assistant. "
        "Give short, direct answers — maximum 2–3 sentences."
    )
    engine = _get_ask_ai_engine()
    result = engine.get_completion(
        prompt=query,
        system_prompt=system_prompt,
        temperature=0.4,
        max_tokens=300
    )
    if result:
        return result.strip()

    # DuckDuckGo fallback (no LLM needed — pure HTTP)
    try:
        params = {"q": query, "format": "json", "no_html": 1}
        r = requests.get("https://api.duckduckgo.com/", params=params, timeout=5)
        data = r.json()

        if data.get("AbstractText"):
            return data["AbstractText"]

        for t in data.get("RelatedTopics", []):
            if isinstance(t, dict) and "Text" in t:
                return t["Text"]

    except Exception as e:
        print("DuckDuckGo error:", e)

    return "I couldn't find an answer."


# ======================================================
# TRANSLATION
# ======================================================

def translate_text(text, dest_lang=None):
    try:
        if dest_lang:
            phrase = text.strip()
            lang_name = dest_lang.lower().strip()
        else:
            command = text.lower().strip().replace("translate", "").strip()
            parts = command.split(" to ")
            phrase = parts[0].strip()
            lang_name = parts[1].strip().lower() if len(parts) == 2 else "french"

        lang_map = {
            "french": "fr", "spanish": "es", "hindi": "hi", "telugu": "te",
            "tamil": "ta", "german": "de", "italian": "it", "japanese": "ja",
            "chinese": "zh-cn", "korean": "ko", "russian": "ru", "arabic": "ar",
            "english": "en", "bengali": "bn", "marathi": "mr", "urdu": "ur",
            "gujarati": "gu", "punjabi": "pa", "malayalam": "ml"
        }

        match = next((name for name in lang_map if lang_name.startswith(name)), None)

        if not match:
            if lang_name in lang_map.values():
                match = [k for k, v in lang_map.items() if v == lang_name][0]
            else:
                match = "french"

        lang_code = lang_map[match]
        translated = GoogleTranslator(source='auto', target=lang_code).translate(phrase)

        msg = f"In {match.capitalize()}, '{phrase}' means: {translated}"
        speak(f"In {match.capitalize()}, '{phrase}' means:")
        print(f"[Translation Output] {translated} ({lang_code})")
        speak(translated, lang_hint=lang_code)

        return msg

    except Exception as e:
        print("Translate error:", e)
        speak("Sorry, I couldn’t translate that.")
        return None


# ======================================================
# DICTIONARY
# ======================================================

def define_word(word):
    word = word.lower().strip()
    word = re.sub(r'\b(what|is|the|meaning|of|a|an|define)\b', '', word).strip()

    if not word:
        speak("Please tell me which word to define.")
        return "Please tell me which word to define."

    try:
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
        response = requests.get(url, timeout=8)

        if response.status_code != 200:
            speak(f"I couldn't find a definition for {word}.")
            return f"I couldn't find a definition for {word}."

        data = response.json()
        meaning = data[0]["meanings"][0]

        pos = meaning.get("partOfSpeech", "word")
        definition = meaning["definitions"][0].get("definition", "No definition found")

        msg = f"The meaning of {word} as a {pos} is: {definition}"
        example = meaning["definitions"][0].get("example")
        if example:
            msg += f" For example, {example}"

        speak(msg)
        return msg

    except Exception as e:
        speak("Sorry, I couldn’t fetch the meaning.")
        print("Define error:", e)
        return "Sorry, I couldn't fetch the meaning."


# ======================================================
# NOTES SYSTEM
# ======================================================

def add_note(text):
    user_id = CONFIG["CURRENT_USER_ID"]
    if not text.strip():
        speak("Tell me what to write.")
        return

    add_note_db(user_id, text)
    speak("Note saved.")
    return "Note saved."


def read_notes():
    user_id = CONFIG["CURRENT_USER_ID"]
    notes = get_notes_with_ids_db(user_id)

    if not notes:
        speak("You have no notes.")
        return

    speak("Here are your notes:")
    for i, row in enumerate(notes, 1):
        speak(f"Note {i}: {row['note']}")
    return "Here are your notes."


def delete_note(number):
    user_id = CONFIG["CURRENT_USER_ID"]
    notes = get_notes_with_ids_db(user_id)

    if number <= 0 or number > len(notes):
        speak("That note number doesn't exist.")
        return

    note_id = notes[number - 1]["id"]
    delete_note_db(user_id, note_id)
    speak("Note deleted.")
    return "Note deleted."


def delete_note_by_text(keyword):
    user_id = CONFIG["CURRENT_USER_ID"]
    notes = get_notes_with_ids_db(user_id)

    keyword = keyword.lower()
    for row in notes:
        if keyword in row["note"].lower():
            delete_note_db(user_id, row["id"])
            speak("I deleted that note.")
            return

    speak("I couldn't find a matching note.")


def update_note(number, new_text):
    user_id = CONFIG["CURRENT_USER_ID"]
    notes = get_notes_with_ids_db(user_id)

    if number <= 0 or number > len(notes):
        speak("That note number doesn't exist.")
        return

    note_id = notes[number - 1]["id"]
    update_note_db(user_id, note_id, new_text)
    speak("Note updated.")
    return "Note updated."


def clear_all_notes():
    user_id = CONFIG["CURRENT_USER_ID"]
    clear_notes_db(user_id)
    speak("All notes cleared.")
    return "All notes cleared."


def pin_note(number):
    user_id = CONFIG["CURRENT_USER_ID"]
    notes = get_notes_with_ids_db(user_id)

    if number <= 0 or number > len(notes):
        speak("That note number doesn't exist.")
        return

    note_id = notes[number - 1]["id"]
    pin_note_db(user_id, note_id)
    speak("Note pinned.")


def unpin_note(number):
    user_id = CONFIG["CURRENT_USER_ID"]
    notes = get_notes_with_ids_db(user_id)

    if number <= 0 or number > len(notes):
        speak("That note number doesn't exist.")
        return

    note_id = notes[number - 1]["id"]
    unpin_note_db(user_id, note_id)
    speak("Note unpinned.")


def mark_note_done(number):
    user_id = CONFIG["CURRENT_USER_ID"]
    notes = get_notes_with_ids_db(user_id)

    if number <= 0 or number > len(notes):
        speak("That note number doesn't exist.")
        return

    note_id = notes[number - 1]["id"]
    mark_note_done_db(user_id, note_id)
    speak("Marked as done.")


def search_notes(keyword):
    user_id = CONFIG["CURRENT_USER_ID"]
    results = search_notes_db(user_id, keyword)

    if not results:
        speak(f"No notes found containing {keyword}.")
        return

    speak(f"I found {len(results)} notes containing {keyword}:")
    for idx, row in enumerate(results, 1):
        speak(f"Match {idx}: {row['note']}")


def show_pinned_notes():
    user_id = CONFIG["CURRENT_USER_ID"]
    notes = get_pinned_notes_db(user_id)

    if not notes:
        speak("You have no pinned notes.")
        return

    speak("Here are your pinned notes:")
    for i, row in enumerate(notes, 1):
        speak(f"Pinned {i}: {row['note']}")


def show_done_notes():
    user_id = CONFIG["CURRENT_USER_ID"]
    notes = get_done_notes_db(user_id)

    if not notes:
        speak("You have no completed notes.")
        return

    speak("Here are your completed notes:")
    for i, row in enumerate(notes, 1):
        speak(f"Done {i}: {row['note']}")


# ======================================================
# REMINDERS
# ======================================================

def set_reminder(task, minutes):
    speak(f"I'll remind you to {task} in {minutes} minutes.")
    threading.Timer(minutes * 60, lambda: speak(f"Reminder: {task}")).start()


# ======================================================
# YOUTUBE-NATIVE MUSIC SYSTEM
# ======================================================

# Add extensions to path for music engine imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'extensions'))

try:
    from youtube_music_service import get_youtube_service
    YOUTUBE_MUSIC_AVAILABLE = True
except ImportError as e:
    print(f"[Music] YouTube music system not available: {e}")
    YOUTUBE_MUSIC_AVAILABLE = False

try:
    from music_engine import get_music_engine, is_music_available
    LOCAL_MUSIC_AVAILABLE = is_music_available()
except ImportError as e:
    print(f"[Music] Local music engine not available: {e}")
    LOCAL_MUSIC_AVAILABLE = False

try:
    from clean_music_engine import get_clean_music_engine, is_clean_music_available
    CLEAN_MUSIC_AVAILABLE = is_clean_music_available()
except ImportError as e:
    print(f"[Music] Clean music engine not available: {e}")
    CLEAN_MUSIC_AVAILABLE = False

def play_music(query=""):
    """Play music using YouTube Data API - native YouTube approach"""
    if YOUTUBE_MUSIC_AVAILABLE:
        try:
            service = get_youtube_service()
            # Add language detection and filtering
            if not query.strip():
                query = "latest songs"
            
            # Detect language and add filters
            query_lower = query.lower()
            if any(word in query_lower for word in ['telugu', 'తెలుగు']):
                search_query = f"{query} telugu songs official"
            elif any(word in query_lower for word in ['hindi', 'हिंदी']):
                search_query = f"{query} hindi songs official"
            elif any(word in query_lower for word in ['tamil', 'தமிழ்']):
                search_query = f"{query} tamil songs official"
            else:
                search_query = f"{query} official songs"
            
            return service.search_and_play_playlist(search_query)
        except Exception as e:
            print(f"[Music] Error playing music: {e}")
            return False
    else:
        speak("YouTube music system is not available. Please check your configuration.")
        return False

def next_song(query: str = ""):
    """Play next song using YouTube-native system"""
    if YOUTUBE_MUSIC_AVAILABLE:
        try:
            service = get_youtube_service()
            return service.play_next()
        except Exception as e:
            print(f"[Music] Error playing next: {e}")
            return False
    else:
        speak("YouTube music system is not available.")
        return False

def pause_music():
    """Pause music - user handles in YouTube"""
    speak("Pause music in YouTube player")
    return True

def resume_music():
    """Resume music - user handles in YouTube"""
    speak("Resume music in YouTube player")
    return True

def previous_song():
    """Play previous song using YouTube-native system"""
    if YOUTUBE_MUSIC_AVAILABLE:
        try:
            service = get_youtube_service()
            return service.play_previous()
        except Exception as e:
            print(f"[Music] Error playing previous: {e}")
            return False
    else:
        speak("YouTube music system is not available.")
        return False

def increase_volume():
    """Increase volume - YouTube player control"""
    speak("Increase volume in YouTube player")
    return True

def lower_volume():
    """Lower volume - YouTube player control"""
    speak("Lower volume in YouTube player")
    return True

def mute_volume():
    """Mute volume - YouTube player control"""
    speak("Volume muted")
    return True

def unmute_volume():
    """Unmute volume - YouTube player control"""
    speak("Volume unmuted")
    return True

def restore_volume():
    """Restore volume to default level - YouTube player control"""
    speak("Volume restored to default level")
    return True

def stop_music():
    """Stop music - user handles in YouTube"""
    speak("Stop music in YouTube player")
    return True

# Local music playback functions
def play_local_music(file_path=""):
    """Play local music file using VLC"""
    if LOCAL_MUSIC_AVAILABLE:
        try:
            engine = get_music_engine()
            if file_path:
                return engine.play_file(file_path)
            else:
                speak("Please specify a music file to play")
                return False
        except Exception as e:
            print(f"[Music] Error playing local music: {e}")
            return False
    else:
        speak("Local music engine is not available.")
        return False

def play_music_playlist(playlist_files=None):
    """Play a playlist of local music files"""
    if LOCAL_MUSIC_AVAILABLE:
        try:
            engine = get_music_engine()
            if playlist_files:
                return engine.play_playlist(playlist_files)
            else:
                speak("Please provide a list of music files")
                return False
        except Exception as e:
            print(f"[Music] Error playing playlist: {e}")
            return False
    else:
        speak("Local music engine is not available.")
        return False

# Clean music playback functions
def play_clean_music(file_path=""):
    """Play music using system default player"""
    if CLEAN_MUSIC_AVAILABLE:
        try:
            engine = get_clean_music_engine()
            if file_path:
                return engine.play_file(file_path)
            else:
                speak("Please specify a music file to play")
                return False
        except Exception as e:
            print(f"[Music] Error playing clean music: {e}")
            return False
    else:
        speak("Clean music engine is not available.")
        return False



# ======================================================
# INTERNET SPEED TEST
# ======================================================

def check_internet_speed():
    speak("Checking internet speed. This may take a moment.")
    try:
        import speedtest
        st = speedtest.Speedtest()
        down = st.download() / 1024 / 1024
        up = st.upload() / 1024 / 1024
        
        down = round(down, 2)
        up = round(up, 2)
        
        speak(f"Download speed is {down} megabits per second.")
        speak(f"Upload speed is {up} megabits per second.")
    except Exception as e:
        print(f"[Speedtest Error] {e}")
        speak("I couldn't check the internet speed.")

# ======================================================
# CRICKET SCORES (IPL)
# ======================================================

def get_cricket_score():
    speak("Checking cricket scores...")
    try:
        from bs4 import BeautifulSoup
        
        url = "https://www.cricbuzz.com/cricket-match/live-scores"
        headers = {'User-Agent': 'Mozilla/5.0'}
        page = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(page.text, "html.parser")
        
        matches = soup.find_all(class_="cb-mtch-lst")
        if not matches:
             speak("No live matches found right now.")
             return
             
        found = False
        # Limit to first 2 matches to avoid speaking too much
        count = 0 
        for match in matches:
             if count >= 2: break
             try:
                # Basic scraping heuristic for cricbuzz live page
                # This classes change often, but let's try standard ones or text search
                bat_tm = match.find(class_="cb-hmscg-bat-txt")
                bwl_tm = match.find(class_="cb-hmscg-bwl-txt")
                score = match.find(class_="cb-lv-scrs-col")
                status = match.find(class_="cb-text-live")
                
                text_out = ""
                if bat_tm: text_out += bat_tm.text + " "
                if score: text_out += score.text + " "
                if status: text_out += ". " + status.text
                
                if text_out:
                    speak(text_out)
                    found = True
                    count += 1
             except (AttributeError, TypeError) as e:
                 print(f"[Cricket] Error parsing match data: {e}")
             except Exception as e:
                 print(f"[Cricket] Unexpected scraping error: {e}")
        
        if not found:
             speak("I found matches but couldn't read the scores clearly.")
             
    except Exception as e:
        print(f"[Cricket Error] {e}")
        speak("I couldn't fetch cricket scores.")

# ======================================================
# GAMES (Rock Paper Scissors)
# ======================================================

def play_rock_paper_scissors(user_choice):
    if not user_choice:
        speak("Rock, paper, or scissors?")
        return # expect routing to handle follow up or re-trigger

    choices = ["rock", "paper", "scissors"]
    user_choice = user_choice.lower().strip()
    
    # helper cleaning
    if "rock" in user_choice: user_choice = "rock"
    elif "paper" in user_choice: user_choice = "paper"
    elif "scissor" in user_choice: user_choice = "scissors"
    
    if user_choice not in choices:
         speak("Please say rock, paper, or scissors.")
         return
         
    comp_choice = random.choice(choices)
    speak(f"I chose {comp_choice}.")
    
    if user_choice == comp_choice:
        speak("It's a tie!")
    elif (user_choice == "rock" and comp_choice == "scissors") or \
         (user_choice == "paper" and comp_choice == "rock") or \
         (user_choice == "scissors" and comp_choice == "paper"):
         speak("You won!")
    else:
         speak("I won!")


# ======================================================
# FILE AND FOLDER CREATION
# ======================================================

def get_location_path(location_hint):
    """Resolve location string to actual path."""
    location_hint = location_hint.lower().strip()
    
    if "desktop" in location_hint:
        return os.path.join(os.path.expanduser("~"), "Desktop")
    elif "documents" in location_hint:
        return os.path.join(os.path.expanduser("~"), "Documents")
    else:
        # Default to Downloads
        return os.path.join(os.path.expanduser("~"), "Downloads")

def get_unique_name(base_path):
    """Generate a unique numbered filename if base_path exists."""
    if not os.path.exists(base_path):
        return base_path
    
    # Split into directory, name, and extension
    directory = os.path.dirname(base_path)
    basename = os.path.basename(base_path)
    
    # Check if it has an extension
    if "." in basename:
        name, ext = os.path.splitext(basename)
    else:
        name = basename
        ext = ""
    
    # Try numbered versions
    counter = 1
    while True:
        new_name = f"{name}({counter}){ext}"
        new_path = os.path.join(directory, new_name)
        if not os.path.exists(new_path):
            return new_path
        counter += 1

def ask_replace_or_rename(path, item_type):
    """
    Ask user if they want to replace existing file/folder.
    Returns 'replace' or 'rename'.
    Timeout after 15 seconds defaults to 'rename'.
    """
    speak(f"This {item_type} already exists. Do you want to replace it?")
    
    try:
        from legacy.sst import listen
        # listen() with timeout (our sst module should support this)
        # If not, we use a simple approach
        response = listen()
        
        if response:
            response = response.lower()
            if "yes" in response or "replace" in response or "overwrite" in response:
                return "replace"
            else:
                return "rename"
        else:
            # No response or timeout
            return "rename"
    except KeyboardInterrupt:
        # User cancelled the prompt
        return "rename"
    except Exception as e:
        # Fallback on error
        print(f"[File Conflict] Error getting user response: {e}")
        return "rename"

def create_file(name, location="Downloads", content=""):
    """Create a file with conflict handling."""
    try:
        # Resolve location
        base_dir = get_location_path(location)
        
        # Ensure directory exists
        os.makedirs(base_dir, exist_ok=True)
        
        # Build full path
        file_path = os.path.join(base_dir, name)
        
        # Check for conflicts
        if os.path.exists(file_path):
            action = ask_replace_or_rename(file_path, "file")
            if action == "rename":
                file_path = get_unique_name(file_path)
                speak(f"Creating {os.path.basename(file_path)} instead.")
        
        # Create file
        with open(file_path, 'w') as f:
            if content:
                f.write(content)
        
        speak(f"File created at {os.path.basename(file_path)}.")
        
    except Exception as e:
        print(f"[File Creation Error] {e}")
        speak("I couldn't create the file.")

def create_folder(name, location="Downloads"):
    """Create a folder with conflict handling."""
    try:
        # Resolve location
        base_dir = get_location_path(location)
        
        # Build full path
        folder_path = os.path.join(base_dir, name)
        
        # Check for conflicts
        if os.path.exists(folder_path):
            action = ask_replace_or_rename(folder_path, "folder")
            if action == "replace":
                # Remove existing folder
                import shutil
                shutil.rmtree(folder_path)
                speak("Replacing existing folder.")
            else:
                folder_path = get_unique_name(folder_path)
                speak(f"Creating {os.path.basename(folder_path)} instead.")
        
        # Create folder
        os.makedirs(folder_path, exist_ok=True)
        
        speak(f"Folder created at {os.path.basename(folder_path)}.")
        
    except Exception as e:
        print(f"[Folder Creation Error] {e}")
        speak("I couldn't create the folder.")


# ======================================================
# CONTINUOUS LISTENING - BORED FLOW
# ======================================================

def handle_bored_flow():
    """
    Conversational flow for 'I'm bored' with continuous listening.
    Keeps listening until user selects an activity.
    """
    speak("What would you like to do? You can listen to songs, watch movies, read something, or play games.")
    
    # Continuous listening until valid choice
    while True:
        try:
            from legacy.sst import listen
            response = listen()
            
            if not response:
                # If no response, ask again
                speak("I didn't catch that. What would you like to do?")
                continue
            
            response = response.lower()
            
            # Route based on keywords
            if "song" in response or "music" in response or "listen" in response:
                play_music()
                break
            
            elif "movie" in response or "watch" in response or "film" in response:
                suggest_movies()
                break
            
            elif "read" in response or "news" in response or "article" in response:
                get_news()
                break
            
            elif "game" in response or "play" in response:
                speak("Let's play rock paper scissors!")
                play_rock_paper_scissors(None)
                break
            
            else:
                # Unrecognized choice
                speak("I didn't understand. Please say songs, movies, read, or games.")
                
        except Exception as e:
            print(f"[Bored Flow Error] {e}")
            speak("Sorry, something went wrong.")
            break


# ======================================================
# MOVIE RECOMMENDATIONS
# ======================================================

def suggest_movies(language="en", genre=None):
    """
    Suggest latest movies with good ratings.
    Prioritizes recent releases over classics.
    """
    try:
        current_year = datetime.datetime.now().year
        
        # TMDb API (free, no key needed for basic discover)
        # Using public endpoint
        url = "https://api.themoviedb.org/3/discover/movie"
        
        # Free API key for demo (replace with your own for production)
        api_key = "8265bd1679663a7ea12ac168da84d2e8"  # Public demo key
        
        params = {
            "api_key": api_key,
            "language": "en-US",
            "sort_by": "popularity.desc",
            "primary_release_year": current_year,
            "vote_average.gte": 6.5,
            "vote_count.gte": 100,
            "page": 1
        }
        
        if genre:
            # Genre IDs: Action=28, Comedy=35, Drama=18, Thriller=53
            genre_map = {
                "action": 28,
                "comedy": 35,
                "drama": 18,
                "thriller": 53,
                "horror": 27,
                "romance": 10749
            }
            if genre.lower() in genre_map:
                params["with_genres"] = genre_map[genre.lower()]
        
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            movies = data.get("results", [])
            
            if not movies:
                # Try previous year if current year has no results
                params["primary_release_year"] = current_year - 1
                response = requests.get(url, params=params, timeout=10)
                if response.status_code == 200:
                    movies = response.json().get("results", [])
            
            if movies:
                # Speak top 5
                movie_names = [m["title"] for m in movies[:5]]
                
                if genre:
                    speak(f"Here are some latest {genre} movies you might enjoy:")
                else:
                    speak("Here are some of the latest movies you might enjoy:")
                
                for i, name in enumerate(movie_names, 1):
                    speak(f"{i}. {name}")
                
                return
        
        # Fallback: curated list
        speak("Here are some popular recent movies: Dune Part Two, Oppenheimer, The Killer, Poor Things, and Barbie.")
        
    except Exception as e:
        print(f"[Movie Recommendation Error] {e}")
        # Fallback
        speak("Here are some popular recent movies: Dune Part Two, Oppenheimer, The Killer, Poor Things, and Barbie.")


# ======================================================
# SMART GREETING
# ======================================================

def get_smart_greeting():
    """
    Generate time and region-based greeting.
    Returns greeting string based on current time and system locale.
    """
    from datetime import datetime
    import locale
    
    # Get current hour
    hour = datetime.now().hour
    
    # Determine time-based greeting
    if 5 <= hour < 12:
        time_greeting = "Good morning"
    elif 12 <= hour < 17:
        time_greeting = "Good afternoon"
    elif 17 <= hour < 21:
        time_greeting = "Good evening"
    else:
        time_greeting = "Good night"
    
    # Detect region from system locale
    try:
        system_locale = locale.getdefaultlocale()[0]  # e.g., 'en_US', 'hi_IN'
        
        if system_locale:
            # Extract country code
            if '_' in system_locale:
                lang, country = system_locale.split('_')
            else:
                lang = system_locale
                country = None
            
            # Region-specific greetings
            if country == 'IN' or lang == 'hi':
                # India - add Namaste for morning
                if hour < 12:
                    return f"Namaste, {time_greeting.lower()}"
                else:
                    return time_greeting
            
            elif country in ['JP', 'ja']:
                # Japan - Konnichiwa
                return f"{time_greeting}"
            
            elif country in ['ES', 'MX', 'AR'] or lang == 'es':
                # Spanish-speaking regions
                time_map = {
                    "Good morning": "Buenos días",
                    "Good afternoon": "Buenas tardes",
                    "Good evening": "Buenas tardes",
                    "Good night": "Buenas noches"
                }
                return time_map.get(time_greeting, time_greeting)
            
            elif country == 'FR' or lang == 'fr':
                # French
                time_map = {
                    "Good morning": "Bonjour",
                    "Good afternoon": "Bon après-midi",
                    "Good evening": "Bonsoir",
                    "Good night": "Bonne nuit"
                }
                return time_map.get(time_greeting, time_greeting)
            
            elif country == 'DE' or lang == 'de':
                # German
                time_map = {
                    "Good morning": "Guten Morgen",
                    "Good afternoon": "Guten Tag",
                    "Good evening": "Guten Abend",
                    "Good night": "Gute Nacht"
                }
                return time_map.get(time_greeting, time_greeting)
    
    except Exception:
        pass
    
    # Default: English greeting
    return time_greeting

def greet_user():
    """
    Greet the user with smart greeting.
    Reusable across startup, wake-up, and greeting triggers.
    """
    greeting = get_smart_greeting()
    username = CONFIG.get("CURRENT_USERNAME", "")
    
    if username:
        speak(f"{greeting}, {username}!")
    else:
        speak(f"{greeting}!")


# ======================================================
# DETERMINISTIC MEMORY SYSTEM
# ======================================================

def detect_and_store_fact(user_id, text):
    """
    Automatically detect and store declarative facts.
    Returns True if fact was detected and stored.
    """
    if not user_id:
        return False
    
    text_lower = text.lower().strip()
    
    # Guard: "my X is" (with nothing after)
    match = re.search(r"my (\w+(?:\s+\w+)*) is$", text_lower)
    if match:
        entity = match.group(1)
        speak(f"What is your {entity}?")
        return True

    # Pattern 1: "my X is Y"
    match = re.search(r"my (\w+(?:\s+\w+)*) is (.+)", text_lower)
    if match:
        key = match.group(1).replace(" ", "_")
        value = match.group(2).strip()
        
        from legacy.memory_manager import update_user_memory
        update_user_memory(user_id, key, value)
        speak("Got it. I'll remember that.")
        return True
    
    # Pattern 2: "I like X" / "I love X"
    match = re.search(r"i (?:like|love|enjoy|prefer) (.+)", text_lower)
    if match:
        value = match.group(1).strip()
        key = f"likes_{value.split()[0].replace(' ', '_')}"
        
        from legacy.memory_manager import update_user_memory
        update_user_memory(user_id, key, value)
        speak("Got it. I'll remember that.")
        return True
    
    # Pattern 3: "I am X"
    match = re.search(r"i am (?:a |an )?(.+)", text_lower)
    if match and len(match.group(1).split()) <= 3:  # Avoid long sentences
        value = match.group(1).strip()
        # Skip common phrases
        if value not in ["bored", "sad", "happy", "here", "back"]:
            key = "identity"
            
            from legacy.memory_manager import update_user_memory
            update_user_memory(user_id, key, value)
            speak("Got it. I'll remember that.")
            return True
    
    # Pattern 4: "remember that X"
    if text_lower.startswith("remember that "):
        fact = text_lower.replace("remember that ", "").strip()
        key = fact.split()[0].replace(" ", "_")
        
        from legacy.memory_manager import update_user_memory
        update_user_memory(user_id, key, fact)
        speak("Got it. I'll remember that.")
        return True
    
    return False

def query_memory_first(user_id, text):
    """
    Query user memory before LLM fallback.
    Returns answer if found, None otherwise.
    """
    if not user_id:
        return None
    
    text_lower = text.lower().strip()
    
    # Load memory
    from legacy.memory_manager import load_user_memory
    memory = load_user_memory(user_id)
    
    if not memory:
        return None
    
    # Pattern 1: "what is my X"
    match = re.search(r"what (?:is|are) my (\w+(?:\s+\w+)*)", text_lower)
    if match:
        key = match.group(1).replace(" ", "_")
        if key in memory:
            return f"Your {match.group(1)} is {memory[key]}."
        else:
            return "I don't have that saved yet."
    
    # Pattern 2: "do I like X"
    match = re.search(r"do i (?:like|love|enjoy|prefer) (.+)", text_lower)
    if match:
        search_term = match.group(1).strip()
        # Search in memory values
        for key, value in memory.items():
            if search_term in str(value).lower():
                return f"Yes, you mentioned you like {value}."
        return "I don't have that information saved."
    
    # Pattern 3: "what do I like"
    if "what do i like" in text_lower or "what are my interests" in text_lower:
        likes = [v for k, v in memory.items() if k.startswith("likes_")]
        if likes:
            return f"You like: {', '.join(likes)}."
        else:
            return "I don't have your preferences saved yet."
    
    # Pattern 4: "what do you know about me"
    if "what do you know about me" in text_lower or "what do you remember" in text_lower:
        if memory:
            facts = []
            for key, value in memory.items():
                if key.startswith("likes_"):
                    facts.append(f"You like {value}")
                else:
                    facts.append(f"Your {key.replace('_', ' ')} is {value}")
            return "Here's what I remember: " + ". ".join(facts[:5]) + "."
        else:
            return "I don't have anything saved about you yet."
    
    return None


# ======================================================
# SYSTEM POWER CONTROL
# ======================================================

# Global storage for scheduled power actions
_scheduled_power_actions = {}

def _get_confirmation(question, timeout=15):
    """
    Ask user for confirmation and wait for response.
    Returns True if confirmed, False otherwise.
    """
    speak(question)
    
    try:
        from legacy.sst import listen
        response = listen()
        
        if response:
            response_lower = response.lower()
            if any(word in response_lower for word in ["yes", "yeah", "sure", "confirm", "okay", "ok", "do it"]):
                return True
            elif any(word in response_lower for word in ["no", "nope", "cancel", "don't", "abort"]):
                return False
        
        # Timeout or unclear response
        speak("No confirmation received. Action cancelled.")
        return False
        
    except Exception as e:
        print(f"[Confirmation Error] {e}")
        speak("I couldn't hear you. Action cancelled.")
        return False

def shutdown_system():
    """Shutdown the system with confirmation."""
    if not _get_confirmation("Are you sure you want to shut down the system?"):
        return
    
    speak("Shutting down the system now.")
    
    
    
    try:
        system = platform.system()
        if system == "Windows":
            subprocess.run(["shutdown", "/s", "/t", "5"], check=True)
        elif system == "Darwin":  # macOS
            subprocess.run(["sudo", "shutdown", "-h", "now"], check=True)
        else:  # Linux
            subprocess.run(["shutdown", "-h", "now"], check=True)
    except Exception as e:
        print(f"[Shutdown Error] {e}")
        speak("I couldn't shut down the system.")

def restart_system():
    """Restart the system with confirmation."""
    if not _get_confirmation("Are you sure you want to restart the system?"):
        return
    
    speak("Restarting the system now.")
    
    import platform
    import subprocess
    
    try:
        system = platform.system()
        if system == "Windows":
            subprocess.run(["shutdown", "/r", "/t", "5"], check=True)
        elif system == "Darwin":  # macOS
            subprocess.run(["sudo", "shutdown", "-r", "now"], check=True)
        else:  # Linux
            subprocess.run(["shutdown", "-r", "now"], check=True)
    except Exception as e:
        print(f"[Restart Error] {e}")
        speak("I couldn't restart the system.")

def sleep_system():
    """Put the system to sleep with confirmation."""
    if not _get_confirmation("Are you sure you want to put the system to sleep?"):
        return
    
    speak("Putting the system to sleep now.")
    
    import platform
    import subprocess
    
    try:
        system = platform.system()
        if system == "Windows":
            subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], check=True)
        elif system == "Darwin":  # macOS
            subprocess.run(["pmset", "sleepnow"], check=True)
        else:  # Linux
            subprocess.run(["systemctl", "suspend"], check=True)
    except Exception as e:
        print(f"[Sleep Error] {e}")
        speak("I couldn't put the system to sleep.")

def schedule_power_action(action_type, delay_minutes):
    """
    Schedule a power action for later execution.
    action_type: 'shutdown', 'restart', or 'sleep'
    delay_minutes: delay in minutes
    """
    global _scheduled_power_actions
    
    # Cancel existing action of same type
    if action_type in _scheduled_power_actions:
        _scheduled_power_actions[action_type].cancel()
    
    speak(f"Okay, I'll {action_type} the system in {delay_minutes} minutes.")
    
    # Map action types to functions
    action_map = {
        'shutdown': lambda: shutdown_system_immediate(),
        'restart': lambda: restart_system_immediate(),
        'sleep': lambda: sleep_system_immediate()
    }
    
    # Schedule the action
    timer = threading.Timer(delay_minutes * 60, action_map[action_type])
    timer.start()
    
    _scheduled_power_actions[action_type] = timer

def shutdown_system_immediate():
    """Shutdown without confirmation (for scheduled actions)."""
    speak("Shutting down the system now.")
    
    import platform
    import subprocess
    
    try:
        system = platform.system()
        if system == "Windows":
            subprocess.run(["shutdown", "/s", "/t", "5"], check=True)
        elif system == "Darwin":
            subprocess.run(["sudo", "shutdown", "-h", "now"], check=True)
        else:
            subprocess.run(["shutdown", "-h", "now"], check=True)
    except Exception as e:
        print(f"[Shutdown Error] {e}")

def restart_system_immediate():
    """Restart without confirmation (for scheduled actions)."""
    speak("Restarting the system now.")
    
    import platform
    import subprocess
    
    try:
        system = platform.system()
        if system == "Windows":
            subprocess.run(["shutdown", "/r", "/t", "5"], check=True)
        elif system == "Darwin":
            subprocess.run(["sudo", "shutdown", "-r", "now"], check=True)
        else:
            subprocess.run(["shutdown", "-r", "now"], check=True)
    except Exception as e:
        print(f"[Restart Error] {e}")

def sleep_system_immediate():
    """Sleep without confirmation (for scheduled actions)."""
    speak("Putting the system to sleep now.")
    
    import platform
    import subprocess
    
    try:
        system = platform.system()
        if system == "Windows":
            subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], check=True)
        elif system == "Darwin":
            subprocess.run(["pmset", "sleepnow"], check=True)
        else:
            subprocess.run(["systemctl", "suspend"], check=True)
    except Exception as e:
        print(f"[Sleep Error] {e}")

def cancel_power_action(action_type):
    """Cancel a scheduled power action."""
    global _scheduled_power_actions
    
    if action_type in _scheduled_power_actions:
        _scheduled_power_actions[action_type].cancel()
        del _scheduled_power_actions[action_type]
        speak(f"{action_type.capitalize()} cancelled.")
    else:
        speak(f"No {action_type} action is scheduled.")

