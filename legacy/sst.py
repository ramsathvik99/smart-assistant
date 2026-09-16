# sst.py
"""
Speech-to-Text module for NOVA.

Backend priority:
  1. PyAudio  (sr.Microphone — chosen device)
  2. sounddevice  (bundled PortAudio — fallback)
  3. None  (graceful fallback, empty string returned)

Self-listening protection
-------------------------
Before opening the microphone this module checks whether TTS output
is in flight.  If it is, it waits up to TTS_DRAIN_TIMEOUT seconds for
silence before proceeding.  This prevents the assistant from capturing
its own speech as a new user command.

Device selection
----------------
_select_input_device() mirrors the four-stage strategy used by
hotword_listener.py (DirectSound "Primary Sound Capture Driver" first,
then any DirectSound device with live audio, then any working input,
finally the OS default).  The result is cached so the probe only runs
once per process.  If the cached device disappears (stream open fails)
the cache is cleared and the selection retried automatically.
"""

import time
import threading
import numpy as np
import speech_recognition as sr

from instance.config import settings as CONFIG

# ── TTS silence guard ─────────────────────────────────────────────────────────
# Maximum seconds to wait for TTS to finish before we open the microphone.
TTS_DRAIN_TIMEOUT = 12.0


def _wait_for_tts_silence() -> None:
    """Block until TTS is idle, so the mic does not capture assistant speech."""
    try:
        from legacy.tts import wait_for_silence
        if not wait_for_silence(timeout=TTS_DRAIN_TIMEOUT):
            print("[SST] TTS drain timed out — proceeding to listen anyway")
    except Exception:
        pass  # If tts module isn't loaded yet, just continue


# ── Detect available audio backend ───────────────────────────────────────────

_PYAUDIO_OK = False
_SOUNDDEVICE_OK = False

try:
    import pyaudio as _pa_probe
    _probe_pa = _pa_probe.PyAudio()   # raises if PortAudio DLL missing
    _probe_pa.terminate()
    _PYAUDIO_OK = True
    print("[SST] Audio backend: PyAudio")
except Exception:
    pass

if not _PYAUDIO_OK:
    try:
        import sounddevice as _sd
        _sd.query_devices()            # raises if no PortAudio
        _SOUNDDEVICE_OK = True
        print("[SST] Audio backend: sounddevice (PyAudio unavailable)")
    except Exception:
        print("[SST] No audio backend available — microphone disabled")

# ── Input device selection ─────────────────────────────────────────────────────
# Cached result: an integer device index or None (use system default).
_cached_input_device_index = None
_device_cache_lock = threading.Lock()


def _test_device_capture(p, device_idx: int, chunk: int = 1536) -> bool:
    """Open *device_idx* briefly and verify it delivers live audio.

    Returns True if the device is active (non-zero, varied signal).
    Mirrors the test used in hotword_listener.py.
    """
    test_stream = None
    try:
        import pyaudio
        test_stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            input_device_index=device_idx,
            frames_per_buffer=chunk,
        )
        data = test_stream.read(chunk, exception_on_overflow=False)
        audio_data = np.frombuffer(data, dtype=np.int16)
        rms = float(np.sqrt(np.mean(audio_data.astype(np.float32) ** 2)))
        unique_len = len(np.unique(audio_data))
        # A working mic delivers a varied signal; a silent/dead device does not.
        return unique_len > 5 and rms > 1.0
    except Exception:
        return False
    finally:
        if test_stream is not None:
            try:
                test_stream.stop_stream()
                test_stream.close()
            except Exception:
                pass


def _find_best_input_device() -> int | None:
    """Select the best available input device using four-stage priority.

    Stage 1 — DirectSound "Primary Sound Capture Driver" (Windows preferred)
    Stage 2 — Any DirectSound input with live audio
    Stage 3 — Any input device with live audio
    Stage 4 — OS default input device (no liveness test)

    Returns the device index, or None to let sr.Microphone use the default.
    """
    if not _PYAUDIO_OK:
        return None

    import pyaudio
    p = pyaudio.PyAudio()
    try:
        device_count = p.get_device_count()

        # Stage 1 — DirectSound "Primary Sound Capture Driver"
        for i in range(device_count):
            try:
                info = p.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) <= 0:
                    continue
                name = info.get("name", "")
                api_idx = info.get("hostApi", -1)
                api_name = (
                    p.get_host_api_info_by_index(api_idx).get("name", "")
                    if api_idx >= 0 else ""
                )
                if "DirectSound" in api_name and "Primary Sound Capture Driver" in name:
                    if _test_device_capture(p, i):
                        print(f"[SST] Selected input device [{i}]: {name} ({api_name})")
                        return i
            except Exception:
                pass

        # Stage 2 — Any DirectSound input with live audio
        for i in range(device_count):
            try:
                info = p.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) <= 0:
                    continue
                api_idx = info.get("hostApi", -1)
                api_name = (
                    p.get_host_api_info_by_index(api_idx).get("name", "")
                    if api_idx >= 0 else ""
                )
                if "DirectSound" in api_name:
                    if _test_device_capture(p, i):
                        name = info.get("name", "")
                        print(f"[SST] Selected input device [{i}]: {name} ({api_name})")
                        return i
            except Exception:
                pass

        # Stage 3 — Any input device with live audio
        for i in range(device_count):
            try:
                info = p.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) <= 0:
                    continue
                if _test_device_capture(p, i):
                    name = info.get("name", "")
                    print(f"[SST] Selected input device [{i}]: {name} (stage-3 fallback)")
                    return i
            except Exception:
                pass

        # Stage 4 — OS default (no liveness test)
        try:
            default_idx = p.get_default_input_device_info().get("index")
            name = p.get_device_info_by_index(default_idx).get("name", "")
            print(f"[SST] Using OS default input device [{default_idx}]: {name}")
            return default_idx
        except Exception as exc:
            print(f"[SST] Could not get default input device: {exc}")
            return None

    finally:
        p.terminate()


def _select_input_device() -> int | None:
    """Return the cached best input device index (runs selection once)."""
    global _cached_input_device_index
    with _device_cache_lock:
        if _cached_input_device_index is None:
            _cached_input_device_index = _find_best_input_device()
    return _cached_input_device_index


def _invalidate_device_cache() -> None:
    """Clear the device cache so the next listen() call re-selects a device.

    Call this when a microphone open fails so a different device is tried.
    """
    global _cached_input_device_index
    with _device_cache_lock:
        _cached_input_device_index = None


# ── Recognizer ────────────────────────────────────────────────────────────────

recognizer = sr.Recognizer()
recognizer.energy_threshold = 300
recognizer.dynamic_energy_threshold = True
recognizer.pause_threshold = 0.9
recognizer.non_speaking_duration = 0.6
recognizer.operation_timeout = None


# ── sounddevice helper ────────────────────────────────────────────────────────

def _record_with_sounddevice(
    duration: float = 8.0, samplerate: int = 16000
) -> "sr.AudioData | None":
    """Record audio using sounddevice and return an sr.AudioData object."""
    import sounddevice as sd

    print("\n🎤 Listening...")
    try:
        recording = sd.rec(
            int(duration * samplerate),
            samplerate=samplerate,
            channels=1,
            dtype="int16",
            blocking=True,
        )
        raw_bytes = recording.tobytes()
        return sr.AudioData(raw_bytes, samplerate, 2)  # 2 bytes/sample (int16)
    except Exception as exc:
        print(f"[SST] sounddevice record error: {exc}")
        return None


# ── TTS fallback speak helper ─────────────────────────────────────────────────

def _tts_speak(text: str) -> None:
    """Route a message through the TTS coordinator (or direct fallback)."""
    try:
        from extensions.system.tts_coordinator import speak as _speak, TTSPriority
        _speak(text, priority=TTSPriority.COMMAND)
    except Exception:
        try:
            from legacy.tts import speak as _speak_direct
            _speak_direct(text)
        except Exception:
            try:
                from instance.config import settings as _cfg
                _asst = _cfg.get_assistant_name() or "Assistant"
            except Exception:
                _asst = "Assistant"
            print(f"{_asst}: {text}")


# ── Public API ────────────────────────────────────────────────────────────────

def listen(
    confirmation: bool = False,
    phrase_time_limit: int = 8,
    ambient_adjust: float = 0.1,
    timeout: int = 5,
) -> str:
    """Listen once and return recognised text.

    Self-listening protection
    -------------------------
    Waits for TTS to finish before opening the microphone, so the
    assistant does not capture its own voice as a new command.

    Device selection
    ----------------
    Uses the same four-stage device-selection strategy as the hotword
    listener.  The chosen device is cached for subsequent calls.
    Falls back to the system default on any open failure.

    Returns '' on timeout, silence, unintelligible speech, or error.
    Never raises.
    """
    # ── Self-listening guard: wait until TTS is silent ────────────────────────
    _wait_for_tts_silence()

    # ── Path 1: PyAudio via sr.Microphone ──────────────────────────────────────
    if _PYAUDIO_OK:
        device_index = _select_input_device()
        return _listen_pyaudio(
            device_index=device_index,
            phrase_time_limit=phrase_time_limit,
            ambient_adjust=ambient_adjust,
            timeout=timeout,
        )

    # ── Path 2: sounddevice ────────────────────────────────────────────────────
    if _SOUNDDEVICE_OK:
        audio = _record_with_sounddevice(duration=float(phrase_time_limit))
        if audio is None:
            return ""
        return _recognise(audio)

    # ── Path 3: No audio available ─────────────────────────────────────────────
    return ""


def _listen_pyaudio(
    device_index: "int | None",
    phrase_time_limit: int,
    ambient_adjust: float,
    timeout: int,
) -> str:
    """Internal: capture via PyAudio/sr.Microphone with the selected device.

    Falls back to the system default on open failure and clears the
    device cache so the next call re-selects.
    """
    import pyaudio  # already confirmed available at module level

    # Try the selected (or default) device.  If it fails, try again with
    # device_index=None (sr.Microphone default) before giving up.
    attempts = [device_index, None] if device_index is not None else [None]
    # De-duplicate: if selected IS None, only try once.
    if attempts[0] == attempts[-1]:
        attempts = [None]

    for attempt_device in attempts:
        try:
            time.sleep(0.05)  # brief settle before opening stream

            mic_kwargs = {}
            if attempt_device is not None:
                mic_kwargs["device_index"] = attempt_device

            with sr.Microphone(**mic_kwargs) as source:
                try:
                    recognizer.adjust_for_ambient_noise(
                        source, duration=ambient_adjust
                    )
                except Exception:
                    pass

                print("\n🎤 Listening...")

                try:
                    audio = recognizer.listen(
                        source,
                        timeout=timeout,
                        phrase_time_limit=phrase_time_limit,
                    )
                except sr.WaitTimeoutError:
                    print(f"[SST] No speech detected within {timeout}s.")
                    _tts_speak("I didn't catch that.")
                    return ""
                except Exception as exc:
                    print(f"[SST listen error] {exc}")
                    return ""

            return _recognise(audio)

        except OSError as exc:
            # Device open failed (unplugged, in-use, wrong index)
            print(f"[SST] Microphone open failed (device={attempt_device}): {exc}")
            _invalidate_device_cache()
            # loop will retry with device_index=None on the next iteration
            continue

        except Exception as exc:
            print(f"[SST] Unexpected microphone error: {exc}")
            _invalidate_device_cache()
            return ""

    # Both attempts exhausted
    print("[SST] Could not open any microphone.")
    return ""


def _recognise(audio: sr.AudioData) -> str:
    """Run Google STT on audio data.  Returns recognised text or ''."""
    print("🧠 Recognizing...")
    try:
        text = recognizer.recognize_google(
            audio,
            language=CONFIG.get("LANGUAGE", "en-US"),
        )
        print(f"You: {text}")
        return text.strip()

    except sr.UnknownValueError:
        print("[SST] Speech not recognised.")
        return ""

    except sr.RequestError as exc:
        print(f"[SST] Google STT service error: {exc}")
        _tts_speak("Speech service unavailable. Please type your command.")
        try:
            return input("You: ")
        except Exception:
            return ""

    except Exception as exc:
        print(f"[SST recognise error]: {exc}")
        return ""


def listen_continuous(terminator: str = "stop message") -> str:
    """Accumulate speech until the terminator phrase is heard.

    Returns '' immediately when no audio backend is available.
    """
    if not _PYAUDIO_OK and not _SOUNDDEVICE_OK:
        print("[SST] No audio backend — skipping continuous listen.")
        return ""

    full_text = ""
    print(f"\n🎤 [Continuous] Listening for '{terminator}'...")

    max_empty = 5
    empty_count = 0

    while True:
        chunk = listen()

        if not chunk:
            empty_count += 1
            if empty_count >= max_empty:
                print("[SST] Too many empty attempts — stopping continuous listen.")
                break
            continue

        empty_count = 0

        if terminator.lower() in chunk.lower():
            clean = chunk.lower().replace(terminator.lower(), "").strip()
            if clean:
                full_text += " " + clean
            break

        full_text += " " + chunk
        print(f"[Captured so far]: {full_text.strip()}")

    return full_text.strip()


def reset_microphone() -> None:
    """Re-adapt the microphone ambient noise level and re-select the device."""
    _invalidate_device_cache()  # force fresh device selection next call
    if _PYAUDIO_OK:
        device_index = _select_input_device()
        mic_kwargs = {}
        if device_index is not None:
            mic_kwargs["device_index"] = device_index
        try:
            with sr.Microphone(**mic_kwargs) as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.8)
        except Exception as exc:
            print(f"[SST] reset_microphone failed: {exc}")
    elif _SOUNDDEVICE_OK:
        pass  # nothing to reset for sounddevice
