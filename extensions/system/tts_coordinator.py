"""
TTS Coordinator - Centralized Text-to-Speech Management

RULE 5: ONE TTS RESPONSE
- All text-to-speech requests route through this coordinator
- Ensures one response per command
- Manages priority queue (user commands > reminders > proactive)
- Prevents overlapping audio
- Single speak() invocation point

Architecture:
  Module A -> tts_coordinator.speak("text", priority="command")
  Module B -> tts_coordinator.speak("text", priority="reminder")
  Module C -> tts_coordinator.speak("text", priority="proactive")
              |
         Coordinator (priority queue)
              |
         legacy.tts.speak() (single invocation)

Initialization contract
-----------------------
initialize_tts_coordinator(speak_func) MUST be called before any
application component calls speak().  It is called during
initialization_manager._phase_core_services() which runs as the
FIRST substantive phase of startup, before any background service.

If speak() is called before initialization (e.g. from a module
imported at the top of assistant.py before startup completes), the
coordinator logs a clear WARNING and falls back directly to
legacy.tts.speak() so speech is never silently dropped.
"""

import logging
import threading
import time
from enum import Enum
from queue import PriorityQueue
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class TTSPriority(Enum):
    """TTS priority levels (higher number = higher priority)"""
    PROACTIVE = 1      # Lowest: idle suggestions
    REMINDER  = 2      # Medium: reminder alerts
    COMMAND   = 3      # High: user command responses
    EMERGENCY = 4      # Highest: emergency alerts


class TTSRequest:
    """Represents a single TTS request"""

    _counter     = 0
    _counter_lock = threading.Lock()

    def __init__(self, text: str, priority: TTSPriority, lang_hint: str = "en"):
        self.text      = text
        self.priority  = priority
        self.lang_hint = lang_hint
        self.timestamp = time.time()
        with TTSRequest._counter_lock:
            self.sequence = TTSRequest._counter
            TTSRequest._counter += 1

    def __lt__(self, other):
        """Sort by: priority (desc), then sequence (asc) for FIFO within a tier."""
        if self.priority.value != other.priority.value:
            return self.priority.value > other.priority.value
        return self.sequence < other.sequence

    def __repr__(self):
        return f"<TTS {self.priority.name}: {self.text[:30]!r}>"


class TTSCoordinator:
    """Centralized TTS management — single speak() invocation point."""

    def __init__(self):
        self.queue         = PriorityQueue()
        self.running       = False
        self.worker_thread: Optional[threading.Thread] = None
        self.speak_func: Optional[Callable] = None
        self._init_lock    = threading.Lock()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self, speak_func: Callable) -> None:
        """Set the underlying speech function (legacy.tts.speak).

        Safe to call multiple times — subsequent calls are no-ops.

        Args:
            speak_func: Reference to legacy.tts.speak
        """
        with self._init_lock:
            if self.speak_func is not None:
                # Already initialized — no-op
                return
            self.speak_func = speak_func
        logger.info("[TTS COORDINATOR] Initialized with speak_func")

    def start(self) -> None:
        """Start the priority-queue worker thread."""
        with self._init_lock:
            if self.running:
                logger.warning("[TTS COORDINATOR] Worker already running — skipping start")
                return
            self.running = True
            self.worker_thread = threading.Thread(
                target=self._worker_loop,
                daemon=True,
                name="assistant-tts-coordinator"
            )
            self.worker_thread.start()
        logger.info("[TTS COORDINATOR] Worker thread started")

    def stop(self) -> None:
        """Stop the coordinator worker thread (waits up to 5 s)."""
        self.running = False
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=5)
        logger.info("[TTS COORDINATOR] Worker thread stopped")

    # ------------------------------------------------------------------
    # Public speak interface
    # ------------------------------------------------------------------

    def speak(self, text: str,
              priority: TTSPriority = TTSPriority.COMMAND,
              lang_hint: str = "en") -> None:
        """Queue a TTS request.

        If the coordinator has not been initialized yet (speak_func is
        None), the request is passed DIRECTLY to legacy.tts.speak() as
        a transparent fallback so speech is never silently dropped.

        Args:
            text:      Text to speak.
            priority:  Priority tier.
            lang_hint: BCP-47 language code hint.
        """
        if not text or not text.strip():
            return

        if self.speak_func is None:
            # Coordinator not yet initialized — fall back to direct TTS.
            # This can happen when a module imported during startup
            # calls speak() before initialize_tts_coordinator() runs.
            logger.warning(
                "[TTS COORDINATOR] speak_func not yet set — "
                "falling back to legacy.tts.speak() directly for: %r",
                text[:60]
            )
            try:
                from legacy.tts import speak as _direct_speak
                _direct_speak(text, lang_hint=lang_hint, block=False)
            except Exception as exc:
                logger.error("[TTS COORDINATOR] Direct fallback also failed: %s", exc)
            return

        request = TTSRequest(text, priority, lang_hint)
        self.queue.put(request)
        logger.debug("[TTS COORDINATOR] Queued: %s", request)

    # ------------------------------------------------------------------
    # Wait helpers
    # ------------------------------------------------------------------

    def wait_until_spoken(self, timeout: float = 30.0) -> None:
        """Block until the coordinator queue is empty.

        Also waits for the underlying legacy TTS queue to drain.
        """
        try:
            self.queue.join()
        except Exception:
            pass
        # Also wait for the underlying legacy engine to finish
        try:
            from legacy.tts import wait_for_silence
            wait_for_silence(timeout=timeout)
        except Exception:
            pass

    def is_speaking(self) -> bool:
        """Return True while any TTS output is in flight."""
        if not self.queue.empty():
            return True
        try:
            from legacy.tts import is_speaking as _leg_speaking
            return _leg_speaking()
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        logger.info("[TTS COORDINATOR WORKER] Started")

        while self.running:
            try:
                request = self.queue.get(timeout=1)
            except Exception:
                # Queue.get timed out — loop and check running flag
                continue

            try:
                logger.info(
                    "[TTS COORDINATOR] Speaking (%s): %r",
                    request.priority.name,
                    request.text[:60]
                )
                # Invoke legacy.tts.speak() — it enqueues to the FIFO
                # worker which calls pyttsx3 / gTTS on its own thread.
                self.speak_func(request.text,
                                lang_hint=request.lang_hint,
                                block=False)
            except Exception as exc:
                logger.error("[TTS COORDINATOR] Error dispatching request: %s", exc)
            finally:
                self.queue.task_done()

        logger.info("[TTS COORDINATOR WORKER] Stopped")


# ── Module-level singleton ────────────────────────────────────────────────────

_tts_coordinator: Optional[TTSCoordinator] = None
_singleton_lock = threading.Lock()


def get_tts_coordinator() -> TTSCoordinator:
    """Get (or lazily create) the global TTS coordinator instance."""
    global _tts_coordinator
    if _tts_coordinator is None:
        with _singleton_lock:
            if _tts_coordinator is None:
                _tts_coordinator = TTSCoordinator()
    return _tts_coordinator


def initialize_tts_coordinator(speak_func: Callable) -> None:
    """Initialize the global TTS coordinator.

    Must be called once at startup, BEFORE any background service
    that may invoke speak().

    Args:
        speak_func: Reference to legacy.tts.speak
    """
    coordinator = get_tts_coordinator()
    coordinator.initialize(speak_func)
    coordinator.start()
    logger.info("[TTS COORDINATOR] Global instance initialized and started")


# ── Public API ────────────────────────────────────────────────────────────────

def speak(text: str,
          priority: TTSPriority = TTSPriority.COMMAND,
          lang_hint: str = "en",
          block: bool = False) -> None:
    """Queue text for speaking through the coordinator.

    This is the ONLY function application code should call for TTS.
    Modules must NOT call legacy.tts.speak() directly (except the
    coordinator's own worker).

    Args:
        text:      Text to speak.
        priority:  Priority tier (default: COMMAND).
        lang_hint: BCP-47 language code.
        block:     If True, wait until all queued speech is done.
                   Use sparingly — can delay the calling thread.
    """
    coordinator = get_tts_coordinator()
    coordinator.speak(text, priority, lang_hint)

    if block:
        coordinator.wait_until_spoken()


def is_speaking() -> bool:
    """Return True while TTS output is in flight."""
    return get_tts_coordinator().is_speaking()


def wait_until_spoken(timeout: float = 30.0) -> None:
    """Block until all queued TTS has been spoken."""
    get_tts_coordinator().wait_until_spoken(timeout=timeout)
