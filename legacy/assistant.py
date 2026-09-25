# assistant.py  (FINAL FIXED VERSION)
import os
import time
import re
import threading
import signal
import sys
from typing import Dict, Any, List

from instance.config import settings as CONFIG
from legacy.sst import listen

# Use TTS Coordinator instead of direct speak()
try:
    from extensions.system.tts_coordinator import speak, TTSPriority
except ImportError:
    # Fallback to direct speak if coordinator not available
    from legacy.tts import speak
    class TTSPriority:
        COMMAND = "command"

from legacy.actions import close_app

from legacy.memory_manager import (
    get_or_create_user,
    add_history,
    get_chat_history,
)

from legacy.actions import (
    open_website, open_app, system_action, search_web, shutdown_assistant, open_camera
)

from extensions.services.app_service import AppService

# Initialize Personality Engine
try:
    from extensions.personality_engine import get_personality, format_response, adjust_behavior, get_behavior_layer, start_proactive_system, update_proactive_interaction
    
    # Global personality instances
    personality = get_personality()
    behavior_layer = get_behavior_layer()
    
    # Start proactive personality system
    start_proactive_system()
    
    print("[PERSONALITY ENGINE] Initialized successfully")
except ImportError as e:
    print(f"[PERSONALITY ENGINE] Import failed: {e}")
    # Fallback to None if module not available
    personality = None
    behavior_layer = None
    def format_response(text, intent=None, context=None): return text
    def adjust_behavior(command, context, memory=None): return None
    def update_proactive_interaction(): pass

app_service = AppService()

def speak_with_personality(text: str, intent: str | None = None, context: Dict[str, Any] | None = None):
    """Speak with assistant's personality formatting"""
    try:
        # Format response through personality engine
        formatted_text = format_response(text, intent, context)
        
        # Update behavior tracking
        if behavior_layer and context:
            command = context.get("command", "")
            behavior_layer.update_interaction(command, context)
        
        # Update proactive interaction time
        update_proactive_interaction()
        
        # Speak the formatted response through TTS Coordinator
        # Use COMMAND priority since this is user-requested
        speak(formatted_text, priority=TTSPriority.COMMAND)
        
    except Exception as e:
        print(f"[PERSONALITY ERROR] Failed to format response: {e}")
        # Fallback to direct speak
        speak(text, priority=TTSPriority.COMMAND)

def get_memory_for_personality() -> List[str] | None:
    """Get recent memory for personality processing"""
    # DISABLED - Preventing LLM interference with memory data
    print("[DEBUG] Personality memory system DISABLED to prevent LLM interference")
    return None


# Initialize Reminder Engine
try:
    from extensions.reminder_engine import initialize_scheduler
    from extensions.database_manager import DatabaseManager
    from legacy.memory_manager import get_connection
    from instance.config import settings
    # NOTE: Do NOT re-import legacy.tts.speak here — it would shadow the
    # TTS coordinator's speak() imported at the top of this module and
    # break every call that passes priority=TTSPriority.COMMAND.
    # The coordinator's speak() (already bound above) accepts both text
    # and priority, so it is safe to use directly as the TTS callback.

    def reminder_sound_alert():
        """Play a simple sound alert before reminder"""
        try:
            import winsound
            winsound.Beep(1000, 200)  # 1000Hz for 200ms
        except ImportError:
            # Fallback: print alert
            print("[REMINDER ALERT] *** BEEP ***")
        except Exception as e:
            print(f"[REMINDER ALERT] Sound failed: {e}")

    # Create database manager for reminder persistence
    class SimplePoolWrapper:
        def __init__(self, connection_func):
            self.get_connection = connection_func
        
        def getconn(self):
            return self.get_connection()
        
        def putconn(self, conn):
            try:
                conn.close()
            except:
                pass

    db_manager = DatabaseManager(SimplePoolWrapper(get_connection))

    # Get the authenticated user ID from session
    user_id = getattr(settings, 'CURRENT_USER_ID', None)

    # Use the coordinator's speak() (already imported at module top).
    # It will route through the priority queue to legacy.tts.speak().
    reminder_scheduler = initialize_scheduler(
        tts_callback=speak,
        sound_callback=reminder_sound_alert,
        db_manager=db_manager,
        user_id=user_id
    )
    print(f"[REMINDER ENGINE] Initialized successfully with database persistence for user {user_id}")
except ImportError as e:
    print(f"[REMINDER ENGINE] Import failed: {e}")
    reminder_scheduler = None
except Exception as e:
    print(f"[REMINDER ENGINE] Initialization error: {e}")
    reminder_scheduler = None

from legacy.skills import (
    tell_time, tell_date, solve_math, take_screenshot, lock_system,
    translate_text, define_word,
    add_note, read_notes, set_reminder,
    delete_note, delete_note_by_text, clear_all_notes, update_note,
    pin_note, unpin_note, mark_note_done,
    search_notes, show_pinned_notes, show_done_notes,
    set_timer, set_alarm,
    convert_currency, convert_units,
    play_music, ask_ai, pause_music, resume_music, stop_music,
    next_song, previous_song, lower_volume, restore_volume, mute_volume, unmute_volume,
    get_weather, get_news
)

# --- DIRECT AI CODE GENERATION BYPASS ---
# Removed direct AI code generation bypass
# ----------------------------------------

# Initialize RAG System (Global Architectural Upgrade)
try:
    from extensions.rag_system import RAGSystem
    rag_system = RAGSystem()
    print("[RAG SYSTEM] Global module initialized")
except ImportError as e:
    print(f"[RAG SYSTEM] Import failed: {e}")
    rag_system = None

# Global Orchestrator Placeholder
orchestrator = None

def shutdown_assistant():
    """Unconditional shutdown function to prevent UnboundLocalError"""
    try:
        # Shutdown reminder engine gracefully
        if reminder_scheduler:
            print("[REMINDER ENGINE] Shutting down...")
            reminder_scheduler.stop()
    except Exception as e:
        print(f"[REMINDER ENGINE] Shutdown error: {e}")
    
    print("Shutting down assistant...")
    sys.exit(0)

# Register shutdown handler for SIGINT (Ctrl+C) - Main Thread Only
def shutdown_handler(sig, frame):
    shutdown_assistant()

if threading.current_thread() is threading.main_thread():
    try:
        signal.signal(signal.SIGINT, shutdown_handler)
    except ValueError:
        # Just in case we are in main thread but signal isn't allowed (e.g. non-main interpreter)
        pass



# ======================================================
# CONVERSATION MEMORY FIXES
# ======================================================

last_response = ""
conversation_history = []

IGNORED_RESPONSES = [
    "yes boss",
    "ok",
    "okay",
    "done",
    ""
]

def get_last_response():
    return last_response if last_response else "Nothing to repeat."

def is_repeat_request(user_input):
    text = user_input.lower().strip()
    exact_triggers = [
        "what",
        "what?",
        "repeat",
        "say that again",
        "come again",
        "didn't get that",
        "did not get that"
    ]
    return text in exact_triggers

def store_interaction(user_input, response):
    global last_response

    clean_response = response.lower().strip() if response else ""

    # Only store meaningful responses
    if clean_response not in IGNORED_RESPONSES:
        last_response = response

    # Always keep history
    conversation_history.append({
        "user": user_input,
        "response": response
    })

def search_history(query):
    query = query.lower().strip().split()
    for item in reversed(conversation_history):
        combined = (item["user"] + " " + item["response"]).lower()
        if any(word in combined for word in query):
            return item["response"]
    return None

def is_history_query(user_input):
    text = user_input.lower()
    triggers = [
        "what did you say",
        "what did you say about",
        "tell me again about"
    ]
    return any(trigger in text for trigger in triggers)

def extract_history_query(user_input):
    text = user_input.lower()
    if "about" in text:
        return text.split("about")[-1].strip()
    return None

# ======================================================
# 1) MAIN COMMAND PROCESSOR
# ======================================================

def process_input(text, user_id=None):
    """Main entry point for processing user input. Routes strictly via Unified Command Router."""
    # Update proactive activity tracking
    try:
        from legacy.proactive_interaction import reset_proactive_timer
        reset_proactive_timer()
    except Exception:
        pass
        
    if not text or not text.strip():
        return

    print(f"[ASSISTANT DEBUG] Command: {text}")

    # Forward to Brain (PHASE 6: multi-intent + dialogue state + goal planner)
    # Falls back transparently to unified_command_router for single-intent commands.
    try:
        try:
            from instance.config import settings as _cfg
            current_uid = getattr(_cfg, 'CURRENT_USER_ID', None) or _cfg.get_last_user()
        except Exception:
            current_uid = None

        effective_uid = user_id or current_uid

        try:
            from core.brain import brain_route_and_execute
            result = brain_route_and_execute(text, user_id=effective_uid)
        except Exception as brain_err:
            # If Brain fails for any reason, fall back to direct single-intent router
            print(f"[BRAIN FALLBACK] {brain_err}")
            from core.unified_command_router import route_and_execute
            result = route_and_execute(text, user_id=effective_uid)

        response = str(result.get("response") or "")
        
        # CRITICAL: Check if the request was properly handled to prevent incorrect fallbacks
        # If the request is marked as handled, do not attempt any additional processing
        if result.get("handled", False):
            print(f"[ASSISTANT DEBUG] Request was properly handled by subsystem. Response: {response}")
            if response:
                # Use TTS Coordinator with COMMAND priority
                speak(response, priority=TTSPriority.COMMAND)
                # Store in conversational memory
                try:
                    from extensions.conversational_memory import store_interaction
                    store_interaction(text, response)
                except Exception as e:
                    print(f"[MEMORY ERROR] {e}")
            return response
        
        # If not marked as handled, process normally
        if response:
            # Use TTS Coordinator with COMMAND priority
            speak(response, priority=TTSPriority.COMMAND)
            # Store in conversational memory
            try:
                from extensions.conversational_memory import store_interaction
                store_interaction(text, response)
            except Exception as e:
                print(f"[MEMORY ERROR] {e}")

        return response
    except Exception as e:
        err = f"Execution failed: {str(e)}"
        print(f"[ASSISTANT ERROR] {err}")
        speak("I encountered an error executing that command.", priority=TTSPriority.COMMAND)
        return err
