import time
import requests
import sys
import os

# Add root and legacy to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'legacy'))

from instance.config import settings as CONFIG

# Use TTS Coordinator instead of direct speak
try:
    from extensions.system.tts_coordinator import speak, TTSPriority
except ImportError:
    # Fallback
    from legacy.tts import speak
    class TTSPriority:
        COMMAND = "command"

from legacy.memory_manager import (
    update_user_memory,
    delete_memory_key,
    load_user_memory
)


# ======================================================
# RANDOM JOKE
# ======================================================
def get_random_joke():
    try:
        url = "https://v2.jokeapi.dev/joke/Any?safe-mode"
        data = requests.get(url, timeout=6).json()

        if data.get("type") == "single":
            return data["joke"]
        else:
            return f"{data.get('setup')} ... {data.get('delivery')}"

    except Exception:
        return "Couldn't fetch a joke right now."


# ======================================================
# CHAT REPLY HANDLER - UPDATED TO USE TTS COORDINATOR
# ======================================================
def chat_reply(text):
    """Handles small talk, memory commands, and clarification requests."""
    user_id = CONFIG.get("CURRENT_USER_ID", None)
    text_l = text.lower().strip()

    # -----------------------------------------------
    # MEMORY: REMEMBER
    # -----------------------------------------------
    if text_l.startswith("remember"):
        fact = text_l.replace("remember", "").strip()

        if not fact:
            speak("What should I remember?", priority=TTSPriority.COMMAND)
            return True

        key = fact.split()[0]

        if user_id:
            update_user_memory(user_id, key, fact)
            msg = f"Okay, I will remember that {fact}."
        else:
            msg = "I can remember things only after you log in."
        
        speak(msg, priority=TTSPriority.COMMAND)
        return msg

    # -----------------------------------------------
    # MEMORY: FORGET
    # -----------------------------------------------
    if text_l.startswith("forget"):
        key = text_l.replace("forget", "").strip()

        if not key:
            speak("What should I forget?", priority=TTSPriority.COMMAND)
            return True

        if user_id:
            delete_memory_key(user_id, key)
            msg = f"Okay, I forgot {key}."
        else:
            msg = "I can forget things only after you log in."

        speak(msg, priority=TTSPriority.COMMAND)
        return msg

    # -----------------------------------------------
    # MEMORY: RECALL
    # -----------------------------------------------
    if "what do you remember" in text_l or "what did i say" in text_l:

        if not user_id:
            msg = "I can recall memory only after you log in."
            speak(msg, priority=TTSPriority.COMMAND)
            return msg

        mem = load_user_memory(user_id)

        if not mem:
            msg = "I don't have anything in memory yet."
            speak(msg, priority=TTSPriority.COMMAND)
            return msg
        else:
            speak("Here's what I remember:", priority=TTSPriority.COMMAND)
            lines = []
            for value in mem.values():
                speak(value, priority=TTSPriority.COMMAND)
                lines.append(value)
            return "Here's what I remember: " + "; ".join(lines)

    # -----------------------------------------------
    # CLARIFICATION / REPEAT REQUESTS
    # -----------------------------------------------
    clarification_exact = [
        "wait", "what?", "what", "repeat", "say again",
        "i don't understand", "i didnt understand",
        "can you repeat", "what did you say",
        "huh", "pardon"
    ]

    if text_l in clarification_exact or text_l.rstrip("?.!") in clarification_exact:
        last = CONFIG.get("LAST_ASSISTANT_MSG")
        msg = last if last else "I haven't said anything recently to repeat."
        speak(msg, priority=TTSPriority.COMMAND)
        return msg

    # -----------------------------------------------
    # BASIC SMALL TALK
    # -----------------------------------------------
    if "how are you" in text_l:
        msg = "I'm doing great, thanks for asking!"
        speak(msg, priority=TTSPriority.COMMAND)
        return msg

    if "your name" in text_l:
        msg = f"My name is Neural Omnie Virtual Assistant. Or you can call me {CONFIG['ASSISTANT_NAME']} in short."
        speak(msg, priority=TTSPriority.COMMAND)
        return msg

    if "who created you" in text_l:
        msg = "I was created by Ram Sathvik."
        speak(msg, priority=TTSPriority.COMMAND)
        return msg

    if "thank" in text_l:
        msg = "You're welcome!"
        speak(msg, priority=TTSPriority.COMMAND)
        return msg

    if "joke" in text_l:
        msg = get_random_joke()
        speak(msg, priority=TTSPriority.COMMAND)
        return msg

    # -----------------------------------------------
    # MORE HUMAN-LIKE SMALL TALK
    # -----------------------------------------------
    if "how was your day" in text_l:
        msg = "My day has been great! Talking with you always makes it better."
        speak(msg, priority=TTSPriority.COMMAND)
        return msg

    if "what are you doing" in text_l:
        msg = "Just hanging out here, ready to help you anytime!"
        speak(msg, priority=TTSPriority.COMMAND)
        return msg

    if "are you there" in text_l:
        msg = "Yep, I'm right here. What's up?"
        speak(msg, priority=TTSPriority.COMMAND)
        return msg

    if "do you like me" in text_l:
        msg = "Of course! I enjoy talking with you."
        speak(msg, priority=TTSPriority.COMMAND)
        return msg

    if "i am bored" in text_l:
        msg = "Want to hear a joke or try something fun?"
        speak(msg, priority=TTSPriority.COMMAND)
        return msg

    if "i am sad" in text_l or "i feel sad" in text_l:
        msg = "I'm here for you. Want to talk about it, or should I cheer you up?"
        speak(msg, priority=TTSPriority.COMMAND)
        return msg

    if "tell me something" in text_l:
        msg = "Did you know? Your brain processes information faster than any computer!"
        speak(msg, priority=TTSPriority.COMMAND)
        return msg

    if "are you smart" in text_l:
        msg = "I try my best! But you're the real boss here."
        speak(msg, priority=TTSPriority.COMMAND)
        return msg

    return False
