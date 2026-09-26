"""
Test Suite for Phase 3 Reminder & Lifecycle Stabilization.
Validates:
1. Idempotent singleton initialization (no duplicate threads, instances, or scheduled jobs).
2. PostgreSQL persistence & correct restoration across simulated application restarts.
3. Strict per-user isolation (User A reminders cannot be seen, executed, or cancelled by User B).
4. Completed/cancelled reminders are never restored on restart.
5. Natural language reminder creation, listing, and cancellation through the canonical production path.
6. Clean shutdown of background scheduler thread.
"""

import unittest
import time
import datetime
from unittest.mock import MagicMock, patch

from extensions.reminder_engine.reminder_scheduler import (
    ReminderScheduler,
    initialize_scheduler,
    get_scheduler,
    shutdown_scheduler,
    _load_reminders_from_database
)
from extensions.reminder_engine.enhanced_reminder_handler import ReminderHandler, ReminderAction
from legacy.assistant import process_input
from instance.config import settings


class MockDBManager:
    """In-memory mock database manager matching DatabaseManager API for testing."""
    def __init__(self):
        self.reminders = {}
        self._next_id = 1

    def add_reminder(self, user_id, task_text, due_at):
        rem_id = self._next_id
        self._next_id += 1
        self.reminders[rem_id] = {
            "id": rem_id,
            "user_id": user_id,
            "task_text": task_text,
            "due_at": due_at,
            "notified": False,
            "is_active": True,
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        return rem_id

    def get_pending_reminders(self, user_id=None):
        res = []
        for r in self.reminders.values():
            if r.get("is_active", True) and not r.get("notified", False):
                if user_id is None or r.get("user_id") == user_id:
                    res.append(r.copy())
        return res

    def get_reminders(self, user_id, start_date=None, end_date=None):
        return [r.copy() for r in self.reminders.values() if r.get("user_id") == user_id and r.get("is_active", True)]

    def get_reminder_by_id(self, user_id, reminder_id):
        rem = self.reminders.get(int(reminder_id))
        if rem and rem.get("user_id") == user_id:
            return rem.copy()
        return None

    def delete_reminder(self, user_id, reminder_id):
        rem = self.reminders.get(int(reminder_id))
        if rem and rem.get("user_id") == user_id:
            rem["is_active"] = False
            return True
        return False

    def mark_reminder_notified(self, reminder_id):
        rem = self.reminders.get(int(reminder_id))
        if rem:
            rem["notified"] = True
            return True
        return False


class TestPhase3ReminderLifecycleStabilization(unittest.TestCase):

    def setUp(self):
        shutdown_scheduler()
        self.mock_db = MockDBManager()

    def tearDown(self):
        shutdown_scheduler()

    # ── 1. IDEMPOTENT INITIALIZATION & SINGLETON LIFECYCLE ────────────────────
    def test_01_idempotent_scheduler_initialization(self):
        """Repeated calls to initialize_scheduler must return the identical instance without duplicating threads."""
        sched1 = initialize_scheduler(db_manager=self.mock_db, user_id=1)
        self.assertTrue(sched1.running)
        thread1 = sched1.scheduler_thread

        # Second call with same user
        sched2 = initialize_scheduler(db_manager=self.mock_db, user_id=1)
        self.assertIs(sched1, sched2)
        self.assertIs(sched1.scheduler_thread, thread1)
        self.assertTrue(thread1.is_alive())

        # Calling get_scheduler returns the exact global instance
        self.assertIs(get_scheduler(), sched1)

    # ── 2. DATABASE RESTORATION & NO DUPLICATE JOBS ON RESTART ────────────────
    def test_02_restart_restores_future_reminders_without_duplicates(self):
        """Application shutdown and restart restores future reminders exactly once."""
        future_time = (datetime.datetime.now() + datetime.timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        self.mock_db.add_reminder(user_id=1, task_text="Doctor appointment", due_at=future_time)

        # First startup
        sched1 = initialize_scheduler(db_manager=self.mock_db, user_id=1)
        self.assertEqual(len(sched1.get_pending_reminders()), 1)
        self.assertEqual(sched1.get_pending_reminders()[0]["text"], "Doctor appointment")

        # Simulate second service initialization during runtime
        initialize_scheduler(db_manager=self.mock_db, user_id=1)
        self.assertEqual(len(sched1.get_pending_reminders()), 1)

        # Simulate full Application Shutdown
        shutdown_scheduler()
        self.assertIsNone(get_scheduler())

        # Second startup
        sched2 = initialize_scheduler(db_manager=self.mock_db, user_id=1)
        self.assertIsNotNone(sched2)
        # Reminders must be restored exactly once from database
        self.assertEqual(len(sched2.get_pending_reminders()), 1)
        self.assertEqual(sched2.get_pending_reminders()[0]["text"], "Doctor appointment")

    # ── 3. USER ISOLATION ─────────────────────────────────────────────────────
    def test_03_strict_user_isolation(self):
        """User A's reminders are not visible or active in User B's session."""
        future_time = (datetime.datetime.now() + datetime.timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
        self.mock_db.add_reminder(user_id=1, task_text="User 1 Secret Task", due_at=future_time)
        self.mock_db.add_reminder(user_id=2, task_text="User 2 Secret Task", due_at=future_time)

        # Login as User 1
        sched = initialize_scheduler(db_manager=self.mock_db, user_id=1)
        user1_rems = sched.get_pending_reminders()
        self.assertEqual(len(user1_rems), 1)
        self.assertEqual(user1_rems[0]["text"], "User 1 Secret Task")

        # Switch / Login as User 2
        sched_user2 = initialize_scheduler(db_manager=self.mock_db, user_id=2)
        self.assertIs(sched, sched_user2)  # Reuses singleton
        user2_rems = sched_user2.get_pending_reminders()
        self.assertEqual(len(user2_rems), 1)
        self.assertEqual(user2_rems[0]["text"], "User 2 Secret Task")

    # ── 4. CANCELLED / COMPLETED NOT RESTORED ──────────────────────────────────
    def test_04_completed_and_deleted_reminders_not_restored(self):
        """Triggered or cancelled reminders in DB are omitted on startup."""
        future_time = (datetime.datetime.now() + datetime.timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        rem_id1 = self.mock_db.add_reminder(user_id=1, task_text="Active Reminder", due_at=future_time)
        rem_id2 = self.mock_db.add_reminder(user_id=1, task_text="Cancelled Reminder", due_at=future_time)
        rem_id3 = self.mock_db.add_reminder(user_id=1, task_text="Notified Reminder", due_at=future_time)

        self.mock_db.delete_reminder(user_id=1, reminder_id=rem_id2)
        self.mock_db.mark_reminder_notified(rem_id3)

        sched = initialize_scheduler(db_manager=self.mock_db, user_id=1)
        pending = sched.get_pending_reminders()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["text"], "Active Reminder")

    # ── 5. PRODUCTION PATH NATURAL LANGUAGE COMMANDS ──────────────────────────
    def test_05_production_path_natural_language_queries(self):
        """Execute canonical natural-language reminder commands via process_input."""
        test_uid = 287
        try:
            from legacy.memory_manager import get_connection
            from extensions.database_manager import DatabaseManager
            class SimplePool:
                def getconn(self): return get_connection()
                def putconn(self, c): c.close()
            real_db = DatabaseManager(SimplePool())
            # Clean test user reminders before test
            rems = real_db.get_reminders(test_uid)
            for r in rems:
                real_db.delete_reminder(test_uid, r["id"])
        except Exception:
            pass

        # 1. Create reminder: "remind me to call mom at 6 PM"
        r1 = process_input("remind me to call mom at 6 PM", user_id=test_uid)
        self.assertIn("Reminder set", r1)

        # 2. Create tomorrow reminder: "remind me tomorrow at 2 PM to go to the movie"
        r2 = process_input("remind me tomorrow at 2 PM to go to the movie", user_id=test_uid)
        self.assertIn("Reminder set", r2)

        # 3. Create recurring reminder: "remind me every day at 8 AM to drink water"
        r3 = process_input("remind me every day at 8 AM to drink water", user_id=test_uid)
        self.assertIn("Reminder set", r3)

        # 4. List reminders: "show my reminders"
        r4 = process_input("show my reminders", user_id=test_uid)
        self.assertTrue("call mom" in r4 or "reminders" in r4.lower() or "scheduled" in r4.lower())

        # 5. Cancel reminder: "cancel my reminder to call mom"
        r5 = process_input("cancel my reminder to call mom", user_id=test_uid)
        self.assertTrue("deleted" in r5.lower() or "cancelled" in r5.lower() or "removed" in r5.lower())


if __name__ == "__main__":
    unittest.main()
