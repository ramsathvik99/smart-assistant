"""
Procedural Sound Effects Subsystem
Generates and plays clean, non-blocking 16-bit 44.1kHz PCM WAV acoustic tones:
- whoosh (aperture transition)
- telemetry_chirp (dual-pulse modulation)
- mission_complete (warm harmonic chord arpeggio)
- listening_start / listening_stop
"""

from __future__ import annotations

import logging
import math
import os
import struct
import threading
import time
import wave
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent
SOUNDS_DIR = PROJECT_ROOT / "data" / "sounds"


def _generate_default_sounds(target_dir: Path):
    """Procedurally synthesizes 16-bit 44.1kHz PCM WAV sound assets if missing."""
    target_dir.mkdir(parents=True, exist_ok=True)
    sample_rate = 44100

    def write_wav(path: Path, samples: list[float]):
        with wave.open(str(path), "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            raw = bytearray()
            for s in samples:
                val = int(max(min(s * 32767.0, 32767.0), -32767.0))
                raw.extend(struct.pack("<h", val))
            wf.writeframes(raw)

    # 1. Deploy Whoosh (~380ms)
    whoosh_path = target_dir / "deploy_whoosh.wav"
    if not whoosh_path.exists():
        n_samples = int(sample_rate * 0.38)
        samples = []
        for i in range(n_samples):
            t = i / sample_rate
            norm = t / 0.38
            env = math.sin(norm * math.pi) ** 1.8
            freq = 220.0 + 750.0 * math.sin(norm * math.pi)
            phase = 2.0 * math.pi * freq * t
            tone = (
                0.55 * math.sin(phase)
                + 0.25 * math.sin(phase * 1.5)
                + 0.15 * math.sin(phase * 2.3)
                + 0.08 * math.sin(phase * 3.7)
            )
            flutter = math.sin(i * 0.77) * math.cos(i * 0.23) * 0.12
            s = (tone + flutter) * env * 0.75
            samples.append(s)
        write_wav(whoosh_path, samples)

    # 2. Telemetry Chirp (~110ms)
    chirp_path = target_dir / "telemetry_chirp.wav"
    if not chirp_path.exists():
        n_samples = int(sample_rate * 0.11)
        samples = []
        for i in range(n_samples):
            t = i / sample_rate
            if t < 0.045:
                p_t = t / 0.045
                env = (1.0 - p_t) ** 1.5
                f = 2100.0 + 400.0 * p_t
                s = (0.65 * math.sin(2 * math.pi * f * t) + 0.25 * math.sin(4 * math.pi * f * t)) * env
            elif t < 0.055:
                s = 0.0
            else:
                p_t = (t - 0.055) / 0.055
                env = (1.0 - p_t) ** 2.0
                f = 2800.0 + 600.0 * p_t
                s = (0.75 * math.sin(2 * math.pi * f * t) + 0.25 * math.sin(4 * math.pi * f * t)) * env
            samples.append(s * 0.65)
        write_wav(chirp_path, samples)

    # 3. Mission Complete Chime (~950ms)
    chime_path = target_dir / "mission_complete.wav"
    if not chime_path.exists():
        n_samples = int(sample_rate * 0.95)
        samples = []
        notes = [
            (0.00, 587.33, 0.40),
            (0.08, 739.99, 0.35),
            (0.16, 880.00, 0.30),
            (0.24, 1174.66, 0.45),
            (0.32, 1479.98, 0.25),
        ]
        decay = 4.0
        for i in range(n_samples):
            t = i / sample_rate
            val = 0.0
            for start, freq, amp in notes:
                if t >= start:
                    dt = t - start
                    env = math.exp(-decay * dt)
                    val += amp * math.sin(2 * math.pi * freq * dt) * env
            samples.append(val * 0.5)
        write_wav(chime_path, samples)

    # 4. Listening Start / Stop
    start_path = target_dir / "listening_start.wav"
    if not start_path.exists():
        n_samples = int(sample_rate * 0.08)
        samples = [math.sin(2 * math.pi * 1760.0 * (i / sample_rate)) * (1.0 - i / n_samples) * 0.4 for i in range(n_samples)]
        write_wav(start_path, samples)

    stop_path = target_dir / "listening_stop.wav"
    if not stop_path.exists():
        n_samples = int(sample_rate * 0.08)
        samples = [math.sin(2 * math.pi * 880.0 * (i / sample_rate)) * (1.0 - i / n_samples) * 0.4 for i in range(n_samples)]
        write_wav(stop_path, samples)


class SoundManager:
    """Manages playback of acoustic feedback tones."""

    def __init__(self, sounds_dir: Optional[Path] = None):
        self.sounds_dir = sounds_dir or SOUNDS_DIR
        self.enabled = True
        try:
            _generate_default_sounds(self.sounds_dir)
        except Exception as e:
            logger.warning(f"Failed to generate default sound effects: {e}")

    def play(self, sound_name: str) -> bool:
        if not self.enabled:
            return False

        fname = sound_name if sound_name.endswith(".wav") else f"{sound_name}.wav"
        target = self.sounds_dir / fname
        if not target.exists():
            return False

        def _play_thread():
            try:
                import winsound
                winsound.PlaySound(str(target), winsound.SND_FILENAME | winsound.SND_ASYNC)
            except Exception as e:
                logger.debug(f"Sound playback error: {e}")

        threading.Thread(target=_play_thread, daemon=True, name="SoundEffectPlay").start()
        return True


_sound_instance: Optional[SoundManager] = None
_snd_lock = threading.Lock()


def get_sound_manager() -> SoundManager:
    global _sound_instance
    with _snd_lock:
        if _sound_instance is None:
            _sound_instance = SoundManager()
        return _sound_instance
