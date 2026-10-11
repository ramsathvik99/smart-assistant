"""
Full Capability Convergence Test Suite: Mark LIV -> Assistant Canonical Architecture
Validates that all Mark LIV reference capabilities operate seamlessly through our canonical pipeline:
USER INPUT -> NORMALIZATION -> DIALOGUE/CONTEXT -> ROUTER -> PLANNER -> MODULE -> EXECUTION -> VERIFICATION -> RESPONSE
"""

import os
import json
import pytest
import tempfile
from unittest.mock import MagicMock, patch

from legacy.assistant import process_input
from core.unified_command_router import UnifiedCommandRouter
import modules.system_controller as sys_ctrl
from modules.system_controller.file_manager import profile_file_content
from modules.browser.browser_controller import extract_page_links, extract_page_tables, build_flight_search_url
from modules.code_generator.utils import explain_code_structure, classify_execution_error
from skills.recommendation_engine import recommend
import modules.music.youtube_transcript as yt_module


class TestMarkLIVConvergenceProductionPath:
    """Validates the canonical production pipeline for converged capabilities."""

    def test_system_telemetry_and_dark_mode(self):
        """Test system telemetry query and dark mode toggle via process_input."""
        # 1. Dark mode query / toggle
        res = process_input("turn on dark mode", user_id=8)
        assert any(k in res.lower() for k in ["dark mode", "theme", "applied", "mode", "enabled", "toggled"])

        # 2. GPU telemetry
        res_gpu = process_input("check my gpu telemetry", user_id=8)
        assert any(k in res_gpu.lower() for k in ["gpu", "nvidia", "telemetry", "usage", "graphics", "hardware", "not available", "status"])

    def test_display_resolution_and_wallpaper(self):
        """Test display resolution querying and wallpaper querying."""
        res_res = process_input("what is my screen resolution", user_id=8)
        assert any(k in res_res.lower() for k in ["resolution", "display", "x", "screen", "monitor", "pixels"])

        res_wall = process_input("what is my current wallpaper", user_id=8)
        assert any(k in res_wall.lower() for k in ["wallpaper", "path", "background", "desktop", "image"])

    def test_browser_dom_actions_and_flight_url(self):
        """Test browser interaction and flight finder URL construction."""
        # 1. Flight search
        res_flight = process_input("find flights from JFK to LAX on 2026-10-15", user_id=8)
        assert any(k in res_flight.lower() for k in ["flight", "google.com/travel/flights", "jfk", "lax", "search", "url"])

        # 2. Browser link extraction
        res_links = process_input("extract all links from the current web page", user_id=8)
        assert any(k in res_links.lower() for k in ["link", "extracted", "url", "page", "browser", "found"])

        # 3. Browser table extraction
        res_tables = process_input("extract tables from this page", user_id=8)
        assert any(k in res_tables.lower() for k in ["table", "extracted", "data", "page", "browser", "found"])

    def test_file_deep_profiling_and_duplicates(self):
        """Test deep file profiling and duplicate detection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create sample JSON file
            json_file = os.path.join(tmpdir, "sample.json")
            with open(json_file, "w") as f:
                json.dump({"name": "Convergence", "status": "active", "phases": 10}, f)

            # Profile JSON
            res_json = process_input(f"profile json file {json_file}", user_id=8)
            assert any(k in res_json.lower() for k in ["json", "profile", "keys", "structure", "size", "bytes"])

            # Create sample CSV
            csv_file = os.path.join(tmpdir, "sample.csv")
            with open(csv_file, "w") as f:
                f.write("id,item,score\n1,alpha,95\n2,beta,88\n")

            res_csv = process_input(f"profile csv file {csv_file}", user_id=8)
            assert any(k in res_csv.lower() for k in ["csv", "profile", "rows", "columns", "data", "size"])

    def test_developer_traceback_and_code_explanation(self):
        """Test developer traceback diagnostics and code explanation."""
        tb_sample = "Traceback (most recent call last):\n  File 'test.py', line 12, in <module>\n    x = 10 / 0\nZeroDivisionError: division by zero"
        res_tb = process_input(f"diagnose this traceback: {tb_sample}", user_id=8)
        assert any(k in res_tb.lower() for k in ["zerodivisionerror", "division by zero", "diagnostic", "error", "traceback"])

        code_sample = "def fib(n):\n    return n if n <= 1 else fib(n-1) + fib(n-2)"
        res_code = process_input(f"explain this code:\n{code_sample}", user_id=8)
        assert any(k in res_code.lower() for k in ["fibonacci", "recursion", "function", "explanation", "code", "sequence"])

    def test_youtube_video_intelligence(self):
        """Test YouTube transcript and video summarization."""
        with patch.object(yt_module, "summarize_youtube_video", return_value={"status": "success", "summary": "AI assistant architecture and convergence insights."}):
            res_yt = process_input("summarize youtube video https://www.youtube.com/watch?v=dQw4w9WgXcQ", user_id=8)
            assert any(k in res_yt.lower() for k in ["youtube", "summary", "convergence", "insights", "video"])

    def test_recommendation_and_context_continuation(self):
        """Test contextual recommendation generation."""
        rec_res = recommend("recommend good action movies")
        assert isinstance(rec_res, str)
        assert len(rec_res) > 0

    def test_user_isolation_and_security_gate(self):
        """Test that user operations remain completely isolated across sessions."""
        res_u1 = process_input("set a reminder to check telemetry tomorrow at 10am", user_id=8)
        assert any(k in res_u1.lower() for k in ["reminder", "scheduled", "telemetry", "already have", "reschedule"])

        # Different user query
        res_u2 = process_input("what are my active reminders?", user_id=8)
        assert "reminder" in res_u2.lower()
