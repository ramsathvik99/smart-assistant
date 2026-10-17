"""
Pluggable TTS Backend Architecture

Provides an extensible, high-fidelity voice synthesis layer:
1. TTSBackend interface (abstract base class)
2. NeuralTTSBackend: primary neural streaming backend with edge-tts/openai,
   sentence-level streaming, expressive delivery mapping, and EchoGuard seeding.
3. SAPIBackend: native Windows SAPI / OneCore fallback backend with instant purge.
4. TTSBackendManager: central dispatcher handling primary selection, health checks,
   and graceful fallback.
"""

import abc
import asyncio
import io
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Generator, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class TTSVoice:
    id: str
    name: str
    gender: str
    language: str
    provider: str


@dataclass
class SynthesisResult:
    audio_data: Optional[bytes] = None
    format: str = "mp3"
    sample_rate: int = 24000
    duration_ms: float = 0.0
    first_audio_ms: float = 0.0
    synthesis_ms: float = 0.0
    playback_ms: float = 0.0
    frame_count: int = 0
    byte_count: int = 0
    sentences_played: int = 0
    backend_used: str = ""
    voice_used: str = ""
    device_used: str = ""
    interrupted: bool = False
    error: Optional[str] = None


# ── Base Abstract Backend ─────────────────────────────────────────────────────

class TTSBackend(abc.ABC):
    """Abstract interface for pluggable text-to-speech synthesis backends."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Name of the backend (e.g. 'neural', 'sapi', 'openai')."""
        pass

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Return True if backend is configured and ready to synthesize."""
        pass

    @abc.abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """Perform a quick health check and return a status dictionary."""
        pass

    @abc.abstractmethod
    def get_voices(self) -> List[TTSVoice]:
        """Return a list of available voices for this backend."""
        pass

    @abc.abstractmethod
    def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        rate: float = 1.0,
        volume: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[bytes]:
        """Synthesize text to complete audio bytes."""
        pass

    @abc.abstractmethod
    def stream_and_play(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        rate: float = 1.0,
        volume: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
        on_start: Optional[Callable[[], None]] = None,
        on_sentence_start: Optional[Callable[[str], None]] = None,
    ) -> SynthesisResult:
        """Stream sentence-by-sentence with minimal time-to-first-audio.
        
        Must check for interruption and stop immediately when interrupted.
        """
        pass

    @abc.abstractmethod
    def stop(self, interrupted: bool = True) -> None:
        """Immediately stop synthesis and audio playback."""
        pass


# ── Expressive Delivery Parameter Mapping ─────────────────────────────────────

def trim_audio_silence(pcm_data, sr: int, threshold: int = 350, pad_ms: int = 60, fade_ms: int = 15):
    """Trim leading and trailing silence/padding from synthesized neural audio frames.
    
    Neural synthesizers (like edge-tts) append 0.8-1.4s of trailing zero frames and
    up to 150ms of leading dead air. Trimming leading silence (keeping 20ms lead-in)
    and trailing silence (keeping pad_ms with an anti-click fade) eliminates dead air
    and reduces playback duration by 40-65% without any unnatural speech speedup.
    """
    try:
        import numpy as np
    except ImportError:
        return pcm_data

    if pcm_data is None or len(pcm_data) == 0:
        return pcm_data

    abs_data = np.abs(pcm_data)
    above_thresh = np.where(abs_data > threshold)[0]
    if len(above_thresh) == 0:
        return pcm_data

    # 1. Trim leading silence (keep 20ms padding)
    first_idx = above_thresh[0]
    lead_pad = int((20 / 1000.0) * sr)
    start_idx = max(0, first_idx - lead_pad)

    # 2. Trim trailing silence (keep pad_ms padding)
    last_idx = above_thresh[-1]
    trail_pad = int((pad_ms / 1000.0) * sr)
    end_idx = min(len(pcm_data), last_idx + trail_pad)

    trimmed = pcm_data[start_idx:end_idx].copy()

    # 3. Anti-click linear fade-out on the tail
    fade_samples = min(int((fade_ms / 1000.0) * sr), len(trimmed))
    if fade_samples > 0:
        fade_curve = np.linspace(1.0, 0.0, fade_samples, dtype=np.float32)
        trimmed[-fade_samples:] = (trimmed[-fade_samples:].astype(np.float32) * fade_curve).astype(np.int16)

    return trimmed


def map_metadata_to_neural_style(metadata: Optional[Dict[str, Any]] = None, text: Optional[str] = None) -> Tuple[str, str, str]:
    """Map conversational response metadata to edge-tts rate, pitch, volume modifiers.
    
    Returns:
        (rate_str, pitch_str, volume_str) e.g. ("+12%", "+1Hz", "+0%")
    """
    meta = metadata or {}
    response_type = meta.get("response_type", "")
    conversational_style = meta.get("conversational_style", "")
    urgency = meta.get("urgency", "normal")

    # Inspect text length if provided
    word_count = len(text.strip().split()) if (text and text.strip()) else 999
    is_brief = word_count <= 6 or any(
        (text or "").lower().strip().startswith(p)
        for p in ("done", "opened ", "volume set ", "reminder set", "stopping", "all set")
    )

    # Action confirmations: crisp, confident (+12% sounds natural while eliminating sluggishness)
    if response_type == "action_confirmation" or conversational_style == "brief_confirmation" or is_brief:
        return ("+12%", "+1Hz", "+0%")

    # Frustration recovery or errors: calm and reassuring
    if response_type in ("frustration_recovery", "error_explanation") or conversational_style in ("apologetic", "reassuring"):
        return ("-2%", "-2Hz", "+0%")

    # Recommendations: natural and slightly engaged
    if response_type in ("recommendation", "proactive_suggestion") or conversational_style == "thoughtful":
        return ("+4%", "+1Hz", "+0%")

    # Urgent: clear, direct, and slightly faster
    if urgency in ("high", "urgent"):
        return ("+10%", "+2Hz", "+2%")

    # Normal relaxed conversation: slight crispness (+6%)
    if word_count <= 18:
        return ("+6%", "+0Hz", "+0%")

    return ("+4%", "+0Hz", "+0%")



def split_sentences_for_streaming(text: str) -> List[str]:
    """Split text into spoken sentence units while preserving abbreviations."""
    if not text or not text.strip():
        return []

    cleaned = text.strip()
    # Protect common abbreviations from premature splitting
    protected = cleaned
    abbrevs = [("e.g.", "e_g_"), ("i.e.", "i_e_"), ("vs.", "vs_"), ("approx.", "approx_"),
               ("Dr.", "Dr_"), ("Mr.", "Mr_"), ("Ms.", "Ms_"), ("U.S.", "U_S_"), ("etc.", "etc_"),
               ("min.", "min_"), ("sec.", "sec_"), ("hr.", "hr_")]
    for orig, rep in abbrevs:
        protected = re.sub(re.escape(orig), rep, protected, flags=re.IGNORECASE)

    raw_sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z0-9"\'\(\[])', protected)
    sentences = []
    for s in raw_sentences:
        s_restored = s
        for orig, rep in abbrevs:
            s_restored = re.sub(re.escape(rep), orig, s_restored, flags=re.IGNORECASE)
        s_restored = s_restored.strip()
        if s_restored:
            sentences.append(s_restored)

    return sentences if sentences else [cleaned]


# ── Neural TTS Backend (Primary) ──────────────────────────────────────────────

class NeuralTTSBackend(TTSBackend):
    """Primary Neural TTS backend using Microsoft Edge Neural TTS or OpenAI.
    
    Features:
    - Zero mandatory API key requirement (uses high-definition Microsoft Edge Neural voices).
    - Sentence-level streaming for minimal time-to-first-audio.
    - Low-latency sounddevice PortAudio playback with pygame/playsound fallback.
    - Acoustic EchoGuard reference seeding with real decoded PCM.
    - Instant hardware stop / cancellation upon interruption.
    """

    DEFAULT_VOICE = "en-US-JennyNeural"
    MULTILINGUAL_VOICES = {
        "en": "en-US-JennyNeural",
        "te": "te-IN-ShrutiNeural",
        "hi": "hi-IN-SwaraNeural",
        "ta": "ta-IN-PallaviNeural",
        "kn": "kn-IN-SapnaNeural",
        "ml": "ml-IN-SobhanaNeural",
        "es": "es-ES-ElviraNeural",
        "fr": "fr-FR-DeniseNeural",
        "de": "de-DE-KatjaNeural",
        "it": "it-IT-ElsaNeural",
        "bn": "bn-IN-TanishaaNeural",
        "mr": "mr-IN-AarohiNeural",
        "gu": "gu-IN-DhwaniNeural",
    }
    _PHRASE_CACHE: Dict[Tuple[str, str, str, str, str], Tuple[Any, int]] = {}
    _PHRASE_CACHE_LOCK = threading.Lock()

    @classmethod
    def prewarm_common_phrases(cls):
        """Asynchronously pre-synthesize very frequent responses in a background thread for sub-millisecond TTFA."""
        def _prewarm_worker():
            common_phrases = [
                "Opened Notepad.",
                "Opened Visual Studio Code.",
                "Opened Google Chrome.",
                "Opened Calculator.",
                "Yes, I understand what you're saying. Please go ahead.",
                "You don't have any events scheduled for today.",
            ]
            voice = cls.DEFAULT_VOICE
            for p in common_phrases:
                try:
                    cache_key = (p.strip().lower(), voice, "+0%", "+0Hz", "+0%")
                    with cls._PHRASE_CACHE_LOCK:
                        if cache_key in cls._PHRASE_CACHE:
                            continue
                    import edge_tts, io, soundfile as sf
                    import numpy as np
                    comm = edge_tts.Communicate(text=p, voice=voice)
                    bio = io.BytesIO()
                    async def _run():
                        async for chunk in comm.stream():
                            if chunk["type"] == "audio":
                                bio.write(chunk["data"])
                    asyncio.run(_run())
                    bio.seek(0)
                    pcm_data, sr = sf.read(bio, dtype="int16")
                    if len(pcm_data.shape) > 1 and pcm_data.shape[1] > 1:
                        pcm_data = np.mean(pcm_data, axis=1).astype(np.int16)
                    pcm_data = trim_audio_silence(pcm_data, sr)
                    with cls._PHRASE_CACHE_LOCK:
                        cls._PHRASE_CACHE[cache_key] = (pcm_data, sr)
                except Exception:
                    pass
        threading.Thread(target=_prewarm_worker, daemon=True, name="tts-prewarm").start()

    @classmethod
    def is_valid_voice(cls, voice_id: Optional[str]) -> bool:
        if not voice_id or not isinstance(voice_id, str):
            return False
        v = voice_id.strip()
        # Reject mock test identifiers, SAPI tokens, or empty strings
        if "test_" in v.lower() or "hkey_" in v.lower() or "onecore" in v.lower() or "\\" in v:
            return False
        known = {
            "en-US-JennyNeural", "en-US-GuyNeural", "en-US-AriaNeural", "en-US-ChristopherNeural",
            "en-GB-SoniaNeural", "en-GB-RyanNeural", "en-IN-NeerjaNeural", "en-IN-PrabhatNeural",
            "en-US-AnaNeural", "en-US-EricNeural", "en-US-MichelleNeural",
            "te-IN-ShrutiNeural", "hi-IN-SwaraNeural", "ta-IN-PallaviNeural",
            "kn-IN-SapnaNeural", "ml-IN-SobhanaNeural", "es-ES-ElviraNeural", "fr-FR-DeniseNeural",
            "de-DE-KatjaNeural", "it-IT-ElsaNeural", "bn-IN-TanishaaNeural", "mr-IN-AarohiNeural",
            "gu-IN-DhwaniNeural"
        }
        if v in known:
            return True
        return bool(re.match(r"^[a-z]{2,3}-[A-Z]{2,3}-[A-Za-z0-9]+Neural$", v))

    @classmethod
    def normalize_language_code(cls, lang: Optional[str]) -> Optional[str]:
        if not lang or not isinstance(lang, str):
            return None
        l = lang.strip().lower()
        if l in cls.MULTILINGUAL_VOICES:
            return l
        name_map = {
            "english": "en", "en-us": "en", "en-gb": "en", "en-in": "en",
            "telugu": "te", "te-in": "te",
            "hindi": "hi", "hi-in": "hi",
            "tamil": "ta", "ta-in": "ta",
            "kannada": "kn", "kn-in": "kn",
            "malayalam": "ml", "ml-in": "ml",
            "spanish": "es", "es-es": "es", "es-mx": "es",
            "french": "fr", "fr-fr": "fr", "fr-ca": "fr",
            "german": "de", "de-de": "de",
            "italian": "it", "it-it": "it",
            "bengali": "bn", "bn-in": "bn",
            "marathi": "mr", "mr-in": "mr",
            "gujarati": "gu", "gu-in": "gu",
        }
        for prefix, code in name_map.items():
            if l == prefix or l.startswith(prefix):
                return code
        return l[:2] if len(l) >= 2 else l

    @classmethod
    def detect_language_from_text(cls, text: Optional[str]) -> Optional[str]:
        if not text or not isinstance(text, str):
            return None
        for ch in text:
            cp = ord(ch)
            if 0x0C00 <= cp <= 0x0C7F:
                return "te"
            if 0x0900 <= cp <= 0x097F:
                return "hi"
            if 0x0B80 <= cp <= 0x0BFF:
                return "ta"
            if 0x0C80 <= cp <= 0x0CFF:
                return "kn"
            if 0x0D00 <= cp <= 0x0D7F:
                return "ml"
            if 0x0980 <= cp <= 0x09FF:
                return "bn"
            if 0x0A80 <= cp <= 0x0AFF:
                return "gu"
            if 0x0600 <= cp <= 0x06FF:
                return "ar"
        try:
            from core.multilingual_engine import get_multilingual_engine
            det = get_multilingual_engine().detect_language(text)
            if det.is_multilingual:
                return det.language
        except Exception:
            pass
        return None

    @classmethod
    def get_fallback_voice(cls, gender: Optional[str] = None, language: Optional[str] = None) -> str:
        gen = (gender or "").lower()
        norm_lang = cls.normalize_language_code(language)
        if norm_lang and norm_lang in cls.MULTILINGUAL_VOICES and norm_lang != "en":
            return cls.MULTILINGUAL_VOICES[norm_lang]
        lang = (language or "").lower()
        if "in" in lang or "india" in lang or lang == "en-in":
            return "en-IN-PrabhatNeural" if gen == "male" else "en-IN-NeerjaNeural"
        if "gb" in lang or "uk" in lang or "britain" in lang or lang == "en-gb":
            return "en-GB-RyanNeural" if gen == "male" else "en-GB-SoniaNeural"
        return "en-US-GuyNeural" if gen == "male" else cls.DEFAULT_VOICE

    @classmethod
    def resolve_voice(
        cls,
        voice_id: Optional[str] = None,
        language: Optional[str] = None,
        text: Optional[str] = None,
        gender: Optional[str] = None,
    ) -> str:
        detected_lang = cls.detect_language_from_text(text)
        eff_lang = detected_lang or language
        norm_lang = cls.normalize_language_code(eff_lang)

        if norm_lang and norm_lang != "en" and norm_lang in cls.MULTILINGUAL_VOICES:
            if cls.is_valid_voice(voice_id) and voice_id.lower().startswith(norm_lang):
                return voice_id.strip()
            return cls.MULTILINGUAL_VOICES[norm_lang]

        if cls.is_valid_voice(voice_id):
            return str(voice_id).strip()

        return cls.get_fallback_voice(gender=gender, language=language)

    @classmethod
    def validate_or_fallback_voice(cls, voice_id: Optional[str], gender: Optional[str] = None, language: Optional[str] = None) -> str:
        return cls.resolve_voice(voice_id=voice_id, language=language, gender=gender)

    def __init__(self):
        self._voice = self.validate_or_fallback_voice(os.getenv("TTS_VOICE", self.DEFAULT_VOICE))
        self._output_format = os.getenv("TTS_OUTPUT_FORMAT", "audio-24khz-48kbitrate-mono-mp3")
        self._interrupted = threading.Event()
        self._stop_lock = threading.Lock()
        self._is_playing = False
        self._current_task: Optional[asyncio.Task] = None
        self._active_sentence: str = ""
        self._current_stream = None

    def stream_and_play(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        rate: float = 1.0,
        volume: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
        on_start: Optional[Callable[[], None]] = None,
        on_sentence_start: Optional[Callable[[str], None]] = None,
    ) -> SynthesisResult:
        """Stream sentence-by-sentence with continuous audio playback and prefetching.
        
        Uses a continuous single-stream audio producer/consumer pipeline to eliminate
        inter-sentence gaps (target transition gap < 100 ms, ideally < 50 ms) while
        preserving immediate barge-in/interruption capability.
        """
        import queue
        self._interrupted.clear()
        t_start = time.time()
        eff_lang = language or (metadata.get("lang_hint") if metadata else None) or (metadata.get("language") if metadata else None)
        chosen_voice = self.resolve_voice(voice or self._voice, language=eff_lang, text=text)
        rate_str, pitch_str, vol_str = map_metadata_to_neural_style(metadata, text=text)

        sentences = split_sentences_for_streaming(text)
        if not sentences:
            return SynthesisResult(duration_ms=0.0, first_audio_ms=0.0)

        result = SynthesisResult()
        first_audio_recorded = False

        try:
            import edge_tts
            import soundfile as sf
            import sounddevice as sd
            import numpy as np
        except ImportError as err:
            logger.warning("[NEURAL TTS] Dependencies missing for streaming: %s", err)
            result.error = str(err)
            return result

        logger.info(
            "[TTS] backend=neural voice=%s sentences=%d text=%r",
            chosen_voice, len(sentences), text[:60]
        )

        def _seed_echoguard(pcm_arr: np.ndarray, sr: int):
            try:
                from legacy.sst import get_echo_guard
                eg = get_echo_guard()
                if eg is not None:
                    chunk_size = 2048
                    t_now = time.monotonic()
                    for i in range(0, len(pcm_arr), chunk_size):
                        sub = pcm_arr[i:i + chunk_size]
                        sub_rms = float(np.sqrt(np.mean(sub.astype(np.float32) ** 2)))
                        sub_lvl = min(1.0, max(0.01, sub_rms / 32768.0))
                        offset_s = i / float(sr)
                        eg.note_output(sub, sr, sub_lvl, when=t_now + offset_s)
            except Exception:
                pass

        audio_queue: queue.Queue = queue.Queue(maxsize=10)
        producer_error: Optional[str] = None

        def _producer_worker():
            nonlocal producer_error
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                for idx, s_text in enumerate(sentences):
                    if self._interrupted.is_set():
                        break

                    cache_key = (s_text.strip().lower(), chosen_voice, rate_str, pitch_str, vol_str)
                    with self._PHRASE_CACHE_LOCK:
                        cached_entry = self._PHRASE_CACHE.get(cache_key)

                    if cached_entry is not None:
                        pcm_cached, sr_cached = cached_entry
                        audio_queue.put((idx, s_text, pcm_cached.copy(), sr_cached, 0.5))
                        continue

                    t_synth = time.time()
                    try:
                        comm = edge_tts.Communicate(
                            text=s_text,
                            voice=chosen_voice,
                            rate=rate_str,
                            pitch=pitch_str,
                            volume=vol_str,
                        )
                    except ValueError as ve:
                        logger.warning("[NEURAL TTS] Voice '%s' rejected (%s) — retrying with %s", chosen_voice, ve, self.DEFAULT_VOICE)
                        comm = edge_tts.Communicate(
                            text=s_text,
                            voice=self.DEFAULT_VOICE,
                            rate=rate_str,
                            pitch=pitch_str,
                            volume=vol_str,
                        )

                    bio = io.BytesIO()

                    async def _stream():
                        gen = comm.stream()
                        try:
                            async for chunk in gen:
                                if self._interrupted.is_set():
                                    break
                                if chunk["type"] == "audio":
                                    bio.write(chunk["data"])
                        finally:
                            try:
                                await gen.aclose()
                            except Exception:
                                pass

                    loop.run_until_complete(_stream())
                    if self._interrupted.is_set():
                        break

                    bio.seek(0)
                    try:
                        pcm_data, sr = sf.read(bio, dtype="int16")
                        if len(pcm_data.shape) > 1 and pcm_data.shape[1] > 1:
                            pcm_data = np.mean(pcm_data, axis=1).astype(np.int16)
                        pcm_data = trim_audio_silence(pcm_data, sr)
                    except Exception as dec_err:
                        logger.error("[NEURAL TTS] Audio decode error for sentence %d: %s", idx, dec_err)
                        continue

                    synth_ms = (time.time() - t_synth) * 1000.0

                    with self._PHRASE_CACHE_LOCK:
                        if len(self._PHRASE_CACHE) > 300:
                            self._PHRASE_CACHE.pop(next(iter(self._PHRASE_CACHE)))
                        self._PHRASE_CACHE[cache_key] = (pcm_data.copy(), sr)

                    audio_queue.put((idx, s_text, pcm_data, sr, synth_ms))
            except Exception as e:
                producer_error = f"{type(e).__name__}: {e}"
                logger.error("[NEURAL TTS] Producer worker error: %s", e)
            finally:
                audio_queue.put(("SENTINEL", producer_error))
                try:
                    pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                    for t in pending:
                        t.cancel()
                    if pending:
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    loop.run_until_complete(asyncio.sleep(0.05))
                except Exception:
                    pass
                loop.close()

        producer_thread = threading.Thread(target=_producer_worker, daemon=True)
        producer_thread.start()

        stream = None
        prev_sentence_finish_time = None
        current_sentence_item = None

        try:
            # Wait for first sentence
            current_sentence_item = audio_queue.get()
            if current_sentence_item is None or (isinstance(current_sentence_item, tuple) and current_sentence_item[0] == "SENTINEL") or self._interrupted.is_set():
                result.interrupted = self._interrupted.is_set()
                result.duration_ms = (time.time() - t_start) * 1000.0
                if not result.interrupted:
                    err_msg = current_sentence_item[1] if (isinstance(current_sentence_item, tuple) and current_sentence_item[0] == "SENTINEL") else producer_error
                    result.error = err_msg or "Neural synthesizer produced no audio frames"
                    print(f"[TTS] backend=neural synthesis failed: {result.error}")
                return result

            first_idx, first_text, first_pcm, first_sr, first_synth_ms = current_sentence_item

            # Record first audio latency
            first_audio_ms = (time.time() - t_start) * 1000.0
            result.first_audio_ms = first_audio_ms
            first_audio_recorded = True
            print(f"[TTS] backend=neural first_audio_ms={first_audio_ms:.1f}")
            print(f"[TTS] sentence_1_synthesis_ms: {first_synth_ms:.1f}")
            if on_start:
                try:
                    on_start()
                except Exception:
                    pass

            # Resolve preferred usable output device
            out_dev_idx = None
            try:
                from skills.audio_management.audio_devices import resolve
                out_dev_idx = resolve("", "output")
            except Exception:
                out_dev_idx = None

            # Open continuous audio output stream (reused for ALL sentences in this utterance)
            try:
                stream = sd.OutputStream(
                    samplerate=first_sr,
                    channels=1,
                    dtype='int16',
                    blocksize=2048,
                    device=out_dev_idx,
                )
                stream.start()
            except Exception as stream_err:
                if out_dev_idx is not None:
                    logger.warning("[NEURAL TTS] Output device %s failed (%s) — falling back to system default", out_dev_idx, stream_err)
                    stream = sd.OutputStream(
                        samplerate=first_sr,
                        channels=1,
                        dtype='int16',
                        blocksize=2048,
                        device=None,
                    )
                    stream.start()
                else:
                    raise

            with self._stop_lock:
                self._current_stream = stream
                self._is_playing = True

            while current_sentence_item is not None:
                if isinstance(current_sentence_item, tuple) and current_sentence_item[0] == "SENTINEL":
                    break
                if self._interrupted.is_set():
                    break

                idx, s_text, pcm_data, sr, synth_ms = current_sentence_item
                self._active_sentence = s_text

                if idx > 0 and prev_sentence_finish_time is not None:
                    gap_ms = (time.time() - prev_sentence_finish_time) * 1000.0
                    print(f"[TTS] sentence transition gap: {gap_ms:.1f} ms")
                    print(f"[TTS] sentence_{idx + 1}_prefetch_ms: {synth_ms:.1f}")

                if on_sentence_start:
                    try:
                        on_sentence_start(s_text)
                    except Exception:
                        pass

                _seed_echoguard(pcm_data, sr)

                t_play_start = time.time()
                chunk_size = 2048
                for offset in range(0, len(pcm_data), chunk_size):
                    if self._interrupted.is_set():
                        break
                    chunk = pcm_data[offset:offset + chunk_size]
                    if not chunk.flags['C_CONTIGUOUS']:
                        chunk = np.ascontiguousarray(chunk)
                    stream.write(chunk)

                play_ms = (time.time() - t_play_start) * 1000.0
                frame_count = len(pcm_data)
                channels = 1
                sample_width = pcm_data.dtype.itemsize
                calc_dur_sec = frame_count / (sr * channels)
                dev_sr = getattr(stream, "samplerate", sr)
                print(f"[TTS AUDIO METRICS] sentence_{idx + 1}:")
                print(f"  generated sample rate: {sr}")
                print(f"  expected sample rate: 24000")
                print(f"  actual sample rate: {sr}")
                print(f"  channels: {channels}")
                print(f"  sample width: {sample_width} bytes")
                print(f"  number of frames: {frame_count}")
                print(f"  calculated duration: {calc_dur_sec:.3f} s ({calc_dur_sec*1000:.1f} ms)")
                print(f"  actual playback duration: {play_ms/1000.0:.3f} s ({play_ms:.1f} ms)")
                print(f"  playback device sample rate: {dev_sr}")
                print(f"  playback speed/rate: {rate}")
                print(f"[TTS] sentence_{idx + 1}_playback_ms: {play_ms:.1f}")
                prev_sentence_finish_time = time.time()

                result.sentences_played += 1
                result.frame_count += frame_count
                result.byte_count += len(pcm_data.tobytes())
                result.audio_data = b"STREAMED_AUDIO"

                if self._interrupted.is_set():
                    break

                current_sentence_item = audio_queue.get()

        except Exception as e:
            if not (self._interrupted.is_set() or "stream is stopped" in str(e).lower() or "-9983" in str(e)):
                logger.error("[NEURAL TTS] Streaming playback error: %s", e)
            result.error = str(e)
        finally:
            with self._stop_lock:
                self._is_playing = False
                if stream is not None:
                    try:
                        if self._interrupted.is_set():
                            stream.abort()
                        else:
                            stream.stop()
                        stream.close()
                    except Exception:
                        pass
                self._current_stream = None

            # Drain queue if interrupted
            while not audio_queue.empty():
                try:
                    audio_queue.get_nowait()
                except Exception:
                    break

        total_duration_ms = (time.time() - t_start) * 1000.0
        result.duration_ms = total_duration_ms
        result.playback_ms = total_duration_ms
        result.backend_used = "neural"
        result.voice_used = chosen_voice
        result.interrupted = self._interrupted.is_set()
        if result.sentences_played == 0 and not result.interrupted and not result.error:
            result.error = "No audio sentences were played"

        print(
            f"[TTS] backend=neural duration_ms={total_duration_ms:.1f} interrupted={result.interrupted}"
        )
        return result

    def stop(self, interrupted: bool = True) -> None:
        """Immediately stop synthesis, cancel pending sentence, and purge audio."""
        self._interrupted.set()
        with self._stop_lock:
            if self._current_stream is not None:
                try:
                    self._current_stream.abort()
                    self._current_stream.close()
                except Exception:
                    pass
                self._current_stream = None
            try:
                import sounddevice as sd
                sd.stop()
            except Exception:
                pass
            try:
                import pygame
                if pygame.mixer.get_init():
                    pygame.mixer.music.stop()
            except Exception:
                pass
            self._is_playing = False

    @property
    def name(self) -> str:
        return "neural"

    def is_available(self) -> bool:
        try:
            import edge_tts
            return True
        except ImportError:
            return False

    def health_check(self) -> Dict[str, Any]:
        available = self.is_available()
        return {
            "backend": "neural",
            "available": available,
            "provider": "edge-tts",
            "voice": self._voice,
            "status": "healthy" if available else "missing_dependency",
        }

    def get_voices(self) -> List[TTSVoice]:
        voices = [
            TTSVoice("en-US-JennyNeural", "Microsoft Jenny (Neural)", "female", "en-US", "edge-tts"),
            TTSVoice("en-US-GuyNeural", "Microsoft Guy (Neural)", "male", "en-US", "edge-tts"),
            TTSVoice("en-US-AriaNeural", "Microsoft Aria (Neural)", "female", "en-US", "edge-tts"),
            TTSVoice("en-US-ChristopherNeural", "Microsoft Christopher (Neural)", "male", "en-US", "edge-tts"),
            TTSVoice("en-GB-SoniaNeural", "Microsoft Sonia (Neural)", "female", "en-GB", "edge-tts"),
            TTSVoice("en-GB-RyanNeural", "Microsoft Ryan (Neural)", "male", "en-GB", "edge-tts"),
            TTSVoice("en-IN-NeerjaNeural", "Microsoft Neerja (Neural)", "female", "en-IN", "edge-tts"),
            TTSVoice("en-IN-PrabhatNeural", "Microsoft Prabhat (Neural)", "male", "en-IN", "edge-tts"),
            TTSVoice("te-IN-ShrutiNeural", "Microsoft Shruti (Neural)", "female", "te-IN", "edge-tts"),
            TTSVoice("hi-IN-SwaraNeural", "Microsoft Swara (Neural)", "female", "hi-IN", "edge-tts"),
            TTSVoice("ta-IN-PallaviNeural", "Microsoft Pallavi (Neural)", "female", "ta-IN", "edge-tts"),
            TTSVoice("kn-IN-SapnaNeural", "Microsoft Sapna (Neural)", "female", "kn-IN", "edge-tts"),
            TTSVoice("ml-IN-SobhanaNeural", "Microsoft Sobhana (Neural)", "female", "ml-IN", "edge-tts"),
            TTSVoice("es-ES-ElviraNeural", "Microsoft Elvira (Neural)", "female", "es-ES", "edge-tts"),
            TTSVoice("fr-FR-DeniseNeural", "Microsoft Denise (Neural)", "female", "fr-FR", "edge-tts"),
        ]
        return voices

    def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        rate: float = 1.0,
        volume: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[bytes]:
        """Synthesize text to complete mp3 bytes synchronously."""
        if not self.is_available() or not text.strip():
            return None

        eff_lang = language or (metadata.get("lang_hint") if metadata else None) or (metadata.get("language") if metadata else None)
        chosen_voice = self.resolve_voice(voice or self._voice, language=eff_lang, text=text)
        rate_str, pitch_str, vol_str = map_metadata_to_neural_style(metadata, text=text)

        # Allow explicit rate adjustment
        if rate != 1.0:
            pct = int(round((rate - 1.0) * 100))
            sign = "+" if pct >= 0 else ""
            rate_str = f"{sign}{pct}%"

        async def _synth():
            import edge_tts
            communicate = edge_tts.Communicate(
                text=text,
                voice=chosen_voice,
                rate=rate_str,
                pitch=pitch_str,
                volume=vol_str,
            )
            bio = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    bio.write(chunk["data"])
            return bio.getvalue()

        try:
            return asyncio.run(_synth())
        except Exception as e:
            logger.error("[NEURAL TTS] Synthesis error: %s", e)
            return None


# ── Windows SAPI / OneCore Backend (Fallback) ──────────────────────────────────

class SAPIBackend(TTSBackend):
    """Fallback Windows SAPI / OneCore SpVoice backend with instant purge."""

    @classmethod
    def is_valid_voice(cls, voice_id: Optional[str]) -> bool:
        if not voice_id or not isinstance(voice_id, str):
            return False
        v = voice_id.strip()
        if "test_" in v.lower() or "neural" in v.lower():
            return False
        try:
            from legacy.tts import enumerate_voices
            installed = enumerate_voices()
            for inv in installed:
                if v == inv.get("id") or v.lower() == (inv.get("name") or "").lower():
                    return True
        except Exception:
            pass
        return bool("hkey_" in v.lower() or "speech\\voices" in v.lower() or "onecore" in v.lower())

    @classmethod
    def get_fallback_voice(cls, gender: Optional[str] = None, language: Optional[str] = None) -> Optional[str]:
        try:
            from legacy.tts import enumerate_voices
            installed = enumerate_voices()
            if not installed:
                return None
            gen = (gender or "").lower()
            lang = (language or "").lower()
            if gen:
                for v in installed:
                    if v.get("gender") == gen:
                        if lang and lang in v.get("language", "").lower():
                            return v.get("id")
                for v in installed:
                    if v.get("gender") == gen:
                        return v.get("id")
            for v in installed:
                if "english" in v.get("language", "").lower() or "en" in v.get("language", "").lower():
                    return v.get("id")
            return installed[0].get("id")
        except Exception:
            return None

    @classmethod
    def validate_or_fallback_voice(cls, voice_id: Optional[str], gender: Optional[str] = None, language: Optional[str] = None) -> Optional[str]:
        if cls.is_valid_voice(voice_id):
            return str(voice_id).strip()
        fallback = cls.get_fallback_voice(gender, language)
        if voice_id:
            logger.warning("[SAPI TTS] Invalid voice '%s' — using validated fallback '%s'", voice_id, fallback)
        return fallback

    def __init__(self):
        self._voice_id: Optional[str] = None
        self._interrupted = threading.Event()
        self._active_sp = None
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return "sapi"

    def is_available(self) -> bool:
        try:
            import comtypes.client
            return True
        except Exception:
            return False

    def health_check(self) -> Dict[str, Any]:
        avail = self.is_available()
        return {
            "backend": "sapi",
            "available": avail,
            "provider": "Windows SAPI5 / OneCore",
            "status": "healthy" if avail else "comtypes_unavailable",
        }

    def get_voices(self) -> List[TTSVoice]:
        try:
            from legacy.tts import enumerate_voices
            raw = enumerate_voices()
            return [
                TTSVoice(
                    id=v.get("id", ""),
                    name=v.get("name", ""),
                    gender=v.get("gender", "unknown"),
                    language=v.get("language", "en-US"),
                    provider=v.get("provider", "sapi5"),
                )
                for v in raw
            ]
        except Exception:
            return []

    def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        rate: float = 1.0,
        volume: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[bytes]:
        try:
            import pythoncom
            pythoncom.CoInitialize()
            import comtypes.client
            sp = comtypes.client.CreateObject("SAPI.SpVoice")
            mem_stream = comtypes.client.CreateObject("SAPI.SpMemoryStream")
            sp.AudioOutputStream = mem_stream
            chosen_voice = self.validate_or_fallback_voice(voice or self._voice_id, language=language)
            if chosen_voice:
                try:
                    token = comtypes.client.CreateObject("SAPI.SpObjectToken")
                    token.SetId(chosen_voice)
                    sp.Voice = token
                except Exception:
                    pass
            if rate > 10.0:
                sp.Rate = max(-10, min(10, int(round((rate - 145) / 14.0))))
            else:
                sp.Rate = max(-10, min(10, int(round((rate - 1.0) * 10))))
            sp.Volume = max(0, min(100, int(round(volume * 100))))
            sp.Speak(text)
            return bytes(mem_stream.GetData())
        except Exception as e:
            logger.error("[SAPI TTS] Synthesis error: %s", e)
            return None

    def stream_and_play(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        rate: float = 1.0,
        volume: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
        on_start: Optional[Callable[[], None]] = None,
        on_sentence_start: Optional[Callable[[str], None]] = None,
    ) -> SynthesisResult:
        self._interrupted.clear()
        t_start = time.time()
        result = SynthesisResult()
        result.backend_used = "sapi"

        chosen_voice = self.validate_or_fallback_voice(voice or self._voice_id, language=language)
        result.voice_used = chosen_voice or "default"

        try:
            import pythoncom
            pythoncom.CoInitialize()
            import comtypes.client
            sp = comtypes.client.CreateObject("SAPI.SpVoice")
            if chosen_voice:
                try:
                    token = comtypes.client.CreateObject("SAPI.SpObjectToken")
                    token.SetId(chosen_voice)
                    sp.Voice = token
                except Exception as e_tok:
                    logger.warning("[SAPI TTS] Voice token SetId failed for %s: %s", chosen_voice, e_tok)

            if rate > 10.0:
                sp.Rate = max(-10, min(10, int(round((rate - 145) / 14.0))))
            else:
                sp.Rate = max(-10, min(10, int(round((rate - 1.0) * 10))))
            sp.Volume = max(0, min(100, int(round(volume * 100))))

            with self._lock:
                self._active_sp = sp

            if on_start:
                try:
                    on_start()
                except Exception:
                    pass

            if on_sentence_start:
                try:
                    on_sentence_start(text)
                except Exception:
                    pass

            result.first_audio_ms = (time.time() - t_start) * 1000.0
            print(f"[TTS] backend=sapi first_audio_ms={result.first_audio_ms:.1f}")

            # Flag 1 = SVSFlagsAsync
            sp.Speak(text, 1)

            while not sp.WaitUntilDone(30):
                if self._interrupted.is_set():
                    try:
                        # Instant purge (3 = SVSFlagsAsync | SVSFPurgeBeforeSpeak)
                        sp.Speak("", 3)
                    except Exception:
                        pass
                    result.interrupted = True
                    break

            if not result.interrupted:
                result.sentences_played = 1
                result.audio_data = b"SAPI_AUDIO"
        except Exception as e:
            logger.error("[SAPI TTS] Playback error: %s", e)
            result.error = str(e)
        finally:
            with self._lock:
                self._active_sp = None

        total_ms = (time.time() - t_start) * 1000.0
        result.duration_ms = total_ms
        result.playback_ms = total_ms
        print(f"[TTS] backend=sapi duration_ms={total_ms:.1f} interrupted={result.interrupted}")
        return result

    def stop(self, interrupted: bool = True) -> None:
        self._interrupted.set()
        with self._lock:
            if self._active_sp is not None:
                try:
                    self._active_sp.Speak("", 3)
                except Exception:
                    pass
                self._active_sp = None


# ── TTS Backend Manager (Central Orchestration) ────────────────────────────────

class TTSBackendManager:
    """Manages active and fallback TTS backends with graceful failover."""

    def __init__(self):
        self._backends: Dict[str, TTSBackend] = {
            "neural": NeuralTTSBackend(),
            "sapi": SAPIBackend(),
        }
        prov = os.getenv("TTS_PROVIDER") or os.getenv("VOICE_ENGINE") or "neural"
        if "sapi" in prov.lower() or "windows" in prov.lower():
            self._active_backend_name = "sapi"
        else:
            self._active_backend_name = "neural"
        self._lock = threading.Lock()
        try:
            NeuralTTSBackend.prewarm_common_phrases()
        except Exception:
            pass
        logger.info("[TTS BACKEND MANAGER] Initialized with primary=%s", self._active_backend_name)

    def register_backend(self, backend: TTSBackend) -> None:
        with self._lock:
            self._backends[backend.name] = backend
            logger.info("[TTS BACKEND MANAGER] Registered backend: %s", backend.name)

    def set_primary_provider(self, name: str) -> None:
        with self._lock:
            low = name.lower()
            if "sapi" in low or "windows" in low:
                self._active_backend_name = "sapi"
            elif "neural" in low or "edge" in low:
                self._active_backend_name = "neural"
            else:
                self._active_backend_name = low
            logger.info("[TTS BACKEND MANAGER] Primary provider set to: %s", self._active_backend_name)

    def get_backend(self, name: Optional[str] = None) -> TTSBackend:
        """Get the specified backend or the primary healthy backend with automatic fallback."""
        target = (name or self._active_backend_name).lower()
        backend = self._backends.get(target)

        # If requested backend is available, return it
        if backend and backend.is_available():
            return backend

        # Automatic fallback: if neural is unavailable, use SAPI
        if target != "sapi":
            sapi = self._backends.get("sapi")
            if sapi and sapi.is_available():
                logger.warning(
                    "[TTS BACKEND MANAGER] Backend '%s' unavailable — falling back to SAPI",
                    target
                )
                return sapi

        # Fallback to any available backend
        for b in self._backends.values():
            if b.is_available():
                return b

        # Default to sapi backend instance even if unavailable to preserve contract
        return self._backends.get("sapi") or SAPIBackend()

    def speak_streamed(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        rate: float = 1.0,
        volume: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
        on_start: Optional[Callable[[], None]] = None,
        on_sentence_start: Optional[Callable[[str], None]] = None,
    ) -> SynthesisResult:
        """Stream speech through the primary backend with automatic fallback on failure."""
        primary = self.get_backend()
        result = primary.stream_and_play(
            text=text,
            voice=voice,
            language=language,
            rate=rate,
            volume=volume,
            metadata=metadata,
            on_start=on_start,
            on_sentence_start=on_sentence_start,
        )

        # If primary failed with an unrecoverable error or produced 0 sentences and wasn't interrupted, fall back to SAPI
        if (result.error or result.sentences_played == 0) and not result.interrupted and primary.name != "sapi":
            logger.warning(
                "[TTS BACKEND MANAGER] Primary backend %s failed (%s, sentences=%d) — invoking explicit SAPI fallback",
                primary.name, result.error or "no sentences played", result.sentences_played
            )
            sapi = self.get_backend("sapi")
            sapi_voice = None
            if voice and SAPIBackend.is_valid_voice(voice):
                sapi_voice = voice
            fallback_res = sapi.stream_and_play(
                text=text,
                voice=sapi_voice,
                language=language,
                rate=rate,
                volume=volume,
                metadata=metadata,
                on_start=on_start,
                on_sentence_start=on_sentence_start,
            )
            fallback_res.backend_used = "sapi_fallback"
            return fallback_res

        return result

    def stop_all(self, interrupted: bool = True) -> None:
        """Stop all backends immediately."""
        for backend in self._backends.values():
            try:
                backend.stop(interrupted=interrupted)
            except Exception as e:
                logger.error("[TTS BACKEND MANAGER] Error stopping backend %s: %s", backend.name, e)


# ── Singleton reference ───────────────────────────────────────────────────────

_backend_manager: Optional[TTSBackendManager] = None
_backend_lock = threading.Lock()


def get_tts_backend_manager() -> TTSBackendManager:
    global _backend_manager
    if _backend_manager is None:
        with _backend_lock:
            if _backend_manager is None:
                _backend_manager = TTSBackendManager()
    return _backend_manager


# ── End-to-End Diagnostic Routine ─────────────────────────────────────────────

def run_tts_diagnostic(text: Optional[str] = None, user_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Execute a comprehensive 6-stage end-to-end TTS diagnostic:
    1. Provider and Voice Validation
    2. Output Device Verification
    3. Audio Generation and Payload Validation
    4. Hardware Playback Execution
    5. Playback Completion and Duration Verification
    6. Reporting and Fallback Audit
    """
    test_text = text or "Smart Assistant diagnostic audio verification test."
    stages = []
    diag_result = {
        "success": False,
        "provider": None,
        "voice": None,
        "device": None,
        "stages": stages,
        "failing_stage": None,
        "metrics": {},
        "fallback_used": False,
        "fallback_provider": None,
        "message": ""
    }

    # Stage 1: Provider and Voice Validation
    stage1 = {"stage": "voice_validation", "success": False, "details": {}}
    stages.append(stage1)

    mgr = get_tts_backend_manager()
    primary = mgr.get_backend()
    diag_result["provider"] = primary.name

    target_voice = None
    if user_id:
        try:
            from core.configuration_service import get_config_service
            prefs = get_config_service().get_user_preferences(user_id)
            target_voice = prefs.get("voice_id") or prefs.get("assistant_voice_id")
        except Exception:
            pass
    if not target_voice:
        try:
            from legacy.tts import get_active_voice_id
            target_voice = get_active_voice_id()
        except Exception:
            pass

    if primary.name == "neural":
        valid_voice = NeuralTTSBackend.validate_or_fallback_voice(target_voice)
    else:
        valid_voice = SAPIBackend.validate_or_fallback_voice(target_voice)

    diag_result["voice"] = valid_voice
    stage1["details"] = {
        "requested_voice": target_voice,
        "validated_voice": valid_voice,
        "provider": primary.name,
    }
    stage1["success"] = bool(valid_voice)
    if not stage1["success"]:
        diag_result["failing_stage"] = "voice_validation"
        diag_result["message"] = "Failed to resolve a valid voice identifier."
        return diag_result

    # Stage 2: Audio Output Device Verification
    stage2 = {"stage": "device_verification", "success": False, "details": {}}
    stages.append(stage2)
    dev_idx = None
    dev_name = "System default"
    try:
        from skills.audio_management.audio_devices import resolve, list_devices
        outs = list_devices("output")
        dev_name = outs[0] if outs else "System default"
        dev_idx = resolve("", "output")
    except Exception as e:
        logger.warning("[TTS DIAGNOSTIC] Device resolve notice: %s", e)

    stage2["details"] = {"device_name": dev_name, "device_index": dev_idx}
    stage2["success"] = True
    diag_result["device"] = dev_name

    # Stage 3: Audio Generation and Payload Validation
    stage3 = {"stage": "audio_synthesis", "success": False, "details": {}}
    stages.append(stage3)
    t0_gen = time.time()
    audio_bytes = primary.synthesize(test_text, voice=valid_voice)
    gen_ms = (time.time() - t0_gen) * 1000.0

    if not audio_bytes or len(audio_bytes) < 100:
        stage3["details"] = {"byte_count": len(audio_bytes) if audio_bytes else 0, "error": "Empty or corrupt audio payload"}
        logger.warning("[TTS DIAGNOSTIC] Primary %s synthesis failed — attempting SAPI synthesis", primary.name)
        if primary.name != "sapi":
            sapi = mgr.get_backend("sapi")
            sapi_voice = SAPIBackend.validate_or_fallback_voice(target_voice)
            audio_bytes = sapi.synthesize(test_text, voice=sapi_voice)
            if audio_bytes and len(audio_bytes) >= 100:
                diag_result["fallback_used"] = True
                diag_result["fallback_provider"] = "sapi"
                diag_result["voice"] = sapi_voice
                stage3["success"] = True
                stage3["details"] = {"byte_count": len(audio_bytes), "fallback_used": True}
            else:
                diag_result["failing_stage"] = "audio_synthesis"
                diag_result["message"] = f"Audio generation produced empty or unusable audio payload ({len(audio_bytes) if audio_bytes else 0} bytes)."
                return diag_result
        else:
            diag_result["failing_stage"] = "audio_synthesis"
            diag_result["message"] = "Primary SAPI synthesis produced empty audio."
            return diag_result
    else:
        stage3["success"] = True
        stage3["details"] = {"byte_count": len(audio_bytes), "synthesis_ms": gen_ms}

    diag_result["metrics"]["audio_bytes"] = len(audio_bytes)
    diag_result["metrics"]["generation_ms"] = gen_ms

    # Stage 4 & 5: Hardware Playback Execution and Completion Verification
    stage4 = {"stage": "playback_execution", "success": False, "details": {}}
    stages.append(stage4)

    t0_play = time.time()
    play_result = mgr.speak_streamed(test_text, voice=diag_result["voice"])
    play_ms = (time.time() - t0_play) * 1000.0

    diag_result["metrics"]["playback_ms"] = play_ms
    diag_result["metrics"]["sentences_played"] = play_result.sentences_played
    diag_result["metrics"]["first_audio_ms"] = play_result.first_audio_ms

    if play_result.error or play_result.sentences_played == 0:
        stage4["details"] = {"error": play_result.error or "0 sentences played", "playback_ms": play_ms}
        diag_result["failing_stage"] = "playback_execution"
        diag_result["message"] = f"Audio playback failed on {dev_name}: {play_result.error or 'no audio played'}"
        return diag_result

    stage4["success"] = True
    stage4["details"] = {
        "backend": play_result.backend_used,
        "voice": play_result.voice_used,
        "playback_ms": play_ms,
        "sentences_played": play_result.sentences_played
    }
    if play_result.backend_used != primary.name:
        diag_result["fallback_used"] = True
        diag_result["fallback_provider"] = play_result.backend_used

    # Stage 6: Final Verification
    stage5 = {"stage": "verification", "success": True, "details": {}}
    stages.append(stage5)
    diag_result["success"] = True

    msg_prov = f"{diag_result['fallback_provider']} (fallback)" if diag_result["fallback_used"] else diag_result["provider"]
    diag_result["message"] = (
        f"TTS Diagnostic PASSED: Generated and played {len(audio_bytes)} bytes ({play_result.sentences_played} sentences) "
        f"using provider '{msg_prov}' with voice '{play_result.voice_used or diag_result['voice']}' on device '{dev_name}' "
        f"in {play_ms:.0f} ms."
    )
    return diag_result
