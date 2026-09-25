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
import math
import numpy as np
import speech_recognition as sr
try:
    import pyaudio
except Exception:
    pyaudio = None
import queue

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
# Audio stream parameters — defined here so _test_device_capture can reference
# CHUNK_SIZE before the full audio-config block below.
CHUNK_SIZE  = 1024   # frames per buffer (64 ms at 16 kHz)
SAMPLE_RATE = 16000
CHANNELS    = 1      # default; overridden per-device after selection
FORMAT      = pyaudio.paInt16 if pyaudio is not None else 8  # 8 == paInt16 raw value

# Cached result: (device_index, channels).
_device_cache_lock  = threading.Lock()
_device_cache_valid = False


def _test_device_capture(
    p, device_idx: int, channels: int = 1, chunk: int = CHUNK_SIZE
) -> bool:
    """Probe *device_idx* at the given *channels* and *chunk* size.

    Returns True only when the device returns a genuinely varied, non-zero
    signal using the SAME chunk size and channel count that the production
    stream will use.  Using a larger probe chunk (the old default of 1536)
    caused the "Primary Sound Capture Driver" stub to pass the test even
    though it returns silent buffers at the production CHUNK_SIZE=1024.
    """
    test_stream = None
    try:
        test_stream = p.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=16000,
            input=True,
            input_device_index=device_idx,
            frames_per_buffer=chunk,
        )
        # Read two consecutive chunks; require BOTH to be non-trivial so that
        # a single lucky non-zero buffer (from PortAudio's internal buffer
        # residue) does not fool the test.
        passing = 0
        for _ in range(2):
            data = test_stream.read(chunk, exception_on_overflow=False)
            audio = np.frombuffer(data, dtype=np.int16)
            if channels == 2:
                # Average L and R channels (same as capture loop downmix)
                L = audio[0::2].astype(np.int32)
                R = audio[1::2].astype(np.int32)
                audio = ((L + R) // 2).astype(np.int16)
            rms        = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))
            unique_len = len(np.unique(audio))
            if unique_len >= 2:
                passing += 1
        return passing == 2
    except Exception:
        return False
    finally:
        if test_stream is not None:
            try:
                test_stream.stop_stream()
                test_stream.close()
            except Exception:
                pass


def _probe_device_channels(p, device_idx: int) -> "tuple[bool, int]":
    """Determine the minimum working channel count for *device_idx*.

    Returns (True, channels) where channels is 1 or 2 if the device
    delivers real audio, or (False, 0) if neither mono nor stereo works.

    Stereo is tried before mono for devices with 2+ channels because some
    Intel Smart Sound array microphones exhibit a hardware-level alternating
    frame artifact in mono mode: every even read returns ~0 RMS while every
    odd read returns full signal, regardless of whether the user is speaking.
    This makes mono RMS-based VAD unreliable.  Opening the same device in
    stereo and downmixing produces a stable, speech-correlated mono signal.

    For single-channel devices, mono is tried directly.
    """
    info = p.get_device_info_by_index(device_idx)
    max_ch = info.get("maxInputChannels", 0)
    if max_ch < 1:
        return False, 0

    # For devices that support stereo, prefer stereo to avoid the
    # alternating-frame artifact seen with Intel Smart Sound arrays in mono.
    if max_ch >= 2:
        if _test_device_capture(p, device_idx, channels=2):
            return True, 2
        # Stereo failed — fall through to mono

    # Mono fallback (works for single-channel devices, or if stereo failed)
    if _test_device_capture(p, device_idx, channels=1):
        return True, 1

    return False, 0


# Cached result: (device_index, channels).
# device_index is an int or None (use system default).
# channels is 1 or 2 depending on what the selected device requires.
_cached_input_device: "tuple[int | None, int]" = (None, 1)
_device_cache_lock = threading.Lock()
_device_cache_valid = False       # False until first selection completes


def _find_best_input_device() -> "tuple[int | None, int]":
    """Select the best available input device and its required channel count.

    Returns (device_index, channels).

    Priority order (revised from the original implementation):

    Stage 1 — DirectSound device whose name is NOT a known stub/aggregate
              (i.e. NOT "Primary Sound Capture Driver") AND that passes the
              two-chunk liveness test at the production CHUNK_SIZE.
              "Primary Sound Capture Driver" is a Windows DirectSound default
              capture stub — it often maps to the real device but returns
              silent buffers when opened in mono at CHUNK_SIZE=1024 / 16 kHz.
              Skipping it forces the selection to find the real hardware.

    Stage 2 — Any DirectSound input (including the stub) that passes the test.
              This handles setups where the stub is the only working device.

    Stage 3 — Any input device with live audio (non-DirectSound fallback).

    Stage 4 — OS default input device (no liveness test, channels=1).
    """
    if not _PYAUDIO_OK:
        return None, 1

    # Known Windows stub device names that are NOT physical microphone hardware.
    # These are allowed as a last resort (Stage 2+) but excluded from Stage 1.
    _STUB_NAMES = {"primary sound capture driver", "microsoft sound mapper"}

    p = pyaudio.PyAudio()
    try:
        device_count = p.get_device_count()

        # Stage 1 — MME non-stub physical hardware (cleanest resampling for Intel SST)
        for i in range(device_count):
            try:
                info = p.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) <= 0:
                    continue
                name    = info.get("name", "")
                api_idx = info.get("hostApi", -1)
                api_name = (
                    p.get_host_api_info_by_index(api_idx).get("name", "")
                    if api_idx >= 0 else ""
                )
                if "MME" not in api_name:
                    continue
                if name.lower().strip() in _STUB_NAMES:
                    continue                      # skip stubs in Stage 1
                ok, ch = _probe_device_channels(p, i)
                if ok:
                    print(f"[SST] Selected input device [{i}]: {name!r} "
                          f"({api_name}) channels={ch}")
                    return i, ch
            except Exception:
                pass

        # Stage 2 — DirectSound, non-stub, live audio
        for i in range(device_count):
            try:
                info = p.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) <= 0:
                    continue
                name    = info.get("name", "")
                api_idx = info.get("hostApi", -1)
                api_name = (
                    p.get_host_api_info_by_index(api_idx).get("name", "")
                    if api_idx >= 0 else ""
                )
                if "DirectSound" not in api_name:
                    continue
                if name.lower().strip() in _STUB_NAMES:
                    continue                      # skip stubs in Stage 2
                ok, ch = _probe_device_channels(p, i)
                if ok:
                    print(f"[SST] Selected input device [{i}]: {name!r} "
                          f"({api_name}) channels={ch} (DirectSound)")
                    return i, ch
            except Exception:
                pass

        # Stage 2 — Any DirectSound input with live audio (including stubs)
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
                if "DirectSound" not in api_name:
                    continue
                ok, ch = _probe_device_channels(p, i)
                if ok:
                    name = info.get("name", "")
                    print(f"[SST] Selected input device [{i}]: {name!r} "
                          f"({api_name}) channels={ch} (stage-2 fallback)")
                    return i, ch
            except Exception:
                pass

        # Stage 3 — Any input device with live audio (non-DirectSound)
        for i in range(device_count):
            try:
                info = p.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) <= 0:
                    continue
                ok, ch = _probe_device_channels(p, i)
                if ok:
                    name = info.get("name", "")
                    print(f"[SST] Selected input device [{i}]: {name!r} "
                          f"channels={ch} (stage-3 fallback)")
                    return i, ch
            except Exception:
                pass

        # Stage 4 — OS default (no liveness test)
        try:
            default_idx = p.get_default_input_device_info().get("index")
            name = p.get_device_info_by_index(default_idx).get("name", "")
            print(f"[SST] Using OS default input device [{default_idx}]: {name!r} "
                  f"channels=1 (stage-4 last resort)")
            return default_idx, 1
        except Exception as exc:
            print(f"[SST] Could not get default input device: {exc}")
            return None, 1

    finally:
        p.terminate()


def _select_input_device() -> "tuple[int | None, int]":
    """Return the cached (device_index, channels) pair (selection runs once)."""
    global _cached_input_device, _device_cache_valid
    with _device_cache_lock:
        if not _device_cache_valid:
            _cached_input_device = _find_best_input_device()
            _device_cache_valid = True
    return _cached_input_device


def _invalidate_device_cache() -> None:
    """Clear the device cache so the next call re-selects a device."""
    global _device_cache_valid
    with _device_cache_lock:
        _device_cache_valid = False


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
        device_index, _ch = _select_input_device()   # _ch unused by sr.Microphone
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
        return ""  # Silence: no "I didn't catch that" for ordinary silence

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


# ── Continuous Audio Stream State ─────────────────────────────────────────────

_continuous_audio_state = {
    'running': False,
    'stop_requested': False,
    'stream': None,
    'pyaudio_instance': None,
    'device_index': None,
    'thread': None
}

# Utterance processing queue for non-blocking STT
_utterance_queue = queue.Queue(maxsize=10)  # Bounded queue to prevent unbounded growth
_utterance_processor_thread = None

# ── EchoGuard & Push-to-Talk Integration ──────────────────────────────────────
_echo_guard_instance = None
_ptt_held: bool = False
_ptt_active_in_utterance: bool = False


def get_echo_guard():
    """Retrieve or initialize the active EchoGuard instance."""
    global _echo_guard_instance
    if _echo_guard_instance is None:
        try:
            from skills.audio_management.echo_guard import get_echo_guard as _init_eg
            _echo_guard_instance = _init_eg()
        except Exception:
            _echo_guard_instance = None
    return _echo_guard_instance


def set_ptt_held(held: bool) -> None:
    """Callback triggered when Push-to-Talk hotkey is pressed or released."""
    global _ptt_held
    _ptt_held = bool(held)


def is_ptt_held() -> bool:
    """Check if Push-to-Talk hotkey is currently held down."""
    return _ptt_held


def _utterance_processor_loop():
    """Process utterances from queue without blocking audio capture."""
    print("[UTTERANCE PROCESSOR] Started")
    while not _continuous_audio_state['stop_requested']:
        try:
            # Get utterance from queue with timeout to allow checking stop flag
            try:
                audio_data = _utterance_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            
            # Process the utterance (STT + intent pipeline)
            _process_utterance(audio_data)
            
        except Exception as e:
            print(f"[UTTERANCE PROCESSOR] Error: {e}")
    
    print("[UTTERANCE PROCESSOR] Stopped")

# (Audio configuration constants — CHUNK_SIZE, SAMPLE_RATE, CHANNELS, FORMAT —
#  are defined near the top of the capture section, before _test_device_capture.)


class _HighPassFilter:
    """Single-pole IIR high-pass filter (cutoff ~80 Hz at 16 kHz sampling).
    Removes infrasonic rumble and DC drift from microphone hardware (e.g. Intel SST).
    """
    def __init__(self, cutoff_hz: float = 80.0, sample_rate: int = 16000):
        dt = 1.0 / sample_rate
        rc = 1.0 / (2.0 * math.pi * cutoff_hz)
        self.alpha = rc / (rc + dt)
        self.prev_x = 0.0
        self.prev_y = 0.0

    def process(self, chunk: np.ndarray) -> np.ndarray:
        if len(chunk) == 0:
            return chunk
        out = np.empty_like(chunk, dtype=np.int16)
        px = self.prev_x
        py = self.prev_y
        alpha = self.alpha
        for i in range(len(chunk)):
            x = float(chunk[i])
            y = alpha * (py + x - px)
            px = x
            py = y
            if y > 32767.0:
                y = 32767.0
            elif y < -32768.0:
                y = -32768.0
            out[i] = int(y)
        self.prev_x = px
        self.prev_y = py
        return out


def _simple_vad(audio_chunk: np.ndarray, threshold: float = 1000.0) -> bool:
    """Energy-based VAD with DC-bias removal.

    Returns True when the zero-centered RMS of *audio_chunk* exceeds *threshold*.
    """
    return _rms(audio_chunk) > threshold


def _rms(audio_chunk: np.ndarray) -> float:
    """Return the RMS energy of *audio_chunk* after removing DC offset."""
    if len(audio_chunk) == 0:
        return 0.0
    centered = audio_chunk.astype(np.float32) - float(np.mean(audio_chunk))
    return float(np.sqrt(np.mean(centered ** 2)))


# ── VAD tuning parameters (configurable) ─────────────────────────────────────
#
# Frame arithmetic: CHUNK_SIZE=1024, SAMPLE_RATE=16000
#   1 chunk ≈ 64 ms  →  ~15.6 chunks/sec
#
# ONSET_WINDOW          How many of the last N frames are examined to confirm
#                       speech onset. Default 8 frames ≈ 512 ms window.
#
# ONSET_MIN_POSITIVES   How many frames inside ONSET_WINDOW must be
#                       speech-positive to confirm onset. Default 4 out of 8.
#
# SILENCE_END_FRAMES    Consecutive silence frames needed to end an utterance.
#                       20 frames ≈ 1.28 s.
#
# MIN_SPEECH_FRAMES     Minimum speech-positive frames inside an utterance
#                       before it is considered valid. Default 6 frames.
#
# MAX_UTTERANCE_FRAMES  Safety ceiling to avoid accumulating memory forever.
#                       300 frames ≈ 19.2 s.

VAD_ONSET_WINDOW        = 8
VAD_ONSET_MIN_POSITIVES = 4
VAD_SILENCE_END_FRAMES  = 20
VAD_MIN_SPEECH_FRAMES   = 6
VAD_MAX_UTTERANCE_FRAMES = 300


def _continuous_audio_stream_loop():
    """Main continuous audio capture loop with stateful, adaptive VAD.

    Distinguishes persistent background/microphone noise from real human speech
    using ambient noise calibration and continuous noise-floor tracking.
    """
    global _continuous_audio_state

    STATE_LISTENING = "LISTENING"
    STATE_SPEAKING  = "SPEAKING"

    ONSET_WIN      = VAD_ONSET_WINDOW
    ONSET_MIN      = VAD_ONSET_MIN_POSITIVES
    SILENCE_END    = VAD_SILENCE_END_FRAMES
    MIN_SPEECH     = VAD_MIN_SPEECH_FRAMES
    MAX_FRAMES     = VAD_MAX_UTTERANCE_FRAMES

    try:
        device_index, stream_channels = _select_input_device()
        print(f"[CONTINUOUS AUDIO] Starting with device {device_index} "
              f"channels={stream_channels}")

        p = pyaudio.PyAudio()
        _continuous_audio_state['pyaudio_instance'] = p

        stream = p.open(
            format=FORMAT,
            channels=stream_channels,
            rate=SAMPLE_RATE,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=CHUNK_SIZE,
        )
        _continuous_audio_state['stream'] = stream
        _continuous_audio_state['device_index'] = device_index

        print("[CONTINUOUS AUDIO] Microphone opened — calibrating ambient noise floor...")

        # ── High-pass filter & Calibration ─────────────────────────────────────
        # Filter removes hardware infrasonic rumble (< 80 Hz) without degrading speech
        hp_filter = _HighPassFilter(cutoff_hz=80.0, sample_rate=SAMPLE_RATE)
        calib_rms = []
        for _ in range(25):  # ~1.5 seconds of baseline noise
            if _continuous_audio_state['stop_requested']:
                break
            raw = stream.read(CHUNK_SIZE, exception_on_overflow=False)
            chunk = np.frombuffer(raw, dtype=np.int16)
            if stream_channels == 2:
                L = chunk[0::2].astype(np.int32)
                R = chunk[1::2].astype(np.int32)
                chunk = ((L + R) // 2).astype(np.int16)
            chunk = hp_filter.process(chunk)
            calib_rms.append(_rms(chunk))

        if calib_rms:
            calib_rms.sort()
            trim_len = max(1, int(len(calib_rms) * 0.85))
            noise_floor = max(100.0, float(np.mean(calib_rms[:trim_len])))
        else:
            noise_floor = 250.0

        speech_thresh = max(noise_floor * 2.2, noise_floor + 900.0, 1200.0)
        silence_thresh = max(noise_floor * 1.35, noise_floor + 300.0, 600.0)

        print(f"[VAD] Baseline noise floor: {noise_floor:.0f} RMS | "
              f"Speech threshold: {speech_thresh:.0f} RMS | "
              f"Silence threshold: {silence_thresh:.0f} RMS")

        # ── VAD state ─────────────────────────────────────────────────────────
        vad_state          = STATE_LISTENING
        onset_ring_bool    = []   # list[bool], len <= ONSET_WIN
        onset_ring_chunks  = []   # list[np.ndarray], len <= ONSET_WIN
        utterance_frames   = []   # numpy chunks
        speech_frame_count = 0    # speech-positive frames inside utterance
        consecutive_silence = 0   # consecutive silence frames inside utterance
        last_queue_full_time = 0.0

        while not _continuous_audio_state['stop_requested']:
            try:
                raw   = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                chunk = np.frombuffer(raw, dtype=np.int16)

                # ── Stereo → mono downmix ─────────────────────────────────────
                if stream_channels == 2:
                    L = chunk[0::2].astype(np.int32)
                    R = chunk[1::2].astype(np.int32)
                    chunk = ((L + R) // 2).astype(np.int16)

                # ── Infrasonic hardware filter ────────────────────────────────
                chunk = hp_filter.process(chunk)

                # ── EchoGuard Acoustic Echo Filter ────────────────────────────
                is_user_speech = True
                _eg = get_echo_guard()
                if _eg is not None:
                    try:
                        is_user_speech = _eg.process_frame(chunk, SAMPLE_RATE)
                    except Exception:
                        is_user_speech = True

                # ── TTS protection ────────────────────────────────────────────
                if _is_tts_speaking():
                    if vad_state == STATE_SPEAKING:
                        print("[VAD] TTS active — discarding in-progress utterance")
                        vad_state           = STATE_LISTENING
                        onset_ring_bool     = []
                        onset_ring_chunks   = []
                        utterance_frames    = []
                        speech_frame_count  = 0
                        consecutive_silence = 0
                    onset_ring_bool   = []
                    onset_ring_chunks = []
                    continue

                frame_rms = _rms(chunk)

                # Dynamically calculate adaptive thresholds from current noise floor
                speech_thresh  = max(noise_floor * 2.2, noise_floor + 900.0, 1200.0)
                silence_thresh = max(noise_floor * 1.35, noise_floor + 300.0, 600.0)

                # ═════════════════════════════════════════════════════════════
                # STATE: LISTENING
                # ═════════════════════════════════════════════════════════════
                if vad_state == STATE_LISTENING:
                    # Adaptive noise floor tracking during silence
                    if frame_rms < silence_thresh:
                        if frame_rms < noise_floor:
                            noise_floor = 0.95 * noise_floor + 0.05 * frame_rms
                        else:
                            noise_floor = 0.98 * noise_floor + 0.02 * frame_rms

                    # Speech detection: energy must exceed threshold AND EchoGuard confirms not echo
                    is_speech = (frame_rms >= speech_thresh) and is_user_speech

                    onset_ring_bool.append(is_speech)
                    onset_ring_chunks.append(chunk)
                    if len(onset_ring_bool) > ONSET_WIN:
                        onset_ring_bool.pop(0)
                        onset_ring_chunks.pop(0)

                    positives = sum(onset_ring_bool)

                    # Onset confirmed via VAD count OR immediate Push-To-Talk activation
                    if _ptt_held or positives >= ONSET_MIN:
                        utterance_frames    = list(onset_ring_chunks) if onset_ring_chunks else [chunk]
                        vad_state           = STATE_SPEAKING
                        _ptt_active_in_utterance = _ptt_held
                        consecutive_silence = 0
                        speech_frame_count  = max(positives, 1)
                        print(f"[VAD] LISTENING -> SPEAKING  "
                              f"{'(PTT active) ' if _ptt_held else ''}"
                              f"onset={positives}/{ONSET_WIN} frames "
                              f"rms={frame_rms:.0f} (floor={noise_floor:.0f}, thresh={speech_thresh:.0f})")
                        onset_ring_bool   = []
                        onset_ring_chunks = []

                # ═════════════════════════════════════════════════════════════
                # STATE: SPEAKING
                # ═════════════════════════════════════════════════════════════
                elif vad_state == STATE_SPEAKING:
                    utterance_frames.append(chunk)

                    # Hysteresis: frame is voiced if above silence threshold
                    if frame_rms >= silence_thresh:
                        consecutive_silence  = 0
                        speech_frame_count  += 1
                    else:
                        consecutive_silence += 1

                    # Safety: check if saturated noise hit max duration
                    if len(utterance_frames) >= MAX_FRAMES:
                        avg_u_rms = np.mean([_rms(f) for f in utterance_frames[-50:]])
                        # If the signal was continuous without normal speech pauses and near noise floor
                        if consecutive_silence <= 2 and avg_u_rms < speech_thresh * 1.2:
                            print(f"[VAD] Saturated ambient noise detected (~{avg_u_rms:.0f} RMS) "
                                   "— adapting noise floor; false utterance dropped")
                            noise_floor = max(noise_floor, float(avg_u_rms))
                        else:
                            print(f"[VAD] SPEAKING -> END_UTTERANCE (max duration reached) "
                                  f"frames={len(utterance_frames)} speech={speech_frame_count}")
                            last_queue_full_time = _vad_finish_utterance(
                                utterance_frames, speech_frame_count,
                                MIN_SPEECH, last_queue_full_time
                            )

                        vad_state                = STATE_LISTENING
                        _ptt_active_in_utterance = False
                        onset_ring_bool          = []
                        onset_ring_chunks        = []
                        utterance_frames         = []
                        speech_frame_count       = 0
                        consecutive_silence      = 0
                        continue

                    # Finalize if PTT was released OR consecutive silence threshold reached
                    ptt_released = _ptt_active_in_utterance and not _ptt_held
                    if ptt_released or consecutive_silence >= SILENCE_END:
                        print(f"[VAD] SPEAKING -> END_UTTERANCE  "
                              f"{'(PTT released) ' if ptt_released else ''}"
                              f"frames={len(utterance_frames)} "
                              f"speech_frames={speech_frame_count} "
                              f"silence_frames={consecutive_silence}")
                        last_queue_full_time = _vad_finish_utterance(
                            utterance_frames, speech_frame_count,
                            1 if ptt_released else MIN_SPEECH, last_queue_full_time
                        )
                        vad_state                = STATE_LISTENING
                        _ptt_active_in_utterance = False
                        onset_ring_bool          = []
                        onset_ring_chunks        = []
                        utterance_frames         = []
                        speech_frame_count       = 0
                        consecutive_silence      = 0

            except Exception as exc:
                print(f"[CONTINUOUS AUDIO] Audio read error: {exc}")
                time.sleep(0.1)

        # ── Shutdown ──────────────────────────────────────────────────────────
        stream.stop_stream()
        stream.close()
        p.terminate()
        print("[CONTINUOUS AUDIO] Microphone closed")

    except Exception as exc:
        print(f"[CONTINUOUS AUDIO] Fatal error: {exc}")
        import traceback
        traceback.print_exc()


def _vad_finish_utterance(
    utterance_frames: list,
    speech_frame_count: int,
    min_speech: int,
    last_queue_full_time: float,
) -> float:
    """Validate and enqueue one complete utterance.  Returns updated last_queue_full_time."""
    if speech_frame_count < min_speech:
        duration_s = len(utterance_frames) * CHUNK_SIZE / SAMPLE_RATE
        print(f"[VAD] utterance too short — dropped "
              f"(speech_frames={speech_frame_count} < min={min_speech}, "
              f"duration={duration_s:.2f}s)")
        return last_queue_full_time

    duration_s = len(utterance_frames) * CHUNK_SIZE / SAMPLE_RATE
    complete_audio = np.concatenate(utterance_frames)
    try:
        _utterance_queue.put_nowait(complete_audio)
        print(f"[VAD] queued utterance  frames={len(utterance_frames)} "
              f"speech_frames={speech_frame_count} "
              f"duration={duration_s:.2f}s")
    except queue.Full:
        now = time.monotonic()
        if now - last_queue_full_time > 5.0:
            print("[VAD] queue full; utterance dropped")
            last_queue_full_time = now
    return last_queue_full_time


def _process_utterance(audio_data: np.ndarray):
    """Process a complete utterance through STT and intent pipeline."""
    try:
        # TTS coordination: don't process if TTS is speaking
        # This prevents self-listening at STT processing time
        if _is_tts_speaking():
            print("[CONTINUOUS AUDIO] Skipping utterance - TTS is speaking")
            return
        
        # Convert to sr.AudioData format
        audio_bytes = audio_data.tobytes()
        audio_sr = sr.AudioData(audio_bytes, SAMPLE_RATE, 2)
        
        # STT recognition
        text = _recognise(audio_sr)
        
        if text and text.strip():
            # Process through existing pipeline
            from legacy.assistant import process_input
            print(f"[CONTINUOUS AUDIO] Processing: {text}")
            process_input(text)
            
    except Exception as e:
        print(f"[CONTINUOUS AUDIO] Utterance processing error: {e}")


def _is_tts_speaking() -> bool:
    """Check if TTS is currently speaking."""
    try:
        from legacy.tts import _tts_active
        # Directly check the TTS active event instead of polling
        return _tts_active.is_set()
    except Exception:
        return False


def start_continuous_audio_stream():
    """Start true continuous audio capture (no listening gaps)."""
    global _continuous_audio_state, _utterance_processor_thread
    
    if _continuous_audio_state['running']:
        print("[CONTINUOUS AUDIO] Already running")
        return False
    
    if not _PYAUDIO_OK:
        print("[CONTINUOUS AUDIO] PyAudio not available")
        return False
    
    _continuous_audio_state['stop_requested'] = False
    _continuous_audio_state['running'] = True
    
    # Start utterance processor thread
    _utterance_processor_thread = threading.Thread(target=_utterance_processor_loop, daemon=True)
    _utterance_processor_thread.start()
    
    # Start audio capture thread
    thread = threading.Thread(target=_continuous_audio_stream_loop, daemon=True)
    _continuous_audio_state['thread'] = thread
    thread.start()
    
    print("[CONTINUOUS AUDIO] Started true continuous capture")
    return True


def stop_continuous_audio_stream():
    """Stop continuous audio capture and close microphone."""
    global _continuous_audio_state, _utterance_processor_thread
    
    if not _continuous_audio_state['running']:
        print("[CONTINUOUS AUDIO] Not running")
        return False
    
    _continuous_audio_state['stop_requested'] = True
    _continuous_audio_state['running'] = False
    
    if _continuous_audio_state['thread']:
        _continuous_audio_state['thread'].join(timeout=3.0)
    
    if _utterance_processor_thread:
        _utterance_processor_thread.join(timeout=3.0)
    
    print("[CONTINUOUS AUDIO] Stopped")
    return True


def is_continuous_audio_running() -> bool:
    """Check if continuous audio capture is running."""
    return _continuous_audio_state['running']


def reset_microphone() -> None:
    """Re-adapt the microphone ambient noise level and re-select the device."""
    _invalidate_device_cache()  # force fresh device selection next call
    if _PYAUDIO_OK:
        device_index, _ch = _select_input_device()   # _ch unused by sr.Microphone
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
