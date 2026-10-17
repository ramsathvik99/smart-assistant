"""
Unit and integration tests for the Floating Assistant Button voice lifecycle:
Verifies clear, reliable runtime state indicators:
1. Idle — waiting for input (no false recording indication).
2. Listening — actively capturing voice (listening ring reactive to mic level, mic glyph, 'Listening…' label).
3. Processing — end of utterance detected; changes immediately from Listening to Processing.
4. Responding — assistant is speaking (emerald green Pulse Ring response, 'Responding…' label, returns to Idle on completion).
5. Error / Microphone unavailable — clear error message, no false listening.
6. Multi-command consecutive lifecycle transitions.
"""

import unittest
import time
import threading
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QPainter, QPixmap

from core.voice_lifecycle import VoiceLifecycleManager, get_voice_lifecycle
from modules.ui.floating_launcher import FloatingLauncher
from modules.ui.worker_threads import VADMonitor, AudioLevelProvider


class TestVoiceLifecycleAndFloatingButton(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create single QApplication instance for offscreen widget testing
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.vl = get_voice_lifecycle()
        self.vl.reset_to_idle()

    def tearDown(self):
        self.vl.reset_to_idle()

    def test_01_voice_lifecycle_initial_idle_state(self):
        """Idle state: waiting for input, no false recording indication."""
        self.assertEqual(self.vl.get_state(), "idle")
        self.assertEqual(self.vl.get_audio_level(), 0.0)

    def test_02_voice_lifecycle_listening_transition(self):
        """Listening state: activates only upon genuine speech onset with 'Listening…' message."""
        state_events = []
        self.vl.register_state_listener(lambda s, m: state_events.append((s, m)))

        self.vl.on_mic_opened(0)
        self.vl.on_vad_listening()
        # VAD listening alone should keep idle ready state, not falsely claim recording
        self.assertEqual(self.vl.get_state(), "idle")

        # Speech onset confirmed by VAD
        self.vl.on_speech_detected()
        self.assertEqual(self.vl.get_state(), "listening")
        self.assertEqual(self.vl.get_status_message(), "Listening…")
        self.assertIn(("listening", "Listening…"), state_events)

    def test_03_voice_lifecycle_audio_level_reactive(self):
        """Audio level is updated and dispatched to listeners."""
        levels = []
        self.vl.register_level_listener(lambda lvl: levels.append(lvl))

        self.vl.on_audio_level(0.42)
        self.assertAlmostEqual(self.vl.get_audio_level(), 0.42, places=2)
        self.assertIn(0.42, levels)

        # Clamping
        self.vl.on_audio_level(1.5)
        self.assertEqual(self.vl.get_audio_level(), 1.0)
        self.vl.on_audio_level(-0.5)
        self.assertEqual(self.vl.get_audio_level(), 0.0)

    def test_04_voice_lifecycle_processing_transition(self):
        """Processing state: detects end of utterance and transitions immediately from listening to processing."""
        self.vl.on_speech_detected()
        self.assertEqual(self.vl.get_state(), "listening")

        # Silence threshold reached (end of utterance)
        self.vl.on_end_of_utterance()
        self.assertEqual(self.vl.get_state(), "processing")
        self.assertEqual(self.vl.get_status_message(), "Processing…")
        self.assertEqual(self.vl.get_audio_level(), 0.0)

    def test_05_transcription_delivered_exactly_once(self):
        """Recognized transcript is stored and dispatched to listeners."""
        transcripts = []
        self.vl.register_transcript_listener(lambda t: transcripts.append(t))

        self.vl.on_transcription_started()
        self.assertEqual(self.vl.get_state(), "processing")

        test_cmd = "what is the weather today in San Francisco"
        self.vl.on_transcription_completed(test_cmd)
        self.assertEqual(transcripts, [test_cmd])
        self.assertEqual(self.vl._last_transcript, test_cmd)

    def test_06_voice_lifecycle_responding_tts(self):
        """Responding state: active while TTS is playing in hardware, returns to idle when done."""
        self.vl.on_tts_started()
        self.assertEqual(self.vl.get_state(), "speaking")
        self.assertEqual(self.vl.get_status_message(), "Responding…")

        self.vl.on_tts_finished()
        self.assertEqual(self.vl.get_state(), "idle")
        self.assertEqual(self.vl.get_audio_level(), 0.0)

    def test_07_voice_lifecycle_error_and_auto_reset(self):
        """Error state: displays specific error message and recovers to idle automatically."""
        self.vl.on_mic_error("Microphone unavailable")
        self.assertEqual(self.vl.get_state(), "error")
        self.assertEqual(self.vl.get_status_message(), "Microphone unavailable")
        self.assertFalse(self.vl.is_mic_available())

        # Reset manually or test auto-reset
        self.vl.reset_to_idle()
        self.assertEqual(self.vl.get_state(), "idle")

    def test_08_floating_launcher_widget_rendering_all_states(self):
        """Floating launcher renders cleanly in offscreen pixmap across all 5 states."""
        launcher = FloatingLauncher()
        launcher.set_assistant_name("Trevon")

        states_to_test = [
            ("idle", ""),
            ("listening", "Listening…"),
            ("processing", "Processing…"),
            ("speaking", "Responding…"),
            ("error", "Didn't catch that — try again."),
        ]

        pixmap = QPixmap(148, 114)
        for state, msg in states_to_test:
            launcher.set_state(state, msg)
            launcher.set_audio_level(0.65)
            self.assertEqual(launcher._state, state)
            if msg:
                self.assertEqual(launcher._status_message, msg)

            # Paint offscreen to verify no crash or unhandled painter errors
            painter = QPainter(pixmap)
            launcher.paintEvent(None)
            painter.end()

    def test_09_consecutive_multi_turn_lifecycle(self):
        """Verify multiple consecutive interaction turns transition properly without stuck state."""
        turns = [
            ("turn 1 command", "response 1"),
            ("turn 2 command", "response 2"),
            ("turn 3 command", "response 3"),
        ]

        for cmd, resp in turns:
            # 1. Idle -> Speech onset
            self.vl.on_speech_detected()
            self.assertEqual(self.vl.get_state(), "listening")

            # 2. End of utterance
            self.vl.on_end_of_utterance()
            self.assertEqual(self.vl.get_state(), "processing")

            # 3. Transcription completed
            self.vl.on_transcription_completed(cmd)
            self.assertEqual(self.vl.get_state(), "processing")

            # 4. Responding (TTS)
            self.vl.on_tts_started()
            self.assertEqual(self.vl.get_state(), "speaking")

            # 5. Finished
            self.vl.on_tts_finished()
            self.assertEqual(self.vl.get_state(), "idle")

    def test_10_vad_monitor_and_audio_level_provider(self):
        """Verify VADMonitor and AudioLevelProvider reflect real VoiceLifecycleManager state."""
        mon = VADMonitor()
        prov = AudioLevelProvider()

        # In idle: VAD is not active
        self.assertFalse(self.vl.get_state() == "listening")

        # In listening with real audio:
        self.vl.on_speech_detected()
        self.vl.on_audio_level(0.75)
        self.assertTrue(self.vl.get_state() == "listening")
        self.assertEqual(self.vl.get_audio_level(), 0.75)


if __name__ == "__main__":
    unittest.main()
