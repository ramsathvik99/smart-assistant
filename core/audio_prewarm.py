"""
core/audio_prewarm.py
=====================
Startup audio device and neural TTS phrase prewarming.

Eliminates cold-start latency (~5s) for deterministic commands and short confirmations by:
1. Pre-initializing the audio output device (PortAudio / sounddevice stream) on a background thread.
2. Pre-warming neural synthesis connection.
3. Pre-rendering common short confirmations into NeuralTTSBackend._PHRASE_CACHE:
   - "Okay", "Done", "Done. Opening Notepad."
   - "Volume set to N percent." (0% to 100%)
   - "Music paused.", "Music resumed."
"""

import logging
import threading
import time
import asyncio
import io
from typing import List, Tuple

logger = logging.getLogger("AudioPrewarm")

_PREWARM_STARTED = False
_PREWARM_LOCK = threading.Lock()


def get_prewarm_phrases() -> List[str]:
    """Return all common short confirmation phrases to pre-render."""
    phrases = [
        "Okay",
        "Done",
        "Done. Opening Notepad.",
        "Music paused.",
        "Music resumed.",
        "Opened Notepad.",
        "Opened Calculator.",
    ]
    # Common volume increments
    for vol in [0, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 100]:
        phrases.append(f"Volume set to {vol} percent.")
    return phrases


def _warmup_audio_device() -> None:
    """Pre-initialize sounddevice PortAudio output device on background thread."""
    try:
        import sounddevice as sd
        from skills.audio_management.audio_devices import resolve
        out_dev = resolve("", "output")
        test_stream = sd.OutputStream(
            samplerate=24000,
            channels=1,
            dtype='int16',
            blocksize=1024,
            device=out_dev,
        )
        test_stream.start()
        test_stream.stop()
        test_stream.close()
        logger.debug("[AUDIO PREWARM] Audio device prewarmed successfully.")
    except Exception as e:
        logger.debug(f"[AUDIO PREWARM] Audio device prewarm skipped: {e}")


async def _synthesize_phrase(edge_tts, sf, np, text: str, voice: str, rate: str, pitch: str, vol: str, trim_fn):
    """Synthesize a single phrase asynchronously."""
    try:
        comm = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch, volume=vol)
        bio = io.BytesIO()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                bio.write(chunk["data"])
        bio.seek(0)
        pcm_data, sr = sf.read(bio, dtype="int16")
        if len(pcm_data.shape) > 1 and pcm_data.shape[1] > 1:
            pcm_data = np.mean(pcm_data, axis=1).astype(np.int16)
        if trim_fn:
            pcm_data = trim_fn(pcm_data, sr)
        return text, pcm_data, sr
    except Exception as e:
        logger.debug(f"[AUDIO PREWARM] Synthesis skipped for '{text}': {e}")
        return text, None, 24000


def _prewarm_worker():
    """Background worker prewarming device and phrase cache."""
    # 1. Warm up audio device hardware
    _warmup_audio_device()

    # 2. Warm up neural TTS phrases
    try:
        from extensions.system.tts_backend import NeuralTTSBackend, trim_audio_silence
        import edge_tts
        import soundfile as sf
        import numpy as np

        phrases = get_prewarm_phrases()
        voice = getattr(NeuralTTSBackend, "DEFAULT_VOICE", "en-US-JennyNeural")

        # Styles: action_confirmation style ("+10%", "+1Hz", "+0%") and normal ("+0%", "+0Hz", "+0%")
        styles = [
            ("+10%", "+1Hz", "+0%"),
            ("+0%", "+0Hz", "+0%"),
        ]

        async def _batch_prewarm():
            tasks = []
            for p in phrases:
                for rate_str, pitch_str, vol_str in styles:
                    cache_key = (p.strip().lower(), voice, rate_str, pitch_str, vol_str)
                    with NeuralTTSBackend._PHRASE_CACHE_LOCK:
                        if cache_key in NeuralTTSBackend._PHRASE_CACHE:
                            continue
                    tasks.append(
                        (cache_key, _synthesize_phrase(
                            edge_tts, sf, np, p, voice, rate_str, pitch_str, vol_str, trim_audio_silence
                        ))
                    )

            if not tasks:
                return

            # Run in concurrent batches of 4
            batch_size = 4
            for i in range(0, len(tasks), batch_size):
                batch = tasks[i:i + batch_size]
                coros = [t[1] for t in batch]
                results = await asyncio.gather(*coros, return_exceptions=True)
                for (ck, _), res in zip(batch, results):
                    if isinstance(res, tuple) and res[1] is not None:
                        _, pcm, sr = res
                        with NeuralTTSBackend._PHRASE_CACHE_LOCK:
                            NeuralTTSBackend._PHRASE_CACHE[ck] = (pcm, sr)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_batch_prewarm())
        finally:
            loop.close()

        logger.info("[AUDIO PREWARM] Prewarmed common confirmation phrases into neural cache.")
    except Exception as e:
        logger.debug(f"[AUDIO PREWARM] Neural phrase prewarm encountered: {e}")


def prewarm_audio_subsystem():
    """Start asynchronous audio device and confirmation phrase prewarming."""
    global _PREWARM_STARTED
    with _PREWARM_LOCK:
        if _PREWARM_STARTED:
            return
        _PREWARM_STARTED = True

    t = threading.Thread(target=_prewarm_worker, daemon=True, name="audio-prewarm")
    t.start()
