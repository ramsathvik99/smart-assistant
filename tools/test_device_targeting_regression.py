import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""
Comprehensive Regression Test Suite for Device-Target Resolution & Preservation.

Verifies:
1. Target Device Resolution at Architecture Level (Windows Workstation vs Android Phone)
2. Semantic Understanding Engine Interpretation
3. Unified Command Router Parameter Extraction & Routing
4. Execution Isolation: Mobile operations execute ONLY on Android phone via ADB;
   Workstation operations execute ONLY on Windows workstation.
5. Verification & Metadata Agreement (requested_target_device, resolved_device, action_selected, etc.)
6. Natural-language variations & Negation handling (e.g. 'Lock my mobile, not the system')
"""

import sys
import unittest
from unittest.mock import patch, MagicMock

from core.target_resolver import resolve_device_target, TargetDeviceType
from core.semantic_understanding import SemanticUnderstandingEngine
from core.unified_command_router import UnifiedCommandRouter, get_router


class DeviceTargetResolutionRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.su = SemanticUnderstandingEngine()
        cls.router = get_router()

    # -------------------------------------------------------------------------
    # 1. ARCHITECTURE-LEVEL TARGET RESOLUTION & PRESERVATION TESTS
    # -------------------------------------------------------------------------
    def test_01_target_resolution_mandatory_nine(self):
        """Test target device resolution on all 9 mandatory commands."""
        cases = [
            ("Lock my phone", TargetDeviceType.ANDROID_PHONE),
            ("Unlock my phone", TargetDeviceType.ANDROID_PHONE),
            ("Lock my computer", TargetDeviceType.WINDOWS_WORKSTATION),
            ("Unlock my computer", TargetDeviceType.WINDOWS_WORKSTATION),
            ("Lock my mobile, not my system", TargetDeviceType.ANDROID_PHONE),
            ("Lock my mobile, not the system", TargetDeviceType.ANDROID_PHONE),
            ("Open WhatsApp on my phone", TargetDeviceType.ANDROID_PHONE),
            ("Show my phone battery", TargetDeviceType.ANDROID_PHONE),
            ("Turn off Bluetooth on my phone", TargetDeviceType.ANDROID_PHONE),
            ("Call Mom on my phone", TargetDeviceType.ANDROID_PHONE),
        ]
        for query, expected_target in cases:
            with self.subTest(query=query):
                res = resolve_device_target(query, user_id=1)
                self.assertEqual(
                    res.target_device,
                    expected_target,
                    f"Query '{query}' resolved to {res.target_device}, expected {expected_target} (reason: {res.reason})"
                )

    def test_02_natural_language_variations(self):
        """Test flexible natural-language phrasing and negation handling."""
        variations = [
            ("Lock my mobile", TargetDeviceType.ANDROID_PHONE),
            ("Lock the phone", TargetDeviceType.ANDROID_PHONE),
            ("I want my mobile locked", TargetDeviceType.ANDROID_PHONE),
            ("Please lock my Android", TargetDeviceType.ANDROID_PHONE),
            ("Unlock my mobile", TargetDeviceType.ANDROID_PHONE),
            ("Please unlock my Android", TargetDeviceType.ANDROID_PHONE),
            ("Lock the computer, not my phone", TargetDeviceType.WINDOWS_WORKSTATION),
            ("Lock my PC, not my mobile", TargetDeviceType.WINDOWS_WORKSTATION),
            ("Turn on Bluetooth on my phone", TargetDeviceType.ANDROID_PHONE),
            ("Turn off Wi-Fi on my phone", TargetDeviceType.ANDROID_PHONE),
            ("Lock workstation", TargetDeviceType.WINDOWS_WORKSTATION),
            ("Unlock workstation", TargetDeviceType.WINDOWS_WORKSTATION),
        ]
        for query, expected_target in variations:
            with self.subTest(query=query):
                res = resolve_device_target(query, user_id=1)
                self.assertEqual(
                    res.target_device,
                    expected_target,
                    f"Variation '{query}' resolved to {res.target_device}, expected {expected_target}"
                )

    # -------------------------------------------------------------------------
    # 2. SEMANTIC UNDERSTANDING PIPELINE TESTS
    # -------------------------------------------------------------------------
    def test_03_semantic_understanding_interpretation(self):
        """Verify SemanticUnderstandingEngine produces correct target entities."""
        # Mobile commands must produce action='remote_device' and target_device='android_phone'
        mobile_queries = [
            "Lock my phone",
            "Unlock my phone",
            "Lock my mobile, not the system",
            "Open WhatsApp on my phone",
            "Show my phone battery",
            "Turn off Bluetooth on my phone",
            "Call Mom on my phone",
        ]
        for q in mobile_queries:
            with self.subTest(query=q):
                cmd = self.su.interpret(q, user_id=1)
                self.assertEqual(cmd.intent, "DEVICE_CONTROL")
                self.assertEqual(cmd.action, "remote_device")
                self.assertEqual(cmd.parameters.get("target_device"), "android_phone")
                self.assertEqual(cmd.parameters.get("requested_device_target"), "android_phone")

        # Workstation commands must produce workstation action and target_device='windows_workstation'
        cmd_pc_lock = self.su.interpret("Lock my computer", user_id=1)
        self.assertEqual(cmd_pc_lock.intent, "DEVICE_CONTROL")
        self.assertEqual(cmd_pc_lock.action, "LOCK")
        self.assertEqual(cmd_pc_lock.parameters.get("target_device"), "windows_workstation")

        cmd_pc_unlock = self.su.interpret("Unlock my computer", user_id=1)
        self.assertEqual(cmd_pc_unlock.intent, "DEVICE_CONTROL")
        self.assertEqual(cmd_pc_unlock.action, "UNLOCK")
        self.assertEqual(cmd_pc_unlock.parameters.get("target_device"), "windows_workstation")

    # -------------------------------------------------------------------------
    # 3. ROUTER PARAMETER EXTRACTION TESTS
    # -------------------------------------------------------------------------
    def test_04_router_route_preservation(self):
        """Verify UnifiedCommandRouter preserves the target and action."""
        mobile_queries = [
            "Lock my phone",
            "Unlock my phone",
            "Lock my mobile, not the system",
            "Open WhatsApp on my phone",
            "Show my phone battery",
            "Turn off Bluetooth on my phone",
            "Call Mom on my phone",
        ]
        for q in mobile_queries:
            with self.subTest(query=q):
                intent, params = self.router.route(q, user_id=1)
                self.assertEqual(intent.name, "DEVICE_CONTROL")
                self.assertEqual(params.get("action"), "remote_device")
                self.assertEqual(params.get("target_device"), "android_phone")
                self.assertEqual(params.get("requested_device_target"), "android_phone")

    # -------------------------------------------------------------------------
    # 4. EXECUTION ISOLATION & VERIFICATION TESTS
    # -------------------------------------------------------------------------
    def test_05_execution_lock_phone_targets_only_phone(self):
        """Verify 'Lock my phone' executes against ADB phone adapter and NEVER touches Windows workstation."""
        with patch("legacy.skills_utilities.lock_system") as mock_pc_lock, \
             patch("core.os_gateway.system_ops.lock_workstation") as mock_ws_lock:
            res = self.router.execute_single_action("Lock my phone", user_id=1)
            # Workstation lock must NEVER be called
            mock_pc_lock.assert_not_called()
            mock_ws_lock.assert_not_called()

            # Result must confirm phone targeting
            self.assertEqual(res.get("requested_target_device"), "android_phone")
            self.assertEqual(res.get("action_selected"), "phone_lock")
            self.assertIn("192.168.1.4:5555", str(res.get("resolved_device")))
            self.assertIn("Locked your phone", res.get("response"))
            self.assertIsNone(res.get("workstation_state"))

    def test_06_execution_unlock_phone_targets_only_phone(self):
        """Verify 'Unlock my phone' executes against Android device controller and respects security restrictions."""
        res = self.router.execute_single_action("Unlock my phone", user_id=1)
        self.assertEqual(res.get("requested_target_device"), "android_phone")
        self.assertEqual(res.get("action_selected"), "phone_unlock")
        self.assertIn("192.168.1.4:5555", str(res.get("resolved_device")))
        self.assertIn("phone", res.get("response").lower())
        self.assertIsNone(res.get("workstation_state"))

    def test_07_execution_lock_computer_targets_only_workstation(self):
        """Verify 'Lock my computer' targets Windows workstation independently."""
        with patch("legacy.skills_utilities.lock_system", return_value="Workstation locked successfully.") as mock_pc_lock:
            res = self.router.execute_single_action("Lock my computer", user_id=1)
            mock_pc_lock.assert_called_once()
            self.assertEqual(res.get("requested_target_device"), "windows_workstation")
            self.assertEqual(res.get("resolved_device"), "windows_workstation")
            self.assertEqual(res.get("action_selected"), "lock_workstation")
            self.assertEqual(res.get("workstation_state"), "LOCKED")

    def test_08_execution_unlock_computer_targets_only_workstation(self):
        """Verify 'Unlock my computer' targets Windows workstation independently."""
        res = self.router.execute_single_action("Unlock my computer", user_id=1)
        self.assertEqual(res.get("requested_target_device"), "windows_workstation")
        self.assertEqual(res.get("resolved_device"), "windows_workstation")
        self.assertEqual(res.get("action_selected"), "unlock_workstation")
        self.assertIn(res.get("workstation_state"), ["LOCKED", "UNLOCKED"])
        self.assertIn("workstation", res.get("response").lower())

    def test_09_execution_lock_mobile_not_system(self):
        """Verify 'Lock my mobile, not the system' locks the phone and NEVER touches the workstation."""
        with patch("legacy.skills_utilities.lock_system") as mock_pc_lock:
            res = self.router.execute_single_action("Lock my mobile, not the system", user_id=1)
            mock_pc_lock.assert_not_called()
            self.assertEqual(res.get("requested_target_device"), "android_phone")
            self.assertEqual(res.get("action_selected"), "phone_lock")
            self.assertIsNone(res.get("workstation_state"))

    def test_10_execution_show_phone_battery(self):
        """Verify 'Show my phone battery' retrieves phone battery info and metadata."""
        res = self.router.execute_single_action("Show my phone battery", user_id=1)
        self.assertEqual(res.get("requested_target_device"), "android_phone")
        self.assertEqual(res.get("action_selected"), "battery_status")
        self.assertIn("phone battery is at", res.get("response").lower())
        self.assertIsNotNone(res.get("battery"))

    def test_11_execution_bluetooth_toggle(self):
        """Verify Bluetooth toggling targets phone."""
        res = self.router.execute_single_action("Turn off Bluetooth on my phone", user_id=1)
        self.assertEqual(res.get("requested_target_device"), "android_phone")
        self.assertIn("bluetooth", res.get("response").lower())
        # Restore bluetooth to on
        from skills.device_management import get_device_controller
        get_device_controller().set_bluetooth(1, True)

    def test_12_execution_call_mom(self):
        """Verify 'Call Mom on my phone' resolves contact on phone and initiates call flow."""
        res = self.router.execute_single_action("Call Mom on my phone", user_id=1)
        self.assertEqual(res.get("requested_target_device"), "android_phone")
        self.assertEqual(res.get("action_selected"), "call")
        self.assertIn("mom", res.get("response").lower())
        self.assertIn(res.get("status"), ("call_initiated", "call_active"))
        # Clean up call state
        from skills.device_management import get_device_controller
        get_device_controller().end_call(user_id=1)


if __name__ == "__main__":
    unittest.main()
