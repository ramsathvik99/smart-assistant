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
    from extensions.system.tts_coordinator import speak, TTSPriority, initialize_tts_coordinator
    try:
        from legacy.tts import speak as _legacy_speak
        initialize_tts_coordinator(_legacy_speak)
    except Exception as _tts_init_err:
        pass
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
    from extensions.reminder_engine import initialize_scheduler, get_scheduler
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
    reminder_scheduler = get_scheduler()
    if reminder_scheduler is None:
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

from collections import defaultdict

# User-scoped conversation memory
last_response_by_user = {}
conversation_history_by_user = defaultdict(list)

# Backward-compatibility handles
last_response = ""
conversation_history = []

IGNORED_RESPONSES = [
    "yes boss",
    "ok",
    "okay",
    "done",
    ""
]

def get_last_response(user_id=None):
    from instance.config import settings
    uid = user_id or getattr(settings, 'CURRENT_USER_ID', None) or 1
    resp = last_response_by_user.get(uid)
    if resp:
        return resp
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

def store_interaction(user_input, response, user_id=None):
    global last_response
    from instance.config import settings
    uid = user_id or getattr(settings, 'CURRENT_USER_ID', None) or 1

    clean_response = response.lower().strip() if response else ""

    # Only store meaningful responses
    if clean_response not in IGNORED_RESPONSES:
        last_response_by_user[uid] = response
        last_response = response

    # User-scoped conversation history
    entry = {
        "user": user_input,
        "response": response,
        "user_id": uid
    }
    conversation_history_by_user[uid].append(entry)
    conversation_history.append(entry)

def search_history(query, user_id=None):
    from instance.config import settings
    uid = user_id or getattr(settings, 'CURRENT_USER_ID', None) or 1
    query_words = query.lower().strip().split()
    user_history = conversation_history_by_user.get(uid, [])
    for item in reversed(user_history):
        combined = (item["user"] + " " + item["response"]).lower()
        if any(word in combined for word in query_words):
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

# ── Utterance deduplication & concurrency controls ───────────
_last_utterance_text: str = ""
_last_utterance_time: float = 0.0
_last_utterance_response: str = ""
_last_utterance_user_id = None
_utterance_lock = threading.Lock()
_current_turn_epoch: int = 0


def process_input(text, user_id=None):
    """Main entry point for processing user input. Routes strictly via Unified Command Router."""
    # Update proactive activity tracking
    try:
        from legacy.proactive_interaction import reset_proactive_timer
        reset_proactive_timer()
    except Exception:
        pass
        
    if not text or not text.strip():
        return ""

    clean_text = text.strip()
    norm_text = clean_text.lower()
    now_mono = time.monotonic()

    # Utterance Deduplication & Atomic Epoch Transition (Requirement 4)
    with _utterance_lock:
        global _last_utterance_text, _last_utterance_time, _last_utterance_response, _last_utterance_user_id, _current_turn_epoch
        from instance.config import settings as _cfg_dup
        suppression_window = float(_cfg_dup.get("DUPLICATE_UTTERANCE_WINDOW", 0.75))
        if norm_text == _last_utterance_text and user_id == _last_utterance_user_id and (now_mono - _last_utterance_time) < suppression_window:
            print(f"[DEDUPLICATION] Suppressed duplicate utterance '{clean_text}' within {now_mono - _last_utterance_time:.3f}s window.")
            return _last_utterance_response

        _current_turn_epoch += 1
        my_epoch = _current_turn_epoch
        _last_utterance_text = norm_text
        _last_utterance_time = now_mono
        _last_utterance_user_id = user_id

    # Performance instrumentation: Start monotonic latency tracker with unique correlation ID (Requirement 7)
    correlation_id = f"turn_{int(now_mono * 1000)}_{my_epoch}"
    tracker = None
    try:
        from core.latency_instrumentation import start_new_tracker
        tracker = start_new_tracker(correlation_id)
        tracker.record("transcription_complete_timestamp", now_mono)
        tracker.record("routing_start_timestamp", time.monotonic())
    except Exception:
        tracker = None

    # Preemption / Interruption: cancel obsolete in-progress speech from earlier turns
    try:
        from extensions.system.tts_coordinator import get_tts_coordinator
        get_tts_coordinator().interrupt_speech()
    except Exception:
        pass

    try:
        print(f"[ASSISTANT DEBUG] Command [{correlation_id}]: {clean_text}")
    except Exception:
        safe_text = str(clean_text).encode("ascii", errors="backslashreplace").decode("ascii")
        print(f"[ASSISTANT DEBUG] Command [{correlation_id}]: {safe_text}")

    # Forward to Brain (PHASE 6: multi-intent + dialogue state + goal planner)
    # Falls back transparently to unified_command_router for single-intent commands.
    try:
        try:
            from instance.config import settings as _cfg
            current_uid = getattr(_cfg, 'CURRENT_USER_ID', None) or _cfg.get_last_user()
        except Exception:
            current_uid = None

        effective_uid = user_id or current_uid

        # Multilingual Language Detection & Canonical Intent Normalization
        from core.multilingual_engine import get_multilingual_engine
        ml_engine = get_multilingual_engine()
        lang_res = ml_engine.detect_language(clean_text, user_id=effective_uid)
        detected_lang = lang_res.language
        ml_engine.set_active_language(effective_uid, detected_lang)

        if lang_res.is_multilingual:
            routing_text = ml_engine.translate_to_english(clean_text, source_lang=detected_lang)
            try:
                print(f"[MULTILINGUAL] Detected {detected_lang} ({lang_res.locale}) -> Canonical routing: {routing_text}")
            except Exception:
                safe_rt = str(routing_text).encode("ascii", errors="backslashreplace").decode("ascii")
                print(f"[MULTILINGUAL] Detected {detected_lang} -> Canonical routing: {safe_rt}")
        else:
            routing_text = clean_text

        try:
            from core.brain import brain_route_and_execute
            result = brain_route_and_execute(routing_text, user_id=effective_uid)
        except Exception as brain_err:
            # If Brain fails for any reason, fall back to direct single-intent router
            print(f"[BRAIN FALLBACK] {brain_err}")
            from core.unified_command_router import route_and_execute
            result = route_and_execute(routing_text, user_id=effective_uid)

        if tracker:
            tracker.record("routing_complete_timestamp", time.monotonic())
            tracker.record("text_answer_available_timestamp", time.monotonic())

        raw_output = str(result.get("response") or "")
        try:
            from extensions.system.conversational_response import sanitize_user_response
            response = sanitize_user_response(raw_output, routing_text)
        except Exception:
            response = raw_output

        # Concurrency check: If a newer request has started during generation, discard speech
        with _utterance_lock:
            if my_epoch != _current_turn_epoch:
                print(f"[SUPERSEDED] Turn {my_epoch} superseded by turn {_current_turn_epoch} — discarding speech.")
                return response
            _last_utterance_response = response

        # CRITICAL: Check if the request was properly handled to prevent incorrect fallbacks
        if response:
            try:
                from extensions.system.conversational_response import compose_conversational_response
                conv_resp = compose_conversational_response(
                    user_input=clean_text,
                    raw_response=response,
                    intent=result.get("intent"),
                    action_result=result,
                    context={"user_id": effective_uid, "command": routing_text},
                    user_id=effective_uid,
                    is_proactive=False,
                )
                final_ui_text = conv_resp.text or response
                spoken_response = conv_resp.speech_text or conv_resp.text or response
                meta = conv_resp.to_dict()
                meta["ui_text"] = final_ui_text
            except Exception as c_err:
                print(f"[CONVERSATIONAL COMPOSER ERROR] {c_err}")
                final_ui_text = response
                spoken_response = response
                meta = {"ui_text": response}

            # Determine response language: explicit requested instruction > user preference > detected input language
            user_pref_lang = None
            try:
                from core.configuration_service import ConfigurationService
                cfg_svc = ConfigurationService.get_instance()
                user_pref_lang = cfg_svc.get_preference(effective_uid, "assistant_language") or cfg_svc.get_preference(effective_uid, "language")
            except Exception:
                pass

            target_resp_lang = (
                ml_engine.get_requested_response_language(effective_uid)
                or user_pref_lang
                or detected_lang
                or "en"
            )
            target_resp_lang = str(target_resp_lang).strip().lower()[:2]
            if target_resp_lang not in ml_engine.LOCALE_MAP:
                target_resp_lang = detected_lang if detected_lang in ml_engine.LOCALE_MAP else "en"

            resp_script = ml_engine.detect_script(final_ui_text)
            already_in_target = resp_script and resp_script[0] == target_resp_lang

            if target_resp_lang != "en" and not already_in_target:
                final_ui_text = ml_engine.translate_from_english(final_ui_text, target_lang=target_resp_lang)
                spoken_response = ml_engine.translate_from_english(spoken_response, target_lang=target_resp_lang)
                response = final_ui_text

            if target_resp_lang != "en" or already_in_target:
                eff_lang_code = resp_script[0] if already_in_target else target_resp_lang
                meta["lang_hint"] = eff_lang_code
                meta["language"] = eff_lang_code
                meta["locale"] = ml_engine.LOCALE_MAP.get(eff_lang_code, f"{eff_lang_code}-IN")
                meta["ui_text"] = final_ui_text

            try:
                print(f"[SPEECH PIPELINE] Final UI Text: {final_ui_text[:120]!r}")
                print(f"[SPEECH PIPELINE] Speech Text: {spoken_response!r}")
                print(f"[SPEECH PIPELINE] Words: {len(spoken_response.split())} | Chars: {len(spoken_response)}")
            except Exception:
                safe_ui = str(final_ui_text[:120]).encode("ascii", errors="backslashreplace").decode("ascii")
                safe_sp = str(spoken_response).encode("ascii", errors="backslashreplace").decode("ascii")
                print(f"[SPEECH PIPELINE] Final UI Text: {safe_ui}")
                print(f"[SPEECH PIPELINE] Speech Text: {safe_sp}")

            if tracker:
                tracker.record("tts_request_timestamp", time.monotonic())

            # Use TTS Coordinator with COMMAND priority and conversational metadata
            speak(spoken_response, priority=TTSPriority.COMMAND, metadata=meta)

            # Store in conversational memory
            try:
                from extensions.conversational_memory import store_interaction
                store_interaction(clean_text, response, user_id=effective_uid)
            except Exception as e:
                print(f"[MEMORY ERROR] {e}")

            # Store in dialogue state manager for repetition and continuation (preserving per-user isolation)
            is_repeat_cmd = routing_text.lower().strip() in (
                "repeat", "repeat that", "say that again", "repeat last part",
                "repeat the last part", "repeat what you said", "what did you say", "come again"
            )
            if not is_repeat_cmd and (final_ui_text or spoken_response):
                try:
                    from extensions.dialogue_state_manager import get_dialogue_manager
                    dm = get_dialogue_manager(str(effective_uid))
                    dm.update_continuation_state(
                        full_response=final_ui_text,
                        spoken_segment=spoken_response
                    )
                    if result and isinstance(result, dict) and result.get("status") in ("success", True, "completed", None) and not result.get("error"):
                        intent_str = str(result.get("intent", ""))
                        if intent_str not in ("GENERAL_CONVERSATION", "GREETINGS", ""):
                            dm.record_execution_result(
                                execution_result=result,
                                intents=[result.get("intent")] if result.get("intent") else []
                            )
                except Exception as d_err:
                    import logging
                    logging.getLogger("legacy.assistant").warning(f"Failed to update dialogue continuation state: {d_err}")

        if tracker:
            tracker.print_breakdown()

        return response
    except Exception as e:
        err = f"Execution failed: {str(e)}"
        print(f"[ASSISTANT ERROR] {err}")
        err_msg = "I encountered an error executing that command."
        target_lang = "en"
        try:
            if 'detected_lang' in locals() and detected_lang != "en":
                target_lang = detected_lang
                err_msg = ml_engine.translate_from_english(err_msg, target_lang=target_lang)
        except Exception:
            pass
        speak(err_msg, priority=TTSPriority.COMMAND, metadata={"lang_hint": target_lang})
        if tracker:
            tracker.set_reason(fallback=str(e))
            tracker.print_breakdown()
        return err
