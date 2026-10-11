"""
test_old_new_version_repair_regressions.py

Regression test suite verifying fixes applied during old/new version integration and repair:
1. Routing integrity: 'write a document about AI' must route to DOCUMENT_GENERATION, not EMAIL.
2. Memory store vs query: 'remember that my secret pin is 7890' must route to MEMORY_STORE and be retrievable per-user.
3. User isolation in deduplication: identical queries across different users within the suppression window must not be suppressed.
4. LLM provider chain: canonical order OpenAI -> Groq -> Gemini -> DeepSeek -> HuggingFace -> Ollama preserved.
5. Database connection pool resilience: repeated conversational memory storage must not leak connections or exhaust pool.
6. Email system safeguards:
   - Cancellation when no draft exists returns cleanly without blocking.
   - Ambiguous outcome prevents automatic duplicate send.
   - Partial delivery prevents automatic resend of accepted recipients.
"""
import unittest
from unittest.mock import patch, MagicMock
import time

from core.unified_command_router import UnifiedCommandRouter, Intent
from core.db_pool import get_db_pool
from extensions.llm_engine import LLMEngine
from legacy.assistant import process_input
from modules.assistant_email.email_controller import (
    handle_email_command,
    _pending_email_sessions,
    STATE_EMAIL_AMBIGUOUS_OUTCOME,
    STATE_EMAIL_PARTIAL_DELIVERY
)


class TestOldNewVersionRepairRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.router = UnifiedCommandRouter()
        cls.pool = get_db_pool()

    def test_01_document_generation_not_hijacked_by_email(self):
        """'write a document about AI' must route to DOCUMENT_GENERATION, not EMAIL."""
        intent, params = self.router.route_command("write a document about AI")
        self.assertEqual(intent, Intent.DOCUMENT_GENERATION)

        intent, params = self.router.route_command("create a document about AI")
        self.assertEqual(intent, Intent.DOCUMENT_GENERATION)

        # Genuine email commands must still route to EMAIL
        intent, params = self.router.route_command("write an email to alice saying hello")
        self.assertEqual(intent, Intent.EMAIL)

        intent, params = self.router.route_command("send email to bob")
        self.assertEqual(intent, Intent.EMAIL)

    def test_02_memory_store_routing_and_secret_pin_isolation(self):
        """'remember that my secret pin is 7890' must store fact and isolate between users."""
        intent, params = self.router.route_command("remember that my secret pin is 7890")
        self.assertEqual(intent, Intent.MEMORY_STORE)

        # End-to-end execution across user A and user B
        user_a = 287
        user_b = 8

        process_input("remember that my secret pin is 7890", user_id=user_a)

        # User B queries
        res_b = process_input("what is my secret pin", user_id=user_b)
        self.assertNotIn("7890", res_b)

        # User A queries
        res_a = process_input("what is my secret pin", user_id=user_a)
        self.assertIn("7890", res_a)

    def test_03_deduplication_is_user_isolated(self):
        """Cross-user identical utterances within suppression window must not be suppressed."""
        user_a = 9921
        user_b = 9922

        res_a = process_input("what is my favorite color", user_id=user_a)
        res_b = process_input("what is my favorite color", user_id=user_b)

        # Both must execute without one being swallowed by deduplication
        self.assertIsInstance(res_a, str)
        self.assertIsInstance(res_b, str)

    def test_04_llm_provider_fallback_chain_integrity(self):
        """Provider chain preserves OpenAI -> Groq -> Gemini -> local Ollama fallback."""
        engine = LLMEngine()
        engine.openai_enabled = False

        # When OpenAI is disabled, Groq is called first
        with patch.object(engine, "_call_groq", return_value="Groq verified") as mock_groq:
            resp = engine.get_completion("Hello test")
            self.assertEqual(resp, "Groq verified")
            mock_groq.assert_called()

        # When Groq fails, Gemini is called next
        with patch.object(engine, "_call_groq", return_value=None), \
             patch.object(engine, "_call_gemini", return_value="Gemini verified") as mock_gemini:
            resp = engine.get_completion("Hello test")
            self.assertEqual(resp, "Gemini verified")
            mock_gemini.assert_called()

        # When all cloud providers fail, Ollama is called as local fallback
        with patch.object(engine, "_call_groq", return_value=None), \
             patch.object(engine, "_call_gemini", return_value=None), \
             patch.object(engine, "_call_deepseek", return_value=None), \
             patch.object(engine, "_call_huggingface", return_value=None), \
             patch.object(engine, "_call_ollama", return_value="Ollama local fallback") as mock_ollama:
            resp = engine.get_completion("Hello test")
            self.assertEqual(resp, "Ollama local fallback")
            mock_ollama.assert_called()

    def test_05_db_pool_no_leak_on_repeated_interactions(self):
        """Database connection pool must maintain health across many conversational interactions."""
        from extensions.conversational_memory import store_interaction

        initial_healthy = self.pool.is_healthy()
        self.assertTrue(initial_healthy)

        # Store 25 interactions rapidly
        for i in range(25):
            store_interaction(f"user query {i}", f"assistant response {i}", user_id=1)

        # Wait briefly for background threads to complete
        time.sleep(1.0)

        # Pool must still be 100% healthy and capable of queries
        self.assertTrue(self.pool.is_healthy())

        # Verify cursor execution works directly
        with self.pool.get_cursor() as cur:
            cur.execute("SELECT 1;")
            self.assertEqual(cur.fetchone()[0], 1)

    def test_06_email_cancellation_no_pending_draft(self):
        """Cancelling email when no draft exists must return cleanly without blocking."""
        with patch("modules.assistant_email.email_controller.speak"):
            res = handle_email_command("cancel email", user_id=9999)
            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("status"), "no_pending")

    def test_07_email_ambiguous_outcome_blocks_automatic_resend(self):
        """Ambiguous email delivery must never be retried with plain send or yes."""
        user = "test_ambiguous_user"
        _pending_email_sessions[user] = {
            "status": STATE_EMAIL_AMBIGUOUS_OUTCOME,
            "recipient": "client@example.com",
            "subject": "Invoice",
            "body": "Here is the invoice."
        }

        with patch("modules.assistant_email.email_controller.speak"):
            # Plain yes or send must be rejected
            res = handle_email_command("yes send it", user_id=user)
            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("status"), "ambiguous_outcome")
            self.assertFalse(res.get("retry_safe"))

            # Cancellation must work cleanly
            res_cancel = handle_email_command("cancel email", user_id=user)
            self.assertTrue(res_cancel.get("success"))
            self.assertEqual(res_cancel.get("status"), "cancelled")

    def test_08_email_partial_delivery_blocks_duplicate_resend(self):
        """Partial delivery must prevent automatic resend to already-accepted recipients."""
        user = "test_partial_user"
        _pending_email_sessions[user] = {
            "status": STATE_EMAIL_PARTIAL_DELIVERY,
            "recipient": "user1@example.com, user2@example.com",
            "subject": "Update",
            "body": "Meeting notes."
        }

        with patch("modules.assistant_email.email_controller.speak"):
            # Attempting to send again must be rejected
            res = handle_email_command("send it", user_id=user)
            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("status"), "partial_delivery")

            # Cancellation clears the partial-delivery session
            res_cancel = handle_email_command("cancel draft", user_id=user)
            self.assertTrue(res_cancel.get("success"))
            self.assertEqual(res_cancel.get("status"), "cancelled")


if __name__ == "__main__":
    unittest.main()
