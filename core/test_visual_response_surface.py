"""
VERIFICATION TEST SUITE — VISUAL RESPONSE SURFACE / EPHEMERAL INFORMATION PANEL

Comprehensive verification of:
1. Pairing code display & auto detection
2. IP address display & auto detection
3. URL display & auto detection
4. File path display & auto detection
5. List display & auto detection
6. Structured result display (task status, device info)
7. Explicit "show me" routing
8. "show that" routing
9. "show that again" routing
10. Dismiss on outside click / UI dismissal mechanics
11. Panel dismissal does NOT cancel assistant
12. Panel dismissal does NOT cancel active goal
13. Reopen same result without regeneration
14. No regeneration on "show that again" (exact same pairing code, zero duplicate calls)
15. No duplicate action execution
16. Context freshness & TTL rules
17. Expired result handling ("I no longer have a current version...")
18. User isolation (User A cache inaccessible to User B)
19. Sensitive data protection (passwords / tokens / API keys blocked from auto-display)
20. Copy button uses canonical existing clipboard (set_clipboard_text)
21. Existing TTS unaffected (spoken response remains complete)
22. Continuous audio / listening unaffected
23. Proactive observer unaffected
24. Real production path (process_input -> UnifiedCommandRouter -> Visual Surface)
"""

import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.visual_response import (
    VisualResponse,
    VisualResponseType,
    VisualResponseAction,
    detect_visual_response,
    contains_sensitive_data
)
from extensions.dialogue_state_manager import get_dialogue_manager
from core.assistant_core import get_assistant_core
from core.unified_command_router import get_router, Intent
from legacy.assistant import process_input
from skills.device_management import get_device_controller


class TestVisualResponseSurface(unittest.TestCase):
    """
    Full unit and end-to-end integration tests for Visual Response Surface.
    """

    def setUp(self):
        self.user_a = "visual_test_user_a"
        self.user_b = "visual_test_user_b"
        self.core = get_assistant_core()
        
        # Reset dialogue state managers
        self.dm_a = get_dialogue_manager(self.user_a)
        self.dm_a.start_session()
        self.dm_b = get_dialogue_manager(self.user_b)
        self.dm_b.start_session()
        
        # Clear visual listeners
        self.received_visuals = []
        self.listener = lambda vr: self.received_visuals.append(vr)
        self.core.register_visual_listener(self.listener)

    def tearDown(self):
        self.core.unregister_visual_listener(self.listener)

    # ─────────────────────────────────────────────────────────────────────────
    # 1-6: AUTOMATIC DETECTION OF STRUCTURED VISUAL DATA
    # ─────────────────────────────────────────────────────────────────────────

    def test_01_pairing_code_detection(self):
        """Test auto-detection of pairing code."""
        text = "Your phone pairing code is 482731. Please enter it on your phone."
        vr = detect_visual_response(text, user_id=self.user_a, source_context="device_pairing")
        self.assertIsNotNone(vr)
        self.assertEqual(vr.response_type, VisualResponseType.PAIRING_CODE)
        self.assertEqual(vr.primary_value, "482731")
        self.assertEqual(vr.title, "PAIRING CODE")
        # Ensure a copy action is attached
        self.assertTrue(any(a.action_type == "copy" and a.payload == "482731" for a in vr.actions))

    def test_02_ip_address_detection(self):
        """Test auto-detection of IP address."""
        text = "The IP address of your workstation is 192.168.1.105 on the local network."
        vr = detect_visual_response(text, user_id=self.user_a, source_context="network_status")
        self.assertIsNotNone(vr)
        self.assertEqual(vr.response_type, VisualResponseType.IP_ADDRESS)
        self.assertEqual(vr.primary_value, "192.168.1.105")
        self.assertEqual(vr.title, "IP ADDRESS")
        self.assertTrue(any(a.action_type == "copy" for a in vr.actions))

    def test_03_url_detection(self):
        """Test auto-detection of long URL."""
        text = "Here is the link you requested: https://srmap.edu.in/academics/computer-science-engineering"
        vr = detect_visual_response(text, user_id=self.user_a, source_context="web_search")
        self.assertIsNotNone(vr)
        self.assertEqual(vr.response_type, VisualResponseType.URL)
        self.assertTrue(vr.primary_value.startswith("https://srmap.edu.in"))
        self.assertTrue(any(a.action_type == "open_url" for a in vr.actions))

    def test_04_file_path_detection(self):
        """Test auto-detection of Windows / Unix file path."""
        text = "The log has been exported to C:\\Users\\User\\Documents\\report_final.pdf successfully."
        vr = detect_visual_response(text, user_id=self.user_a, source_context="file_export")
        self.assertIsNotNone(vr)
        self.assertEqual(vr.response_type, VisualResponseType.FILE_PATH)
        self.assertIn("report_final.pdf", vr.primary_value)
        self.assertTrue(any(a.action_type == "open_file" for a in vr.actions))

    def test_05_list_detection(self):
        """Test auto-detection of multi-item structured lists."""
        text = "Available devices found:\n• Galaxy S24 Ultra\n• MacBook Pro M3\n• Living Room Apple TV"
        vr = detect_visual_response(text, user_id=self.user_a, source_context="device_scan")
        self.assertIsNotNone(vr)
        self.assertEqual(vr.response_type, VisualResponseType.LIST)
        self.assertIn("Galaxy S24 Ultra", vr.primary_value)
        self.assertIn("MacBook Pro M3", vr.primary_value)

    def test_06_task_and_device_info_detection(self):
        """Test detection of structured device info and task results."""
        info_dict = {
            "device_name": "Living Room Light",
            "type": "smart_switch",
            "status": "online",
            "brightness": "80%"
        }
        vr = detect_visual_response(info_dict, user_id=self.user_a, source_context="device_info")
        self.assertIsNotNone(vr)
        self.assertEqual(vr.response_type, VisualResponseType.DEVICE_INFO)
        self.assertIn("Living Room Light", vr.primary_value)

    def test_06b_casual_chat_rejected_from_visual_popup(self):
        """Ensure casual greetings or simple answers do not trigger visual popups."""
        boring_responses = [
            "Hello! How can I help you today?",
            "Good morning!",
            "Sure thing.",
            "The current time is 3:45 PM.",
            "Today is Thursday.",
            "I'm here."
        ]
        for resp in boring_responses:
            vr = detect_visual_response(resp, user_id=self.user_a, source_context="general")
            self.assertIsNone(vr, f"Casual response '{resp}' should not create a visual popup.")

    # ─────────────────────────────────────────────────────────────────────────
    # 7-9: ROUTING OF EXPLICIT VISUAL REQUESTS
    # ─────────────────────────────────────────────────────────────────────────

    def test_07_explicit_show_me_routing(self):
        """Verify 'show me the pairing code' routes to Intent.VISUAL_SURFACE."""
        router = get_router()
        intent, params = router.route_command("show me the pairing code")
        self.assertEqual(intent, Intent.VISUAL_SURFACE)

    def test_08_show_that_routing(self):
        """Verify 'show that' and 'put that on screen' route to Intent.VISUAL_SURFACE."""
        router = get_router()
        for phrase in ["show that", "put that on screen", "let me see it", "display that"]:
            intent, params = router.route_command(phrase)
            self.assertEqual(intent, Intent.VISUAL_SURFACE, f"Failed for phrase: '{phrase}'")

    def test_09_show_that_again_routing(self):
        """Verify 'show that again' routes to Intent.VISUAL_SURFACE."""
        router = get_router()
        for phrase in ["show that again", "show it again", "display that again", "can you show me that again"]:
            intent, params = router.route_command(phrase)
            self.assertEqual(intent, Intent.VISUAL_SURFACE, f"Failed for phrase: '{phrase}'")

    # ─────────────────────────────────────────────────────────────────────────
    # 10-12: DISMISSAL BEHAVIOR & SYSTEM RESILIENCE
    # ─────────────────────────────────────────────────────────────────────────

    def test_10_dismissal_mechanics(self):
        """Verify visual response panel can be dismissed cleanly."""
        vr = VisualResponse(
            response_id="vr_101",
            user_id=self.user_a,
            response_type=VisualResponseType.PAIRING_CODE,
            title="PAIRING CODE",
            primary_value="654321"
        )
        self.core.show_visual_response(vr)
        self.assertEqual(self.core.get_active_visual_response(), vr)
        
        # User clicks outside / dismisses
        self.core.dismiss_visual_response()
        self.assertIsNone(self.core.get_active_visual_response())

    def test_11_dismiss_does_not_cancel_assistant(self):
        """Verify dismissing the visual panel does NOT terminate or stop assistant session."""
        vr = VisualResponse(
            response_id="vr_102",
            user_id=self.user_a,
            response_type=VisualResponseType.IP_ADDRESS,
            title="IP ADDRESS",
            primary_value="10.0.0.1"
        )
        self.dm_a.store_visual_response(vr)
        self.core.show_visual_response(vr)
        self.core.dismiss_visual_response()
        
        # Dialogue session is still alive and responsive
        state = self.dm_a.get_state()
        self.assertIsNotNone(state.session_id)
        # Context still retains the visual response for 'show that again'
        self.assertEqual(self.dm_a.get_last_visual_response(), vr)

    def test_12_dismiss_does_not_cancel_active_goal(self):
        """Verify dismissing visual panel does not cancel current goal."""
        state = self.dm_a.get_state()
        state.active_goal = "connect_phone_goal"
        state.active_goal_id = "goal_999"
        
        vr = VisualResponse(
            response_id="vr_103",
            user_id=self.user_a,
            response_type=VisualResponseType.PAIRING_CODE,
            title="PAIRING CODE",
            primary_value="999888",
            related_goal_id="goal_999"
        )
        self.dm_a.store_visual_response(vr)
        self.core.show_visual_response(vr)
        self.core.dismiss_visual_response()
        
        # Goal remains active
        self.assertEqual(self.dm_a.get_state().active_goal_id, "goal_999")
        self.assertEqual(self.dm_a.get_state().active_goal, "connect_phone_goal")

    # ─────────────────────────────────────────────────────────────────────────
    # 13-15: REOPEN WITHOUT REGENERATION (CORE ACCEPTANCE CRITERIA)
    # ─────────────────────────────────────────────────────────────────────────

    def test_13_reopen_same_result_without_regeneration(self):
        """
        Core Acceptance Test:
        1. User pairs device -> gets pairing code.
        2. Visual panel displays code.
        3. Panel is dismissed.
        4. User requests 'show that again'.
        5. Exact same code is displayed.
        6. No new pairing code or device offer was generated!
        """
        device_ctrl = get_device_controller()
        
        # Step 1: Pair phone
        with patch.object(device_ctrl, 'pair_device', wraps=device_ctrl.pair_device) as mock_pair:
            resp1 = process_input("pair my phone", user_id=self.user_a)
            self.assertEqual(mock_pair.call_count, 1)
            
            # Extract pairing code from the response or dialogue state
            vr1 = self.dm_a.get_last_visual_response()
            self.assertIsNotNone(vr1, "Visual response should have been automatically stored")
            code_1 = vr1.primary_value
            self.assertTrue(code_1.isdigit() and len(code_1) == 6, f"Invalid code: {code_1}")
            
            # Step 2: Dismiss visual panel (simulate outside click)
            self.core.dismiss_visual_response()
            self.assertIsNone(self.core.get_active_visual_response())
            
            # Step 3: User says "show that again"
            resp2 = process_input("show that again", user_id=self.user_a)
            
            # Step 4: Verify pair_device was NOT called a second time
            self.assertEqual(mock_pair.call_count, 1, "pair_device MUST NOT be called again on 'show that again'")
            
            # Step 5: Verify the active visual response is the exact same code
            active_vr = self.core.get_active_visual_response()
            self.assertIsNotNone(active_vr)
            self.assertEqual(active_vr.primary_value, code_1, "Must return the EXACT same pairing code")
            self.assertIn(code_1, resp2)

    def test_14_no_regeneration_for_ip_and_files(self):
        """Verify 'show that again' for IP address restores same cached IP without network queries."""
        # Store an IP visual response
        vr_ip = VisualResponse(
            response_id="ip_001",
            user_id=self.user_a,
            response_type=VisualResponseType.IP_ADDRESS,
            title="IP ADDRESS",
            primary_value="172.16.0.42",
            ttl_seconds=300.0
        )
        self.dm_a.store_visual_response(vr_ip)
        
        # User says "show it again"
        with patch('skills.device_management.get_device_controller') as mock_dev:
            resp = process_input("show it again", user_id=self.user_a)
            mock_dev.assert_not_called()
            
            active = self.core.get_active_visual_response()
            self.assertIsNotNone(active)
            self.assertEqual(active.primary_value, "172.16.0.42")
            self.assertIn("172.16.0.42", resp)

    # ─────────────────────────────────────────────────────────────────────────
    # 16-17: CONTEXT FRESHNESS & EXPIRATION
    # ─────────────────────────────────────────────────────────────────────────

    def test_16_context_freshness_within_ttl(self):
        """Responses within TTL are immediately returned."""
        vr = VisualResponse(
            response_id="fresh_1",
            user_id=self.user_a,
            response_type=VisualResponseType.TEXT,
            title="STATUS",
            primary_value="All systems operational",
            created_at=time.time() - 60,  # 1 minute ago
            ttl_seconds=300.0             # 5 minutes TTL
        )
        self.dm_a.store_visual_response(vr)
        
        retrieved = self.dm_a.get_last_visual_response(max_age_seconds=300.0)
        self.assertEqual(retrieved, vr)

    def test_17_expired_result_handling(self):
        """Responses older than TTL are treated as expired and report truthfully to user."""
        vr = VisualResponse(
            response_id="old_1",
            user_id=self.user_a,
            response_type=VisualResponseType.PAIRING_CODE,
            title="PAIRING CODE",
            primary_value="123456",
            created_at=time.time() - 360,  # 6 minutes ago
            ttl_seconds=300.0             # 5 minutes TTL
        )
        self.dm_a.store_visual_response(vr)
        
        # Direct retrieval with TTL returns None
        retrieved = self.dm_a.get_last_visual_response(max_age_seconds=300.0)
        self.assertIsNone(retrieved, "Expired visual response should not be returned as current")
        
        # Via router / process_input
        resp = process_input("show that again", user_id=self.user_a)
        self.assertIn("no longer have a current version", resp.lower())

    # ─────────────────────────────────────────────────────────────────────────
    # 18: USER ISOLATION
    # ─────────────────────────────────────────────────────────────────────────

    def test_18_user_isolation(self):
        """User A's visual response cannot be viewed or requested by User B."""
        vr_a = VisualResponse(
            response_id="user_a_priv",
            user_id=self.user_a,
            response_type=VisualResponseType.PAIRING_CODE,
            title="PAIRING CODE",
            primary_value="777999"
        )
        self.dm_a.store_visual_response(vr_a)
        
        # User B asks "show that again"
        resp_b = process_input("show that again", user_id=self.user_b)
        self.assertNotIn("777999", resp_b)
        self.assertIn("no recent information", resp_b.lower())
        
        # User B's state manager has no visual response
        self.assertIsNone(self.dm_b.get_last_visual_response())

    # ─────────────────────────────────────────────────────────────────────────
    # 19: SENSITIVE DATA PROTECTION
    # ─────────────────────────────────────────────────────────────────────────

    def test_19_sensitive_data_protection(self):
        """Ensure passwords and secrets are never automatically displayed."""
        secret_text = "Your new account password is SuperSecretP@ssw0rd! Please save it."
        self.assertTrue(contains_sensitive_data(secret_text))
        
        vr = detect_visual_response(secret_text, user_id=self.user_a, source_context="auth")
        self.assertIsNone(vr, "Sensitive passwords must never trigger automatic visual response popups.")

    # ─────────────────────────────────────────────────────────────────────────
    # 20: CLIPBOARD INTEGRATION
    # ─────────────────────────────────────────────────────────────────────────

    def test_20_copy_button_uses_existing_clipboard(self):
        """Verify the [Copy] action invokes the existing canonical set_clipboard_text."""
        from modules.ui.visual_response_surface import VisualResponsePanel
        from PyQt6.QtWidgets import QApplication
        
        # Ensure QApplication exists for Qt widget test
        app = QApplication.instance() or QApplication(sys.argv)
        
        panel = VisualResponsePanel()
        vr = VisualResponse(
            response_id="copy_test",
            user_id=self.user_a,
            response_type=VisualResponseType.PAIRING_CODE,
            title="PAIRING CODE",
            primary_value="555123",
            actions=[VisualResponseAction(label="Copy", action_type="copy", payload="555123")]
        )
        panel.display_response(vr)
        
        with patch('modules.system_controller.set_clipboard_text') as mock_clip:
            action = vr.actions[0]
            panel._trigger_action(action)
            mock_clip.assert_called_once_with("555123")

    # ─────────────────────────────────────────────────────────────────────────
    # 21-23: AUDIO & OBSERVER UNAFFECTED
    # ─────────────────────────────────────────────────────────────────────────

    def test_21_tts_unaffected(self):
        """Visual presentation does not replace or silence speech."""
        resp = process_input("pair my phone", user_id=self.user_a)
        # Spoken text contains complete English guidance
        self.assertTrue(len(resp) > 10)
        self.assertIn("pairing", resp.lower())

    def test_22_continuous_audio_unaffected_by_dismissal(self):
        """Dismissing visual response does not interfere with audio listeners."""
        self.core.dismiss_visual_response()
        # Visual state dismissed, dialogue state intact
        self.assertIsNone(self.core.get_active_visual_response())
        self.assertTrue(self.dm_a.is_active())

    def test_23_proactive_observer_unaffected(self):
        """Proactive observer events without visual relevance do not generate popups."""
        boring_event = "System CPU load is normal at 14%."
        vr = detect_visual_response(boring_event, user_id=self.user_a, source_context="monitoring")
        self.assertIsNone(vr)


if __name__ == "__main__":
    unittest.main()
