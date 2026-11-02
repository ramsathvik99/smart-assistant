"""
core/stream_speaker.py
======================
Low-latency sentence-by-sentence streaming speech for plain questions & conversation.

Connects LLMEngine.stream_completion with NeuralTTSBackend.stream_and_play:
- Streams tokens from language model
- Yields sentences as soon as completed
- Applies make_speakable sanitization
- Synthesizes and plays first sentence immediately via Neural TTS
- Updates UI text progressively
- Halts cleanly on barge-in / cancellation
"""

import re
import time
import logging
import threading
from typing import Optional, Dict, Any, Callable, Iterator

from extensions.llm_engine import LLMEngine
from core.speech_safety import make_speakable
from core.question_gate import is_plain_question
from core.turn_deadline import get_current_turn_deadline
from core.latency_instrumentation import get_current_tracker

logger = logging.getLogger(__name__)

# Global cancellation event for barge-in / new turn preemption
_ACTIVE_CANCEL_EVENT: Optional[threading.Event] = None
_CANCEL_LOCK = threading.Lock()


def get_or_create_cancel_event() -> threading.Event:
    """Get or create the cancellation event for current speech stream."""
    global _ACTIVE_CANCEL_EVENT
    with _CANCEL_LOCK:
        if _ACTIVE_CANCEL_EVENT is None:
            _ACTIVE_CANCEL_EVENT = threading.Event()
        return _ACTIVE_CANCEL_EVENT


def cancel_current_stream():
    """Cancel active streaming speech immediately (barge-in / speech start)."""
    global _ACTIVE_CANCEL_EVENT
    with _CANCEL_LOCK:
        if _ACTIVE_CANCEL_EVENT is not None:
            _ACTIVE_CANCEL_EVENT.set()
    try:
        from extensions.system.tts_coordinator import get_tts_coordinator
        get_tts_coordinator().interrupt_speech()
    except Exception:
        pass


def stream_and_speak(
    prompt: str,
    context: Optional[str] = None,
    memory: Optional[str] = None,
    system_prompt: Optional[str] = None,
    user_id: Optional[int] = None,
    on_text_update: Optional[Callable[[str], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Dict[str, Any]:
    """
    Generate conversational answer and speak sentence-by-sentence via streaming TTS.

    Args:
        prompt: User's question or chat prompt.
        context: Recent conversation context turns.
        memory: Long-term retrieved background facts.
        system_prompt: Optional custom persona / system prompt.
        user_id: Target user ID.
        on_text_update: Optional callback invoked with progressive accumulated UI text.
        cancel_event: Optional external cancellation event.

    Returns:
        dict with keys: 'response', 'status', 'streamed'
    """
    global _ACTIVE_CANCEL_EVENT
    eff_cancel = cancel_event or get_or_create_cancel_event()
    eff_cancel.clear()

    engine = LLMEngine()
    tracker = get_current_tracker()
    if tracker:
        tracker.record("llm_start_timestamp", time.monotonic())

    # Obtain primary neural TTS backend
    neural_backend = None
    try:
        from extensions.system.tts_coordinator import get_tts_coordinator
        coord = get_tts_coordinator()
        if coord and hasattr(coord, "backend") and coord.backend:
            neural_backend = coord.backend
    except Exception:
        neural_backend = None

    if neural_backend is None:
        try:
            from extensions.system.tts_backend import NeuralTTSBackend
            neural_backend = NeuralTTSBackend()
        except Exception as e:
            logger.warning("[STREAM_SPEAKER] Neural backend unavailable: %s", e)

    accumulated_ui_sentences = []
    spoken_sentences = []
    stream_failed_midway = False

    def _sentence_generator() -> Iterator[str]:
        nonlocal stream_failed_midway
        try:
            raw_gen = engine.stream_completion(
                prompt=prompt,
                system_prompt=system_prompt,
                context=context,
                memory=memory,
                user_id=user_id,
                cancel_event=eff_cancel
            )
            for raw_sentence in raw_gen:
                if eff_cancel.is_set():
                    logger.info("[STREAM_SPEAKER] Stream cancelled by barge-in.")
                    break
                
                raw_low = raw_sentence.lower().strip()
                if re.match(r'^today\s+is\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|[a-z]+\s+\d+).*', raw_low):
                    continue
                if re.match(r'^i\s+am\s+[a-z0-9_\s]+?(?:assistant|companion).*', raw_low):
                    continue
                if re.match(r'^today,?\s+i(?:\'ll| will)\s+be\s+explaining.*', raw_low):
                    continue
                clean = make_speakable(raw_sentence)
                if clean:
                    spoken_sentences.append(clean)
                    accumulated_ui_sentences.append(raw_sentence)
                    
                    if on_text_update:
                        try:
                            on_text_update(" ".join(accumulated_ui_sentences))
                        except Exception:
                            pass
                    
                    yield clean
        except Exception as err:
            logger.error("[STREAM_SPEAKER] Error during streaming: %s", err)
            stream_failed_midway = True
            # Finish with what was already spoken and do not repeat it

    # If neural backend is available, dispatch streaming sentence generator to audio queue
    if neural_backend is not None and hasattr(neural_backend, "stream_and_play"):
        logger.info("[STREAM_SPEAKER] Starting streaming speech for prompt: %r", prompt[:50])

        # ── Wire legacy._tts_active so sst._is_tts_speaking() returns True ──────
        # stream_and_speak bypasses the legacy _tts_worker, so _tts_active is never
        # set by that path. Set it manually here and clear it after playback finishes.
        _tts_active_ref = None
        try:
            from legacy.tts import _tts_active as _leg_active, _speech_start_time as _leg_sst
            import legacy.tts as _leg_tts
            _tts_active_ref = _leg_active
            _leg_active.set()
            _leg_tts._speech_start_time = time.monotonic()
        except Exception:
            pass
        try:
            from core.voice_lifecycle import get_voice_lifecycle
            get_voice_lifecycle().on_tts_started()
        except Exception:
            pass

        try:
            tts_result = neural_backend.stream_and_play(
                text=_sentence_generator(),
                metadata={"source": "stream_speaker", "ui_text": prompt}
            )
        finally:
            # Always clear _tts_active and fire on_tts_finished, even if an exception occurs
            if _tts_active_ref is not None:
                try:
                    _tts_active_ref.clear()
                except Exception:
                    pass
            try:
                from core.voice_lifecycle import get_voice_lifecycle
                get_voice_lifecycle().on_tts_finished()
            except Exception:
                pass
        # ── end _tts_active wiring ────────────────────────────────────────────────

        full_response = " ".join(accumulated_ui_sentences).strip()
        if not full_response and spoken_sentences:
            full_response = " ".join(spoken_sentences).strip()

        if tracker:
            tracker.record("text_answer_available_timestamp", time.monotonic())

        return {
            "status": "success",
            "response": full_response,
            "streamed": True,
            "interrupted": eff_cancel.is_set() or getattr(tts_result, "interrupted", False),
        }
    else:
        # Fallback: consume generator directly without audio dispatch
        for _ in _sentence_generator():
            pass
        full_response = " ".join(accumulated_ui_sentences).strip()
        return {
            "status": "success",
            "response": full_response,
            "streamed": False,
        }
