import os
import time
import queue
import threading
import tempfile
from gtts import gTTS
from playsound import playsound
import pyttsx3
from instance.config import settings as CONFIG
from legacy.memory_manager import add_history

# ── Conversational Memory logging ───────────────────────────────
try:
    from extensions.conversational_memory import store_interaction as _store_interaction
    _conv_memory_ok = True
except Exception as _cm_err:
    print(f"[TTS] conversational_memory unavailable: {_cm_err}")
    _conv_memory_ok = False
    def _store_interaction(cmd, resp): pass

# Holds the current user command so speak() can log it.
# Set by assistant.process_input() at the start of every interaction.
current_user_command: str = ""

# Tkinter root reference for thread-safe GUI updates
_tk_root = None

def set_root(root):
    global _tk_root
    _tk_root = root

# Floating button reference (set from main.py)
floating_ref = None

def _start_animation():
    global floating_ref, _tk_root
    try:
        if floating_ref and _tk_root:
            _tk_root.after_idle(floating_ref.start_anim)
    except Exception as e:
        print(f"[TTS Animation Error] Failed to start animation: {e}")

def _stop_animation():
    global floating_ref, _tk_root
    try:
        if floating_ref and _tk_root:
            _tk_root.after_idle(floating_ref.stop_anim)
    except Exception as e:
        print(f"[TTS Animation Error] Failed to stop animation: {e}")


# ----------------------------------------------------
#  TTS QUEUE + WORKER THREAD
# ----------------------------------------------------
_tts_queue = queue.Queue()

# Threading primitives
_worker_lock = threading.Lock()   # prevents double-start race on _ensure_tts_worker
_tts_active  = threading.Event()  # set while the worker is actually synthesizing speech
# _tts_active is clear() when idle, set() when a phrase is playing.
# sst.py can call wait_for_silence() to block until TTS finishes.


def _tts_worker():
    import pythoncom
    pythoncom.CoInitialize()

    while True:
        text, lang_hint = _tts_queue.get()
        if text is None:          # poison-pill shutdown signal
            _tts_queue.task_done()
            break

        _start_animation()
        _tts_active.set()         # mark TTS as speaking

        try:
            success = False
            if lang_hint == 'en':
                success = _speak_pyttsx3(text)
                if not success:
                    # pyttsx3 failed — fall back to gTTS for English
                    print("[TTS] pyttsx3 failed; trying gTTS fallback for English")
                    success = _speak_gtts(text, 'en')
            else:
                success = _speak_gtts(text, lang_hint)
                if not success:
                    print(f"[TTS] gTTS failed for lang={lang_hint}")

            if not success:
                print(f"[TTS] Both synthesis engines failed for text: {text[:60]!r}")
        finally:
            _tts_active.clear()   # mark TTS as idle
            _stop_animation()
            _tts_queue.task_done()


# TTS worker thread — started on demand
_tts_thread = None


def _ensure_tts_worker():
    """Start TTS worker thread if not already running.

    Protected by a lock so concurrent first-time callers cannot
    start two worker threads.
    """
    global _tts_thread
    with _worker_lock:
        if _tts_thread is None or not _tts_thread.is_alive():
            _tts_thread = threading.Thread(target=_tts_worker, daemon=True,
                                           name="assistant-tts-worker")
            _tts_thread.start()
            print("[TTS] Background worker started")


# ── Public helpers ────────────────────────────────────────────────────────────

def is_speaking() -> bool:
    """Return True while the TTS worker is actively synthesising speech.

    Callers (e.g. sst.listen()) can poll this to avoid self-listening.
    """
    return _tts_active.is_set() or not _tts_queue.empty()


def wait_for_silence(timeout: float = 15.0) -> bool:
    """Block until TTS is idle (queue drained + synthesis finished).

    Returns True if silence was reached within *timeout* seconds,
    False if the timeout elapsed while TTS was still running.
    This is safe to call from any thread.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _tts_queue.empty() and not _tts_active.is_set():
            return True
        time.sleep(0.05)
    return False


# ----------------------------------------------------
# Internal pyttsx3 (English voice)
# Returns True on success, False on failure.
# ----------------------------------------------------
def _speak_pyttsx3(text: str) -> bool:
    try:
        import pythoncom
        pythoncom.CoInitialize()

        engine = pyttsx3.init()

        voices = engine.getProperty("voices")
        if voices:
            selected = voices[0].id
            for v in voices:
                if "zira" in v.name.lower() or "female" in v.name.lower():
                    selected = v.id
            engine.setProperty("voice", selected)

        engine.setProperty("rate", 135)
        engine.setProperty("volume", 1.0)

        engine.say(text)
        engine.runAndWait()
        engine.stop()
        return True

    except Exception as e:
        print(f"[TTS pyttsx3 Error] {e}")
        return False


# ----------------------------------------------------
# gTTS (Multi-language)
# Returns True on success, False on failure.
# ----------------------------------------------------
def _speak_gtts(text: str, lang: str) -> bool:
    temp_file = None
    try:
        import pythoncom
        pythoncom.CoInitialize()

        temp_file = os.path.join(
            tempfile.gettempdir(),
            f"assistant_tts_{int(time.time() * 1000)}.mp3"
        )
        tts_obj = gTTS(text=text, lang=lang)
        tts_obj.save(temp_file)
        playsound(temp_file)
        return True

    except Exception as e:
        print(f"[TTS gTTS Error] {e}")
        return False

    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except OSError:
                pass


# ----------------------------------------------------
# Public speak() — queues the request only.
# Does NOT perform synthesis directly.
# ----------------------------------------------------
def speak(text, lang_hint='en', block=False):
    """Speak text with TTS — starts worker thread if needed.

    This function queues the text and returns immediately unless
    *block=True*.  It is the underlying engine called by the
    TTS Coordinator's worker; do not call it directly from
    application code — use the coordinator instead.
    """
    # Ensure TTS worker is running (thread-safe)
    _ensure_tts_worker()

    # Normalise to string
    if not isinstance(text, str):
        text = str(text)

    if not text.strip():
        return

    # Silence raw code output
    if "def " in text or "class " in text or "import " in text or "{" in text:
        text = "I've created the code file for you."

    # Use per-user configured name for console label; never fall back to "Nova"
    try:
        _asst_label = CONFIG.get_assistant_name() or "Assistant"
    except Exception:
        _asst_label = "Assistant"
    print(f"{_asst_label}: {text}")

    # Log to messages table
    user_id = CONFIG.get("CURRENT_USER_ID")
    if user_id:
        try:
            add_history(user_id, "assistant", text)
        except Exception as e:
            print(f"[DB LOG ERROR] {e}")

    # Log to conversational memory
    if _conv_memory_ok and current_user_command.strip():
        try:
            _store_interaction(current_user_command, text)
        except Exception as _cm_log_err:
            print(f"[CONV_MEMORY LOG ERROR] {_cm_log_err}")

    _tts_queue.put((text, lang_hint))

    if block:
        wait_until_spoken()


def wait_until_spoken():
    """Block until all currently queued TTS messages have been spoken."""
    _tts_queue.join()
