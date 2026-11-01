import os
import sys
import time
import datetime
import threading
from typing import Dict, Any

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.unified_command_router import unified_router
from extensions.database_manager import DatabaseManager
from extensions.reminder_engine.reminder_scheduler import (
    ReminderScheduler,
    initialize_scheduler,
    get_scheduler,
    shutdown_scheduler
)

# Test User IDs (using established test users in PostgreSQL users table)
USER_A = 500
USER_B = 501
USER_C = 502

def get_db():
    from legacy.memory_manager import get_connection
    class SimplePoolWrapper:
        def __init__(self, conn_func):
            self.conn_func = conn_func
        def getconn(self):
            return self.conn_func()
        def putconn(self, conn):
            try:
                conn.close()
            except:
                pass
    return DatabaseManager(SimplePoolWrapper(get_connection))

def cleanup_test_data(db):
    try:
        with db._get_cursor() as cur:
            cur.execute("DELETE FROM reminders WHERE user_id IN (%s, %s, %s) AND (task_text ILIKE '%%autotest%%')", (USER_A, USER_B, USER_C))
            print(f"[CLEANUP] Deleted test rows. Remaining: {count_test_records(db)}")
    except Exception as e:
        print(f"[CLEANUP ERROR] {e}")

def count_test_records(db) -> int:
    try:
        with db._get_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM reminders WHERE user_id IN (%s, %s, %s) AND (task_text ILIKE '%%autotest%%')", (USER_A, USER_B, USER_C))
            return cur.fetchone()[0]
    except Exception as e:
        print(f"[COUNT ERROR] {e}")
        return -1

def run_all_tests():
    db = get_db()
    cleanup_test_data(db)
    results = {}
    # Use deterministic router patterns for test isolation to avoid external LLM rate-limit flapping
    unified_router._semantic_enabled = False

    print("======================================================================")
    print("STARTING 10-POINT REMINDER REGRESSION TEST SUITE")
    print("======================================================================")

    # -------------------------------------------------------------------------
    # TEST 1: Same-user cancellation through actual production router
    # -------------------------------------------------------------------------
    print("\n--- TEST 1: Same-user cancellation through actual production router ---")
    try:
        shutdown_scheduler()
        sched = initialize_scheduler(db_manager=db, user_id=USER_A)
        
        # 1. Create reminder via router
        create_res = unified_router.execute_single_action(
            "remind me to test autotest same user tomorrow at 10am",
            user_id=USER_A
        )
        print("Create response:", create_res)
        assert create_res.get("status") == "success", f"Create failed: {create_res}"
        
        # Verify in DB and memory
        with db._get_cursor() as cur:
            cur.execute("SELECT id, task_text FROM reminders WHERE user_id = %s AND task_text ILIKE '%%autotest same user%%'", (USER_A,))
            row = cur.fetchone()
        assert row is not None, "Reminder not found in database"
        rem_id = str(row[0])
        print(f"Created reminder ID: {rem_id}")
        
        mem_rem = next((r for r in sched.reminders if str(r["id"]) == rem_id), None)
        assert mem_rem is not None, "Reminder not found in scheduler memory"
        assert mem_rem.get("state") == "SCHEDULED", f"State is {mem_rem.get('state')}"

        # 2. Cancel reminder via router with same user
        cancel_res = unified_router.execute_single_action(
            f"cancel reminder #{rem_id}",
            user_id=USER_A
        )
        print("Cancel response:", cancel_res)
        assert cancel_res.get("status") == "success", f"Cancel failed: {cancel_res}"

        # 3. Verify side-effects: DB row deleted and in-memory removed
        with db._get_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM reminders WHERE id = %s", (int(rem_id),))
            cnt = cur.fetchone()[0]
        assert cnt == 0, "Reminder still exists in database after cancellation"

        mem_rem_after = next((r for r in sched.reminders if str(r["id"]) == rem_id), None)
        assert mem_rem_after is None, "Reminder still exists in scheduler memory after cancellation"

        results["TEST_1"] = "PASS"
        print("[TEST 1 PASSED]")
    except Exception as e:
        print(f"[TEST 1 FAILED] {e}")
        import traceback
        traceback.print_exc()
        results["TEST_1"] = f"FAIL: {e}"

    # -------------------------------------------------------------------------
    # TEST 2: Cross-user cancellation through production router
    # -------------------------------------------------------------------------
    print("\n--- TEST 2: Cross-user cancellation through production router ---")
    try:
        # User A creates a reminder
        create_res = unified_router.execute_single_action(
            "remind me to test autotest cross user tomorrow at 11am",
            user_id=USER_A
        )
        assert create_res.get("status") == "success"
        with db._get_cursor() as cur:
            cur.execute("SELECT id FROM reminders WHERE user_id = %s AND task_text ILIKE '%%autotest cross user%%'", (USER_A,))
            rem_id = str(cur.fetchone()[0])
        
        # User B attempts to cancel User A's reminder
        cancel_res_b = unified_router.execute_single_action(
            f"cancel reminder #{rem_id}",
            user_id=USER_B
        )
        print("User B cancel response:", cancel_res_b)
        assert cancel_res_b.get("status") == "error", f"Cross-user cancel should fail, got: {cancel_res_b}"

        # Verify DB still has User A's reminder
        with db._get_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM reminders WHERE id = %s AND user_id = %s", (int(rem_id), USER_A))
            cnt = cur.fetchone()[0]
        assert cnt == 1, "User A's reminder was deleted from DB by User B!"

        # Clean up this reminder with User A
        cancel_res_a = unified_router.execute_single_action(
            f"cancel reminder #{rem_id}",
            user_id=USER_A
        )
        assert cancel_res_a.get("status") == "success"

        results["TEST_2"] = "PASS"
        print("[TEST 2 PASSED]")
    except Exception as e:
        print(f"[TEST 2 FAILED] {e}")
        import traceback
        traceback.print_exc()
        results["TEST_2"] = f"FAIL: {e}"

    # -------------------------------------------------------------------------
    # TEST 3: Database-backed cancellation deletes exactly one DB row and removes in-memory job
    # -------------------------------------------------------------------------
    print("\n--- TEST 3: DB-backed cancellation deletes exactly one row & in-memory ---")
    try:
        # Insert two reminders with same task name
        due_str = (datetime.datetime.now() + datetime.timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S")
        id_1 = db.add_reminder(USER_A, "AUTOTEST_ONE_ROW_1", due_str)
        id_2 = db.add_reminder(USER_A, "AUTOTEST_ONE_ROW_2", due_str)
        sched = get_scheduler()
        sched.add_reminder_at_time("AUTOTEST_ONE_ROW_1", datetime.datetime.now() + datetime.timedelta(hours=4), str(id_1), USER_A, is_db_backed=True)
        sched.add_reminder_at_time("AUTOTEST_ONE_ROW_2", datetime.datetime.now() + datetime.timedelta(hours=4), str(id_2), USER_A, is_db_backed=True)

        # Cancel id_1
        ok = sched.cancel_reminder(str(id_1), user_id=USER_A)
        assert ok is True, "cancel_reminder returned False"

        # Check DB: id_1 gone, id_2 present
        with db._get_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM reminders WHERE id = %s", (id_1,))
            cnt_1 = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM reminders WHERE id = %s", (id_2,))
            cnt_2 = cur.fetchone()[0]
        assert cnt_1 == 0, "id_1 still exists in DB"
        assert cnt_2 == 1, "id_2 was accidentally deleted"

        # Check memory: id_1 gone, id_2 present
        assert not any(str(r["id"]) == str(id_1) for r in sched.reminders), "id_1 still in memory"
        assert any(str(r["id"]) == str(id_2) for r in sched.reminders), "id_2 missing from memory"

        # Cleanup id_2
        sched.cancel_reminder(str(id_2), user_id=USER_A)

        results["TEST_3"] = "PASS"
        print("[TEST 3 PASSED]")
    except Exception as e:
        print(f"[TEST 3 FAILED] {e}")
        import traceback
        traceback.print_exc()
        results["TEST_3"] = f"FAIL: {e}"

    # -------------------------------------------------------------------------
    # TEST 4: Memory-only cancellation performs no SQL
    # -------------------------------------------------------------------------
    print("\n--- TEST 4: Memory-only cancellation performs no SQL ---")
    try:
        class TrackingDBWrapper:
            def __init__(self, real_db):
                self.real_db = real_db
                self.sql_count = 0
            def _get_cursor(self):
                self.sql_count += 1
                return self.real_db._get_cursor()
            def delete_reminder(self, *args, **kwargs):
                self.sql_count += 1
                return self.real_db.delete_reminder(*args, **kwargs)

        tracking_db = TrackingDBWrapper(db)
        mem_sched = ReminderScheduler(tts_callback=None, sound_callback=None, db_manager=tracking_db, user_id=USER_A)
        
        # Add a memory-only reminder (is_db_backed=False)
        target_dt = datetime.datetime.now() + datetime.timedelta(hours=5)
        mem_id = mem_sched.add_reminder(
            text="AUTOTEST_MEM_ONLY",
            target_time=target_dt,
            user_id=USER_A,
            is_db_backed=False
        )
        assert mem_id != "", "Failed to add memory-only reminder"
        
        # Reset tracking counter
        tracking_db.sql_count = 0

        # Cancel memory-only reminder
        cancel_ok = mem_sched.cancel_reminder(mem_id, user_id=USER_A)
        assert cancel_ok is True, "cancel_reminder failed for memory-only reminder"
        assert tracking_db.sql_count == 0, f"Expected 0 SQL queries, but got {tracking_db.sql_count}!"

        # Ensure removed from memory
        assert not any(str(r["id"]) == str(mem_id) for r in mem_sched.reminders)
        mem_sched.stop()

        results["TEST_4"] = "PASS"
        print("[TEST 4 PASSED]")
    except Exception as e:
        print(f"[TEST 4 FAILED] {e}")
        import traceback
        traceback.print_exc()
        results["TEST_4"] = f"FAIL: {e}"

    # -------------------------------------------------------------------------
    # TEST 5: Database deletion failure preserves recoverable scheduler state
    # -------------------------------------------------------------------------
    print("\n--- TEST 5: DB deletion failure preserves recoverable scheduler state ---")
    try:
        class FailingDBManager:
            def delete_reminder(self, user_id, reminder_id):
                raise RuntimeError("Simulated DB connection drop")

        failing_db = FailingDBManager()
        test_sched = ReminderScheduler(tts_callback=None, sound_callback=None, db_manager=failing_db, user_id=USER_A)
        target_dt = datetime.datetime.now() + datetime.timedelta(hours=6)
        
        # Manually register a DB-backed reminder in test_sched
        test_sched.add_reminder_at_time(
            text="AUTOTEST_RECOVERABLE",
            target_time=target_dt,
            reminder_id="88801",
            user_id=USER_A,
            is_db_backed=True
        )

        # Attempt cancellation
        cancel_ok = test_sched.cancel_reminder("88801", user_id=USER_A)
        assert cancel_ok is False, "Cancellation should fail when DB fails"

        # Verify state is recovered to SCHEDULED and still in memory
        with test_sched._lock:
            rem = next((r for r in test_sched.reminders if str(r["id"]) == "88801"), None)
        assert rem is not None, "Reminder was incorrectly removed on DB failure!"
        assert rem.get("state") == "SCHEDULED", f"Expected state 'SCHEDULED' after rollback, got '{rem.get('state')}'"
        assert rem.get("triggered") is False

        test_sched.stop()
        results["TEST_5"] = "PASS"
        print("[TEST 5 PASSED]")
    except Exception as e:
        print(f"[TEST 5 FAILED] {e}")
        import traceback
        traceback.print_exc()
        results["TEST_5"] = f"FAIL: {e}"

    # -------------------------------------------------------------------------
    # TEST 6: Cancellation racing with triggering
    # -------------------------------------------------------------------------
    print("\n--- TEST 6: Cancellation racing with triggering ---")
    try:
        spoken_messages = []
        def dummy_tts(msg):
            # Simulate slight delay during speech
            time.sleep(0.1)
            spoken_messages.append(msg)

        race_sched = ReminderScheduler(tts_callback=dummy_tts, sound_callback=None, db_manager=db, user_id=USER_A)
        
        # Add a reminder that triggers in 0.2 seconds
        due_str = (datetime.datetime.now() + datetime.timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
        db_id = db.add_reminder(USER_A, "AUTOTEST_RACE_TRIG", due_str)
        
        race_sched.add_reminder(
            text="AUTOTEST_RACE_TRIG",
            delay_seconds=0.2,
            reminder_id=str(db_id),
            user_id=USER_A,
            is_db_backed=True
        )

        # Wait until reminder transitions into TRIGGERING or TRIGGERED
        t0 = time.time()
        while time.time() - t0 < 3.0:
            with race_sched._lock:
                rem = next((r for r in race_sched.reminders if str(r["id"]) == str(db_id)), None)
                if rem and rem.get("state") in ("TRIGGERING", "TRIGGERED"):
                    break
            time.sleep(0.05)
        
        # Attempt cancellation while triggering / after triggered
        cancel_attempt = race_sched.cancel_reminder(str(db_id), user_id=USER_A)
        assert cancel_attempt is False, f"Cancellation succeeded on a triggering/triggered reminder: {cancel_attempt}"
        
        race_sched.stop()
        # Clean up DB
        db.delete_reminder(USER_A, db_id)

        results["TEST_6"] = "PASS"
        print("[TEST 6 PASSED]")
    except Exception as e:
        print(f"[TEST 6 FAILED] {e}")
        import traceback
        traceback.print_exc()
        results["TEST_6"] = f"FAIL: {e}"

    # -------------------------------------------------------------------------
    # TEST 7: Cancellation racing with rescheduling
    # -------------------------------------------------------------------------
    print("\n--- TEST 7: Cancellation racing with rescheduling ---")
    try:
        race_sched = ReminderScheduler(tts_callback=None, sound_callback=None, db_manager=db, user_id=USER_A)
        due_str = (datetime.datetime.now() + datetime.timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S")
        db_id = str(db.add_reminder(USER_A, "AUTOTEST_RACE_RESCHED", due_str))
        
        race_sched.add_reminder_at_time(
            text="AUTOTEST_RACE_RESCHED",
            target_time=datetime.datetime.now() + datetime.timedelta(hours=7),
            reminder_id=db_id,
            user_id=USER_A,
            is_db_backed=True
        )

        # Force state to RESCHEDULING under lock to simulate an in-flight reschedule
        with race_sched._lock:
            rem = next(r for r in race_sched.reminders if str(r["id"]) == db_id)
            rem["state"] = "RESCHEDULING"

        # Attempt cancellation while in RESCHEDULING
        cancel_during_resched = race_sched.cancel_reminder(db_id, user_id=USER_A)
        assert cancel_during_resched is False, "Cancellation succeeded while reminder was in RESCHEDULING!"

        # Restore state to SCHEDULED
        with race_sched._lock:
            rem["state"] = "SCHEDULED"

        # Reschedule properly to new time
        new_time = datetime.datetime.now() + datetime.timedelta(hours=8)
        resched_ok = race_sched.reschedule_reminder(db_id, new_time, new_text="AUTOTEST_RESCHEDULED_OK", user_id=USER_A)
        assert resched_ok is True, "Proper reschedule failed"
        assert rem["text"] == "AUTOTEST_RESCHEDULED_OK"
        assert rem["state"] == "SCHEDULED"

        # Cancel cleanly
        cancel_ok = race_sched.cancel_reminder(db_id, user_id=USER_A)
        assert cancel_ok is True

        race_sched.stop()
        results["TEST_7"] = "PASS"
        print("[TEST 7 PASSED]")
    except Exception as e:
        print(f"[TEST 7 FAILED] {e}")
        import traceback
        traceback.print_exc()
        results["TEST_7"] = f"FAIL: {e}"

    # -------------------------------------------------------------------------
    # TEST 8: Two simultaneous cancellation requests
    # -------------------------------------------------------------------------
    print("\n--- TEST 8: Two simultaneous cancellation requests ---")
    try:
        race_sched = ReminderScheduler(tts_callback=None, sound_callback=None, db_manager=db, user_id=USER_A)
        due_str = (datetime.datetime.now() + datetime.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M:%S")
        db_id = str(db.add_reminder(USER_A, "AUTOTEST_SIMUL_CANCEL", due_str))
        
        race_sched.add_reminder_at_time(
            text="AUTOTEST_SIMUL_CANCEL",
            target_time=datetime.datetime.now() + datetime.timedelta(hours=9),
            reminder_id=db_id,
            user_id=USER_A,
            is_db_backed=True
        )

        results_threads = []
        def cancel_worker():
            res = race_sched.cancel_reminder(db_id, user_id=USER_A)
            results_threads.append(res)

        t1 = threading.Thread(target=cancel_worker)
        t2 = threading.Thread(target=cancel_worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        print(f"Two simultaneous cancellation results: {results_threads}")
        # Exactly one must succeed, and exactly one must fail
        assert sorted(results_threads) == [False, True], f"Expected exactly one True and one False, got: {results_threads}"

        # DB must have 0 rows
        with db._get_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM reminders WHERE id = %s", (int(db_id),))
            cnt = cur.fetchone()[0]
        assert cnt == 0, f"Expected 0 DB rows, found {cnt}"

        # Memory must have 0 rows
        assert not any(str(r["id"]) == db_id for r in race_sched.reminders)

        race_sched.stop()
        results["TEST_8"] = "PASS"
        print("[TEST 8 PASSED]")
    except Exception as e:
        print(f"[TEST 8 FAILED] {e}")
        import traceback
        traceback.print_exc()
        results["TEST_8"] = f"FAIL: {e}"

    # -------------------------------------------------------------------------
    # TEST 9: Cancellation of recurring reminders
    # -------------------------------------------------------------------------
    print("\n--- TEST 9: Cancellation of recurring reminders ---")
    try:
        race_sched = ReminderScheduler(tts_callback=None, sound_callback=None, db_manager=db, user_id=USER_A)
        due_str = (datetime.datetime.now() + datetime.timedelta(hours=10)).strftime("%Y-%m-%d %H:%M:%S")
        db_id = str(db.add_reminder(USER_A, "AUTOTEST_RECURRING daily", due_str))
        
        race_sched.add_reminder_at_time(
            text="AUTOTEST_RECURRING daily",
            target_time=datetime.datetime.now() + datetime.timedelta(hours=10),
            reminder_id=db_id,
            user_id=USER_A,
            recurrence={"frequency": "daily", "interval": 1},
            is_db_backed=True
        )

        with race_sched._lock:
            rem = next(r for r in race_sched.reminders if str(r["id"]) == db_id)
            assert rem.get("recurrence") is not None

        cancel_ok = race_sched.cancel_reminder(db_id, user_id=USER_A)
        assert cancel_ok is True, "Failed to cancel recurring reminder"

        with db._get_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM reminders WHERE id = %s", (int(db_id),))
            cnt = cur.fetchone()[0]
        assert cnt == 0, "Recurring reminder row still exists in DB!"
        assert not any(str(r["id"]) == db_id for r in race_sched.reminders), "Recurring reminder still in memory!"

        race_sched.stop()
        results["TEST_9"] = "PASS"
        print("[TEST 9 PASSED]")
    except Exception as e:
        print(f"[TEST 9 FAILED] {e}")
        import traceback
        traceback.print_exc()
        results["TEST_9"] = f"FAIL: {e}"

    # -------------------------------------------------------------------------
    # TEST 10: Creation, editing, rescheduling, and restart persistence regressions
    # -------------------------------------------------------------------------
    print("\n--- TEST 10: Creation, editing, rescheduling, restart persistence regressions ---")
    try:
        shutdown_scheduler()
        sched_1 = initialize_scheduler(db_manager=db, user_id=USER_A)
        
        # 1. Creation
        due_dt_1 = datetime.datetime.now() + datetime.timedelta(hours=11)
        due_str_1 = due_dt_1.strftime("%Y-%m-%d %H:%M:%S")
        rem_id = str(db.add_reminder(USER_A, "AUTOTEST_LIFECYCLE_INIT", due_str_1))
        sched_1.add_reminder_at_time("AUTOTEST_LIFECYCLE_INIT", due_dt_1, rem_id, USER_A, is_db_backed=True)

        # 2. Text editing
        edit_ok = sched_1.edit_reminder(rem_id, new_text="AUTOTEST_LIFECYCLE_EDITED", user_id=USER_A)
        assert edit_ok is True, "edit_reminder failed"
        # Verify DB updated
        rem_db = db.get_reminder_by_id(USER_A, int(rem_id))
        assert rem_db["task_text"] == "AUTOTEST_LIFECYCLE_EDITED", f"DB task_text not updated: {rem_db}"

        # 3. Rescheduling
        due_dt_2 = datetime.datetime.now() + datetime.timedelta(hours=15)
        resched_ok = sched_1.reschedule_reminder(rem_id, due_dt_2, new_text="AUTOTEST_LIFECYCLE_RESCHEDULED", user_id=USER_A)
        assert resched_ok is True, "reschedule_reminder failed"
        rem_db = db.get_reminder_by_id(USER_A, int(rem_id))
        assert rem_db["task_text"] == "AUTOTEST_LIFECYCLE_RESCHEDULED"
        expected_due_str = due_dt_2.strftime("%Y-%m-%d %H:%M:%S")
        actual_due_str = rem_db["due_at"].strftime("%Y-%m-%d %H:%M:%S") if isinstance(rem_db["due_at"], datetime.datetime) else str(rem_db["due_at"])
        assert actual_due_str == expected_due_str, f"DB due_at mismatch: {actual_due_str} != {expected_due_str}"

        # 4. Restart persistence simulation: shutdown scheduler, restart new scheduler instance with db_manager
        shutdown_scheduler()
        sched_2 = initialize_scheduler(db_manager=db, user_id=USER_A)
        
        # Verify reminder was reloaded into sched_2 from database
        with sched_2._lock:
            reloaded = next((r for r in sched_2.reminders if str(r["id"]) == rem_id), None)
        assert reloaded is not None, "Reminder was not reloaded upon scheduler restart!"
        assert reloaded["text"] == "AUTOTEST_LIFECYCLE_RESCHEDULED"
        assert reloaded["is_db_backed"] is True
        assert reloaded["state"] == "SCHEDULED"

        # Final cleanup through sched_2
        cancel_ok = sched_2.cancel_reminder(rem_id, user_id=USER_A)
        assert cancel_ok is True

        sched_2.stop()
        results["TEST_10"] = "PASS"
        print("[TEST 10 PASSED]")
    except Exception as e:
        print(f"[TEST 10 FAILED] {e}")
        import traceback
        traceback.print_exc()
        results["TEST_10"] = f"FAIL: {e}"

    # -------------------------------------------------------------------------
    # FINAL CLEANUP & AUDIT
    # -------------------------------------------------------------------------
    print("\n--- FINAL CLEANUP AND RECORD AUDIT ---")
    cleanup_test_data(db)
    final_count = count_test_records(db)
    print(f"Final AUTOTEST record count in PostgreSQL: {final_count}")
    assert final_count == 0, f"Leftover records in PostgreSQL: {final_count}"

    print("\n======================================================================")
    print("REGRESSION TEST RESULTS SUMMARY:")
    for test, res in results.items():
        print(f"  {test}: {res}")
    print("======================================================================")

    all_passed = all(res == "PASS" for res in results.values()) and len(results) == 10
    if all_passed:
        print("ALL 10 REGRESSION TESTS PASSED PERFECTLY!")
        sys.exit(0)
    else:
        print("SOME TESTS FAILED!")
        sys.exit(1)

if __name__ == "__main__":
    run_all_tests()
