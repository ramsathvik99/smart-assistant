"""
Test Suite for Core Audio & Interaction Capabilities.
Verifies audio device selection, EchoGuard separation, PushToTalk, ConfirmationGate,
and optional WakeWord lifecycle.
"""

import time
import unittest
import sys
import numpy as np
from unittest.mock import patch, MagicMock

from skills.audio_management.audio_devices import list_devices, resolve, DEFAULT_LABEL
from skills.audio_management.echo_guard import EchoGuard, band_energies
from skills.audio_management.hotkey import PushToTalk, chord_label, is_ptt_enabled, set_ptt_enabled
from skills.audio_management.confirmation_gate import ConfirmationGate, get_confirmation_gate


class TestAudioInteractionIntegration(unittest.TestCase):

    # ── 1. Audio Device Selection ────────────────────────────────────────────
    def test_01_audio_device_listing_and_name_resolution(self):
        """Verify device listing and name-based resolution."""
        sample_devices = [
            {"name": "Realtek Microphone", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 0, "default_samplerate": 16000},
            {"name": "Realtek Speakers", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 48000},
        ]
        sample_hostapis = [{"name": "MME"}]

        mock_sd = MagicMock()
        mock_sd.query_devices.return_value = sample_devices
        mock_sd.query_hostapis.return_value = sample_hostapis
        mock_sd.default.device = [0, 1]

        with patch.dict("sys.modules", {"sounddevice": mock_sd}), \
             patch("skills.audio_management.audio_devices._usable", return_value=True), \
             patch("skills.audio_management.audio_devices._transport_works", return_value=True):

            # Test listing
            mics = list_devices(kind="input", refresh=True)
            self.assertIn("Realtek Microphone", mics)

            # Test resolving default vs specific name
            dev_idx = resolve("", kind="input")
            self.assertIsNone(dev_idx, "Empty string should resolve to None (system default)")

            dev_idx = resolve("Realtek Microphone", kind="input")
            self.assertEqual(dev_idx, 0)



    # ── 2. EchoGuard & DSP Timbre Subtraction ─────────────────────────────────
    def test_02_echoguard_band_energies_and_separation(self):
        """Verify EchoGuard separates echo from authentic user speech."""
        eg = EchoGuard()
        sr = 16000
        duration = 0.1
        t = np.linspace(0, duration, int(sr * duration), endpoint=False)

        # Assistant tone at 350 Hz
        tts_pcm = (np.sin(2 * np.pi * 350 * t) * 12000).astype(np.int16)
        now = time.monotonic()
        eg.note_output(tts_pcm, sr, 0.4, when=now)

        # Microphone receives the same tone (echo)
        is_user_echo = eg.is_user_speech(tts_pcm, sr, 0.4, when=now)
        self.assertFalse(is_user_echo, "EchoGuard should identify assistant playback as echo, NOT user speech")

        # Microphone receives user voice (different frequency/formants e.g. 1800 Hz)
        user_pcm = (np.sin(2 * np.pi * 1800 * t) * 14000).astype(np.int16)
        is_user_real = eg.is_user_speech(user_pcm, sr, 0.45, when=now)
        self.assertTrue(is_user_real, "EchoGuard should identify different acoustic content as genuine user speech")


    # ── 3. PushToTalk & Hotkey Control ───────────────────────────────────────
    def test_03_push_to_talk_state_and_non_interference(self):
        """Verify PushToTalk state transitions without breaking continuous listening."""
        events = []
        ptt = PushToTalk(on_change=lambda held: events.append(held))
        
        self.assertEqual(ptt.label, "Ctrl+Space")
        self.assertFalse(ptt.held)

        # Verify global toggle state
        set_ptt_enabled(False)
        self.assertFalse(is_ptt_enabled())
        set_ptt_enabled(True)
        self.assertTrue(is_ptt_enabled())
        set_ptt_enabled(False)

    # ── 4. Unforgeable Confirmation Gate ─────────────────────────────────────
    def test_04_confirmation_gate_lifecycle_and_user_isolation(self):
        """Verify ConfirmationGate requires user confirmation and prevents unauthorized execution."""
        gate = ConfirmationGate()
        executed_actions = []

        def dangerous_action():
            executed_actions.append("deleted")
            return "File deleted"

        # 1. Request confirmation
        req = gate.request_confirmation(
            key="del_1",
            title="Delete Database",
            detail="Permanent deletion of records",
            action_callable=dangerous_action,
            user_id=1,
            timeout_seconds=2.0
        )
        self.assertEqual(req["status"], "confirmation_required")
        self.assertEqual(len(executed_actions), 0, "Dangerous action must not run before confirmation")

        # 2. Reject by user ID mismatch
        unauth_res = gate.resolve(key="del_1", accepted=True, user_id=2)
        self.assertFalse(unauth_res["success"])
        self.assertEqual(unauth_res["status"], "unauthorized")
        self.assertEqual(len(executed_actions), 0)

        # 3. User cancels
        gate.request_confirmation("del_cancel", "Delete File", "Detail", dangerous_action, user_id=1)
        cancel_res = gate.resolve("del_cancel", accepted=False, user_id=1)
        self.assertFalse(cancel_res["success"])
        self.assertEqual(cancel_res["status"], "cancelled")
        self.assertEqual(len(executed_actions), 0)

        # 4. User confirms with correct user ID
        gate.request_confirmation("del_confirm", "Delete Temp", "Detail", dangerous_action, user_id=1)
        confirm_res = gate.resolve("del_confirm", accepted=True, user_id=1)
        self.assertTrue(confirm_res["success"])
        self.assertEqual(confirm_res["status"], "executed")
        self.assertEqual(len(executed_actions), 1)

    def test_05_confirmation_gate_expiration(self):
        """Verify expired confirmation is abandoned."""
        gate = ConfirmationGate()
        run_count = []
        gate.request_confirmation(
            key="exp_1",
            title="Reboot",
            detail="Detail",
            action_callable=lambda: run_count.append(1),
            user_id=1,
            timeout_seconds=0.05
        )
        time.sleep(0.08)
        res = gate.resolve("exp_1", accepted=True, user_id=1)
        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "expired")
        self.assertEqual(len(run_count), 0)

    # ── 5. Continuous Audio / No Wake-Word Subsystem ─────────────────────────
    def test_06_continuous_audio_no_wake_word_subsystem(self):
        """Verify wake-word module is removed and continuous audio pipeline is clean."""
        # 1. wake_word module should not exist in skills.audio_management
        with self.assertRaises(ImportError):
            import skills.audio_management.wake_word  # noqa: F401

        # 2. Package exports do not contain wake-word symbols
        import skills.audio_management as audio_pkg
        self.assertFalse(hasattr(audio_pkg, "is_wakeword_installed"))
        self.assertFalse(hasattr(audio_pkg, "is_wakeword_ready"))
        self.assertFalse(hasattr(audio_pkg, "setup_wakeword"))

        # 3. EchoGuard and Audio Devices operate continuously without wake-word gating
        eg = EchoGuard()
        self.assertTrue(eg.calibrated)
        # Empty input is not user speech
        self.assertFalse(eg.is_user_speech(np.zeros(160, dtype=np.float32), sr=16000, level=0.0))


if __name__ == "__main__":
    unittest.main()

