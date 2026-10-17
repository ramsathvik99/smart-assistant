import os
import sys
import time
import queue
import threading
import tempfile

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

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
_voice_rate:   int        = 135    # words-per-minute (conversational default: 125-145 wpm)
_voice_volume: float      = 1.0   # 0.0 – 1.0
_last_playback_metrics: dict = {}

def get_last_playback_metrics() -> dict:
    return dict(_last_playback_metrics)

def get_active_voice_id() -> str | None:
    return _voice_id


_cached_voices: list[dict] | None = None
_cached_voices_lock = threading.Lock()

def invalidate_voice_cache() -> None:
    """Clear voice enumeration cache if voices are installed or updated."""
    global _cached_voices
    with _cached_voices_lock:
        _cached_voices = None


def enumerate_voices() -> list[dict]:
    """
    Return a list of all real installed voices on this Windows system
    (covering both SAPI5 and OneCore voice tokens).
    Each entry: {id, name, gender, language, provider}
    Safe to call from any thread; cached after first successful discovery.
    """
    global _cached_voices
    with _cached_voices_lock:
        if _cached_voices is not None:
            return list(_cached_voices)
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

    with _cached_voices_lock:
        _cached_voices = list(results)

    return results


def validate_user_voice(
    voice_id: str | None,
    provider: str | None = None,
    user_prefs: dict | None = None,
) -> tuple[str, str]:
    """
    Validate requested voice_id against active/target provider.
    Rejects test IDs, SAPI registry IDs on Neural backends, and Neural strings on SAPI backends.
    Returns (valid_provider, valid_voice_id).
    """
    prefs = user_prefs or {}
    target_prov = (provider or prefs.get("voice_engine") or prefs.get("voice_provider") or prefs.get("assistant_voice_provider") or "").lower()

    vid_str = str(voice_id).strip() if voice_id else ""
    vid_lower = vid_str.lower()

    if not target_prov:
        if "hkey_" in vid_lower or "speech\\voices" in vid_lower or "onecore" in vid_lower or "desktop" in vid_lower:
            target_prov = "sapi"
        elif "neural" in vid_lower:
            target_prov = "neural"
        else:
            try:
                from extensions.system.tts_backend import get_tts_backend_manager
                target_prov = get_tts_backend_manager().get_backend().name
            except Exception:
                target_prov = os.getenv("TTS_PROVIDER", "neural").lower()

    gender = prefs.get("gender") or prefs.get("voice_gender")
    language = prefs.get("language") or prefs.get("voice_language")

    if "sapi" in target_prov or "windows" in target_prov:
        from extensions.system.tts_backend import SAPIBackend
        valid_voice = SAPIBackend.validate_or_fallback_voice(vid_str if vid_str else None, gender=gender, language=language)
        return "sapi", valid_voice or "default"
    else:
        from extensions.system.tts_backend import NeuralTTSBackend
        valid_voice = NeuralTTSBackend.validate_or_fallback_voice(vid_str if vid_str else None, gender=gender, language=language)
        return "neural", valid_voice


def apply_voice_profile(voice_id: str | None, rate: int = 135, volume: float = 1.0, user_id: int | None = None, provider: str | None = None):
    """
    Set the per-user voice identity that all subsequent TTS calls will use.
    Performs provider-aware voice validation, corrects obsolete/test IDs,
    and persists corrected valid profiles per-user.
    """
    global _voice_id, _voice_rate, _voice_volume
    target_rate   = max(80, min(300, int(rate)))
    target_volume = max(0.0, min(1.0, float(volume)))

    eff_uid = user_id
    if eff_uid is None:
        try:
            import config as settings
            eff_uid = getattr(settings, "CURRENT_USER_ID", None) or settings.get_last_user()
        except Exception:
            eff_uid = None

    user_prefs = {}
    if eff_uid:
        try:
            from core.configuration_service import get_config_service
            user_prefs = get_config_service().get_user_preferences(eff_uid)
        except Exception:
            pass

    valid_provider, valid_voice = validate_user_voice(voice_id, provider=provider, user_prefs=user_prefs)

    # If the requested voice was invalid/test ID and had to be corrected, persist the correction
    if voice_id and voice_id != valid_voice and eff_uid:
        print(f"[VOICE] Correcting invalid voice {voice_id!r} -> {valid_voice!r} (provider={valid_provider}) for user {eff_uid}")
        try:
            from core.configuration_service import get_config_service
            cfg = get_config_service()
            cfg.set_preference(eff_uid, "voice_id", valid_voice)
            cfg.set_preference(eff_uid, "voice_provider", valid_provider)
        except Exception as e_pers:
            print(f"[VOICE] Could not persist corrected voice: {e_pers}")

    # Deduplication guard: ignore redundant re-applications of identical voice settings
    if _voice_id == valid_voice and _voice_rate == target_rate and _voice_volume == target_volume:
        return

    _voice_id     = valid_voice
    _voice_rate   = target_rate
    _voice_volume = target_volume
    print(f"[VOICE] Applying voice: {_voice_id} (provider={valid_provider})")
    print(f"[TTS] Voice profile applied — id={_voice_id!r}, rate={_voice_rate}, volume={_voice_volume}")

    try:
        from extensions.system.tts_backend import get_tts_backend_manager
        backend_mgr = get_tts_backend_manager()
        backend_mgr.set_primary_provider(valid_provider)
        if valid_provider == "neural":
            neural_be = backend_mgr.get_backend("neural")
            if hasattr(neural_be, "_voice"):
                neural_be._voice = valid_voice
        elif valid_provider == "sapi":
            sapi_be = backend_mgr.get_backend("sapi")
            if hasattr(sapi_be, "_voice_id"):
                sapi_be._voice_id = valid_voice
    except Exception as e:
        print(f"[TTS] Voice sync warning: {e}")


def preview_voice(voice_id: str, rate: int = 155, volume: float = 1.0, text: str = "Hello. This is a preview of my voice.") -> bool:
    """
    Speak a short preview sample using THAT SPECIFIC voice token immediately.
    Logs [VOICE] Previewing voice: <voice_id>
    Provider-aware: uses Neural TTS for neural voices, SAPI for Windows voices.
    """
    print(f"[VOICE] Previewing voice: {voice_id}")
    prov, valid_voice = validate_user_voice(voice_id)
    if prov == "neural":
        try:
            from extensions.system.tts_backend import get_tts_backend_manager
            be = get_tts_backend_manager().get_backend("neural")
            if be.is_available():
                res = be.stream_and_play(text, voice=valid_voice, rate=rate / 155.0, volume=volume)
                if not res.error and res.sentences_played > 0:
                    return True
        except Exception as e:
            print(f"[VOICE] Neural preview failed ({e}) — falling back to SAPI")
    return _speak_pyttsx3(text, voice_id=valid_voice, rate=rate, volume=volume)

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
        try:
            from core.voice_lifecycle import get_voice_lifecycle
            get_voice_lifecycle().on_tts_started()
        except Exception:
            pass
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
        playback_backend = "unknown"
        playback_voice = _voice_id
        sentences_played = 0
        byte_count = 0
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
                    playback_backend = active_backend.name
                    # If lang_hint is English (or omitted) and _voice_id is set, pass it;
                    # otherwise let active_backend resolve to the proper target multilingual neural voice.
                    req_voice = _voice_id if (not lang_hint or str(lang_hint).lower() in ("en", "en-us", "en-gb", "en-in")) else None
                    res = active_backend.stream_and_play(
                        text,
                        voice=req_voice,
                        language=lang_hint,
                        rate=_voice_rate / 155.0,
                        volume=_voice_volume,
                        metadata=meta,
                    )
                    playback_voice = res.voice_used or _voice_id
                    sentences_played = res.sentences_played
                    byte_count = res.byte_count
                    if res.interrupted or _tts_interrupted.is_set():
                        continue
                    if not res.error and res.sentences_played > 0:
                        success = True
                    else:
                        print(f"[TTS DIAGNOSTIC] Neural backend stream error ({res.error or '0 sentences'}) [voice={req_voice}, lang={lang_hint}] — falling back to SAPI/pyttsx3")
            except Exception as _neural_err:
                print(f"[TTS DIAGNOSTIC] Neural backend exception: {_neural_err} [voice={_voice_id}, lang={lang_hint}] — falling back to SAPI/pyttsx3")

            # ── 2. Fallback to native Windows SAPI / OneCore (English) ──
            if not success and not _tts_interrupted.is_set():
                playback_backend = "sapi_fallback"
                if lang_hint == 'en':
                    success = _speak_pyttsx3(text)
                    if not success and not _tts_interrupted.is_set():
                        # pyttsx3 failed — fall back to gTTS for English
                        print("[TTS DIAGNOSTIC] pyttsx3 failed; trying gTTS fallback for English")
                        playback_backend = "gtts_fallback"
                        success = _speak_gtts(text, 'en')
                else:
                    playback_backend = "gtts_fallback"
                    success = _speak_gtts(text, lang_hint)
                    if not success and not _tts_interrupted.is_set():
                        print(f"[TTS DIAGNOSTIC] gTTS failed for lang={lang_hint}")

            if not success and not _tts_interrupted.is_set():
                print(f"[TTS DIAGNOSTIC] Both synthesis engines failed for text: {text[:60]!r}")
        finally:
            duration = max(0.001, time.monotonic() - t_start)
            ui_text = (meta.get("ui_text") or meta.get("text") or text) if isinstance(meta, dict) else text
            metrics = {
                "ui_text": ui_text,
                "speech_text": text,
                "word_count": len(text.split()),
                "char_count": len(text),
                "duration": duration,
                "playback_duration_sec": duration,
                "success": bool(success),
                "interrupted": bool(_tts_interrupted.is_set()),
                "backend_used": playback_backend,
                "voice_used": playback_voice,
                "sentences_played": sentences_played,
                "byte_count": byte_count,
                "timestamp": time.time(),
            }
            global _last_playback_metrics
            _last_playback_metrics = metrics
            try:
                if success:
                    print(f"[TTS METRICS] UI text: {ui_text[:100]!r} | Speech text: {text!r} | Words: {metrics['word_count']} | Chars: {metrics['char_count']} | Duration: {duration:.2f}s | Backend: {playback_backend}")
                elif _tts_interrupted.is_set():
                    print(f"[TTS METRICS] INTERRUPTED: UI text: {ui_text[:60]!r} | Duration: {duration:.2f}s")
                else:
                    print(f"[TTS METRICS] PLAYBACK FAILED: UI text: {ui_text[:60]!r} | Duration: {duration:.2f}s | Backend: {playback_backend}")
            except Exception:
                try:
                    print(f"[TTS METRICS] UI text: {ascii(ui_text[:100])} | Speech text: {ascii(text)} | Duration: {duration:.2f}s | Backend: {playback_backend}")
                except Exception:
                    pass
            with _tts_state_lock:
                _active_tts_text = ""
            _tts_active.clear()   # mark TTS as idle
            _stop_animation()
            try:
                from core.voice_lifecycle import get_voice_lifecycle
                get_voice_lifecycle().on_tts_finished()
            except Exception:
                pass
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
    raw_vid = voice_id if voice_id is not None else _voice_id
    effective_rate = rate if rate is not None else _voice_rate
    effective_vol = volume if volume is not None else _voice_volume

    from extensions.system.tts_backend import SAPIBackend
    effective_vid = SAPIBackend.validate_or_fallback_voice(raw_vid)

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

        # Convert WPM (80-300, baseline ~145 conversational) to SAPI Rate (-10 to +10)
        sapi_rate = max(-10, min(10, int(round((effective_rate - 145) / 14.0))))
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

    # Adapt text for natural spoken conversation (pauses, numbers, clean structure)
    try:
        from extensions.system.speech_adapter import adapt_for_speech
        text, _ = adapt_for_speech(text)
    except Exception:
        pass

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
    try:
        print(f"{_asst_label}: {text}")
    except Exception:
        try:
            print(f"{_asst_label}: {ascii(text)}")
        except Exception:
            pass

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
            from core.voice_lifecycle import get_voice_lifecycle
            get_voice_lifecycle().on_tts_finished()
        except Exception:
            pass
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


def run_tts_diagnostic(text: str | None = None, user_id: int | None = None) -> dict:
    """Run full 6-stage end-to-end TTS diagnostic."""
    from extensions.system.tts_backend import run_tts_diagnostic as _diag
    return _diag(text=text, user_id=user_id)


