import unittest
from unittest.mock import MagicMock, patch
from core.target_resolver import resolve_device_target, TargetDeviceType
from core.semantic_understanding import semantic_understanding_engine
from core.unified_command_router import unified_router, Intent
from core.brain import brain_process
from extensions.dialogue_state_manager import get_dialogue_manager

class TestUnifiedArchitectureCoordination(unittest.TestCase):
    """
    Verification suite for the One Unified Intelligence, Coordinated Modules architecture.
    Validates Section 10 requirements:
    1. Phone control vs computer control
    2. App launching vs app info queries
    3. Questions vs commands ('Tell me about machine learning')
    4. Corrections and cancellations ('No, I mean my mobile, not my computer')
    5. Context-dependent references & continuation ('Continue what we were doing')
    6. Memory & reminders ('Remember this for tomorrow')
    7. Capability isolation & prohibited capabilities
    """

    @classmethod
    def setUpClass(cls):
        cls.dm = get_dialogue_manager("1")
        cls.router = unified_router

    def test_01_phone_control_vs_computer_control_isolation(self):
        """Verify Phone Control strictly activates Android capabilities and prohibits Workstation controls."""
        phone_cmd = semantic_understanding_engine.interpret("Lock my phone.", user_id=1)
        self.assertEqual(phone_cmd.target_device, "android_phone")
        self.assertIn("android_device", phone_cmd.required_capabilities)
        self.assertIn("windows_workstation", phone_cmd.prohibited_capabilities)
        self.assertTrue(phone_cmd.action_required)

        pc_cmd = semantic_understanding_engine.interpret("Lock my computer.", user_id=1)
        self.assertEqual(pc_cmd.target_device, "windows_workstation")
        self.assertIn("windows_workstation", pc_cmd.required_capabilities)
        self.assertIn("android_device", pc_cmd.prohibited_capabilities)
        self.assertTrue(pc_cmd.action_required)

    def test_02_conversational_question_does_not_activate_device_or_os_mutations(self):
        """Verify 'Tell me about machine learning' is a QUESTION with action_required=False and prohibits mutations."""
        cmd = semantic_understanding_engine.interpret("Tell me about machine learning.", user_id=1)
        self.assertEqual(cmd.request_type, "QUESTION")
        self.assertEqual(cmd.intent, "GENERAL_CONVERSATION")
        self.assertFalse(cmd.action_required)
        self.assertIn("conversational_knowledge", cmd.required_capabilities)
        self.assertIn("windows_workstation", cmd.prohibited_capabilities)
        self.assertIn("android_device", cmd.prohibited_capabilities)
        self.assertIn("applications", cmd.prohibited_capabilities)

        # Execute through brain and verify no workstation or device lock/mutation occurs
        with patch("legacy.skills_utilities.lock_system") as mock_lock:
            res = brain_process("Tell me about machine learning.", user_id="1")
            mock_lock.assert_not_called()
            self.assertIn(res.get("intent"), ("GENERAL_CONVERSATION", "KNOWLEDGE_QUERY"))
            self.assertFalse(res.get("action_required", False))
            self.assertTrue(len(res.get("response", "")) > 0)

    def test_03_memory_and_reminder_directive(self):
        """Verify 'Remember this for tomorrow' activates persistent memory and reminder capabilities."""
        cmd = semantic_understanding_engine.interpret("Remember this for tomorrow.", user_id=1)
        self.assertEqual(cmd.request_type, "INSTRUCTION")
        self.assertEqual(cmd.intent, "REMINDERS")
        self.assertEqual(cmd.action, "create_reminder")
        self.assertTrue(cmd.action_required)
        self.assertIn("persistent_memory", cmd.required_capabilities)
        self.assertIn("reminders", cmd.required_capabilities)
        self.assertIn("windows_workstation", cmd.prohibited_capabilities)
        self.assertIn("android_device", cmd.prohibited_capabilities)

    def test_04_contextual_continuation(self):
        """Verify 'Continue what we were doing' activates task_continuation and resumes context."""
        cmd = semantic_understanding_engine.interpret("Continue what we were doing.", user_id=1)
        self.assertEqual(cmd.request_type, "CONTINUATION")
        self.assertTrue(cmd.is_continuation)
        self.assertIn("task_continuation", cmd.required_capabilities)
        self.assertIn("windows_workstation", cmd.prohibited_capabilities)
        self.assertIn("android_device", cmd.prohibited_capabilities)

        # Execute through brain and verify clean continuation without unintended actions
        with patch("legacy.skills_utilities.lock_system") as mock_lock:
            res = brain_process("Continue what we were doing.", user_id="1")
            mock_lock.assert_not_called()
            self.assertEqual(res.get("intent"), "GOAL_MANAGEMENT")
            self.assertTrue(res.get("handled"))

    def test_05_target_correction_context_resolution(self):
        """Verify 'No, I mean my mobile, not my computer' resolves target correction and binds to previous action."""
        # Seed dialogue state with a lock action
        self.dm.current_state.last_action = "lock"
        self.dm.current_state.recent_actions = [{"action": "lock", "target": "workstation"}]

        cmd = semantic_understanding_engine.interpret(
            "No, I mean my mobile, not my computer.",
            dialogue_state=self.dm.current_state,
            user_id=1
        )
        self.assertTrue(cmd.is_correction)
        self.assertEqual(cmd.target_device, "android_phone")
        self.assertIn("android_device", cmd.required_capabilities)
        self.assertIn("windows_workstation", cmd.prohibited_capabilities)
        self.assertEqual(cmd.parameters.get("requested_action"), "phone_lock")

    def test_06_app_launch_vs_app_query_distinction(self):
        """Verify app launching requires action, whereas application status query does not mutate system."""
        open_cmd = semantic_understanding_engine.interpret("Open Notepad", user_id=1)
        self.assertTrue(open_cmd.action_required)
        self.assertEqual(open_cmd.intent, "OPEN_APPLICATION")

        query_cmd = semantic_understanding_engine.interpret("Is Chrome running?", user_id=1)
        self.assertFalse(query_cmd.action_required)

    def test_07_full_pipeline_single_authoritative_brain_execution(self):
        """Verify complete pipeline execution: phone command flows through brain to ADB and never touches Windows."""
        with patch("legacy.skills_utilities.lock_system") as mock_pc_lock:
            res = brain_process("Lock my phone", user_id="1")
            mock_pc_lock.assert_not_called()
            self.assertEqual(res.get("requested_target_device"), "android_phone")
            self.assertEqual(res.get("action_selected"), "phone_lock")
            # "already_locked" is also valid when the phone screen is already off
            self.assertIn(res.get("status"), ("success", "already_locked"),
                          "Phone lock must succeed or report already-locked state")


if __name__ == "__main__":
    unittest.main()

