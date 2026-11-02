"""
Master Regression Suite for 30 Capability Domains
=================================================
Automated, rigorous validation across all 30 domains specified in Part C of the Master Directive:
 1. General knowledge
 2. Technical explanations
 3. Coding explanations
 4. Code generation
 5. Current time and date
 6. Historical facts
 7. Current officeholders
 8. Current events and news
 9. Personal memory
10. Persistent cross-session memory
11. Private document retrieval
12. Hybrid memory and web research
13. Mathematical questions
14. Conversational requests
15. Follow-up questions
16. Corrections
17. Negative instructions
18. Ambiguous requests
19. Misspelled requests
20. Abbreviations and slang
21. Voice and typed parity
22. Provider failures
23. Retrieval failures
24. Device targeting
25. Application control
26. Workstation operations
27. Phone operations
28. Multi-intent requests
29. Reminders and scheduling
30. Result verification and truthful reporting
"""

import sys
import os
import json
import time
import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath("."))

from core.semantic_understanding import semantic_understanding_engine
from core.target_resolver import resolve_device_target, TargetDeviceType
from core.unified_command_router import unified_router, Intent
from core.brain import brain_process
from extensions.dialogue_state_manager import get_dialogue_manager
from core.chatgpt_memory import get_chatgpt_memory


class Test30DomainsMasterSuite(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.user_id = 1
        cls.dm = get_dialogue_manager(str(cls.user_id))
        cls.mem = get_chatgpt_memory()

    # 1. General knowledge
    def test_domain_01_general_knowledge(self):
        query = "Why is the sky blue?"
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.request_type, "QUESTION")
        self.assertFalse(sem.action_required)
        self.assertEqual(sem.target_device, "none")
        self.assertIn("conversational_knowledge", sem.required_capabilities)

    # 2. Technical explanations
    def test_domain_02_technical_explanations(self):
        query = "Explain how recursion works with a base case."
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.request_type, "QUESTION")
        self.assertFalse(sem.action_required)
        self.assertIn("conversational_knowledge", sem.required_capabilities)
        self.assertIn("windows_workstation", sem.prohibited_capabilities)

    # 3. Coding explanations
    def test_domain_03_coding_explanations(self):
        query = "Explain the time complexity of binary search."
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.request_type, "QUESTION")
        self.assertFalse(sem.action_required)
        self.assertNotEqual(sem.intent, "CODE_GENERATION")

    # 4. Code generation
    def test_domain_04_code_generation(self):
        query = "Write binary search code in Python."
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.request_type, "INSTRUCTION")
        self.assertTrue(sem.action_required)
        self.assertIn(sem.intent, ("CONTENT_INSERTION", "CODE_GENERATION"))

    # 5. Current time and date
    def test_domain_05_current_time_and_date(self):
        time_q = "What is the current time?"
        sem_time = semantic_understanding_engine.interpret(time_q, user_id=self.user_id)
        self.assertEqual(sem_time.intent, "TIME_QUERY")
        self.assertFalse(sem_time.action_required)

        date_q = "What year are we currently in?"
        sem_date = semantic_understanding_engine.interpret(date_q, user_id=self.user_id)
        self.assertEqual(sem_date.intent, "DATE_QUERY")
        self.assertFalse(sem_date.action_required)

    # 6. Historical facts
    def test_domain_06_historical_facts(self):
        query = "What year did Apollo 11 land on the moon?"
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.request_type, "QUESTION")
        self.assertFalse(sem.action_required)
        self.assertNotEqual(sem.intent, "DATE_QUERY")

    # 7. Current officeholders
    def test_domain_07_current_officeholders(self):
        query = "Who is the current president of the USA?"
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.request_type, "QUESTION")
        self.assertIn(sem.intent, ("RAG_SEARCH", "GENERAL_CONVERSATION"))
        self.assertTrue(sem.parameters.get("requires_live_search", False) or sem.intent == "GENERAL_CONVERSATION")

    # 8. Current events and news
    def test_domain_08_current_events_and_news(self):
        query = "What is the latest news today?"
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.request_type, "QUESTION")
        self.assertIn(sem.intent, ("RAG_SEARCH", "GENERAL_CONVERSATION"))

    # 9. Personal memory
    def test_domain_09_personal_memory(self):
        query = "What is my university name?"
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.intent, "MEMORY_QUERY")
        self.assertEqual(sem.request_type, "QUESTION")
        self.assertFalse(sem.action_required)

    # 10. Persistent cross-session memory
    def test_domain_10_persistent_cross_session_memory(self):
        # Verify facts exist in PostgreSQL persistent store
        facts = self.mem.get_user_facts(self.user_id)
        self.assertIsInstance(facts, dict)
        self.assertTrue(len(facts) > 0, "PostgreSQL user facts must not be empty.")

    # 11. Private document retrieval
    def test_domain_11_private_document_retrieval(self):
        query = "What does my artificial neural networks report say?"
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.intent, "RAG_SEARCH")
        self.assertEqual(sem.request_type, "QUESTION")
        self.assertFalse(sem.action_required)

    # 12. Hybrid memory and web research
    def test_domain_12_hybrid_memory_and_web_research(self):
        query = "What are the job prospects for my degree?"
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.intent, "RAG_SEARCH")
        self.assertTrue(sem.parameters.get("requires_live_search", False))
        self.assertTrue(sem.parameters.get("requires_memory", False))

    # 13. Mathematical questions
    def test_domain_13_mathematical_questions(self):
        query = "Calculate 125 multiplied by 8."
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.intent, "CALCULATOR")

    # 14. Conversational requests
    def test_domain_14_conversational_requests(self):
        query = "Tell me a programming joke."
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.intent, "GENERAL_CONVERSATION")
        self.assertEqual(sem.action, "joke")
        self.assertFalse(sem.action_required)

    # 15. Follow-up questions
    def test_domain_15_follow_up_questions(self):
        query = "What about yesterday?"
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.intent, "GENERAL_CONVERSATION")
        self.assertEqual(sem.action, "follow_up_inquiry")

    # 16. Corrections
    def test_domain_16_corrections(self):
        query = "No, I meant my phone."
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.target_device, "android_phone")
        self.assertTrue(sem.is_correction)

    # 17. Negative instructions
    def test_domain_17_negative_instructions(self):
        query = "Don't open that app."
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.intent, "NEGATION")
        self.assertFalse(sem.action_required)

    # 18. Ambiguous requests
    def test_domain_18_ambiguous_requests(self):
        query = "Open open run run."
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.intent, "CLARIFICATION")
        self.assertFalse(sem.action_required)

    # 19. Misspelled requests
    def test_domain_19_misspelled_requests(self):
        query = "unloack my phone"
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.target_device, "android_phone")
        self.assertEqual(sem.intent, "DEVICE_CONTROL")

    # 20. Abbreviations and slang
    def test_domain_20_abbreviations_and_slang(self):
        query = "wats the currnt time plz"
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.intent, "TIME_QUERY")

        potus_q = "who's potus rite now"
        sem_potus = semantic_understanding_engine.interpret(potus_q, user_id=self.user_id)
        self.assertEqual(sem_potus.intent, "RAG_SEARCH")

    # 21. Voice and typed parity
    def test_domain_21_voice_and_typed_parity(self):
        # Typed execution
        typed_cmd = "what is the date"
        res_typed = unified_router.route_command(typed_cmd, user_id=self.user_id)
        self.assertEqual(res_typed[0], Intent.DATE_QUERY)

        # Voice execution with wake-word preamble
        voice_cmd = "hey trevon what is the date please"
        res_voice = unified_router.route_command(voice_cmd, user_id=self.user_id)
        self.assertEqual(res_voice[0], Intent.DATE_QUERY)

    # 22. Provider failures
    def test_domain_22_provider_failures_and_resilience(self):
        # Verify offline fallback works when LLM is unavailable
        with patch("extensions.llm_engine.LLMEngine.get_completion", return_value=None):
            res = unified_router.execute_single_action("What year did Apollo 11 land on the moon?", user_id=self.user_id)
            self.assertTrue(res.get("handled"))
            self.assertIn("1969", res.get("response", ""))

    # 23. Retrieval failures
    def test_domain_23_retrieval_failures(self):
        res = self.mem.query_user_documents(self.user_id, "nonexistent mars recipe xyz998877")
        self.assertIn(res, (None, "", []), "Nonexistent document query must return empty/None without hallucination.")

    # 24. Device targeting
    def test_domain_24_device_targeting(self):
        dev_res = resolve_device_target("Lock my phone", user_id=self.user_id)
        self.assertEqual(dev_res.target_device, TargetDeviceType.ANDROID_PHONE)

        dev_res_ws = resolve_device_target("Lock my computer", user_id=self.user_id)
        self.assertEqual(dev_res_ws.target_device, TargetDeviceType.WINDOWS_WORKSTATION)

    # 25. Application control
    def test_domain_25_application_control(self):
        query = "Open Notepad"
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.intent, "OPEN_APPLICATION")
        self.assertTrue(sem.action_required)

    # 26. Workstation operations
    def test_domain_26_workstation_operations(self):
        query = "Check my laptop battery."
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.target_device, "windows_workstation")
        self.assertIn("windows_workstation", sem.required_capabilities)

    # 27. Phone operations
    def test_domain_27_phone_operations(self):
        query = "Check my phone battery."
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.target_device, "android_phone")
        self.assertIn("android_device", sem.required_capabilities)
        self.assertIn("windows_workstation", sem.prohibited_capabilities)

    # 28. Multi-intent requests
    def test_domain_28_multi_intent_requests(self):
        query = "Calculate 15 + 25 and what time is it"
        from core.multi_intent_analyzer import multi_intent_analyzer
        analysis = multi_intent_analyzer.analyze(query)
        self.assertTrue(analysis.has_multiple_intents)
        self.assertEqual(len(analysis.intents), 2)

    # 29. Reminders and scheduling
    def test_domain_29_reminders_and_scheduling(self):
        query = "Set a reminder to submit the report tomorrow at 5pm."
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.intent, "REMINDERS")
        self.assertEqual(sem.action, "create")
        self.assertTrue(sem.action_required)

    # 30. Result verification and truthful reporting
    def test_domain_30_result_verification_and_truthful_reporting(self):
        query = "Are you sure?"
        sem = semantic_understanding_engine.interpret(query, user_id=self.user_id)
        self.assertEqual(sem.intent, "GENERAL_CONVERSATION")
        self.assertEqual(sem.action, "conversational_verification")
        self.assertFalse(sem.action_required)


if __name__ == "__main__":
    unittest.main()
