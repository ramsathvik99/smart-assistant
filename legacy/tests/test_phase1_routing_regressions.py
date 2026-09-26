"""
Test Suite for Phase 1 Routing Regressions Repair.
Validates:
1. Document Generation natural language variations (present and past tense verbs, with/without assistant names).
2. Conversational queries directed at assistant remain GENERAL_CONVERSATION and are NOT hijacked by RAG_SEARCH.
3. Information retrieval queries correctly route to RAG_SEARCH.
4. Known-good commands (music, reminders, apps, system controls) preserve deterministic resolution.
5. Production path execution verification for all required test queries.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch

from core.unified_command_router import UnifiedCommandRouter, Intent


class TestPhase1RoutingRegressions(unittest.TestCase):

    def setUp(self):
        self.router = UnifiedCommandRouter()
        self.router._semantic_enabled = False  # Pure deterministic verification

    # ── 1. DOCUMENT GENERATION INTENT & ROUTE TESTS ───────────────────────────
    def test_01_document_generation_queries(self):
        doc_queries = [
            ("create a document about AI", Intent.DOCUMENT_GENERATION, "docx"),
            ("created a document about AI", Intent.DOCUMENT_GENERATION, "docx"),
            ("generate a report about AI", Intent.DOCUMENT_GENERATION, "docx"),
            ("generated a report about AI", Intent.DOCUMENT_GENERATION, "docx"),
            ("make a document about AI", Intent.DOCUMENT_GENERATION, "docx"),
            ("made a document about AI", Intent.DOCUMENT_GENERATION, "docx"),
            ("write a document about AI", Intent.DOCUMENT_GENERATION, "docx"),
            ("wrote a document about AI", Intent.DOCUMENT_GENERATION, "docx"),
            ("build a document about AI", Intent.DOCUMENT_GENERATION, "docx"),
            ("built a document about AI", Intent.DOCUMENT_GENERATION, "docx"),
            ("Friday create a document about AI", Intent.DOCUMENT_GENERATION, "docx"),
            ("Friday created a document about AI", Intent.DOCUMENT_GENERATION, "docx"),
        ]

        for query, expected_intent, expected_doctype in doc_queries:
            with self.subTest(query=query):
                intent, params = self.router.route_command(query)
                self.assertEqual(
                    intent,
                    expected_intent,
                    f"Query '{query}' resolved to {intent.name}, expected {expected_intent.name}"
                )
                self.assertEqual(
                    params.get("doc_type"),
                    expected_doctype,
                    f"Query '{query}' had doc_type '{params.get('doc_type')}', expected '{expected_doctype}'"
                )

    # ── 2. CONVERSATION DIRECTED AT ASSISTANT (NOT RAG HIJACKED) ───────────────
    def test_02_conversational_queries_not_hijacked_by_rag(self):
        conversational_queries = [
            "Friday why are you doing this",
            "Friday why did you do that",
            "Friday who are you",
            "Friday what can you do",
            "Friday what are you doing",
            "Friday how are you doing",
            "why are you doing this",
            "why did you say that",
            "who are you",
            "what can you do",
            "what are you doing",
            "how are you doing",
        ]

        for query in conversational_queries:
            with self.subTest(query=query):
                intent, params = self.router.route_command(query)
                self.assertEqual(
                    intent,
                    Intent.GENERAL_CONVERSATION,
                    f"Conversational query '{query}' was hijacked by {intent.name}, expected GENERAL_CONVERSATION"
                )

    # ── 3. INFORMATION RETRIEVAL (RAG_SEARCH) ─────────────────────────────────
    def test_03_genuine_information_queries_reach_rag(self):
        rag_queries = [
            "why is the sky blue",
            "what is quantum computing",
            "who is the president of India",
            "when was Python created",
            "how does TCP work",
        ]

        for query in rag_queries:
            with self.subTest(query=query):
                intent, params = self.router.route_command(query)
                self.assertEqual(
                    intent,
                    Intent.RAG_SEARCH,
                    f"Information query '{query}' resolved to {intent.name}, expected RAG_SEARCH"
                )

    # ── 4. KNOWN-GOOD SYSTEM COMMANDS ─────────────────────────────────────────
    def test_04_known_good_commands_preserve_deterministic_routing(self):
        known_good = [
            ("play Telugu songs", Intent.MUSIC),
            ("play music", Intent.MUSIC),
            ("remind me to call mom at 6 PM", Intent.REMINDERS),
            ("open Chrome", Intent.OPEN_APPLICATION),
            ("turn up the volume", Intent.DEVICE_CONTROL),
        ]

        for query, expected_intent in known_good:
            with self.subTest(query=query):
                intent, params = self.router.route_command(query)
                self.assertEqual(
                    intent,
                    expected_intent,
                    f"Known-good command '{query}' resolved to {intent.name}, expected {expected_intent.name}"
                )

    # ── 5. PRODUCTION PATH EXECUTION ROUTING ───────────────────────────────────
    def test_05_production_path_execution(self):
        # 1. Document Generation routes to DocumentTools (mocking disk write to keep test fast)
        with patch("modules.document_tools.create_docx_document") as mock_docx:
            mock_docx.return_value = {"success": True, "filepath": "data/users/1/docs/test_ai.docx", "message": "Word document created."}
            res = self.router.execute_single_action("Friday created a document about AI", user_id=1)
            self.assertEqual(res["intent"], "DOCUMENT_GENERATION")
            self.assertEqual(res["status"], "success")
            mock_docx.assert_called_once()

        # 2. Conversational query routes to Dialogue/Conversation
        res = self.router.execute_single_action("Friday why are you doing this", user_id=1)
        self.assertEqual(res["intent"], "GENERAL_CONVERSATION")


if __name__ == "__main__":
    unittest.main()
