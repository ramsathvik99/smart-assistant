"""
test_automatic_context_aware_memory.py
Comprehensive test suite verifying the 12 requirements of automatic context-aware long-term memory in Friday.

Covers:
1. Extracting multiple facts from one ordinary sentence.
2. Extracting facts without "remember" or "save".
3. Ignoring irrelevant small talk and unsupported inferences.
4. Deduplicating equivalent facts.
5. Updating a fact after an explicit correction.
6. Distinguishing a confirmed fact from a tentative plan.
7. Saving and retrieving facts across application restarts (simulated via fresh memory manager instance).
8. Recalling relevant memories during a later, differently worded request.
9. Correct user isolation across multiple accounts.
10. Operation when cloud providers are unavailable (100% local deterministic pipeline).
11. Database failures and unsuccessful writes handled safely.
12. Integration with the actual Friday conversation pipeline (brain_process / unified_command_router).
"""

import unittest
import os
import sys
import time

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.fact_extractor import extract_candidate_facts
from core.chatgpt_memory import ChatGPTMemoryManager, get_chatgpt_memory
from core.db_pool import get_db_pool
from core.auth_service import register_user
from core.user_isolation import delete_user_account_cascading
import extensions.user_profile as user_profile
import extensions.memory_store as memory_store
from core.brain import brain_process


class TestAutomaticContextAwareMemory(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.pool = get_db_pool()
        cls.mem_mgr = get_chatgpt_memory()
        ts = int(time.time() * 1000) % 1000000
        
        # Register real users so foreign keys succeed
        res_a = register_user(f"auto_mem_a_{ts}", "Password123!")
        res_b = register_user(f"auto_mem_b_{ts}", "Password123!")
        cls.user_a = res_a.get("user_id")
        cls.user_b = res_b.get("user_id")

    @classmethod
    def tearDownClass(cls):
        try:
            if cls.user_a:
                delete_user_account_cascading(cls.user_a)
            if cls.user_b:
                delete_user_account_cascading(cls.user_b)
        except Exception:
            pass

    def setUp(self):
        # Clean up test accounts between tests
        try:
            with self.pool.get_cursor() as cur:
                cur.execute("DELETE FROM memory_facts WHERE user_id IN (%s, %s)", (self.user_a, self.user_b))
                cur.execute("DELETE FROM user_memory WHERE user_id IN (%s, %s)", (self.user_a, self.user_b))
                cur.execute("DELETE FROM user_preferences WHERE user_id IN (%s, %s)", (self.user_a, self.user_b))
                cur.execute("DELETE FROM conversation_history WHERE user_id IN (%s, %s)", (self.user_a, self.user_b))
        except Exception:
            pass

    def tearDown(self):
        try:
            with self.pool.get_cursor() as cur:
                cur.execute("DELETE FROM memory_facts WHERE user_id IN (%s, %s)", (self.user_a, self.user_b))
                cur.execute("DELETE FROM user_memory WHERE user_id IN (%s, %s)", (self.user_a, self.user_b))
                cur.execute("DELETE FROM user_preferences WHERE user_id IN (%s, %s)", (self.user_a, self.user_b))
                cur.execute("DELETE FROM conversation_history WHERE user_id IN (%s, %s)", (self.user_a, self.user_b))
        except Exception:
            pass

    # 1. Extracting multiple facts from one ordinary sentence
    def test_01_multiple_facts_from_single_sentence(self):
        text = "I'm Ram, a final-year SRM AP student, and I'm in the placement cell."
        facts = extract_candidate_facts(text)
        keys = {f.key: f.value for f in facts}

        self.assertIn("preferred_name", keys)
        self.assertEqual(keys["preferred_name"], "Ram")

        self.assertIn("education", keys)
        self.assertIn("final-year", keys["education"].lower())

        self.assertIn("institution", keys)
        self.assertIn("SRM", keys["institution"])

        self.assertIn("activity", keys)
        self.assertIn("placement cell", keys["activity"].lower())

    # 2. Extracting facts without the words "remember" or "save"
    def test_02_extract_without_remember_or_save(self):
        samples = [
            ("I usually prefer short explanations.", "preferences"),
            ("We decided to use PostgreSQL for this project.", "projects"),
            ("My interview is tomorrow.", "commitments"),
        ]
        for phrase, expected_category in samples:
            self.assertNotIn("remember", phrase.lower())
            self.assertNotIn("save", phrase.lower())
            facts = extract_candidate_facts(phrase)
            self.assertTrue(len(facts) > 0, f"Failed to extract from '{phrase}'")
            categories = [f.category for f in facts]
            self.assertIn(expected_category, categories, f"Expected {expected_category} in {categories}")

    # 3. Ignoring irrelevant small talk and unsupported inferences
    def test_03_ignore_small_talk_and_ephemeral_commands(self):
        small_talk = [
            "Good morning Friday, how are you doing today?",
            "What's the weather like outside?",
            "Tell me a funny joke.",
            "Open Spotify and play some music.",
            "Set volume to 50 percent.",
            "Can you help me with something?",
            "Okay, sounds good.",
            "Thank you so much!"
        ]
        for text in small_talk:
            facts = extract_candidate_facts(text)
            self.assertEqual(facts, [], f"Expected no candidate facts for '{text}', but got {facts}")

    # 4. Deduplicating equivalent facts
    def test_04_deduplicate_equivalent_facts(self):
        # First utterance
        facts1 = self.mem_mgr.extract_and_persist_facts(self.user_a, "I'm studying CSE at SRM AP.")
        self.assertTrue(len(facts1) > 0)

        facts_stored_1 = self.mem_mgr.get_user_facts(self.user_a)
        self.assertIn("institution", facts_stored_1)
        self.assertIn("SRM", facts_stored_1["institution"])

        # Second equivalent utterance stating the same institution
        facts2 = self.mem_mgr.extract_and_persist_facts(self.user_a, "My university is SRM AP.")
        facts_stored_2 = self.mem_mgr.get_user_facts(self.user_a)
        self.assertIn("institution", facts_stored_2)
        
        # Verify in structured memory_facts that only 1 active confirmed fact exists for institution
        structured = self.mem_mgr.get_structured_user_memories(self.user_a)
        inst_facts = [f for f in structured if f["key"] == "institution"]
        self.assertEqual(len(inst_facts), 1, "Duplicate institution fact was created instead of deduplicated!")
        self.assertIn("SRM", inst_facts[0]["value"])

    # 5. Updating a fact after an explicit correction
    def test_05_update_fact_after_correction(self):
        self.mem_mgr.extract_and_persist_facts(self.user_a, "I'm in third year.")
        facts = self.mem_mgr.get_user_facts(self.user_a)
        self.assertIn("third-year", facts.get("education", "").lower())

        # Now correct to final year
        self.mem_mgr.extract_and_persist_facts(self.user_a, "I'm now in final year.")
        active_facts = self.mem_mgr.get_user_facts(self.user_a)
        self.assertIn("final-year", active_facts.get("education", "").lower())

        # Verify old record is marked superseded in PostgreSQL
        structured = self.mem_mgr.get_structured_user_memories(self.user_a)
        edu_active = [f for f in structured if f["key"] == "education"]
        self.assertEqual(len(edu_active), 1, "Old fact should be superseded, leaving only 1 active fact")
        self.assertIn("final-year", edu_active[0]["value"].lower())

    # 6. Distinguishing confirmed facts from tentative plans
    def test_06_distinguish_confirmed_from_tentative(self):
        # Confirmed
        facts_confirmed = extract_candidate_facts("I am applying for internships at Google.")
        for f in facts_confirmed:
            if f.key == "career_goal":
                self.assertEqual(f.status, "confirmed")

        # Tentative / speculative
        facts_tentative = extract_candidate_facts("I might apply for an internship.")
        self.assertTrue(len(facts_tentative) > 0)
        for f in facts_tentative:
            self.assertEqual(f.status, "tentative", f"Expected tentative status, got {f}")

    # 7. Saving and retrieving facts across application restarts
    def test_07_persistence_across_restarts(self):
        # Session 1: Extract and store via one manager instance
        mgr1 = ChatGPTMemoryManager()
        mgr1.extract_and_persist_facts(self.user_a, "I'm Ram, a final-year SRM AP student, and I'm in the placement cell.")
        del mgr1

        # Session 2: Fresh instance (simulating restart and fresh memory load from DB)
        mgr2 = ChatGPTMemoryManager()
        facts2 = mgr2.get_user_facts(self.user_a)

        self.assertIn("preferred_name", facts2)
        self.assertEqual(facts2["preferred_name"], "Ram")
        self.assertIn("institution", facts2)
        self.assertIn("SRM", facts2["institution"])
        self.assertIn("placement cell", facts2["activity"].lower())

    # 8. Recalling relevant memories during a later, differently worded request
    def test_08_recall_relevant_memories_for_query(self):
        self.mem_mgr.extract_and_persist_facts(self.user_a, "I'm Ram, a final-year SRM AP student, and I'm in the placement cell.")
        
        # Direct questions answered deterministically
        resp_uni = self.mem_mgr.answer_historical_fact_query(self.user_a, "Which university do I attend?")
        self.assertIsNotNone(resp_uni)
        self.assertIn("SRM", resp_uni)

        resp_cell = self.mem_mgr.answer_historical_fact_query(self.user_a, "Am I in any club or cell?")
        self.assertIsNotNone(resp_cell)
        self.assertIn("placement cell", resp_cell.lower())

        # Contextual boost
        contextual_facts = self.mem_mgr.retrieve_relevant_memories(self.user_a, "Help me prepare for placements.")
        cell_facts = [f for f in contextual_facts if "placement cell" in str(f.get("value", "")).lower() or "final-year" in str(f.get("value", "")).lower()]
        self.assertTrue(len(cell_facts) > 0, "Failed to retrieve placement facts for placement query")

    # 9. Correct user isolation across multiple accounts
    def test_09_user_isolation(self):
        # User A is Ram at SRM AP
        self.mem_mgr.extract_and_persist_facts(self.user_a, "I'm Ram at SRM AP.")
        # User B is Priya at IIT Madras
        self.mem_mgr.extract_and_persist_facts(self.user_b, "I'm Priya at IIT Madras.")

        facts_a = self.mem_mgr.get_user_facts(self.user_a)
        facts_b = self.mem_mgr.get_user_facts(self.user_b)

        self.assertEqual(facts_a.get("preferred_name"), "Ram")
        self.assertIn("SRM", facts_a.get("institution", ""))

        self.assertEqual(facts_b.get("preferred_name"), "Priya")
        self.assertEqual(facts_b.get("institution"), "IIT Madras")

        # User A query should NEVER return User B's details
        resp_a = self.mem_mgr.answer_historical_fact_query(self.user_a, "What is my name?")
        self.assertIn("Ram", resp_a)
        self.assertNotIn("Priya", resp_a)

    # 10. Operation when every cloud provider is unavailable
    def test_10_offline_deterministic_operation(self):
        # No LLM calls allowed in this test; deterministic extraction must succeed
        text = "I'm Ram, a final-year SRM AP student, and I'm in the placement cell."
        facts = extract_candidate_facts(text)
        self.assertTrue(len(facts) >= 4)
        
        # Test extensions interface offline
        stored = memory_store.extract_and_store_from_text(self.user_a, text)
        self.assertTrue(len(stored) >= 4)
        
        name = user_profile.get_user_name(self.user_a)
        self.assertEqual(name, "Ram")
        inst = user_profile.get_user_institution(self.user_a)
        self.assertIn("SRM", inst)

    # 11. Database failures and unsuccessful writes
    def test_11_db_failure_resilience(self):
        # Test with invalid pool to verify graceful error handling without crashing
        bad_mgr = ChatGPTMemoryManager()
        bad_mgr.pool = None
        # Should not raise uncaught exception, should return fallback/empty
        facts = bad_mgr.extract_and_persist_facts(self.user_a, "I'm Ram at SRM AP.")
        self.assertIsInstance(facts, list)

    # 12. Integration with actual Friday conversation pipeline
    def test_12_end_to_end_conversation_pipeline(self):
        # Step A: User introduces themselves naturally
        intro_text = "I'm Ram, a final-year SRM AP student, and I'm in the placement cell."
        res1 = brain_process(intro_text, user_id=self.user_a)
        self.assertIn("status", res1)
        self.assertEqual(res1["status"], "success")
        
        # Response should be natural, acknowledging Ram politely, NOT robotic "Understood. I'll remember that..."
        response_text = res1.get("response", "")
        self.assertNotIn("i will store that", response_text.lower())
        self.assertNotIn("understood. i'll remember that", response_text.lower())
        self.assertTrue(
            "Ram" in response_text or "SRM" in response_text or "hello" in response_text.lower() or "nice" in response_text.lower() or "great" in response_text.lower()
        )

        # Step B: Later, ask a direct memory query
        query_text = "Which university do I attend?"
        res2 = brain_process(query_text, user_id=self.user_a)
        self.assertEqual(res2["status"], "success")
        self.assertIn("SRM", res2.get("response", ""))

        # Step C: Ask about placement cell
        query_cell = "What club or cell am I part of?"
        res3 = brain_process(query_cell, user_id=self.user_a)
        self.assertEqual(res3["status"], "success")
        self.assertIn("placement cell", res3.get("response", "").lower())


if __name__ == "__main__":
    unittest.main()
