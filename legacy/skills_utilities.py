"""
Skills Utilities - Implementations for common skill functions needed by unified_command_router

Provides: tell_time, tell_date, solve_math, translate_text, etc.
"""

import logging
import re
import datetime
from typing import Optional

logger = logging.getLogger(__name__)

def tell_time() -> str:
    """Get current time"""
    try:
        now = datetime.datetime.now()
        time_str = now.strftime("%I:%M %p")  # 12-hour format with AM/PM
        return f"The current time is {time_str}."
    except Exception as e:
        logger.error(f"Error getting time: {e}")
        return "Unable to retrieve current time."

def tell_date() -> str:
    """Get current date"""
    try:
        now = datetime.datetime.now()
        date_str = now.strftime("%A, %B %d, %Y")  # e.g., "Monday, January 15, 2024"
        return f"Today is {date_str}."
    except Exception as e:
        logger.error(f"Error getting date: {e}")
        return "Unable to retrieve current date."

def solve_math(expression: str) -> Optional[str]:
    """Solve mathematical expression"""
    try:
        # Extract the mathematical expression from the input
        # Remove common phrases
        math_text = expression.lower()
        phrases_to_remove = ["what is", "calculate", "what's", "math", "solve"]
        for phrase in phrases_to_remove:
            math_text = math_text.replace(phrase, " ")
        
        math_text = math_text.strip()
        
        # Replace common words with operators
        math_text = math_text.replace("times", "*")
        math_text = math_text.replace("multiplied by", "*")
        math_text = math_text.replace("divided by", "/")
        math_text = math_text.replace("plus", "+")
        math_text = math_text.replace("minus", "-")
        
        # Extract numbers and operators
        # Simple regex to validate mathematical expression
        if not re.match(r'^[0-9+\-*/().\s]+$', math_text):
            return None
        
        # Evaluate the expression safely
        try:
            result = eval(math_text)
            return f"The answer is {result}."
        except ZeroDivisionError:
            return "Cannot divide by zero."
        except SyntaxError:
            return "Invalid mathematical expression."
            
    except Exception as e:
        logger.error(f"Error solving math: {e}")
        return None

def translate_text(text: str) -> Optional[str]:
    """Translate text to another language"""
    try:
        # Extract source and target languages
        text_lower = text.lower()
        
        # Pattern: "translate [text] to [language]" or "say [text] in [language]"
        patterns = [
            r'translate\s+["\']?(.+?)["\']?\s+(?:to|into)\s+(\w+)',
            r'say\s+["\']?(.+?)["\']?\s+in\s+(\w+)',
        ]
        
        target_text = None
        target_lang = None
        
        for pattern in patterns:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                target_text = match.group(1).strip()
                target_lang = match.group(2).strip()
                break
        
        if not target_text or not target_lang:
            return None
        
        try:
            from deep_translator import GoogleTranslator
            
            # Map language names to language codes
            lang_map = {
                "spanish": "es",
                "french": "fr",
                "german": "de",
                "italian": "it",
                "portuguese": "pt",
                "russian": "ru",
                "chinese": "zh-CN",
                "japanese": "ja",
                "korean": "ko",
                "hindi": "hi",
                "telugu": "te",
                "tamil": "ta",
                "kannada": "kn",
                "malayalam": "ml",
            }
            
            lang_code = lang_map.get(target_lang.lower(), target_lang.lower())
            
            translator = GoogleTranslator(source='en', target=lang_code)
            translated = translator.translate(target_text)
            
            return f"{target_text} in {target_lang} is: {translated}"
            
        except ImportError:
            return f"Translation service not available. Please install deep_translator."
        except Exception as e:
            logger.error(f"Translation error: {e}")
            return f"Could not translate text: {str(e)}"
            
    except Exception as e:
        logger.error(f"Error in translate_text: {e}")
        return None

def shutdown_system() -> Optional[str]:
    """Shutdown the system"""
    try:
        import os
        import platform
        
        system = platform.system()
        try:
            from instance.config import settings as _cfg
            _asst = _cfg.get_assistant_name() or "Assistant"
        except Exception:
            _asst = "Assistant"
        
        if system == "Windows":
            os.system(f"shutdown /s /t 60 /c '{_asst} initiated system shutdown'")
            return "System shutdown initiated. The system will shut down in 60 seconds."
        elif system == "Darwin":  # macOS
            os.system("osascript -e 'tell app \"System Events\" to shut down'")
            return "System shutdown initiated."
        elif system == "Linux":
            os.system(f"shutdown -h +1 '{_asst} initiated system shutdown'")
            return "System shutdown initiated. The system will shut down in 1 minute."
        else:
            return "Shutdown not supported on this system."
            
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
        return f"Failed to initiate shutdown: {str(e)}"

def restart_system() -> Optional[str]:
    """Restart the system"""
    try:
        import os
        import platform
        
        system = platform.system()
        try:
            from instance.config import settings as _cfg
            _asst = _cfg.get_assistant_name() or "Assistant"
        except Exception:
            _asst = "Assistant"
        
        if system == "Windows":
            os.system(f"shutdown /r /t 60 /c '{_asst} initiated system restart'")
            return "System restart initiated. The system will restart in 60 seconds."
        elif system == "Darwin":  # macOS
            os.system("osascript -e 'tell app \"System Events\" to restart'")
            return "System restart initiated."
        elif system == "Linux":
            os.system(f"shutdown -r +1 '{_asst} initiated system restart'")
            return "System restart initiated. The system will restart in 1 minute."
        else:
            return "Restart not supported on this system."
            
    except Exception as e:
        logger.error(f"Error during restart: {e}")
        return f"Failed to initiate restart: {str(e)}"

def lock_system() -> Optional[str]:
    """Lock the system"""
    try:
        import os
        import platform
        
        system = platform.system()
        
        if system == "Windows":
            os.system("rundll32.exe user32.dll,LockWorkStation")
            return "System locked."
        elif system == "Darwin":  # macOS
            os.system("open /System/Library/CoreServices/Menu\\ Extras/User.menu/Contents/Resources/CGSession -l")
            return "System locked."
        elif system == "Linux":
            os.system("gnome-screensaver-command -l")
            return "System locked."
        else:
            return "Lock not supported on this system."
            
    except Exception as e:
        logger.error(f"Error locking system: {e}")
        return f"Failed to lock system: {str(e)}"

def sleep_system() -> Optional[str]:
    """Put the system to sleep"""
    try:
        import platform
        import subprocess
        system = platform.system()
        if system == "Windows":
            try:
                import ctypes
                ctypes.windll.powrprof.SetSuspendState(0, 1, 0)
            except Exception:
                subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], check=False)
            return "System sleep initiated."
        elif system == "Darwin":
            subprocess.run(["pmset", "sleepnow"], check=False)
            return "System sleep initiated."
        elif system == "Linux":
            subprocess.run(["systemctl", "suspend"], check=False)
            return "System sleep initiated."
        else:
            return "Sleep not supported on this system."
    except Exception as e:
        logger.error(f"Error putting system to sleep: {e}")
        return f"Failed to sleep system: {str(e)}"

def get_weather(query: str) -> Optional[str]:
    """Get weather information (placeholder - needs API integration)"""
    try:
        from extensions.weather_engine import get_weather_for_query
        return get_weather_for_query(query)
    except ImportError:
        return "Weather service not available."
    except Exception as e:
        logger.error(f"Error getting weather: {e}")
        return f"Could not retrieve weather information: {str(e)}"

# Export functions
__all__ = [
    'tell_time',
    'tell_date',
    'solve_math',
    'translate_text',
    'shutdown_system',
    'restart_system',
    'lock_system',
    'sleep_system',
    'get_weather',
]
