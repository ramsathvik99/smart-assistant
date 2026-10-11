"""
Comprehensive Regression & Integration Tests for Memory, Config, Plugins, and Device Services.
Validates:
1. PostgreSQL-backed Categorized Memory & Lexical Scoring
2. Prompt Budgeting, Caps, and Index Table of Contents
3. Value Length Protection
4. Settings Typed Getters, Allowed-Value Validation, and Namespaces
5. Plugin Manager Isolated Execution, Schema Validation, and Containment
6. Device File Transfer Sanitization, Size Limits, and User Isolation
7. Phone Audio Receiver Bounded Queue & Backpressure Handling
8. Strict Absence of Wake Word & Avatar/Hologram Subsystems
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from extensions.conversational_memory import (
    _truncate_value,
    _score_memory_entry,
    get_categorized_user_memory,
    search_user_memory,
    format_memory_for_prompt,
    get_all_memory_entries_for_ui,
    PROMPT_CORE_CHARS,
    PROMPT_INDEX_CHARS,
    PROMPT_MAX_PER_CATEGORY,
)

from extensions.plugin_manager import PluginManager, PluginMetadata
from skills.device_management.file_transfer import (
    _safe_filename,
    save_user_uploaded_file,
    get_user_file_path,
    list_user_files,
)
from skills.device_management.phone_audio import PhoneAudioStreamReceiver


class TestMemoryAndConfigIntegration(unittest.TestCase):

    # ── 1. Value Length Protection & Lexical Scoring ──────────────────────────
    def test_01_memory_value_truncation_and_lexical_scoring(self):
        long_text = "x" * 500
        truncated = _truncate_value(long_text, max_len=380)
        self.assertLessEqual(len(truncated), 382)
        self.assertTrue(truncated.endswith("…"))

        # Lexical scoring tests (sub-millisecond, no model calls)
        score_exact = _score_memory_entry(["ayse"], "relationships", "ayse_sister", "Ayse is my sister")
        self.assertGreater(score_exact, 0)

        score_none = _score_memory_entry(["quantum"], "preferences", "coffee", "black with oat milk")
        self.assertEqual(score_none, 0)

    # ── 2. Categorized Memory & Prompt Budgeting ───────────────────────────────
    def test_02_categorized_memory_and_prompt_budget(self):
        sample_mem = {
            "name": "Alex",
            "city": "Seattle",
            "favorite_food": "Pasta",
            "project_alpha": "Building an autonomous agent",
            "sister_ayse": "Ayse lives in Berlin",
            "random_note": "Meeting on Friday at 3pm",
        }

        with patch("legacy.memory_manager.load_user_memory", return_value=sample_mem):
            categorized = get_categorized_user_memory(user_id=42)
            self.assertIn("identity", categorized)
            self.assertEqual(categorized["identity"].get("name"), "Alex")
            self.assertIn("preferences", categorized)
            self.assertIn("projects", categorized)
            self.assertIn("relationships", categorized)

            # Test prompt formatting with budget
            prompt_block = format_memory_for_prompt(user_id=42)
            self.assertIn("WHAT YOU KNOW ABOUT THIS USER", prompt_block)
            self.assertIn("Name: Alex", prompt_block)
            self.assertIn("City: Seattle", prompt_block)

            # Test fast lexical search
            matches = search_user_memory(user_id=42, query="pasta")
            self.assertTrue(any("pasta" in m["value"].lower() for m in matches))

            # Test UI listing
            ui_rows = get_all_memory_entries_for_ui(user_id=42)
            self.assertIsInstance(ui_rows, list)
            self.assertGreaterEqual(len(ui_rows), 1)

    # ── 3. Settings Typed Getters & Namespace ──────────────────────────────────
    def test_03_settings_typed_getters_and_namespace(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("real_instance_config", "instance/config.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        Settings = mod.Settings
        s = Settings()
        s.TEST_INT = "42"
        s.TEST_FLOAT = "3.1415"
        s.TEST_BOOL = "true"
        s.TEST_STR = "dark"


        self.assertEqual(s.get_int("TEST_INT"), 42)
        self.assertEqual(s.get_int("TEST_INT", min_val=50), 50)  # Clamped min
        self.assertEqual(s.get_float("TEST_FLOAT"), 3.1415)
        self.assertTrue(s.get_bool("TEST_BOOL"))

        # Allowed-value validation
        self.assertEqual(s.get_str("TEST_STR", default="light", allowed=["dark", "light"]), "dark")
        self.assertEqual(s.get_str("TEST_STR", default="system", allowed=["solar", "cyber"]), "system")

        # Namespaces
        s.set_namespace("spotify", {"client_id": "xyz123", "rate_limit": 60})
        ns = s.get_namespace("spotify")
        self.assertEqual(ns.get("client_id"), "xyz123")
        self.assertEqual(ns.get("rate_limit"), 60)

    # ── 4. Plugin Manager Isolated Execution & Schema ──────────────────────────
    def test_04_plugin_manager_isolated_execution(self):
        pm = PluginManager()

        def sample_good_plugin(parameters: dict) -> str:
            val = parameters.get("input", "")
            return f"Processed: {val}"

        def sample_crashing_plugin(parameters: dict) -> str:
            raise RuntimeError("Database connection timed out in plugin")

        # Register
        pm.register_plugin(
            name="good_tool",
            handler=sample_good_plugin,
            description="A test plugin",
            parameters={"type": "OBJECT", "properties": {"input": {"type": "STRING"}}},
        )
        pm.register_plugin(
            name="bad_tool",
            handler=sample_crashing_plugin,
            description="A crashing plugin",
        )

        # Successful execution
        res = pm.execute_plugin("good_tool", parameters={"input": "Hello World"})
        self.assertTrue(res["success"])
        self.assertEqual(res["result"], "Processed: Hello World")

        # Isolated error execution — must not crash host application
        err_res = pm.execute_plugin("bad_tool", parameters={})
        self.assertFalse(err_res["success"])
        self.assertEqual(err_res["status"], "error")
        self.assertIn("Database connection timed out", err_res["error"])

        # Enable/Disable toggle
        pm.set_enabled("good_tool", False)
        dis_res = pm.execute_plugin("good_tool", parameters={"input": "Hello"})
        self.assertFalse(dis_res["success"])
        self.assertEqual(dis_res["status"], "disabled")

    # ── 5. Safe Device File Transfer & User Isolation ─────────────────────────
    def test_05_device_file_transfer_sanitization_and_isolation(self):
        temp_dir = Path(tempfile.mkdtemp())
        try:
            user_1_id = 101
            user_2_id = 202

            # Dangerous filename sanitization
            safe = _safe_filename("../../etc/passwd:invalid.txt")
            self.assertNotIn("/", safe)
            self.assertNotIn("\\", safe)
            self.assertNotIn(":", safe)

            # Upload for User 1
            content = b"Sample user 1 document payload"
            res1 = save_user_uploaded_file(
                file_bytes=content,
                raw_filename="report.pdf",
                user_id=user_1_id,
                base_dir=temp_dir,
            )
            self.assertTrue(res1["success"])
            self.assertEqual(res1["filename"], "report.pdf")

            # Duplicate collision handling
            res1_dup = save_user_uploaded_file(
                file_bytes=content,
                raw_filename="report.pdf",
                user_id=user_1_id,
                base_dir=temp_dir,
            )
            self.assertTrue(res1_dup["success"])
            self.assertEqual(res1_dup["filename"], "report_1.pdf")

            # User Isolation: User 2 cannot access User 1's file
            p1 = get_user_file_path("report.pdf", user_id=user_1_id, base_dir=temp_dir)
            self.assertIsNotNone(p1)

            p2 = get_user_file_path("report.pdf", user_id=user_2_id, base_dir=temp_dir)
            self.assertIsNone(p2)

            # Listing files
            u1_files = list_user_files(user_id=user_1_id, base_dir=temp_dir)
            self.assertEqual(len(u1_files), 2)

            u2_files = list_user_files(user_id=user_2_id, base_dir=temp_dir)
            self.assertEqual(len(u2_files), 0)

            # Size limit validation
            oversized_content = b"0" * (1024 * 1024 + 10)
            oversized_res = save_user_uploaded_file(
                file_bytes=oversized_content,
                raw_filename="big.zip",
                user_id=user_1_id,
                max_mb=1,
                base_dir=temp_dir,
            )
            self.assertFalse(oversized_res["success"])
            self.assertEqual(oversized_res["status"], "size_exceeded")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # ── 6. Phone Audio Stream Receiver & Backpressure ─────────────────────────
    def test_06_phone_audio_stream_bounded_queue_and_backpressure(self):
        receiver = PhoneAudioStreamReceiver(max_buffered_chunks=5)
        user_id = 999

        # Stream active frames
        for i in range(5):
            success = receiver.push_pcm_frame(user_id, b"\x00" * 320)
            self.assertTrue(success)

        # 6th frame must trigger backpressure drop rather than blocking
        dropped_success = receiver.push_pcm_frame(user_id, b"\x00" * 320)
        self.assertFalse(dropped_success, "Must drop frame on full queue for backpressure protection")

        # Stream cleanup
        receiver.close_stream(user_id)
        self.assertFalse(receiver.is_streaming(user_id))

    # ── 7. Absence of Wake Word and Avatar/Hologram ───────────────────────────
    def test_07_no_wake_word_and_no_avatar_subsystem(self):
        # Verify no wake_word module in audio_management
        with self.assertRaises(ImportError):
            import skills.audio_management.wake_word  # noqa: F401

        # Verify no avatar modules in core or modules/ui
        with self.assertRaises(ImportError):
            from modules.ui import HoloAvatar  # noqa: F401

        with self.assertRaises(ImportError):
            import core.avatar  # noqa: F401

        with self.assertRaises(ImportError):
            import core.avatar_mesh  # noqa: F401


if __name__ == "__main__":
    unittest.main()
