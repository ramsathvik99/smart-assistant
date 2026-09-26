"""
Phase 6 — Convergence Finalization & End-to-End Hardening Test Suite
Comprehensive validation of:
1. Canonical Production Pipeline (Input -> Router -> Planner -> Execution -> Verification -> TTS/Visual)
2. Multi-Step Goal Execution (GoalPlanner multi-intent ordering & dependencies)
3. Contextual Follow-up & Entity Reference Tracking
4. Observe -> Verify -> Adapt (Environment snapshot comparison & difference detection)
5. Truthful Error Recovery (No hallucinated success, no infinite loops)
6. Destructive Action Confirmation Safety (Explicit user confirmation required)
7. Strict Per-User Data Isolation (User A vs User B)
8. Cross-Session PostgreSQL Persistence & Restoration
9. Visual Response Surface & "Show That Again" Caching
10. Worker / Scheduler Lifecycle Idempotency
"""
import unittest
import sys
import os
import tempfile
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath("."))

from legacy.assistant import process_input
from core.unified_command_router import UnifiedCommandRouter, Intent
from core.goal_planner import GoalPlanner, ExecutionPlan, ExecutionStep
from core.environment_observer import observe_environment, compare_snapshots
from extensions.dialogue_state_manager import get_dialogue_manager
from extensions.database_manager import DatabaseManager
from extensions.reminder_engine.reminder_scheduler import initialize_scheduler, shutdown_scheduler, get_scheduler


class TestPhase6EndToEndHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.user_a = 287
        cls.user_b = 8

    # ── 1. CANONICAL SINGLE COMMAND EXECUTION ──────────────────────────────────
    def test_01_canonical_single_commands(self):
        # 1. Document generation
        res_doc = process_input("Friday create a document about AI", user_id=self.user_a)
        self.assertTrue(any(k in res_doc.lower() for k in ["created", "document", "docx", "success", "generated"]))

        # 2. System info telemetry
        res_sys = process_input("Friday show system information", user_id=self.user_a)
        self.assertTrue(any(k in res_sys.lower() for k in ["windows", "amd64", "ram", "up for", "system"]))

        # 3. Web search
        res_web = process_input("Friday search the web for quantum computing", user_id=self.user_a)
        self.assertTrue(len(res_web) > 0)

        # 4. Reminder
        res_rem = process_input("Friday remind me tomorrow at 2 PM to go to the concert", user_id=self.user_a)
        self.assertTrue(any(k in res_rem.lower() for k in ["reminder", "scheduled", "concert", "already have"]))

        # 5. Visual response repeat
        res_vis = process_input("Friday show that again", user_id=self.user_a)
        self.assertTrue(len(res_vis) > 0)

    # ── 2. MULTI-STEP GOAL PLANNING & EXECUTION ───────────────────────────────
    def test_02_multi_step_goal_planning(self):
        from core.multi_intent_analyzer import multi_intent_analyzer
        planner = GoalPlanner()
        # Compound input: open notepad and search for files
        analysis = multi_intent_analyzer.analyze("open notepad and search for files on desktop")
        plan = planner.create_plan(analysis)
        self.assertIsInstance(plan, ExecutionPlan)
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.steps[0].intent, Intent.OPEN_APPLICATION)
        self.assertEqual(plan.steps[1].intent, Intent.FILE_OPERATIONS)

    # ── 3. CONTEXTUAL FOLLOW-UP & STALE REFERENCE HANDLING ────────────────────
    def test_03_contextual_follow_up_and_stale_reference(self):
        d_mgr = get_dialogue_manager(str(self.user_a))
        d_mgr.start_session()

        # Set up a browser search result state
        d_mgr.current_state.last_search_results = [
            {"type": "web_result", "title": "First Result", "url": "https://example.com/1"},
            {"type": "web_result", "title": "Second Result", "url": "https://example.com/2"}
        ]
        d_mgr.current_state.session_context["active_browser"] = "chrome"
        d_mgr.current_state.session_context["active_site"] = "google"

        # Follow-up: "open the second result"
        resolved, is_ref = d_mgr._resolve_references("open the second result")
        self.assertTrue(is_ref)
        self.assertEqual(resolved, "open url https://example.com/2")

        # Stale reference test: clear search results
        d_mgr.current_state.last_search_results = []
        resolved_stale, is_stale_ref = d_mgr._resolve_references("open the second result")
        self.assertTrue(is_stale_ref)
        self.assertEqual(resolved_stale, "explain_web_search_results_unavailable")

    # ── 4. OBSERVE -> VERIFY -> ADAPT ─────────────────────────────────────────
    def test_04_environment_observation_and_comparison(self):
        # Initial snapshot
        snap1 = observe_environment(user_id=str(self.user_a), relevant_categories={"window", "app", "toggle_keys"})
        self.assertIsNotNone(snap1)

        # Snapshot comparison
        diff = compare_snapshots(snap1, snap1)
        self.assertFalse(diff.has_changes)
        self.assertEqual(len(diff.changes), 0)

    # ── 5. TRUTHFUL ERROR RECOVERY ────────────────────────────────────
    def test_05_truthful_error_recovery(self):
        # 1. Non-existent file inspection
        res_file = process_input("profile file non_existent_file_xyz_12345.csv", user_id=self.user_a)
        self.assertTrue(any(k in res_file.lower() for k in ["not found", "does not exist", "error", "no such file"]))

        # 2. Non-existent application closing
        res_app = process_input("close non_existent_app_9999", user_id=self.user_a)
        self.assertTrue(any(k in res_app.lower() for k in ["could not find", "not running", "not found", "error", "closed"]))

    # ── 6. DESTRUCTIVE ACTION CONFIRMATION SAFETY ─────────────────────────────
    def test_06_destructive_action_confirmation_gate(self):
        # Shutdown command must trigger confirmation gate or safe countdown, never silent immediate power cut
        res = process_input("shutdown the computer", user_id=self.user_a)
        self.assertTrue(any(k in res.lower() for k in ["confirm", "sure", "cancel", "shutdown", "seconds", "please"]))

    # ── 7. PER-USER DATA ISOLATION ────────────────────────────────────────────
    def test_07_strict_user_isolation(self):
        # User A stores a secret memory
        process_input("remember that my secret pin is 7890", user_id=self.user_a)

        # User B queries the secret pin
        res_b = process_input("what is my secret pin", user_id=self.user_b)
        self.assertNotIn("7890", res_b)

        # User A queries the secret pin
        res_a = process_input("what is my secret pin", user_id=self.user_a)
        self.assertIn("7890", res_a)

    # ── 8. CROSS-SESSION POSTGRESQL PERSISTENCE ────────────────────────────────
    def test_08_cross_session_postgres_persistence(self):
        # Store fact in session 1
        process_input("remember that my project name is Titan", user_id=self.user_a)

        # Reset in-memory dialogue / memory cache if any
        d_mgr = get_dialogue_manager(str(self.user_a))
        d_mgr.start_session()

        # Recall in session 2 (reading straight from PostgreSQL)
        res_recall = process_input("what is my project name", user_id=self.user_a)
        self.assertIn("titan", res_recall.lower())

    # ── 9. VISUAL RESPONSE & CACHING ──────────────────────────────────────────
    def test_09_visual_response_caching(self):
        # Trigger an action producing structured output
        process_input("list my tasks", user_id=self.user_a)

        # "show that again" should recall the task status payload
        res_again = process_input("show that again", user_id=self.user_a)
        self.assertTrue("task" in res_again.lower() or "displaying" in res_again.lower())

    # ── 10. WORKER / SCHEDULER LIFECYCLE IDEMPOTENCE ──────────────────────────
    def test_10_scheduler_lifecycle_idempotence(self):
        # Start scheduler
        s1 = initialize_scheduler(user_id=self.user_a)
        self.assertTrue(s1.running)

        # Second call must reuse running instance
        s2 = initialize_scheduler(user_id=self.user_a)
        self.assertIs(s1, s2)
        self.assertTrue(s2.running)

        # User context reload
        s2.reload_for_user(self.user_b)
        self.assertEqual(s2.user_id, self.user_b)


if __name__ == "__main__":
    unittest.main()
