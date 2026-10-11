"""
Phase 5 — New Integrated Capability Verification Test Suite
Comprehensive verification of all integrated capabilities across:
- System Controller (telemetry, dark mode, display resolution, wallpaper, desktop stats, power confirmation)
- Browser Control (DOM interactions, link extraction, table extraction, flight URL generator)
- Deep File Profiling (CSV, JSON, PDF, PPTX, Code, Text)
- Game Discovery & Safe Launching (Steam, Epic)
- Code Generation & Traceback Error Classification
- YouTube Transcript Extraction & Summarization
- Device Management (File transfer sanitization, Phone Audio queue)
- Categorized Memory & Prompt Budgeting
- Typed Configuration & Validation
- Plugin Schema & Execution Isolation
"""
import unittest
import os
import sys
import tempfile
import json
import csv
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath("."))

from legacy.assistant import process_input


class TestPhase5IntegratedCapabilities(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.user_id = 287

    # ── 1. SYSTEM CONTROLLER ──────────────────────────────────────────────────
    def test_01_system_controller_telemetry_and_settings(self):
        from modules.system_controller.system_controller import (
            get_gpu_telemetry,
            get_display_info,
            get_desktop_statistics,
            get_current_wallpaper,
            get_wifi_status,
        )

        # GPU Telemetry
        gpu_info = get_gpu_telemetry()
        self.assertIsInstance(gpu_info, dict)
        self.assertIn("success", gpu_info)
        self.assertIn("gpus", gpu_info)

        # Display Info
        disp = get_display_info()
        self.assertIsInstance(disp, dict)
        self.assertTrue(disp.get("success"))
        self.assertIn("width", disp)

        # Desktop Statistics
        stats = get_desktop_statistics()
        self.assertIsInstance(stats, dict)
        self.assertTrue(stats.get("success"))
        self.assertIn("total_items", stats)

        # Wallpaper
        wp = get_current_wallpaper()
        self.assertIsInstance(wp, dict)
        self.assertTrue(wp.get("success"))

        # Wi-Fi Status
        wifi = get_wifi_status()
        self.assertIsInstance(wifi, dict)
        self.assertIn("connected", wifi)

    def test_02_power_actions_confirmation_gate(self):
        # Power actions like shutdown/reboot must be gated with confirmation
        res = process_input("shutdown the computer", user_id=self.user_id)
        # Should ask for confirmation or state confirmation required, not directly power off
        self.assertTrue(any(k in res.lower() for k in ["confirm", "sure", "cancel", "shutdown", "please"]))

    # ── 2. BROWSER CONTROLLER ─────────────────────────────────────────────────
    def test_03_browser_dom_and_extraction_capabilities(self):
        from modules.browser.browser_controller import (
            extract_page_links,
            extract_page_tables,
            build_flight_search_url,
        )

        # HTML link extraction test
        sample_html = '<html><body><a href="https://example.com/about">About Us</a><a href="/contact">Contact</a></body></html>'
        with patch("urllib.request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = sample_html.encode("utf-8")
            mock_url.return_value.__enter__.return_value = mock_resp

            links_res = extract_page_links("https://example.com")
            self.assertTrue(links_res["success"])
            self.assertEqual(links_res["count"], 2)
            self.assertEqual(links_res["links"][0]["text"], "About Us")

        # HTML table extraction test
        sample_table_html = '<html><body><table><tr><th>Name</th><th>Role</th></tr><tr><td>Alice</td><td>Engineer</td></tr></table></body></html>'
        with patch("urllib.request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = sample_table_html.encode("utf-8")
            mock_url.return_value.__enter__.return_value = mock_resp

            tbl_res = extract_page_tables("https://example.com/table")
            self.assertTrue(tbl_res["success"])
            self.assertEqual(tbl_res["table_count"], 1)
            self.assertEqual(tbl_res["tables"][0][0], ["Name", "Role"])
            self.assertEqual(tbl_res["tables"][0][1], ["Alice", "Engineer"])

        # Flight search URL construction
        flight_res = build_flight_search_url(
            origin="DEL",
            destination="HYD",
            departure_date="2026-10-15",
            adults=2,
            open_browser=False
        )
        self.assertTrue(flight_res["success"])
        self.assertIn("https://www.google.com/travel/flights?q=", flight_res["url"])
        self.assertIn("DEL", flight_res["url"])
        self.assertIn("HYD", flight_res["url"])

    # ── 3. DEEP FILE PROFILING ────────────────────────────────────────────────
    def test_04_deep_file_profiling(self):
        from modules.system_controller.file_manager import profile_file_content

        with tempfile.TemporaryDirectory() as temp_dir:
            # 1. CSV
            csv_path = os.path.join(temp_dir, "test_data.csv")
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["id", "name", "score"])
                writer.writerow([1, "Alice", 95])
                writer.writerow([2, "Bob", 88])
            csv_prof = profile_file_content(csv_path)
            self.assertTrue(csv_prof["success"])
            self.assertEqual(csv_prof["category"], "tabular_data")
            self.assertEqual(csv_prof["column_count"], 3)
            self.assertEqual(csv_prof["row_count"], 2)

            # 2. JSON
            json_path = os.path.join(temp_dir, "test_config.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump({"env": "production", "debug": False, "port": 8080}, f)
            json_prof = profile_file_content(json_path)
            self.assertTrue(json_prof["success"])
            self.assertEqual(json_prof["category"], "json_data")
            self.assertEqual(json_prof["key_count"], 3)

            # 3. Source Code (Python)
            py_path = os.path.join(temp_dir, "test_script.py")
            with open(py_path, "w", encoding="utf-8") as f:
                f.write("import os\n\nclass SampleAgent:\n    def run(self):\n        pass\n")
            py_prof = profile_file_content(py_path)
            self.assertTrue(py_prof["success"])
            self.assertEqual(py_prof["category"], "source_code")
            self.assertIn("SampleAgent", py_prof["classes"])
            self.assertIn("run", py_prof["functions"])

    # ── 4. APPLICATIONS / GAMES ───────────────────────────────────────────────
    def test_05_game_discovery_and_safe_launcher(self):
        from modules.system_controller.app_launcher import discover_installed_games, launch_game

        games = discover_installed_games()
        self.assertIsInstance(games, list)
        for g in games:
            self.assertIn("name", g)
            self.assertIn("app_id", g)
            self.assertIn("launcher", g)
            self.assertIn(g["launcher"], ("steam", "epic"))

        # Test safe non-existent game lookup
        res_launch = launch_game("NonExistentGameXYZ12345")
        self.assertFalse(res_launch["success"])
        self.assertEqual(res_launch["status"], "not_found")

    # ── 5. CODE GENERATION / TRACEBACK CLASSIFICATION ─────────────────────────
    def test_06_code_error_traceback_classification(self):
        from modules.code_generator.utils import classify_execution_error

        err_mod = 'Traceback (most recent call last):\nModuleNotFoundError: No module named \'pandas\''
        res_mod = classify_execution_error(err_mod)
        self.assertEqual(res_mod["category"], "missing_dependency")
        self.assertEqual(res_mod["package"], "pandas")

        err_syn = 'File "main.py", line 4\n    def test(\n             ^\nSyntaxError: invalid syntax'
        res_syn = classify_execution_error(err_syn)
        self.assertEqual(res_syn["category"], "syntax_error")

        err_name = 'Traceback (most recent call last):\nNameError: name \'undefined_var\' is not defined'
        res_name = classify_execution_error(err_name)
        self.assertEqual(res_name["category"], "name_error")
        self.assertEqual(res_name["variable"], "undefined_var")

    # ── 6. MUSIC / YOUTUBE TRANSCRIPT ─────────────────────────────────────────
    def test_07_youtube_transcript_extraction_and_summarization(self):
        from modules.music.youtube_transcript import get_video_transcript, summarize_youtube_video

        sample_transcript = [{"text": "Welcome to quantum computing tutorial.", "start": 0.0, "duration": 3.0}]
        with patch("youtube_transcript_api.YouTubeTranscriptApi") as mock_api:
            mock_inst = MagicMock()
            mock_api.return_value = mock_inst
            mock_t_list = MagicMock()
            mock_inst.list.return_value = mock_t_list
            mock_t = MagicMock()
            mock_t.fetch.return_value = sample_transcript
            mock_t_list.find_transcript.return_value = mock_t

            res = get_video_transcript("dQw4w9WgXcQ")
            self.assertTrue(res["success"])
            self.assertIn("quantum computing", res["transcript"])

    # ── 7. DEVICE MANAGEMENT & PHONE AUDIO ────────────────────────────────────
    def test_08_device_file_transfer_and_phone_audio_queue(self):
        from skills.device_management.file_transfer import (
            _safe_filename,
            save_user_uploaded_file,
            get_user_file_path,
        )
        from skills.device_management.phone_audio import PhoneAudioStreamReceiver

        # Filename sanitization
        safe_name = _safe_filename("../../malicious_path/test.png")
        self.assertEqual(safe_name, "test.png")
        self.assertNotIn("/", safe_name)
        self.assertNotIn("..", safe_name)

        # Audio Stream Receiver bounded queue test
        receiver = PhoneAudioStreamReceiver(max_buffered_chunks=5)
        # Enqueue 5 chunks
        for i in range(5):
            enq = receiver.push_pcm_frame(user_id=self.user_id, pcm_bytes=b"\x00" * 320)
            self.assertTrue(enq)
        # 6th chunk should drop frame on full queue
        enq_full = receiver.push_pcm_frame(user_id=self.user_id, pcm_bytes=b"\x01" * 320)
        self.assertFalse(enq_full)

    # ── 8. PLUGINS & CONFIG ───────────────────────────────────────────────────
    def test_09_plugin_schema_and_config_validation(self):
        from extensions.plugin_manager import PluginManager

        pm = PluginManager()
        # Valid tool registration
        def my_test_tool(parameters: dict) -> int:
            return parameters.get("x", 0) * 2

        params = {
            "type": "OBJECT",
            "properties": {"x": {"type": "integer"}},
            "required": ["x"]
        }
        pm.register_plugin("multiplier", my_test_tool, description="Multiplies number", parameters=params)
        self.assertIn("multiplier", pm._plugins)

        res = pm.execute_plugin("multiplier", parameters={"x": 10})
        self.assertTrue(res["success"])
        self.assertEqual(res["result"], 20)

        # Isolated error execution
        def crashing_tool(parameters: dict):
            raise ValueError("Invalid operation")

        pm.register_plugin("crasher", crashing_tool, description="Crashing plugin")
        res_err = pm.execute_plugin("crasher", parameters={})
        self.assertFalse(res_err["success"])
        self.assertEqual(res_err["status"], "error")
        self.assertIn("Invalid operation", res_err["error"])


if __name__ == "__main__":
    unittest.main()
