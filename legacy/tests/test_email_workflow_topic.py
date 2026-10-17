"""
test_email_workflow_topic.py

Automated test suite verifying the topic-based email generation and sending workflow:
1. Understanding recipient and topic from the command:
   "Can you send a mail to Sathvik about the reexam that is going to be conducted tomorrow, and if you miss this, there is no other chance."
2. Recipient resolution to email address (e.g. 'satvik'/'sathvik' -> 'ramsathvik.a.v@gmail.com').
3. Well-written subject and body generation preserving supplied details without hallucinating.
4. Direct sending via configured authenticated email provider without voice dictation prompt.
5. Explicit voice dictation flows entered ONLY when explicitly requested.
6. Incomplete requests prompt only for missing information (recipient or topic) without dictation.
7. Explicit drafting requests save draft without sending.
8. Brain semantic relevance topic extraction (no Topic: None).
9. UnifiedCommandRouter parameter extraction for Intent.EMAIL.
"""
import unittest
from unittest.mock import patch, MagicMock

from core.unified_command_router import UnifiedCommandRouter, Intent
from modules.assistant_email.email_controller import (
    handle_email_command,
    _parse_email_intent,
    _pending_email_sessions,
    STATE_RECORDING_EMAIL_MESSAGE
)
from modules.assistant_email.email_ai import (
    rewrite_professional,
    generate_subject_from_text,
    _format_fallback_body
)
from modules.assistant_email.user_storage import list_drafts


class TestEmailWorkflowTopic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.router = UnifiedCommandRouter()

    def setUp(self):
        _pending_email_sessions.clear()

    def tearDown(self):
        _pending_email_sessions.clear()

    def test_01_parse_email_intent_extracts_recipient_topic_and_modes(self):
        """Verify _parse_email_intent extracts recipient, topic, send_versus_draft, and is_dictation."""
        cmd = "Can you send a mail to Sathvik about the reexam that is going to be conducted tomorrow, and if you miss this, there is no other chance."
        parsed = _parse_email_intent(cmd)

        self.assertEqual(parsed.get("action"), "compose")
        self.assertEqual(parsed.get("recipient_raw"), "Sathvik")
        self.assertIn("reexam", parsed.get("topic", "").lower())
        self.assertIn("tomorrow", parsed.get("topic", "").lower())
        self.assertEqual(parsed.get("send_versus_draft"), "send")
        self.assertFalse(parsed.get("is_dictation"))

    def test_02_router_extracts_structured_email_parameters(self):
        """UnifiedCommandRouter must extract structured recipient, topic, action, and modes for Intent.EMAIL."""
        cmd = "Can you send a mail to Sathvik about the reexam that is going to be conducted tomorrow, and if you miss this, there is no other chance."
        intent, params = self.router.route_command(cmd)

        self.assertEqual(intent, Intent.EMAIL)
        self.assertEqual(params.get("recipient"), "Sathvik")
        self.assertIn("reexam", params.get("topic", "").lower())
        self.assertEqual(params.get("send_versus_draft"), "send")
        self.assertFalse(params.get("is_dictation"))

    def test_03_topic_based_send_executes_without_dictation_prompt(self):
        """
        When user provides recipient and topic, handle_email_command must generate and send the email
        directly, never prompting: 'Say your message, then say stop message'.
        """
        cmd = "Can you send a mail to Sathvik about the reexam that is going to be conducted tomorrow, and if you miss this, there is no other chance."
        user = "test_topic_user"

        mock_send_result = {
            "success": True,
            "status": "success",
            "message": "Email delivered successfully",
            "attachments_count": 0
        }

        spoken_messages = []
        with patch("modules.assistant_email.email_controller.speak", side_effect=lambda msg: spoken_messages.append(msg)), \
             patch("modules.assistant_email.email_controller.get_credentials", return_value=("test@gmail.com", "app_pass")), \
             patch("modules.assistant_email.email_controller.send_email", return_value=mock_send_result) as mock_sender:

            res = handle_email_command(cmd, user_id=user)

            # Must succeed and indicate success
            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("status"), "success")
            self.assertEqual(res.get("recipient"), "ramsathvik.a.v@gmail.com")

            # Must NEVER have prompted for voice dictation
            for msg in spoken_messages:
                self.assertNotIn("stop message", msg.lower())
                self.assertNotIn("say your message", msg.lower())

            # Verified send_email was called with generated subject and body
            mock_sender.assert_called_once()
            call_kwargs = mock_sender.call_args[1]
            self.assertEqual(call_kwargs["to_email"], "ramsathvik.a.v@gmail.com")
            self.assertIn("re-examination", call_kwargs["subject"].lower())
            self.assertIn("tomorrow", call_kwargs["body"].lower())
            self.assertIn("no other chance", call_kwargs["body"].lower())

    def test_04_explicit_dictation_enters_recording_state(self):
        """Explicit dictation requests must activate STATE_RECORDING_EMAIL_MESSAGE with prompt."""
        cmd = "I want to dictate an email to Sathvik"
        user = "test_dictate_user"

        spoken_messages = []
        with patch("modules.assistant_email.email_controller.speak", side_effect=lambda msg: spoken_messages.append(msg)):
            res = handle_email_command(cmd, user_id=user)

            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("status"), "recording_email_message")
            self.assertEqual(_pending_email_sessions.get(user, {}).get("status"), STATE_RECORDING_EMAIL_MESSAGE)

            # Voice dictation prompt MUST be spoken
            prompt_spoken = any("stop message" in msg.lower() for msg in spoken_messages)
            self.assertTrue(prompt_spoken)

    def test_05_incomplete_request_missing_topic_prompts_only_for_topic(self):
        """When recipient is present but topic is missing, prompt only for topic without dictation."""
        cmd = "Send an email to Sathvik"
        user = "test_missing_topic_user"

        spoken_messages = []
        with patch("modules.assistant_email.email_controller.speak", side_effect=lambda msg: spoken_messages.append(msg)):
            res = handle_email_command(cmd, user_id=user)

            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("status"), "clarification")
            self.assertTrue(res.get("needs_clarification"))
            self.assertIn("What would you like the email to", res.get("message"))

            # No voice dictation prompt
            for msg in spoken_messages:
                self.assertNotIn("stop message", msg.lower())

            # Now provide purpose in next turn
            mock_send_result = {"success": True, "status": "success", "message": "Sent", "attachments_count": 0}
            with patch("modules.assistant_email.email_controller.get_credentials", return_value=("test@gmail.com", "pass")), \
                 patch("modules.assistant_email.email_controller.send_email", return_value=mock_send_result):
                res_turn2 = handle_email_command("about the reexam scheduled for tomorrow", user_id=user)
                self.assertTrue(res_turn2.get("success"))
                self.assertEqual(res_turn2.get("status"), "success")

    def test_06_incomplete_request_missing_recipient_prompts_only_for_recipient(self):
        """When topic is present but recipient is missing, prompt only for recipient without dictation."""
        cmd = "Send an email about the reexam tomorrow"
        user = "test_missing_recip_user"

        spoken_messages = []
        with patch("modules.assistant_email.email_controller.speak", side_effect=lambda msg: spoken_messages.append(msg)):
            res = handle_email_command(cmd, user_id=user)

            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("status"), "clarification")
            self.assertTrue(res.get("needs_clarification"))
            self.assertIn("Who should I send this email to?", res.get("message"))

            # Now provide recipient in next turn
            mock_send_result = {"success": True, "status": "success", "message": "Sent", "attachments_count": 0}
            with patch("modules.assistant_email.email_controller.get_credentials", return_value=("test@gmail.com", "pass")), \
                 patch("modules.assistant_email.email_controller.send_email", return_value=mock_send_result):
                res_turn2 = handle_email_command("to Sathvik", user_id=user)
                self.assertTrue(res_turn2.get("success"))
                self.assertEqual(res_turn2.get("status"), "success")
                self.assertEqual(res_turn2.get("recipient"), "ramsathvik.a.v@gmail.com")

    def test_07_explicit_draft_request_saves_draft_without_sending(self):
        """When user explicitly asks to draft an email, draft is saved and NOT sent."""
        cmd = "Can you draft an email to Sathvik about the reexam that is going to be conducted tomorrow"
        user = "test_draft_user"

        spoken_messages = []
        with patch("modules.assistant_email.email_controller.speak", side_effect=lambda msg: spoken_messages.append(msg)), \
             patch("modules.assistant_email.email_controller.send_email") as mock_sender:

            res = handle_email_command(cmd, user_id=user)

            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("status"), "draft_saved")
            self.assertIsNotNone(res.get("draft_id"))

            # send_email must NOT have been called
            mock_sender.assert_not_called()

            # Draft must be saved in storage
            drafts = list_drafts(user)
            self.assertTrue(any(d.get("recipient") == "ramsathvik.a.v@gmail.com" for d in drafts))

    def test_08_fallback_deterministic_generation_preserves_facts(self):
        """Deterministic fallback must generate professional subject and body preserving all user facts without hallucinations."""
        topic = "the reexam that is going to be conducted tomorrow, and if you miss this, there is no other chance"
        subject = generate_subject_from_text(topic)
        body = _format_fallback_body(topic, "Sathvik", tone="professional")

        self.assertIn("re-examination", subject.lower())
        self.assertIn("tomorrow", subject.lower())
        self.assertIn("Dear Sathvik,", body)
        self.assertIn("tomorrow", body.lower())
        self.assertIn("no other chance", body.lower())
        # Ensure no hallucinated venues or times
        self.assertNotIn("Room 101", body)
        self.assertNotIn("9:00 AM", body)


if __name__ == "__main__":
    unittest.main()
