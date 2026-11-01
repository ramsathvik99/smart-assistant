"""
Local STT Engine using faster-whisper (CTranslate2, int8 CPU).

Provides low-latency, offline, single-pass multilingual speech recognition.
"""

from __future__ import annotations

import logging
import math
import os
import re
import threading
import time
from typing import Optional, Tuple

import numpy as np

# Suppress HuggingFace symlinks warning on Windows
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

logger = logging.getLogger(__name__)

# Default languages supported from MultilingualEngine LOCALE_MAP
SUPPORTED_LANGUAGES = {
    "en", "te", "hi", "ta", "kn", "ml", "es", "fr", "de", "it", "bn", "mr", "gu"
}


def get_stt_model_dir() -> str:
    """Return canonical directory for local STT models in user data folder."""
    base = os.getenv("LOCALAPPDATA")
    if not base:
        base = os.path.expanduser("~")
    model_dir = os.path.join(base, "smart_assistant", "models", "whisper")
    os.makedirs(model_dir, exist_ok=True)
    return model_dir


# --- Phase 2: Hallucination rejection ---

# Known hallucinated phrases that faster-whisper produces on silence/noise
_HALLUCINATION_PATTERNS: set[str] = {
    "[blank_audio]",
    "(blank audio)",
    "thank you for watching",
    "thanks for watching",
    "thank you for listening",
    "thanks for listening",
    "please subscribe",
    "like and subscribe",
    "subtitles by",
    "transcribed by",
    "translated by",
    "(applause)",
    "(music)",
    "(laughter)",
    "(silence)",
    "(no audio)",
    "(inaudible)",
    "you",
    "...",
    "the end",
    "bye",
    "goodbye",
}

# Regex to detect significant non-Latin script (Cyrillic, Arabic, CJK) in what should be English
_NON_LATIN_RE = re.compile(
    r"[\u0400-\u04FF\u0600-\u06FF\u3000-\u9FFF\uAC00-\uD7AF]"
)


def _filter_hallucinated_segments(segments: list) -> list:
    """
    Filter out hallucinated segments from faster-whisper output.
    
    Rejects segments that:
    - Have no_speech_prob > 0.85 (likely silence/noise)
    - Have avg_logprob < -1.0 (very low confidence)
    - Match known hallucination patterns
    - Contain significant non-Latin characters (wrong-script hallucinations)
    """
    filtered = []
    for seg in segments:
        text = getattr(seg, "text", "").strip()
        if not text:
            continue

        # Check no_speech probability
        no_speech = getattr(seg, "no_speech_prob", 0.0)
        if no_speech > 0.85:
            logger.debug("[STT] Rejected hallucination (no_speech=%.2f): '%s'", no_speech, text)
            continue

        # Check average log probability
        avg_lp = getattr(seg, "avg_logprob", -0.5)
        if avg_lp < -1.0:
            logger.debug("[STT] Rejected low-confidence (logprob=%.2f): '%s'", avg_lp, text)
            continue

        # Check against known hallucination patterns
        text_lower = text.lower().strip(" .,!?")
        if text_lower in _HALLUCINATION_PATTERNS:
            logger.debug("[STT] Rejected known hallucination pattern: '%s'", text)
            continue

        # Reject text that is mostly non-Latin characters (wrong-script hallucination)
        non_latin_chars = len(_NON_LATIN_RE.findall(text))
        if non_latin_chars > 0 and non_latin_chars / max(len(text), 1) > 0.3:
            logger.debug("[STT] Rejected non-Latin hallucination (%d/%d): '%s'", non_latin_chars, len(text), text)
            continue

        filtered.append(seg)
    return filtered


class LocalWhisperSTT:
    """
    Local Whisper STT engine backed by faster-whisper and CTranslate2.
    
    Loads model lazily in a background thread, performs single-pass
    transcription with language identification, and never raises exceptions.
    """

    _instance: Optional[LocalWhisperSTT] = None
    _singleton_lock = threading.Lock()

    @classmethod
    def get_instance(cls, model_size: Optional[str] = None, auto_load: bool = True) -> LocalWhisperSTT:
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls(model_size=model_size, auto_load=auto_load)
            return cls._instance

    def __init__(self, model_size: Optional[str] = None, auto_load: bool = True):
        # Allow override from parameter, config, or env var. Default: 'base'
        if model_size:
            self._model_size = model_size
        else:
            try:
                from instance.config import settings
                self._model_size = getattr(settings, "STT_MODEL", os.getenv("STT_MODEL", "base"))
            except Exception:
                self._model_size = os.getenv("STT_MODEL", "base")

        self._lock = threading.Lock()
        self._model = None
        self._is_loading = False
        self._load_failed = False
        self._init_thread: Optional[threading.Thread] = None

        if auto_load:
            self._init_thread = threading.Thread(
                target=self._load_model,
                daemon=True,
                name="WhisperSTT-Loader"
            )
            self._init_thread.start()

    @property
    def model_size(self) -> str:
        return self._model_size

    def is_available(self) -> bool:
        """Check if local Whisper model is loaded and ready for transcription."""
        with self._lock:
            return self._model is not None

    def _load_model(self) -> None:
        """Load faster-whisper CTranslate2 model safely."""
        with self._lock:
            if self._model is not None or self._load_failed:
                return
            self._is_loading = True

        print("[STT] Voice engine loading...")
        try:
            from faster_whisper import WhisperModel

            download_dir = get_stt_model_dir()
            logger.info(
                "[STT] Loading faster-whisper model '%s' (CPU, int8, storage: %s)...",
                self._model_size,
                download_dir
            )
            cpu_threads = int(os.getenv("WHISPER_CPU_THREADS", "6"))
            model = WhisperModel(
                self._model_size,
                device="cpu",
                compute_type="int8",
                cpu_threads=cpu_threads,
                download_root=download_dir
            )
            with self._lock:
                self._model = model
                self._load_failed = False
            logger.info("[STT] Local Whisper model '%s' successfully loaded.", self._model_size)
            print(f"[STT] Voice engine ready ({self._model_size}).")

            # --- Phase 1: Auto warm-up with 1s dummy transcription ---
            try:
                t0 = time.perf_counter()
                dummy_pcm = np.zeros(16000, dtype=np.float32)  # 1 second at 16kHz
                model.transcribe(dummy_pcm, beam_size=1, vad_filter=False)
                warm_ms = (time.perf_counter() - t0) * 1000
                print(f"[STT] Voice engine warm ({warm_ms:.0f}ms)")
            except Exception as warm_exc:
                logger.debug("[STT] Auto warm-up exception (non-fatal): %s", warm_exc)
        except Exception as exc:
            logger.warning(
                "[STT] Local Whisper model '%s' failed to load: %s. Local STT unavailable.",
                self._model_size,
                exc
            )
            with self._lock:
                self._model = None
                self._load_failed = True
        finally:
            with self._lock:
                self._is_loading = False

    def warm_up(self, timeout: float = 25.0) -> bool:
        """
        Wait for background initialization to complete and execute a dummy pass
        to warm up CTranslate2 execution graphs.
        """
        if self._init_thread and self._init_thread.is_alive():
            self._init_thread.join(timeout=timeout)

        if self._model is None and not self._load_failed:
            self._load_model()

        with self._lock:
            if self._model is not None:
                try:
                    t0 = time.perf_counter()
                    dummy_pcm = np.zeros(16000, dtype=np.float32)  # 1 second at 16kHz
                    self._model.transcribe(dummy_pcm, beam_size=1, vad_filter=False)
                    warm_ms = (time.perf_counter() - t0) * 1000
                    print(f"[STT] Voice engine warm ({warm_ms:.0f}ms)")
                    return True
                except Exception as exc:
                    logger.debug("[STT] Warm up probe exception (non-fatal): %s", exc)
                    return True
            return False

    def _resolve_assistant_name(self) -> str:
        """Dynamically resolve active assistant name."""
        try:
            from instance.config import settings
            name = getattr(settings, "CURRENT_ASSISTANT_NAME", None)
            if not name:
                from instance.config import get_assistant_name
                name = get_assistant_name()
            if not name:
                name = "Friday"
        except Exception:
            name = "Friday"
        return name

    def _get_hotwords(self) -> str:
        """Construct hotwords string boosting the assistant name and key command words."""
        name = self._resolve_assistant_name()
        return f"Hey {name} {name} Friday Trevon set schedule create open play start stop pause resume show tell check remind search find weather music time date"

    def _get_initial_prompt(self) -> str:
        """Construct context-biasing initial prompt with assistant name and key command keywords."""
        name = self._resolve_assistant_name()
        return (
            f"Hey {name}, {name}. "
            f"set, schedule, create, open, play, start, stop, pause, resume, "
            f"show, tell, check, remind, search, find, call, send, email, clear, delete, "
            f"what, when, how, who, why, meeting, alarm, timer, reminder, event, calendar, "
            f"note, weather, music, song, volume, app, window, time, date."
        )

    def transcribe(
        self,
        audio_int16: np.ndarray,
        sample_rate: int = 16000,
        language_hint: Optional[str] = None
    ) -> Tuple[str, str, float]:
        """
        Transcribe raw audio into (text, language, confidence).
        
        Args:
            audio_int16: 1D numpy array of 16-bit PCM audio samples.
            sample_rate: Sampling rate of input audio (typically 16000).
            language_hint: Optional ISO 2-letter language code of active user.
            
        Returns:
            Tuple[str, str, float]: (recognized_text, detected_language, confidence)
            Returns ("", "en", 0.0) on silence, error, or uninitialized engine.
            Never raises exceptions.
        """
        try:
            if audio_int16 is None or len(audio_int16) == 0:
                return "", "en", 0.0

            # If model is still initializing on background thread, do not block
            with self._lock:
                if self._model is None:
                    return "", "en", 0.0

            # Convert int16 -> normalized float32 in [-1.0, 1.0]
            if audio_int16.dtype == np.int16:
                audio_float = audio_int16.astype(np.float32) / 32768.0
            else:
                audio_float = np.asarray(audio_int16, dtype=np.float32)
                max_abs = float(np.max(np.abs(audio_float))) if len(audio_float) > 0 else 0.0
                if max_abs > 1.0:
                    audio_float = audio_float / max(max_abs, 32768.0)

            # Resample to 16 kHz if necessary
            if sample_rate != 16000 and sample_rate > 0:
                target_len = int(len(audio_float) * 16000 / sample_rate)
                if target_len <= 0:
                    return "", "en", 0.0
                audio_float = np.interp(
                    np.linspace(0, len(audio_float), target_len, endpoint=False),
                    np.arange(len(audio_float)),
                    audio_float
                ).astype(np.float32)

            initial_prompt = self._get_initial_prompt()
            hotwords = self._get_hotwords()

            # Single pass transcription with language biasing and hotwords
            kwargs = {
                "beam_size": 1,
                "vad_filter": False,
                "condition_on_previous_text": False,
                "without_timestamps": True,
                "initial_prompt": initial_prompt,
            }
            if hotwords:
                kwargs["hotwords"] = hotwords

            # Language hint locking: avoid scanning 99 languages when active language is known
            if language_hint and language_hint in SUPPORTED_LANGUAGES:
                kwargs["language"] = language_hint
            elif not language_hint:
                kwargs["language"] = "en"

            segments_gen, info = self._model.transcribe(
                audio_float,
                **kwargs
            )

            # --- Phase 1: Per-utterance timing ---
            t_transcribe_start = time.perf_counter()

            segments = list(segments_gen)

            # --- Phase 2: Hallucination filtering ---
            segments = _filter_hallucinated_segments(segments)

            text = " ".join(seg.text.strip() for seg in segments if seg.text.strip()).strip()

            # Log transcription timing
            t_transcribe_elapsed = time.perf_counter() - t_transcribe_start
            audio_duration_s = len(audio_float) / 16000.0
            rtf = t_transcribe_elapsed / audio_duration_s if audio_duration_s > 0 else 0.0
            logger.info(
                "[STT] Transcribed %.1fs audio in %.0fms (RTF=%.2f) -> %d chars",
                audio_duration_s, t_transcribe_elapsed * 1000, rtf, len(text)
            )

            if not text:
                return "", "en", 0.0

            detected_lang = getattr(info, "language", "en")
            lang_prob = float(getattr(info, "language_probability", 0.0))

            # Restrict detected language to supported languages
            if detected_lang not in SUPPORTED_LANGUAGES:
                if language_hint and language_hint in SUPPORTED_LANGUAGES:
                    detected_lang = language_hint
                else:
                    detected_lang = "en"
            elif language_hint and language_hint in SUPPORTED_LANGUAGES and language_hint != detected_lang:
                # If language_hint is active and detection confidence is low, prefer the hint
                if lang_prob < 0.60:
                    detected_lang = language_hint

            # Compute combined confidence score
            if segments:
                avg_probs = [
                    math.exp(max(-5.0, min(0.0, getattr(seg, "avg_logprob", -0.5))))
                    for seg in segments
                ]
                seg_conf = float(np.mean(avg_probs)) if avg_probs else 0.85
                raw_conf = 0.35 * lang_prob + 0.65 * seg_conf
                confidence = round(max(0.1, min(1.0, raw_conf)), 2)
            else:
                confidence = round(max(0.1, min(1.0, lang_prob)), 2)

            return text, detected_lang, confidence

        except Exception as exc:
            logger.warning("[STT] Local Whisper transcribe error: %s", exc)
            return "", "en", 0.0


def get_stt_engine(model_size: Optional[str] = None) -> LocalWhisperSTT:
    """Canonical factory for LocalWhisperSTT engine."""
    return LocalWhisperSTT.get_instance(model_size=model_size)
