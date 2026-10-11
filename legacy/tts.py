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

# Qt/Tkinter root reference — kept for backward-compat signature only
# With PyQt6 UI, the floating_ref is a _TkBridgeAdapter that handles
# thread-safety internally via QTimer.singleShot.
_tk_root = None

def set_root(root):
    global _tk_root
    _tk_root = root  # no-op in PyQt6 mode; kept for API compatibility

# Floating button reference (set from main.py)
floating_ref = None

# ── Per-user voice identity state ────────────────────────────────────────────
# These are set once at login via apply_voice_profile() and read on every
# pyttsx3 call.  Thread-safe: written only from the main thread at login/settings-save,
# read only from the TTS worker thread which calls _speak_pyttsx3().
_voice_id:     str | None = None   # SAPI5 voice id string; None = pyttsx3 default
_voice_rate:   int        = 155    # words-per-minute
_voice_volume: float      = 1.0   # 0.0 – 1.0
_last_playback_metrics: dict = {}

def get_last_playback_metrics() -> dict:
    return dict(_last_playback_metrics)


def enumerate_voices() -> list[dict]:
    """
    Return a list of all real installed voices on this Windows system
    (covering both SAPI5 and OneCore voice tokens).
    Each entry: {id, name, gender, language, provider}
    Safe to call from any thread.
    """
    import winreg
    import locale

    def _lcid_to_locale(val):
        if not val:
            return "English (United States)"
        s = str(val).strip()
        lang_map = {
            "409": "English (United States)",
            "809": "English (United Kingdom)",
            "1009": "English (Canada)",
            "1809": "English (Ireland)",
            "4009": "English (India)",
            "en-AU": "English (Australia)",
            "en-US": "English (United States)",
            "en-GB": "English (United Kingdom)",
            "en-CA": "English (Canada)",
            "en-IN": "English (India)",
            "en-IE": "English (Ireland)",
        }
        if s in lang_map:
            return lang_map[s]
        try:
            code_int = int(s, 16) if not s.isdigit() else int(s)
            return locale.windows_locale.get(code_int, s).replace("_", " ")
        except Exception:
            return s

    results = []
    seen_ids = set()
    registry_paths = [
        (r"SOFTWARE\Microsoft\Speech\Voices\Tokens", "sapi5"),
        (r"SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens", "onecore")
    ]

    for reg_path, provider in registry_paths:
        try:
            root_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path)
            subkeys_count = winreg.QueryInfoKey(root_key)[0]
            for i in range(subkeys_count):
                token_name = winreg.EnumKey(root_key, i)
                full_id = f"HKEY_LOCAL_MACHINE\\{reg_path}\\{token_name}"
                if full_id in seen_ids:
                    continue
                seen_ids.add(full_id)

                try:
                    skey = winreg.OpenKey(root_key, token_name)
                    try:
                        desc, _ = winreg.QueryValueEx(skey, "")
                    except Exception:
                        desc = token_name

                    gender = "unknown"
                    lang_str = "English (United States)"
                    try:
                        attr_key = winreg.OpenKey(skey, "Attributes")
                        try:
                            g_val, _ = winreg.QueryValueEx(attr_key, "Gender")
                            if g_val and str(g_val).lower() in ("male", "female"):
                                gender = str(g_val).lower()
                        except Exception:
                            pass
                        try:
                            l_val, _ = winreg.QueryValueEx(attr_key, "Language")
                            lang_str = _lcid_to_locale(l_val)
                        except Exception:
                            pass
                    except Exception:
                        pass

                    if gender == "unknown":
                        name_lower = desc.lower()
                        if any(w in name_lower for w in ("zira", "hazel", "linda", "catherine", "susan", "heera", "female")):
                            gender = "female"
                        elif any(w in name_lower for w in ("david", "mark", "george", "richard", "ravi", "james", "sean", "male")):
                            gender = "male"

                    results.append({
                        "id": full_id,
                        "name": desc,
                        "gender": gender,
                        "language": lang_str,
                        "provider": provider
                    })
                except Exception:
                    pass
        except Exception as e:
            print(f"[TTS] Error reading {reg_path}: {e}")

    if not results:
        # Fallback to pyttsx3 default enumeration if registry search yielded nothing
        try:
            import pyttsx3
            eng = pyttsx3.init()
            raw = eng.getProperty("voices") or []
            for v in raw:
                results.append({
                    "id": getattr(v, "id", ""),
                    "name": getattr(v, "name", ""),
                    "gender": "male" if "david" in getattr(v, "name", "").lower() else "female",
                    "language": "English (United States)",
                    "provider": "sapi5"
                })
            eng.stop()
        except Exception:
            pass

    print("[VOICE DISCOVERY] Provider: sapi5")
    print(f"[VOICE DISCOVERY] Found {len(results)} voices")
    for v in results:
        print(f"[VOICE DISCOVERY] Voice:\n    name={v.get('name')}\n    id={v.get('id')}\n    languages={v.get('language')}")

    return results


def apply_voice_profile(voice_id: str | None, rate: int = 155, volume: float = 1.0):
    """
    Set the per-user voice identity that all subsequent pyttsx3 calls will use.
    Call this once at login and again whenever the user saves new settings.
    Thread-safe: only call from the main/UI thread.
    """
    global _voice_id, _voice_rate, _voice_volume
    _voice_id     = voice_id
    _voice_rate   = max(80, min(300, int(rate)))
    _voice_volume = max(0.0, min(1.0, float(volume)))
    if voice_id:
        print(f"[VOICE] Applying voice: {voice_id}")
    print(f"[TTS] Voice profile applied — id={voice_id!r}, rate={_voice_rate}, volume={_voice_volume}")


def preview_voice(voice_id: str, rate: int = 155, volume: float = 1.0, text: str = "Hello. This is a preview of my voice.") -> bool:
    """
    Speak a short preview sample using THAT SPECIFIC voice token immediately.
    Logs [VOICE] Previewing voice: <voice_id>
    """
    print(f"[VOICE] Previewing voice: {voice_id}")
    return _speak_pyttsx3(text, voice_id=voice_id, rate=rate, volume=volume)

# Speech listener callbacks (e.g. for chat feed updates)
_speech_callbacks = []
_speech_callbacks_lock = threading.Lock()

def register_speech_callback(cb):
    """Register a callback invoked with the spoken text when TTS speaks."""
    with _speech_callbacks_lock:
        if cb not in _speech_callbacks:
            _speech_callbacks.append(cb)

def unregister_speech_callback(cb):
    """Unregister a previously registered speech callback."""
    with _speech_callbacks_lock:
        if cb in _speech_callbacks:
            _speech_callbacks.remove(cb)

def _notify_speech_callbacks(text: str):
    with _speech_callbacks_lock:
        cbs = list(_speech_callbacks)
    for cb in cbs:
        try:
            cb(text)
        except Exception as e:
            print(f"[TTS Callback Error] {e}")

def _start_animation():
    """Notify the floating launcher that TTS started. Works with both
    the old Tkinter FloatingButton and the new PyQt6 _TkBridgeAdapter."""
    global floating_ref
    try:
        if floating_ref:
            floating_ref.start_anim()
    except Exception as e:
        print(f"[TTS Animation Error] Failed to start animation: {e}")

def _stop_animation():
    """Notify the floating launcher that TTS stopped."""
    global floating_ref
    try:
        if floating_ref:
            floating_ref.stop_anim()
    except Exception as e:
        print(f"[TTS Animation Error] Failed to stop animation: {e}")


# ----------------------------------------------------
#  TTS QUEUE + WORKER THREAD
# ----------------------------------------------------
_tts_queue = queue.Queue()

# Threading primitives & barge-in state
_worker_lock      = threading.Lock()   # prevents double-start race on _ensure_tts_worker
_tts_active       = threading.Event()  # set while the worker is actually synthesizing speech
_tts_interrupted  = threading.Event()  # set when barge-in or stop is requested
_tts_state_lock   = threading.Lock()
_active_sp_voice  = None               # active COM SpVoice object for instant purge
_active_tts_text  = ""                 # text currently being spoken
_last_interrupted_speech = None        # {'text': ..., 'timestamp': ...}


def _tts_worker():
    import pythoncom
    pythoncom.CoInitialize()

    while True:
        text, lang_hint = _tts_queue.get()
        if text is None:          # poison-pill shutdown signal
            _tts_queue.task_done()
            break

        _tts_interrupted.clear()
        with _tts_state_lock:
            global _active_tts_text
            _active_tts_text = text

        _start_animation()
        _tts_active.set()         # mark TTS as speaking
        _notify_speech_callbacks(text)

        meta = None
        try:
            from extensions.system.tts_coordinator import get_tts_coordinator
            cur_req = get_tts_coordinator()._current_request
            if cur_req and cur_req.text == text:
                meta = cur_req.metadata
        except Exception:
            pass

        t_start = time.monotonic()
        try:
            success = False
            if _tts_interrupted.is_set():
                continue

            # ── 1. Try Pluggable Neural Streaming TTS Backend ─────────
            try:
                from extensions.system.tts_backend import get_tts_backend_manager
                backend_mgr = get_tts_backend_manager()
                active_backend = backend_mgr.get_backend()
                if active_backend.name != "sapi" and active_backend.is_available():
                    res = active_backend.stream_and_play(text, metadata=meta)
                    if res.interrupted or _tts_interrupted.is_set():
                        continue
                    if not res.error:
                        success = True
            except Exception as _neural_err:
                print(f"[TTS] Neural backend notice ({_neural_err}) — falling back to SAPI/pyttsx3")

            # ── 2. Fallback to native Windows SAPI / OneCore (English) ──
            if not success and not _tts_interrupted.is_set():
                if lang_hint == 'en':
                    success = _speak_pyttsx3(text)
                    if not success and not _tts_interrupted.is_set():
                        # pyttsx3 failed — fall back to gTTS for English
                        print("[TTS] pyttsx3 failed; trying gTTS fallback for English")
                        success = _speak_gtts(text, 'en')
                else:
                    success = _speak_gtts(text, lang_hint)
                    if not success and not _tts_interrupted.is_set():
                        print(f"[TTS] gTTS failed for lang={lang_hint}")

            if not success and not _tts_interrupted.is_set():
                print(f"[TTS] Both synthesis engines failed for text: {text[:60]!r}")
        finally:
            duration = max(0.01, time.monotonic() - t_start)
            ui_text = (meta.get("ui_text") or meta.get("text") or text) if isinstance(meta, dict) else text
            metrics = {
                "ui_text": ui_text,
                "speech_text": text,
                "word_count": len(text.split()),
                "char_count": len(text),
                "duration": duration,
                "timestamp": time.time(),
            }
            global _last_playback_metrics
            _last_playback_metrics = metrics
            print(f"[TTS METRICS] UI text: {ui_text[:100]!r} | Speech text: {text!r} | Words: {metrics['word_count']} | Chars: {metrics['char_count']} | Duration: {duration:.2f}s")
            with _tts_state_lock:
                _active_tts_text = ""
            _tts_active.clear()   # mark TTS as idle
            _stop_animation()
            _tts_queue.task_done()
            try:
                from legacy.sst import get_echo_guard
                _eg = get_echo_guard()
                if _eg is not None:
                    _eg.reset()
            except Exception:
                pass


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
# Internal Windows SAPI / pyttsx3 (English voice)
# Returns True on success, False on failure.
# ----------------------------------------------------
def _speak_pyttsx3(text: str, voice_id: str | None = None, rate: int | None = None, volume: float | None = None) -> bool:
    """
    Synthesise speech using Windows SAPI / pyttsx3 with the specified or current per-user voice profile.
    Supports both SAPI5 and OneCore voice tokens.
    Supports instantaneous barge-in cancellation via SAPI purge flags.
    """
    global _active_sp_voice
    effective_vid = voice_id if voice_id is not None else _voice_id
    effective_rate = rate if rate is not None else _voice_rate
    effective_vol = volume if volume is not None else _voice_volume

    # Try native Windows SAPI SpVoice first (supports SAPI5 and OneCore tokens flawlessly)
    try:
        import pythoncom
        pythoncom.CoInitialize()
        import comtypes.client
        import numpy as np

        sp = comtypes.client.CreateObject("SAPI.SpVoice")
        if effective_vid:
            try:
                token = comtypes.client.CreateObject("SAPI.SpObjectToken")
                token.SetId(effective_vid)
                sp.Voice = token
            except Exception as e_tok:
                print(f"[TTS] Saved voice_id {effective_vid!r} not available ({e_tok}) — using engine default")

        # Convert WPM (80-300, baseline 155) to SAPI Rate (-10 to +10)
        sapi_rate = max(-10, min(10, int(round((effective_rate - 155) / 12.0))))
        sp.Rate = sapi_rate
        sp.Volume = max(0, min(100, int(round(effective_vol * 100))))

        with _tts_state_lock:
            _active_sp_voice = sp

        # Note output in EchoGuard without expensive duplicate pre-synthesis
        try:
            from legacy.sst import get_echo_guard
            eg = get_echo_guard()
            if eg is not None:
                sr = 22050
                t_now = time.monotonic()
                dummy_pcm = np.zeros(int(sr * 0.05), dtype=np.int16)
                eg.note_output(dummy_pcm, sr, 0.5, when=t_now)
        except Exception:
            pass

        # Speak asynchronously (flag 1 = SVSFlagsAsync) so we can monitor for barge-in
        sp.Speak(text, 1)

        # Loop until finished or interrupted
        while not sp.WaitUntilDone(30):
            if _tts_interrupted.is_set():
                try:
                    # Instant purge (3 = SVSFlagsAsync | SVSFPurgeBeforeSpeak)
                    sp.Speak("", 3)
                except Exception:
                    pass
                return False

        return not _tts_interrupted.is_set()
    except Exception as sapi_err:
        print(f"[TTS SAPI Notice] Fallback to pyttsx3: {sapi_err}")
    finally:
        with _tts_state_lock:
            if _active_sp_voice is sp:
                _active_sp_voice = None

    # Fallback to standard pyttsx3
    try:
        import pythoncom
        pythoncom.CoInitialize()
        engine = pyttsx3.init()
        if effective_vid:
            try:
                engine.setProperty("voice", effective_vid)
            except Exception:
                pass
        engine.setProperty("rate", effective_rate)
        engine.setProperty("volume", effective_vol)
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
def speak(text, lang_hint='en', block=False, user_id=None):
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

    # Silence raw fenced code blocks
    if text.strip().startswith("```") and "```" in text.strip()[3:]:
        text = "I've created the code file for you."

    # Use per-user configured name for console label; never fall back to "Nova"
    try:
        _asst_label = CONFIG.get_assistant_name() or "Assistant"
    except Exception:
        _asst_label = "Assistant"
    print(f"{_asst_label}: {text}")

    # Log to messages table if explicit user_id is provided
    target_uid = user_id or CONFIG.get("CURRENT_USER_ID")
    if target_uid and user_id is not None:
        try:
            add_history(target_uid, "assistant", text)
        except Exception as e:
            print(f"[DB LOG ERROR] {e}")

    # Log to conversational memory
    if _conv_memory_ok and current_user_command.strip():
        try:
            _store_interaction(current_user_command, text, user_id=user_id)
        except Exception as _cm_log_err:
            print(f"[CONV_MEMORY LOG ERROR] {_cm_log_err}")

    _tts_queue.put((text, lang_hint))

    if block:
        wait_until_spoken()


def wait_until_spoken():
    """Block until all currently queued TTS messages have been spoken."""
    _tts_queue.join()


def stop_speaking(interrupted: bool = False):
    """Drain TTS queue and stop current speech synthesis immediately."""
    global _last_interrupted_speech, _active_sp_voice
    try:
        _tts_interrupted.set()

        # Stop active pluggable TTS backends immediately
        try:
            from extensions.system.tts_backend import get_tts_backend_manager
            get_tts_backend_manager().stop_all(interrupted=interrupted)
        except Exception:
            pass

        with _tts_state_lock:
            if interrupted and _active_tts_text:
                _last_interrupted_speech = {
                    "text": _active_tts_text,
                    "timestamp": time.time(),
                }
                print(f"[TTS BARGE-IN] Interrupted while speaking: {_active_tts_text[:60]!r}")
                try:
                    from extensions.dialogue_state_manager import get_dialogue_manager
                    get_dialogue_manager().update_continuation_state(interrupted_speech=_active_tts_text)
                except Exception:
                    pass
            if _active_sp_voice is not None:
                try:
                    # SVSFlagsAsync | SVSFPurgeBeforeSpeak (3) purges active hardware buffer
                    _active_sp_voice.Speak("", 3)
                except Exception:
                    pass
                _active_sp_voice = None

        while not _tts_queue.empty():
            try:
                _tts_queue.get_nowait()
                _tts_queue.task_done()
            except Exception:
                break

        _tts_active.clear()
        _stop_animation()
        try:
            from legacy.sst import get_echo_guard
            _eg = get_echo_guard()
            if _eg is not None:
                _eg.reset()
        except Exception:
            pass
    except Exception as e:
        print(f"[TTS] Error stopping speech: {e}")


def get_last_interrupted_speech() -> dict | None:
    """Return details of the last interrupted speech, if any."""
    global _last_interrupted_speech
    return _last_interrupted_speech


def clear_interrupted_speech() -> None:
    """Clear the interrupted speech record."""
    global _last_interrupted_speech
    _last_interrupted_speech = None


def is_interrupted() -> bool:
    """Return True if TTS was interrupted."""
    return _tts_interrupted.is_set()

