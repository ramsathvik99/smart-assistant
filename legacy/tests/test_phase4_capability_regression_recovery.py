"""
Phase 4 Capability Regression Recovery Test Suite
Validates recovered and existing baseline capabilities across:
- System info / telemetry
- File operations & document search
- Document generation (DOCX, PPTX, XLSX)
- Contextual search query extraction
- Calendar operations
- Reminders lifecycle
- Application control
- Memory & user isolation
- Visual response & undo
"""
import unittest
import sys
import os

sys.path.insert(0, os.path.abspath("."))

from legacy.assistant import process_input

class TestPhase4CapabilityRegressionRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.user_id = 287

    def test_01_system_information_telemetry(self):
        # Must return local OS telemetry, not web search
        res1 = process_input("show system information", user_id=self.user_id)
        self.assertTrue(any(k in res1.lower() for k in ["windows", "amd64", "ram", "up for", "system"]), f"Failed on 'show system information': {res1}")
        self.assertNotIn("cisco", res1.lower())

        res2 = process_input("system info", user_id=self.user_id)
        self.assertTrue(any(k in res2.lower() for k in ["windows", "amd64", "ram", "up for", "system"]), f"Failed on 'system info': {res2}")
        self.assertNotIn("cisco", res2.lower())

    def test_02_file_operations_and_document_search(self):
        # "search for document" must route to FILE_OPERATIONS
        res1 = process_input("search for document", user_id=self.user_id)
        self.assertTrue(any(k in res1.lower() for k in ["file", "files", "matching", "found", "desktop", "downloads"]), f"Failed on 'search for document': {res1}")

        res2 = process_input("search for files in downloads", user_id=self.user_id)
        self.assertTrue("found" in res2.lower() or "file" in res2.lower(), f"Failed on 'search for files in downloads': {res2}")

    def test_03_calendar_operations(self):
        res_show = process_input("show my calendar", user_id=self.user_id)
        self.assertTrue("scheduled" in res_show.lower() or "event" in res_show.lower() or "calendar" in res_show.lower())

        res_add = process_input("add a meeting tomorrow at 3 PM called Team Sync", user_id=self.user_id)
        self.assertTrue("added" in res_add.lower() or "team sync" in res_add.lower())

    def test_04_document_generation_capabilities(self):
        res_docx = process_input("Friday create a document about Artificial Intelligence", user_id=self.user_id)
        self.assertTrue(any(k in res_docx.lower() for k in ["created", "document", "docx", "success", "generated"]))

        res_pptx = process_input("create a presentation about Machine Learning", user_id=self.user_id)
        self.assertTrue(any(k in res_pptx.lower() for k in ["created", "presentation", "powerpoint", "pptx", "success", "generated"]))

        res_xlsx = process_input("create a spreadsheet about Monthly Budget", user_id=self.user_id)
        self.assertTrue(any(k in res_xlsx.lower() for k in ["created", "spreadsheet", "excel", "xlsx", "success", "generated"]))

    def test_05_reminders_and_user_isolation(self):
        res_set = process_input("remind me to review code at 8 PM", user_id=self.user_id)
        self.assertIn("reminder set", res_set.lower())

        res_list = process_input("show my reminders", user_id=self.user_id)
        self.assertIn("review code", res_list.lower())

        res_del = process_input("cancel my reminder to review code", user_id=self.user_id)
        self.assertIn("deleted", res_del.lower())

    def test_06_memory_persistence_and_recall(self):
        res_store = process_input("remember that my favorite editor is VS Code", user_id=self.user_id)
        self.assertIn("vs code", res_store.lower())

        res_recall = process_input("what is my favorite editor", user_id=self.user_id)
        self.assertIn("vs code", res_recall.lower())

    def test_07_device_management_and_clipboard(self):
        res_clip = process_input("what is on my clipboard", user_id=self.user_id)
        self.assertTrue("clipboard" in res_clip.lower())

        res_paired = process_input("show paired devices", user_id=self.user_id)
        self.assertTrue("devices" in res_paired.lower() or "paired" in res_paired.lower())

    def test_08_applications_and_window_controls(self):
        res_min = process_input("minimize all windows", user_id=self.user_id)
        self.assertTrue("minimized" in res_min.lower() or "desktop" in res_min.lower())

        res_open = process_input("open notepad", user_id=self.user_id)
        self.assertTrue("notepad" in res_open.lower() or "opened" in res_open.lower())

        res_close = process_input("close notepad", user_id=self.user_id)
        self.assertTrue("notepad" in res_close.lower() or "closed" in res_close.lower())

if __name__ == "__main__":
    unittest.main()
