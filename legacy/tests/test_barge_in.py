"""
Tests for Conversational Barge-In / Speech Interruption Architecture.

Validates:
1. Instant TTS interruption & hardware purge state transitions.
2. EchoGuard distinguishing assistant audio from user speech.
3. VAD barge-in triggering during TTS playback.
4. Context preservation: corrections ("No, Guntur"), parameter changes,
   cancellations ("Don't send it"), and pauses ("Wait").
"""

import unittest
import time
import numpy as np

# 1. Test EchoGuard separation of Echo vs User Voice
class TestEchoGuardBargeIn(unittest.TestCase):
    def test_echoguard_distinguishes_echo_from_user(self):
        from skills.audio_management.echo_guard import EchoGuard
        eg = EchoGuard()
        sr = 16000
        duration = 0.1
        t = np.linspace(0, duration, int(sr * duration), endpoint=False)
        
        # Assistant tone at 350 Hz
        tts_pcm = (np.sin(2 * np.pi * 350 * t) * 12000).astype(np.int16)
        now = time.monotonic()
        eg.note_output(tts_pcm, sr, 0.4, when=now)

        # Microphone receives the same tone (echo)
        is_user = eg.is_user_speech(tts_pcm, sr, 0.4, when=now)
        self.assertFalse(is_user, "EchoGuard should identify assistant playback as echo, NOT user speech")

        # Microphone receives user voice (different frequency/formants e.g. 1800 Hz)
        user_pcm = (np.sin(2 * np.pi * 1800 * t) * 14000).astype(np.int16)
        is_user_real = eg.is_user_speech(user_pcm, sr, 0.45, when=now)
        self.assertTrue(is_user_real, "EchoGuard should identify different acoustic content as genuine user speech")


# 2. Test Instant TTS Interruption & Coordinator Flush
class TestTTSInterruption(unittest.TestCase):
    def test_tts_stop_speaking_sets_interrupted(self):
        from legacy.tts import stop_speaking, is_interrupted, get_last_interrupted_speech, _tts_interrupted, _tts_active
        
        # Simulate active TTS
        _tts_active.set()
        stop_speaking(interrupted=True)
        
        self.assertTrue(is_interrupted(), "stop_speaking(interrupted=True) should set interrupted event")
        self.assertFalse(_tts_active.is_set(), "_tts_active must be cleared immediately upon interruption")

    def test_coordinator_interrupt_speech(self):
        from extensions.system.tts_coordinator import get_tts_coordinator, interrupt_speech
        from legacy.tts import speak as legacy_speak
        coord = get_tts_coordinator()
        coord.initialize(legacy_speak)
        
        # Enqueue dummy request
        coord.speak("This is a long test sentence that would normally play.")
        
        # Interrupt
        interrupt_speech()
        self.assertTrue(coord.queue.empty(), "Coordinator queue must be emptied immediately upon interruption")

    def test_vad_bargein_trigger_stops_tts(self):
        from legacy.tts import _tts_active, stop_speaking, is_interrupted
        from legacy.sst import _is_tts_speaking
        
        # Simulate assistant speaking
        _tts_active.set()
        self.assertTrue(_is_tts_speaking())
        
        # Simulate barge-in trigger (e.g. from VAD when user speech is detected)
        from extensions.system.tts_coordinator import interrupt_speech
        interrupt_speech()
        
        # Verify TTS is silenced
        self.assertFalse(_is_tts_speaking(), "TTS must no longer be speaking after barge-in")
        self.assertTrue(is_interrupted(), "Interruption flag must be set")



# 3. Test Contextual Interruption Understanding in DialogueStateManager & Brain
class TestContextualInterruption(unittest.TestCase):
    def setUp(self):
        from extensions.dialogue_state_manager import get_dialogue_manager
        self.user_id = f"test_bargein_{int(time.time() * 1000)}"
        self.dm = get_dialogue_manager(self.user_id)

    def test_interruption_correction_weather(self):
        from core.brain import brain_process
        
        # Turn 1: Weather query
        r1 = brain_process("what is the weather in Hyderabad", user_id=self.user_id)
        self.assertEqual(r1.get("intent"), "WEATHER_QUERY")
        
        # Turn 2: User barges in: "No, I meant Guntur"
        r2 = brain_process("No, I meant Guntur", user_id=self.user_id)
        self.assertEqual(r2.get("intent"), "WEATHER_QUERY")
        self.assertIn("Guntur", str(r2.get("response")), "Response should be for Guntur")

    def test_interruption_short_pause(self):
        from core.brain import brain_process
        
        # User says "Wait..."
        r = brain_process("Wait...", user_id=self.user_id)
        self.assertEqual(r.get("goal_status"), "WAITING_FOR_USER")
        self.assertIn("paused", r.get("response").lower())

    def test_interruption_cancellation(self):
        from core.brain import brain_process
        
        # User says "Don't send it"
        r = brain_process("Don't send it", user_id=self.user_id)
        self.assertEqual(r.get("goal_status"), "CANCELLED")
        self.assertIn("cancelled", r.get("response").lower())

    def test_unrelated_interruption_command(self):
        from core.brain import brain_process
        
        # User says "what time is it"
        r = brain_process("what time is it", user_id=self.user_id)
        self.assertEqual(r.get("intent"), "TIME_QUERY")


if __name__ == "__main__":
    unittest.main()
