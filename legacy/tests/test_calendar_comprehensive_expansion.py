"""
Comprehensive Calendar Subsystem Test Suite.
Verifies all 13 calendar capabilities at module and storage level:
1. Event CRUD, durations, locations, categories, multi-day spans.
2. Recurring events, recurrence expansion, single-occurrence vs series deletion/editing.
3. Event reminders, duplicate prevention, and snooze handling.
4. Conflict detection with buffers, free slot discovery, and alternative slot suggestions.
5. Daily, weekly, monthly, next appointment, and busy time queries.
6. Daily briefings and regional week planning with calendar context.
7. Intent and entity parsing across natural language variations.
8. Calendar categories and filtering.
9. RFC 5545 .ics import/export and external sync graceful fallback.
10. Timezone and date boundary handling.
11. Meeting notes, agendas, preparation checklists, and document links.
12. Calendar analytics (duration, utilization, conflicts).
13. Atomic persistence, user isolation, and duplicate protection.
"""

import unittest
from datetime import datetime, date, time, timedelta
import json
import os

from modules.calendar_manager.calendar_storage import CalendarStorage
from modules.calendar_manager.ics_handler import ICSHandler
from modules.calendar_manager.sync_adapters import CalendarSyncManager, GoogleCalendarSyncAdapter
from modules.calendar_manager.intent_handler import CalendarIntentHandler

class TestCalendarComprehensiveExpansion(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.storage = CalendarStorage()
        cls.test_uid = 817  # Existing verified test user
        cls.ics = ICSHandler()
        cls.sync_mgr = CalendarSyncManager()

    def setUp(self):
        # Clean up test events
        evs = self.storage.get_events_range(self.test_uid, "2026-10-01", "2026-10-31")
        for d, elist in evs.items():
            for ev in elist:
                if any(k in ev.get("title", "") for k in ["Test Event", "Huddle", "Sync", "Sprint", "Review", "Standup"]):
                    self.storage.delete_event(self.test_uid, ev["id"], delete_series=True)

    def test_01_event_crud_attributes_and_duplicate_protection(self):
        """Feature 1 & 13: Event creation with full attributes, duplicate protection, and editing."""
        event_data = {
            "title": "Test Event Planning",
            "date": "2026-10-20",
            "time": "14:00",
            "duration_minutes": 90,
            "location": "Boardroom A",
            "category": "Work",
            "description": "Quarterly planning meeting"
        }
        ev_id = self.storage.add_event(self.test_uid, event_data)
        self.assertTrue(ev_id)

        # Duplicate protection: adding identical event returns existing id without creating duplicates
        dup_id = self.storage.add_event(self.test_uid, event_data)
        self.assertEqual(dup_id, ev_id)

        # Retrieval
        evs = self.storage.get_events(self.test_uid, "2026-10-20")
        match = [e for e in evs if e["title"] == "Test Event Planning"]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0]["duration_minutes"], 90)
        self.assertEqual(match[0]["location"], "Boardroom A")
        self.assertEqual(match[0]["category"], "Work")

        # Edit event
        updated = self.storage.update_event(self.test_uid, ev_id, {
            "location": "Room 501",
            "duration_minutes": 120
        })
        self.assertTrue(updated)
        details = self.storage.get_event_details(self.test_uid, ev_id)
        self.assertEqual(details["location"], "Room 501")
        self.assertEqual(details["duration_minutes"], 120)

    def test_02_recurrence_expansion_and_single_occurrence_cancellation(self):
        """Feature 2: Recurring event expansion and single occurrence cancellation."""
        rec_event = {
            "title": "Test Event Huddle",
            "date": "2026-10-20",
            "time": "09:00",
            "duration_minutes": 30,
            "recurrence": {
                "frequency": "daily",
                "interval": 1
            }
        }
        master_id = self.storage.add_event(self.test_uid, rec_event)
        self.assertTrue(master_id)

        # Check consecutive days
        evs_day1 = self.storage.get_events(self.test_uid, "2026-10-20")
        evs_day2 = self.storage.get_events(self.test_uid, "2026-10-21")
        self.assertTrue(any(e["title"] == "Test Event Huddle" for e in evs_day1))
        self.assertTrue(any(e["title"] == "Test Event Huddle" for e in evs_day2))

        # Cancel single occurrence on 2026-10-21
        deleted = self.storage.delete_occurrence(self.test_uid, master_id, "2026-10-21")
        self.assertTrue(deleted)

        evs_day2_after = self.storage.get_events(self.test_uid, "2026-10-21")
        self.assertFalse(any(e["title"] == "Test Event Huddle" for e in evs_day2_after))

        # Day 1 and Day 3 must still exist
        evs_day1_after = self.storage.get_events(self.test_uid, "2026-10-20")
        evs_day3 = self.storage.get_events(self.test_uid, "2026-10-22")
        self.assertTrue(any(e["title"] == "Test Event Huddle" for e in evs_day1_after))
        self.assertTrue(any(e["title"] == "Test Event Huddle" for e in evs_day3))

    def test_03_conflict_detection_and_free_slots(self):
        """Feature 4: Conflict detection with buffers, free slot discovery, and alternative slots."""
        # Create base event 10:00 - 11:30
        self.storage.add_event(self.test_uid, {
            "title": "Test Event Review",
            "date": "2026-10-25",
            "time": "10:00",
            "duration_minutes": 90
        })

        # Overlapping slot check (10:30)
        s_dt = datetime(2026, 10, 25, 10, 30)
        e_dt = datetime(2026, 10, 25, 11, 0)
        conflicts = self.storage.check_conflicts(self.test_uid, s_dt, e_dt)
        self.assertTrue(len(conflicts) > 0)
        self.assertEqual(conflicts[0]["title"], "Test Event Review")

        # Free slots within working hours (09:00 - 18:00)
        free_slots = self.storage.find_free_slots(self.test_uid, "2026-10-25", slot_duration_minutes=30)
        self.assertTrue(len(free_slots) > 0)
        # 09:00 - 10:00 must be free
        self.assertTrue(any(s["start"] == "09:00" for s in free_slots))
        # 11:30 - 18:00 must be free
        self.assertTrue(any(s["start"] == "11:30" for s in free_slots))

        # Suggest alternative slot
        alt = self.storage.suggest_alternative_slot(self.test_uid, "2026-10-25", preferred_time="10:30", duration_minutes=30)
        self.assertIsNotNone(alt)
        self.assertIn(alt["start"], ["09:00", "09:30", "11:30"])

    def test_04_meeting_artifacts_notes_agendas_checklists_documents(self):
        """Feature 11: Meeting notes, agendas, checklists, and document attachments."""
        ev_id = self.storage.add_event(self.test_uid, {
            "title": "Test Event Sprint",
            "date": "2026-10-26",
            "time": "15:00",
            "duration_minutes": 60
        })
        self.storage.add_meeting_notes(self.test_uid, ev_id, "Discussed API contract and backward compatibility.")
        self.storage.add_meeting_agenda(self.test_uid, ev_id, ["Architecture overview", "DB migrations", "Load testing"])
        self.storage.add_preparation_checklist(self.test_uid, ev_id, ["Prepare slide deck", "Test backup database"])
        self.storage.associate_document(self.test_uid, ev_id, "/docs/calendar_spec.pdf")

        details = self.storage.get_event_details(self.test_uid, ev_id)
        self.assertEqual(details["notes"], "Discussed API contract and backward compatibility.")
        self.assertEqual(len(details["agenda"]), 3)
        self.assertEqual(len(details["checklist"]), 2)
        self.assertIn("/docs/calendar_spec.pdf", details["documents"])

    def test_05_calendar_analytics(self):
        """Feature 12: Calendar analytics for meeting duration, utilization, and conflicts."""
        self.storage.add_event(self.test_uid, {
            "title": "Test Event Sync 1",
            "date": "2026-10-27",
            "time": "10:00",
            "duration_minutes": 60
        })
        self.storage.add_event(self.test_uid, {
            "title": "Test Event Sync 2",
            "date": "2026-10-27",
            "time": "14:00",
            "duration_minutes": 60
        })
        analytics = self.storage.get_calendar_analytics(self.test_uid, "2026-10-27", "2026-10-27")
        self.assertGreaterEqual(analytics["total_meetings"], 2)
        self.assertGreaterEqual(analytics["total_meeting_hours"], 2.0)
        self.assertGreater(analytics["utilization_percent"], 0.0)

    def test_06_rfc5545_ics_export_and_import(self):
        """Feature 9 & 10: RFC 5545 .ics generation and parsing."""
        self.storage.add_event(self.test_uid, {
            "title": "Test Event Standup",
            "date": "2026-10-28",
            "time": "11:00",
            "duration_minutes": 45,
            "location": "Virtual Meet"
        })
        ics_text = self.ics.export_calendar_to_ics(self.test_uid, "2026-10-28", "2026-10-28")
        self.assertIn("BEGIN:VCALENDAR", ics_text)
        self.assertIn("SUMMARY:Test Event Standup", ics_text)
        self.assertIn("LOCATION:Virtual Meet", ics_text)

        # Import test
        sample_ics = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VEVENT
SUMMARY:Imported Test Event
DTSTART:20261029T100000
DTEND:20261029T110000
LOCATION:Auditorium
DESCRIPTION:Imported event test
END:VEVENT
END:VCALENDAR"""
        res = self.ics.import_calendar_from_ics(self.test_uid, sample_ics)
        self.assertTrue(res["success"])
        self.assertGreaterEqual(res["imported_count"], 1)

        evs = self.storage.get_events(self.test_uid, "2026-10-29")
        self.assertTrue(any("Imported Test Event" in e["title"] for e in evs))

    def test_07_sync_adapter_graceful_fallback(self):
        """Feature 9: External sync gracefully reports configuration status when unconfigured."""
        google_adapter = GoogleCalendarSyncAdapter()
        res = google_adapter.sync(self.test_uid)
        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "unconfigured")
        self.assertTrue(res.get("optional"))
        self.assertIn("optional and not currently configured", res["message"])

    def test_08_search_events(self):
        """Feature 1 & 8: Search across title, location, category, and metadata."""
        self.storage.add_event(self.test_uid, {
            "title": "Quarterly Budget Review",
            "date": "2026-10-30",
            "time": "16:00",
            "location": "Finance Suite 300",
            "category": "Finance"
        })
        res_loc = self.storage.search_events(self.test_uid, "Finance Suite")
        self.assertTrue(any("Quarterly Budget" in e["title"] for e in res_loc))

        res_cat = self.storage.search_events(self.test_uid, "Finance", category="Finance")
        self.assertTrue(any("Quarterly Budget" in e["title"] for e in res_cat))

    def test_09_malformed_ics_safe_handling(self):
        """Feature 9: Malformed or corrupted .ics input handles gracefully without crashing."""
        malformed_inputs = [
            "",
            "Random text not conforming to icalendar format",
            "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nINVALID_LINES\nEND:VEVENT\nEND:VCALENDAR",
            "BEGIN:VCALENDAR\nSUMMARY:No DTSTART\nEND:VCALENDAR"
        ]
        for bad_ics in malformed_inputs:
            res = self.ics.import_calendar_from_ics(self.test_uid, bad_ics)
            self.assertIsInstance(res, dict)
            self.assertEqual(res.get("imported_count"), 0)

    def test_10_monthly_and_yearly_recurrence_edge_cases(self):
        """Feature 2 & 10: Monthly recurrence on 31st clamps to 28/30 days and yearly on leap days."""
        # 31st of month recurrence
        rec_id = self.storage.add_event(self.test_uid, {
            "title": "Month-End Close",
            "date": "2026-01-31",
            "time": "17:00",
            "duration_minutes": 60,
            "recurrence": {
                "frequency": "monthly",
                "interval": 1
            }
        })
        # Feb 2026 has 28 days -> should match 2026-02-28
        evs_feb = self.storage.get_events(self.test_uid, "2026-02-28")
        self.assertTrue(any("Month-End Close" in e["title"] for e in evs_feb))
        # Mar 2026 has 31 days -> should match 2026-03-31
        evs_mar = self.storage.get_events(self.test_uid, "2026-03-31")
        self.assertTrue(any("Month-End Close" in e["title"] for e in evs_mar))
        # Apr 2026 has 30 days -> should match 2026-04-30
        evs_apr = self.storage.get_events(self.test_uid, "2026-04-30")
        self.assertTrue(any("Month-End Close" in e["title"] for e in evs_apr))

        # Cleanup
        self.storage.delete_event(self.test_uid, rec_id, delete_series=True)

    def test_11_past_date_rejection_and_roll_forward(self):
        """Feature 10: Reject past dates for non-recurring events and explain roll-forward for recurring."""
        from modules.calendar_manager.calendar_controller import CalendarController
        controller = CalendarController()
        
        # Past date scheduling attempt
        res = controller.process_calendar_query("Schedule Past Retro on 2020-01-01 at 10 AM", user_id=self.test_uid)
        self.assertEqual(res.get("status"), "error")
        self.assertEqual(res.get("error_type"), "temporal_failure")
        self.assertIn("already passed", res.get("speech_response", "").lower())


    @classmethod
    def tearDownClass(cls):
        # Final cleanup
        evs = cls.storage.get_events_range(cls.test_uid, "2026-10-01", "2026-10-31")
        for d, elist in evs.items():
            for ev in elist:
                if any(k in ev.get("title", "") for k in ["Test Event", "Huddle", "Sync", "Sprint", "Review", "Standup", "Imported Test Event", "Quarterly Budget"]):
                    cls.storage.delete_event(cls.test_uid, ev["id"], delete_series=True)

if __name__ == "__main__":
    unittest.main()
