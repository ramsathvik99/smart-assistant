"""
Progress Acknowledgement Subsystem.
Provides non-blocking acoustic and visual cues when an operation takes longer than 1.5s,
without talking over the pending answer.
"""
import threading
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ProgressAcknowledger:
    """
    Monitors long-running operations (>1.5s) and emits a lightweight, non-blocking
    procedural audio chime / visual status without interrupting or delaying the response.
    """
    def __init__(self, delay: float = 1.5, cue_sound: str = "telemetry_chirp"):
        self.delay = delay
        self.cue_sound = cue_sound
        self._timer: Optional[threading.Timer] = None
        self._completed = False
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            self._completed = False
            self._timer = threading.Timer(self.delay, self._on_timeout)
            self._timer.daemon = True
            self._timer.start()

    def stop(self):
        with self._lock:
            self._completed = True
            if self._timer:
                self._timer.cancel()
                self._timer = None

    def _on_timeout(self):
        with self._lock:
            if self._completed:
                return

        # 1. Update visual voice lifecycle status message if available
        try:
            from core.voice_lifecycle import get_voice_lifecycle
            get_voice_lifecycle().on_thinking("Working on it…")
        except Exception as e:
            logger.debug(f"[ProgressAck] Voice lifecycle notice: {e}")

        # 2. Trigger non-blocking acoustic cue (short ~110ms telemetry chirp)
        try:
            from instance.config import settings as CONFIG
            enable_cue = getattr(CONFIG, "ENABLE_PROGRESS_CUE", True)
            if enable_cue:
                from skills.audio_management.sound_effects import get_sound_manager
                get_sound_manager().play(self.cue_sound)
        except Exception as e:
            logger.debug(f"[ProgressAck] Acoustic cue notice: {e}")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def acknowledge_progress(delay: float = 1.5, cue_sound: str = "telemetry_chirp") -> ProgressAcknowledger:
    """Convenience factory for ProgressAcknowledger context manager."""
    return ProgressAcknowledger(delay=delay, cue_sound=cue_sound)
