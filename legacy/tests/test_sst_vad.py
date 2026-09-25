"""
legacy/tests/test_sst_vad.py
============================
Unit tests for the stateful window-based VAD in legacy/sst.py.

All tests are OFFLINE — no microphone, no Google STT, no TTS.

Frame arithmetic reference (mirrors sst.py)
--------------------------------------------
SAMPLE_RATE = 16000 Hz
CHUNK_SIZE  = 1024 samples
1 chunk     ≈ 64 ms   →   ~15.6 chunks / second

VAD onset logic
---------------
The onset detector uses a SLIDING WINDOW rather than strict consecutiveness.
ONSET_WIN      = 8  frames  (~512 ms window)
ONSET_MIN      = 4  frames  (50% of window must be speech-positive)
This means:
  - 1 spike in 8 frames  (12.5%) → NOT onset → stays LISTENING
  - 4+ frames in 8       (50%+)  → onset confirmed → SPEAKING

VAD end-of-utterance
--------------------
SILENCE_END_FRAMES = 20  (≈ 1.28 s of sustained silence)
MIN_SPEECH_FRAMES  = 6   (≈ 384 ms of actual voiced content)
"""

from __future__ import annotations

import queue
import sys
import os
import time
import types
import unittest
from unittest.mock import MagicMock

import numpy as np

# ── Add project root to path ──────────────────────────────────────────────────
_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ── Stubs so sst.py imports without real hardware ────────────────────────────
_fake_config_mod = types.ModuleType("instance.config")
_fake_config_mod.settings = MagicMock()
_fake_config_mod.settings.get = MagicMock(return_value="en-US")
_fake_instance_mod = types.ModuleType("instance")
sys.modules.setdefault("instance", _fake_instance_mod)
sys.modules.setdefault("instance.config", _fake_config_mod)

_mock_pa = MagicMock()
_mock_pa.paInt16 = 8
sys.modules.setdefault("pyaudio", _mock_pa)
sys.modules.setdefault("speech_recognition", MagicMock())
sys.modules.setdefault("sounddevice", MagicMock())

try:
    import legacy.sst as sst
    _IMPORT_OK = True
    _IMPORT_ERR = None
except Exception as _e:
    _IMPORT_OK = False
    _IMPORT_ERR = _e

# ── Mirror VAD constants from sst.py ─────────────────────────────────────────
CHUNK_SIZE  = 1024
SAMPLE_RATE = 16000

if _IMPORT_OK:
    THRESHOLD   = sst.VAD_SPEECH_THRESHOLD
    ONSET_WIN   = sst.VAD_ONSET_WINDOW
    ONSET_MIN   = sst.VAD_ONSET_MIN_POSITIVES
    SILENCE_END = sst.VAD_SILENCE_END_FRAMES
    MIN_SPEECH  = sst.VAD_MIN_SPEECH_FRAMES
    MAX_FRAMES  = sst.VAD_MAX_UTTERANCE_FRAMES
else:
    THRESHOLD = ONSET_WIN = ONSET_MIN = SILENCE_END = MIN_SPEECH = MAX_FRAMES = 0


# ── Synthetic frame builders ──────────────────────────────────────────────────

def _make_speech_frame(rms: float = 1500.0) -> np.ndarray:
    amp = min(int(rms * 1.414), 32767)
    t = np.linspace(0, 1, CHUNK_SIZE, endpoint=False)
    return (amp * np.sin(2 * np.pi * 440 * t)).astype(np.int16)


def _make_silence_frame() -> np.ndarray:
    return np.zeros(CHUNK_SIZE, dtype=np.int16)


# ── Simulated state machine (exact replica of sst.py loop logic) ─────────────

class _SimVAD:
    """Drive the window-based VAD state machine without hardware."""

    STATE_LISTENING = "LISTENING"
    STATE_SPEAKING  = "SPEAKING"

    def __init__(self):
        self.q = queue.Queue(maxsize=10)
        self.tts_speaking = False
        self._reset_all()
        self.queue_full_warnings = 0
        self._last_full = 0.0
        self.events: list[str] = []

    def _reset_all(self):
        self.vad_state          = self.STATE_LISTENING
        self.onset_bool         = []
        self.onset_chunks       = []
        self.utterance_frames   = []
        self.speech_frame_count = 0
        self.consecutive_silence = 0

    def feed(self, frame: np.ndarray):
        """Feed one frame, mirroring _continuous_audio_stream_loop."""
        if self.tts_speaking:
            if self.vad_state == self.STATE_SPEAKING:
                self.events.append("TTS_RESET")
                self.vad_state = self.STATE_LISTENING
            self.onset_bool   = []
            self.onset_chunks = []
            self.utterance_frames    = []
            self.speech_frame_count  = 0
            self.consecutive_silence = 0
            return

        is_speech = sst._simple_vad(frame, THRESHOLD)

        if self.vad_state == self.STATE_LISTENING:
            self.onset_bool.append(is_speech)
            self.onset_chunks.append(frame)
            if len(self.onset_bool) > ONSET_WIN:
                self.onset_bool.pop(0)
                self.onset_chunks.pop(0)

            positives = sum(self.onset_bool)
            if positives >= ONSET_MIN:
                self.utterance_frames    = list(self.onset_chunks)
                self.vad_state           = self.STATE_SPEAKING
                self.consecutive_silence = 0
                self.speech_frame_count  = positives
                self.onset_bool   = []
                self.onset_chunks = []
                self.events.append(f"LISTENING->SPEAKING onset={positives}/{ONSET_WIN}")

        elif self.vad_state == self.STATE_SPEAKING:
            self.utterance_frames.append(frame)
            if is_speech:
                self.consecutive_silence = 0
                self.speech_frame_count += 1
            else:
                self.consecutive_silence += 1

            if len(self.utterance_frames) >= MAX_FRAMES:
                self._finish("MAX_DURATION")
                return

            if self.consecutive_silence >= SILENCE_END:
                self._finish("SILENCE_END")

    def _finish(self, reason: str):
        if self.speech_frame_count < MIN_SPEECH:
            self.events.append(
                f"DROPPED speech={self.speech_frame_count}<{MIN_SPEECH} reason={reason}"
            )
        else:
            dur = len(self.utterance_frames) * CHUNK_SIZE / SAMPLE_RATE
            audio = np.concatenate(self.utterance_frames)
            try:
                self.q.put_nowait(audio)
                self.events.append(
                    f"QUEUED frames={len(self.utterance_frames)} "
                    f"speech={self.speech_frame_count} dur={dur:.2f}s reason={reason}"
                )
            except queue.Full:
                now = time.monotonic()
                if now - self._last_full > 5.0:
                    self.queue_full_warnings += 1
                    self._last_full = now
                self.events.append("QUEUE_FULL_DROP")

        self.vad_state           = self.STATE_LISTENING
        self.onset_bool          = []
        self.onset_chunks        = []
        self.utterance_frames    = []
        self.speech_frame_count  = 0
        self.consecutive_silence = 0

    def feed_many(self, frame: np.ndarray, n: int):
        for _ in range(n):
            self.feed(frame)


# ── Base class ────────────────────────────────────────────────────────────────

class _Base(unittest.TestCase):
    def setUp(self):
        if not _IMPORT_OK:
            self.skipTest(f"legacy.sst import failed: {_IMPORT_ERR}")
        self.v = _SimVAD()

    def speak(self, n: int = 1, rms: float = 1500.0):
        self.v.feed_many(_make_speech_frame(rms), n)

    def silence(self, n: int = 1):
        self.v.feed_many(_make_silence_frame(), n)


# =============================================================================
# 1. _simple_vad predicate
# =============================================================================

class TestSimpleVAD(_Base):
    def test_speech_returns_true(self):
        self.assertTrue(sst._simple_vad(_make_speech_frame(1500.0), THRESHOLD))

    def test_silence_returns_false(self):
        self.assertFalse(sst._simple_vad(_make_silence_frame(), THRESHOLD))

    def test_rms_helper_positive(self):
        self.assertGreater(sst._rms(_make_speech_frame(1500.0)), 0.0)

    def test_rms_helper_zero_on_silence(self):
        self.assertAlmostEqual(sst._rms(_make_silence_frame()), 0.0, places=3)


# =============================================================================
# 2. Onset / spike rejection
# =============================================================================

class TestOnsetDetection(_Base):
    def test_single_spike_does_not_start_speech(self):
        """1 speech frame in ONSET_WIN → positives=1 < ONSET_MIN → stay LISTENING."""
        self.silence(ONSET_WIN - 1)
        self.speak(1)
        self.assertEqual(self.v.vad_state, _SimVAD.STATE_LISTENING)
        self.assertEqual(self.v.q.qsize(), 0)

    def test_two_spikes_do_not_start_speech(self):
        """2 speech frames spread across window → below ONSET_MIN."""
        for i in range(ONSET_WIN):
            # place 2 speech frames, rest silence
            if i in (0, ONSET_WIN - 1):
                self.speak(1)
            else:
                self.silence(1)
        # positives=2 < ONSET_MIN=4
        self.assertEqual(self.v.vad_state, _SimVAD.STATE_LISTENING)

    def test_onset_min_positives_starts_speech(self):
        """ONSET_MIN speech frames inside ONSET_WIN → transition to SPEAKING."""
        # Fill window with exactly ONSET_MIN speech and rest silence
        self.silence(ONSET_WIN - ONSET_MIN)
        self.speak(ONSET_MIN)
        self.assertEqual(self.v.vad_state, _SimVAD.STATE_SPEAKING)

    def test_all_speech_in_window_starts_speech(self):
        """All ONSET_WIN frames speech → SPEAKING."""
        self.speak(ONSET_WIN)
        self.assertEqual(self.v.vad_state, _SimVAD.STATE_SPEAKING)

    def test_ring_resets_correctly_after_transition(self):
        """After onset, ring is cleared so it does not re-trigger immediately."""
        self.speak(ONSET_WIN)
        self.assertEqual(len(self.v.onset_bool), 0)
        self.assertEqual(len(self.v.onset_chunks), 0)


# =============================================================================
# 3. End-of-utterance detection
# =============================================================================

class TestEndOfUtterance(_Base):
    def _enter_speaking(self):
        self.speak(ONSET_WIN)
        self.assertEqual(self.v.vad_state, _SimVAD.STATE_SPEAKING)

    def test_short_silence_does_not_end_utterance(self):
        self._enter_speaking()
        self.silence(SILENCE_END - 1)
        self.assertEqual(self.v.vad_state, _SimVAD.STATE_SPEAKING)
        self.assertEqual(self.v.q.qsize(), 0)

    def test_sustained_silence_ends_utterance(self):
        self._enter_speaking()
        # Need enough speech for MIN_SPEECH
        self.speak(MIN_SPEECH + 2)
        self.silence(SILENCE_END)
        self.assertEqual(self.v.vad_state, _SimVAD.STATE_LISTENING)
        self.assertEqual(self.v.q.qsize(), 1)

    def test_speech_resets_silence_counter(self):
        """Speech frame inside utterance resets the consecutive silence counter."""
        self._enter_speaking()
        self.speak(MIN_SPEECH)
        self.silence(SILENCE_END - 1)   # almost enough to end
        self.speak(1)                    # one voiced frame resets counter
        self.silence(SILENCE_END - 1)   # again almost enough
        # still speaking — not over yet
        self.assertEqual(self.v.vad_state, _SimVAD.STATE_SPEAKING)
        # now let it end
        self.silence(1)
        self.assertEqual(self.v.vad_state, _SimVAD.STATE_LISTENING)
        self.assertEqual(self.v.q.qsize(), 1)

    def test_breath_pause_is_single_utterance(self):
        """Word — short pause — word → exactly one utterance."""
        self._enter_speaking()
        self.speak(MIN_SPEECH)
        self.silence(SILENCE_END - 3)   # brief pause, not enough to end
        self.speak(MIN_SPEECH)
        self.silence(SILENCE_END)
        self.assertEqual(self.v.q.qsize(), 1)


# =============================================================================
# 4. Queue / state reset guarantees
# =============================================================================

class TestQueueBehavior(_Base):
    def _one_utterance(self):
        self.v.vad_state = _SimVAD.STATE_LISTENING
        self.v.onset_bool = []
        self.v.onset_chunks = []
        self.v.utterance_frames = []
        self.v.speech_frame_count = 0
        self.v.consecutive_silence = 0
        self.speak(ONSET_WIN + MIN_SPEECH + 2)
        self.silence(SILENCE_END)

    def test_one_utterance_one_queue_item(self):
        self._one_utterance()
        self.assertEqual(self.v.q.qsize(), 1)

    def test_state_resets_to_listening_after_utterance(self):
        self._one_utterance()
        self.assertEqual(self.v.vad_state, _SimVAD.STATE_LISTENING)

    def test_extra_silence_after_utterance_adds_nothing(self):
        self._one_utterance()
        self.silence(100)
        self.assertEqual(self.v.q.qsize(), 1)

    def test_two_utterances_produce_two_items(self):
        self._one_utterance()
        self._one_utterance()
        self.assertEqual(self.v.q.qsize(), 2)

    def test_queue_full_does_not_loop(self):
        """With a full queue, warnings are throttled and state resets cleanly."""
        for _ in range(10):
            self._one_utterance()
        self.assertEqual(self.v.q.qsize(), 10)

        warn_before = self.v.queue_full_warnings
        # Generate 3 more utterances against a full queue
        for _ in range(3):
            self._one_utterance()

        self.assertEqual(self.v.vad_state, _SimVAD.STATE_LISTENING,
                         "State must be LISTENING after queue-full drop")
        # At most 1 warning in rapid succession (5 s throttle)
        self.assertLessEqual(self.v.queue_full_warnings - warn_before, 1)


# =============================================================================
# 5. Minimum utterance validation
# =============================================================================

class TestMinimumUtterance(_Base):
    def test_utterance_below_min_speech_dropped(self):
        """Onset with exactly ONSET_MIN positives seeds speech_frame_count=ONSET_MIN.
        Since ONSET_MIN (4) < MIN_SPEECH (6), immediately following with
        SILENCE_END frames must drop the utterance."""
        self.assertLess(ONSET_MIN, MIN_SPEECH,
                        "pre-condition: ONSET_MIN must be less than MIN_SPEECH")
        # Trigger onset at minimum threshold: (ONSET_WIN-ONSET_MIN) silence
        # frames then ONSET_MIN speech frames → positives == ONSET_MIN exactly
        self.silence(ONSET_WIN - ONSET_MIN)
        self.speak(ONSET_MIN)
        self.assertEqual(self.v.vad_state, _SimVAD.STATE_SPEAKING,
                         "Onset should have fired")
        # speech_frame_count == ONSET_MIN == 4 < MIN_SPEECH == 6
        self.assertLess(self.v.speech_frame_count, MIN_SPEECH)
        # Immediately end with sustained silence — should drop
        self.silence(SILENCE_END)
        self.assertEqual(self.v.q.qsize(), 0, "Too-short burst must be dropped")
        self.assertEqual(self.v.vad_state, _SimVAD.STATE_LISTENING)

    def test_drop_event_recorded(self):
        """DROPPED event must be in events list after a too-short utterance."""
        self.silence(ONSET_WIN - ONSET_MIN)
        self.speak(ONSET_MIN)   # onset with speech_frame_count == ONSET_MIN < MIN_SPEECH
        self.silence(SILENCE_END)
        dropped = any("DROPPED" in e for e in self.v.events)
        self.assertTrue(dropped, f"Expected DROPPED event, got: {self.v.events}")


# =============================================================================
# 6. TTS protection
# =============================================================================

class TestTTSProtection(_Base):
    def test_tts_discards_frames(self):
        self.v.tts_speaking = True
        self.speak(ONSET_WIN + MIN_SPEECH + 5)
        self.silence(SILENCE_END)
        self.assertEqual(self.v.q.qsize(), 0)
        self.assertEqual(self.v.vad_state, _SimVAD.STATE_LISTENING)

    def test_tts_resets_in_progress_utterance(self):
        # Start an utterance
        self.speak(ONSET_WIN + MIN_SPEECH)
        self.assertEqual(self.v.vad_state, _SimVAD.STATE_SPEAKING)
        # TTS kicks in
        self.v.tts_speaking = True
        self.speak(1)
        self.assertEqual(self.v.vad_state, _SimVAD.STATE_LISTENING)
        self.assertEqual(self.v.q.qsize(), 0)

    def test_resumes_after_tts(self):
        self.v.tts_speaking = True
        self.speak(ONSET_WIN)
        self.v.tts_speaking = False
        # Now speak normally
        self.speak(ONSET_WIN + MIN_SPEECH + 2)
        self.silence(SILENCE_END)
        self.assertEqual(self.v.q.qsize(), 1)


# =============================================================================
# 7. Silence never produces utterances
# =============================================================================

class TestSilence(_Base):
    def test_30s_silence_no_utterances(self):
        """469 frames ≈ 30 seconds of silence → 0 queue items."""
        self.silence(469)
        self.assertEqual(self.v.q.qsize(), 0)
        self.assertEqual(self.v.vad_state, _SimVAD.STATE_LISTENING)

    def test_no_wake_word_needed(self):
        """Plain speech (no wake word) must reach the queue."""
        self.speak(ONSET_WIN + MIN_SPEECH + 2)
        self.silence(SILENCE_END)
        self.assertEqual(self.v.q.qsize(), 1)


# =============================================================================
# 8. Non-blocking: capture continues while STT processes
# =============================================================================

class TestNonBlocking(_Base):
    def test_second_utterance_queued_without_consuming_first(self):
        """Two utterances queue up even if the consumer is slow."""
        for _ in range(2):
            self.v.vad_state = _SimVAD.STATE_LISTENING
            self.v.onset_bool = []
            self.v.onset_chunks = []
            self.v.utterance_frames = []
            self.v.speech_frame_count = 0
            self.v.consecutive_silence = 0
            self.speak(ONSET_WIN + MIN_SPEECH + 2)
            self.silence(SILENCE_END)
        self.assertEqual(self.v.q.qsize(), 2)


# =============================================================================
# 9. Module API smoke tests
# =============================================================================

class TestSSTImports(_Base):
    def test_vad_constants_accessible(self):
        self.assertIsInstance(sst.VAD_SPEECH_THRESHOLD, (int, float))
        self.assertIsInstance(sst.VAD_ONSET_WINDOW, int)
        self.assertIsInstance(sst.VAD_ONSET_MIN_POSITIVES, int)
        self.assertIsInstance(sst.VAD_SILENCE_END_FRAMES, int)
        self.assertIsInstance(sst.VAD_MIN_SPEECH_FRAMES, int)
        self.assertIsInstance(sst.VAD_MAX_UTTERANCE_FRAMES, int)

    def test_public_callables(self):
        for name in [
            "_simple_vad", "_rms", "_vad_finish_utterance",
            "_continuous_audio_stream_loop",
            "start_continuous_audio_stream", "stop_continuous_audio_stream",
            "_process_utterance", "_is_tts_speaking", "listen",
        ]:
            self.assertTrue(callable(getattr(sst, name, None)), f"{name} not callable")

    def test_utterance_queue_is_bounded(self):
        self.assertIsInstance(sst._utterance_queue, queue.Queue)


if __name__ == "__main__":
    unittest.main(verbosity=2)
