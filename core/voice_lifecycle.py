"""
Smart Assistant — Canonical Voice Lifecycle & State Interface
Tracks genuine microphone capture, speech activity detection (VAD),
transcription processing, TTS response delivery, and device errors.
Provides thread-safe state synchronization for the Floating Assistant Button and UI.
"""

from __future__ import annotations

import time
import threading
from typing import Callable, Optional, List, Dict, Any


class VoiceLifecycleManager:
    """
    Central thread-safe coordinator for voice-input lifecycle events.
    Exposes real runtime states:
      - 'idle': Standby, waiting for input. Microphone is not recording speech.
      - 'listening': Actively capturing user speech in real time.
      - 'processing': End of utterance detected; speech recognition / planning active.
      - 'speaking': Assistant is actively speaking TTS audio.
      - 'error': Microphone unavailable, capture failed, or recognition timed out.
    """
    _instance: Optional[VoiceLifecycleManager] = None
    _singleton_lock = threading.Lock()

    def __new__(cls) -> VoiceLifecycleManager:
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = super(VoiceLifecycleManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        self._lock = threading.RLock()
        self._state: str = "idle"
        self._status_message: str = ""
        self._last_transcript: str = ""
        self._audio_level: float = 0.0
        self._mic_available: bool = False
        self._active_device_index: Optional[int] = None
        self._last_speech_time: float = 0.0

        # Listeners
        self._state_listeners: List[Callable[[str, str], None]] = []
        self._level_listeners: List[Callable[[float], None]] = []
        self._transcript_listeners: List[Callable[[str], None]] = []

        # Auto-reset error timer handle
        self._error_reset_timer: Optional[threading.Timer] = None

        self._initialized = True
        print("[VOICE LIFECYCLE] Initialized as Single Source of Truth for Voice State")

    # ── State Accessors ────────────────────────────────────────────────────────
    def get_state(self) -> str:
        with self._lock:
            return self._state

    def get_status_message(self) -> str:
        with self._lock:
            return self._status_message

    def get_audio_level(self) -> float:
        with self._lock:
            return self._audio_level

    def is_mic_available(self) -> bool:
        with self._lock:
            return self._mic_available

    # ── Listener Registration ──────────────────────────────────────────────────
    def register_state_listener(self, callback: Callable[[str, str], None]) -> None:
        """Register a callback for (state: str, message: str) updates."""
        with self._lock:
            if callback not in self._state_listeners:
                self._state_listeners.append(callback)

    def unregister_state_listener(self, callback: Callable[[str, str], None]) -> None:
        with self._lock:
            if callback in self._state_listeners:
                self._state_listeners.remove(callback)

    def register_level_listener(self, callback: Callable[[float], None]) -> None:
        """Register a callback for (level: float) updates (0.0 to 1.0)."""
        with self._lock:
            if callback not in self._level_listeners:
                self._level_listeners.append(callback)

    def unregister_level_listener(self, callback: Callable[[float], None]) -> None:
        with self._lock:
            if callback in self._level_listeners:
                self._level_listeners.remove(callback)

    def register_transcript_listener(self, callback: Callable[[str], None]) -> None:
        """Register a callback for (transcript: str) updates."""
        with self._lock:
            if callback not in self._transcript_listeners:
                self._transcript_listeners.append(callback)

    def unregister_transcript_listener(self, callback: Callable[[str], None]) -> None:
        with self._lock:
            if callback in self._transcript_listeners:
                self._transcript_listeners.remove(callback)

    # ── Internal State Dispatch ────────────────────────────────────────────────
    def _set_state_locked(self, new_state: str, message: str = "") -> None:
        """Must be called while holding self._lock."""
        if self._error_reset_timer:
            try:
                self._error_reset_timer.cancel()
            except Exception:
                pass
            self._error_reset_timer = None

        state_changed = (new_state != self._state)
        msg_changed = (message != self._status_message)
        if not state_changed and not msg_changed:
            return

        self._state = new_state
        self._status_message = message or ""
        listeners = list(self._state_listeners)

        # Notify AssistantCore as well for unified state broadcast
        try:
            from core.assistant_core import assistant_core
            assistant_core.set_state(new_state)
        except Exception:
            pass

        # Schedule auto-reset if in error state
        if new_state == "error":
            def _auto_reset():
                with self._lock:
                    if self._state == "error":
                        self._set_state_locked("idle", "")
            self._error_reset_timer = threading.Timer(2.8, _auto_reset)
            self._error_reset_timer.daemon = True
            self._error_reset_timer.start()

        # Invoke callbacks outside lock
        for cb in listeners:
            try:
                cb(new_state, self._status_message)
            except Exception as e:
                print(f"[VOICE LIFECYCLE] Error in state listener: {e}")

    # ── Real Microphone & Voice Lifecycle Events ───────────────────────────────
    def on_mic_opened(self, device_index: Optional[int] = None) -> None:
        """Called when audio stream / PyAudio / sounddevice opens successfully."""
        with self._lock:
            self._mic_available = True
            self._active_device_index = device_index
            if self._state == "error":
                self._set_state_locked("idle", "")

    def on_mic_closed(self) -> None:
        """Called when audio stream is closed."""
        with self._lock:
            self._mic_available = False
            self._audio_level = 0.0
            if self._state not in ("speaking", "processing"):
                self._set_state_locked("idle", "")

    def on_mic_error(self, error_message: str = "Microphone unavailable") -> None:
        """Called when microphone device open or stream read fails."""
        with self._lock:
            self._mic_available = False
            self._audio_level = 0.0
            print(f"[VOICE LIFECYCLE] Microphone error: {error_message}")
            self._set_state_locked("error", error_message)

    def on_vad_listening(self) -> None:
        """Called when audio stream is active and on standby waiting for speech."""
        with self._lock:
            self._mic_available = True
            self._audio_level = 0.0
            # If not in processing or speaking, keep state as idle/ready (do not fake recording)
            if self._state not in ("processing", "speaking", "listening"):
                self._set_state_locked("idle", "")

    def on_speech_detected(self) -> None:
        """Called when VAD confirms genuine speech activity onset."""
        with self._lock:
            self._last_speech_time = time.monotonic()
            self._set_state_locked("listening", "Listening…")

    def on_audio_level(self, level: float) -> None:
        """Called with live normalized audio energy (0.0 to 1.0)."""
        clean_level = max(0.0, min(1.0, float(level)))
        with self._lock:
            self._audio_level = clean_level
            listeners = list(self._level_listeners)

        for cb in listeners:
            try:
                cb(clean_level)
            except Exception:
                pass

    def on_end_of_utterance(self) -> None:
        """Called when VAD detects end of utterance (silence threshold reached)."""
        with self._lock:
            self._audio_level = 0.0
            # Microphone capture for this utterance is complete; transition immediately to processing
            self._set_state_locked("processing", "Processing…")

    def on_transcription_started(self) -> None:
        """Called when speech recognition begins."""
        with self._lock:
            self._set_state_locked("processing", "Processing…")

    def on_transcription_completed(self, text: str) -> None:
        """Called when recognized transcript is available."""
        with self._lock:
            clean_text = (text or "").strip()
            self._last_transcript = clean_text
            self._set_state_locked("processing", "Processing…")
            transcript_listeners = list(self._transcript_listeners)

        for cb in transcript_listeners:
            try:
                cb(clean_text)
            except Exception as e:
                print(f"[VOICE LIFECYCLE] Error in transcript listener: {e}")

    def on_transcription_error(self, message: str = "Didn't catch that — try again.") -> None:
        """Called when speech recognition fails or times out."""
        with self._lock:
            self._audio_level = 0.0
            print(f"[VOICE LIFECYCLE] Transcription notice: {message}")
            self._set_state_locked("error", message)

    def on_assistant_executing(self, command: str) -> None:
        """Called when command is handed to planner/router pipeline."""
        with self._lock:
            self._set_state_locked("processing", "Processing…")

    def on_tts_started(self) -> None:
        """Called when TTS playback begins."""
        with self._lock:
            self._set_state_locked("speaking", "Responding…")

    def on_tts_finished(self) -> None:
        """Called when TTS playback finishes."""
        with self._lock:
            self._audio_level = 0.0
            self._set_state_locked("idle", "")

    def reset_to_idle(self) -> None:
        """Force reset to idle standby."""
        with self._lock:
            self._audio_level = 0.0
            self._set_state_locked("idle", "")


def get_voice_lifecycle() -> VoiceLifecycleManager:
    """Return the global VoiceLifecycleManager singleton."""
    return VoiceLifecycleManager()
