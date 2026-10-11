"""
Test Suite for Floating Pulse Ring Quick Actions & Assistant Control Center Integration.
Validates:
1. Left-click Pulse Ring preserves single-click window toggle/focus.
2. Double-click opens compact Quick Actions HUD anchored to the Pulse Ring with multimedia & video actions.
3. Right-click opens structured Assistant Control Center anchored to the Pulse Ring with runtime, media, and session management.
4. Independent operation: Opening one menu automatically hides the other.
5. Outside click dismisses either menu without cancelling speech, audio, or goals.
6. Action event routing for all quick actions and control center items.
7. Production Reachability: Device Pairing, Devices, File Transfer with strict user isolation.
8. Strict absence of wake-word and avatar/hologram subsystems.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPoint, QEvent

# Ensure QApplication exists for headless test runs
_app = QApplication.instance() or QApplication(sys.argv)

from modules.ui.floating_launcher import FloatingLauncher, QuickActionsPanel, AssistantControlCenterPanel
from skills.device_management.device_controller import DeviceController
from skills.device_management.device_pairing import DevicePairingManager
from skills.device_management.file_transfer import save_user_uploaded_file, list_user_files


class TestQuickActionsIntegration(unittest.TestCase):

    def setUp(self):
        self.launcher = FloatingLauncher()
        self.launcher.set_user_context("TestUser", "Trevon")

    def tearDown(self):
        self.launcher.close()

    # ── 1. Left-Click Pulse Ring Behavior ─────────────────────────────────────
    def test_01_left_click_preserves_single_click_behavior(self):
        received = []
        self.launcher.single_clicked.connect(lambda: received.append("single"))
        self.launcher._on_single_click_timeout()
        self.assertIn("single", received)

    # ── 2. Double-Click Opens Compact Quick Actions HUD ───────────────────────
    def test_02_double_click_opens_quick_actions_hud(self):
        received = []
        self.launcher.double_clicked.connect(lambda: received.append("double"))
        self.launcher._on_double_click()

        self.assertIn("double", received)
        self.assertTrue(self.launcher._quick_hud.isVisible())
        self.assertFalse(self.launcher._control_center.isVisible())

        # Verify action buttons exist in Quick Actions HUD
        from PyQt6.QtWidgets import QPushButton
        btn_labels = [b.text() for b in self.launcher._quick_hud.findChildren(QPushButton)]
        self.assertTrue(any("Voice" in lbl for lbl in btn_labels))
        self.assertTrue(any("Video" in lbl for lbl in btn_labels))
        self.assertTrue(any("Summarize" in lbl for lbl in btn_labels))
        self.assertTrue(any("Capture" in lbl for lbl in btn_labels))
        self.assertTrue(any("Send File" in lbl for lbl in btn_labels))
        self.assertTrue(any("Devices" in lbl for lbl in btn_labels))
        self.assertTrue(any("Pair Device" in lbl for lbl in btn_labels))
        self.assertTrue(any("Memory" in lbl for lbl in btn_labels))
        self.assertTrue(any("Status" in lbl for lbl in btn_labels))

    # ── 3. Right-Click Opens Structured Assistant Control Center ──────────────
    def test_03_right_click_opens_assistant_control_center(self):
        mock_event = MagicMock()
        self.launcher.contextMenuEvent(mock_event)

        self.assertTrue(self.launcher._control_center.isVisible())
        self.assertFalse(self.launcher._quick_hud.isVisible())

        # Verify Control Center sections and buttons
        from PyQt6.QtWidgets import QPushButton
        cc_text = " ".join([b.text() for b in self.launcher._control_center.findChildren(QPushButton)])
        self.assertIn("Dashboard", cc_text)
        self.assertIn("Restart", cc_text)
        self.assertIn("Exit", cc_text)
        self.assertIn("Listening", cc_text)
        self.assertIn("Play / Pause", cc_text)
        self.assertIn("Next Track", cc_text)
        self.assertIn("Silence", cc_text)
        self.assertIn("Microphone", cc_text)
        self.assertIn("Sign Out", cc_text)
        self.assertIn("Preferences", cc_text)
        self.assertIn("Telemetry", cc_text)

    # ── 4. Independent Operation: Switching Closes Opposite Menu ─────────────
    def test_04_menus_operate_independently_and_exclusively(self):
        # Open Quick HUD via Double-Click
        self.launcher._on_double_click()
        self.assertTrue(self.launcher._quick_hud.isVisible())
        self.assertFalse(self.launcher._control_center.isVisible())

        # Open Control Center via Right-Click -> Quick HUD should close
        mock_event = MagicMock()
        self.launcher.contextMenuEvent(mock_event)
        self.assertTrue(self.launcher._control_center.isVisible())
        self.assertFalse(self.launcher._quick_hud.isVisible())

        # Re-trigger Double-Click -> Control Center should close
        self.launcher._on_double_click()
        self.assertTrue(self.launcher._quick_hud.isVisible())
        self.assertFalse(self.launcher._control_center.isVisible())

    # ── 5. Outside-Click Dismissal ─────────────────────────────────────────────
    def test_05_outside_click_dismisses_active_panel(self):
        # Test Quick HUD dismissal
        self.launcher._quick_hud.show()
        self.assertTrue(self.launcher._quick_hud.isVisible())
        outside_event = MagicMock()
        outside_event.type.return_value = QEvent.Type.MouseButtonPress
        outside_event.globalPosition().toPoint.return_value = QPoint(-500, -500)
        self.launcher._quick_hud.eventFilter(None, outside_event)
        self.assertFalse(self.launcher._quick_hud.isVisible())

        # Test Control Center dismissal
        self.launcher._control_center.show()
        self.assertTrue(self.launcher._control_center.isVisible())
        self.launcher._control_center.eventFilter(None, outside_event)
        self.assertFalse(self.launcher._control_center.isVisible())

    # ── 6. Action Event Routing ────────────────────────────────────────────────
    def test_06_action_event_emission(self):
        triggered_actions = []
        self.launcher.action_requested.connect(lambda a: triggered_actions.append(a))

        # Test triggering actions from Quick HUD
        for act in ["talk", "play_video", "summarize_video", "capture_screen", "send_file", "devices", "pair_device", "system_status", "memory"]:
            self.launcher._quick_hud._on_action(act)
            self.assertIn(act, triggered_actions)

        # Test triggering actions from Control Center
        for act in ["dashboard", "restart", "quit", "toggle_listening", "media_play_pause", "media_next", "mute_tts", "reset_mic", "logout", "settings", "telemetry", "web_dashboard"]:
            self.launcher._control_center._on_action(act)
            self.assertIn(act, triggered_actions)

    # ── 7. Production Reachability: Device Pairing & Devices ───────────────────
    def test_07_pair_device_and_devices_reachability(self):
        controller = DeviceController()
        user_id = 777

        # Pair Device
        pair_res = controller.pair_device(user_id=user_id)
        self.assertTrue(pair_res["success"])
        self.assertEqual(len(pair_res["code"]), 6)
        self.assertTrue(pair_res["code"].isdigit())
        self.assertIn("qr_payload", pair_res)

        # List Devices
        dev_res = controller.list_devices(user_id=user_id)
        self.assertTrue(dev_res["success"])
        self.assertEqual(dev_res["count"], 0)

    # ── 8. Production Reachability: User-Isolated File Transfer ────────────────
    def test_08_send_file_reachability_and_user_isolation(self):
        u1 = 111
        u2 = 222
        res1 = save_user_uploaded_file(b"Doc for User 1", "test.txt", user_id=u1)
        self.assertTrue(res1["success"])

        # Check files for User 1
        u1_files = list_user_files(user_id=u1)
        self.assertTrue(any(f["name"] == "test.txt" for f in u1_files))

        # Check files for User 2 (must be isolated)
        u2_files = list_user_files(user_id=u2)
        self.assertFalse(any(f["name"] == "test.txt" for f in u2_files))

    # ── 9. Absence of Wake Word and Avatar/Hologram ───────────────────────────
    def test_09_no_wake_word_and_no_avatar(self):
        # Ensure no wake-word modules
        with self.assertRaises(ImportError):
            import skills.audio_management.wake_word  # noqa: F401

        # Ensure no avatar modules
        with self.assertRaises(ImportError):
            from modules.ui import HoloAvatar  # noqa: F401


if __name__ == "__main__":
    unittest.main()
