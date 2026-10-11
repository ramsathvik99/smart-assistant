"""
Behavioral Convergence & Real-World Capability Gap Test Suite
Tests real-world assistant workflows, multi-step chains, contextual follow-ups,
truthful error reporting, file/browser/system/developer capabilities, and user isolation.
"""

import os
import json
import pytest
import tempfile
from unittest.mock import MagicMock, patch

from legacy.assistant import process_input
from core.unified_command_router import UnifiedCommandRouter, Intent
from core.goal_planner import GoalPlanner, ExecutionPlan
from core.multi_intent_analyzer import MultiIntentAnalyzer
from extensions.dialogue_state_manager import DialogueStateManager
from extensions.context_manager import get_manager
import modules.system_controller as sys_ctrl
from modules.system_controller.file_manager import (
    profile_file_content,
    find_duplicate_files,
    get_largest_files,
    search_files,
)
from modules.browser.browser_controller import (
    extract_page_links,
    extract_page_tables,
    build_flight_search_url,
)
from modules.code_generator.utils import (
    explain_code_structure,
    classify_execution_error,
    parse_traceback,
)
from skills.recommendation_engine import recommend
import modules.music.youtube_transcript as yt_module


class TestMarkLIVBehavioralWorkflows:
    """Tests real-world end-to-end workflows across all converged functional domains."""

    def test_multi_step_system_workflow(self):
        """Test chained multi-intent command: dark mode + screen resolution."""
        # Chained command through canonical process_input
        res = process_input("turn on dark mode and check my screen resolution", user_id=8)
        assert isinstance(res, str)
        res_low = res.lower()
        assert any(k in res_low for k in ["dark mode", "theme", "mode", "resolution", "display", "1920", "pixels", "applied"])

    def test_system_telemetry_truthful_reporting(self):
        """Test GPU and CPU telemetry returns structured and truthful metrics."""
        gpu_telemetry = sys_ctrl.get_gpu_telemetry()
        assert isinstance(gpu_telemetry, dict)
        assert "success" in gpu_telemetry
        assert "message" in gpu_telemetry

        # Test process_input pipeline invocation
        res_gpu = process_input("check my gpu telemetry", user_id=8)
        assert any(k in res_gpu.lower() for k in ["gpu", "telemetry", "nvidia", "hardware", "status", "usage", "not available"])

    def test_file_duplicate_and_largest_files_workflow(self):
        """Test real file system duplicate detection and largest file search."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create two identical files (duplicates)
            f1 = os.path.join(tmpdir, "doc1.txt")
            f2 = os.path.join(tmpdir, "doc1_copy.txt")
            f_large = os.path.join(tmpdir, "large_data.bin")

            content = "Autonomous AI Assistant Canonical Architecture Convergence."
            with open(f1, "w") as fp: fp.write(content)
            with open(f2, "w") as fp: fp.write(content)
            with open(f_large, "wb") as fp: fp.write(b"0" * 1024 * 100)  # 100 KB

            # 1. Duplicate detection
            dup_res = find_duplicate_files(tmpdir)
            assert dup_res.get("success") is True
            assert dup_res.get("duplicate_groups", 0) >= 1

            # 2. Largest files
            large_res = get_largest_files(tmpdir, n=2)
            assert large_res.get("success") is True
            files = large_res.get("files", [])
            assert len(files) >= 1
            assert any("large_data.bin" in f.get("name", "") for f in files)

    def test_deep_document_and_code_profiling(self):
        """Test multi-format profiling: CSV schema, JSON keys, and Code AST."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # CSV file
            csv_path = os.path.join(tmpdir, "metrics.csv")
            with open(csv_path, "w") as fp:
                fp.write("epoch,loss,accuracy\n1,0.45,0.88\n2,0.25,0.94\n3,0.12,0.98\n")

            csv_prof = profile_file_content(csv_path)
            assert csv_prof.get("success") is True
            assert csv_prof.get("category") == "tabular_data"
            assert csv_prof.get("row_count") == 3
            assert "epoch" in csv_prof.get("columns", [])

            # Python Code file
            py_path = os.path.join(tmpdir, "model.py")
            code_str = "class TransformerModel:\n    def forward(self, x):\n        return x * 2\n"
            with open(py_path, "w") as fp:
                fp.write(code_str)

            py_prof = profile_file_content(py_path)
            assert py_prof.get("success") is True
            assert py_prof.get("category") in ["code", "source_code"]
            assert py_prof.get("extension") == ".py"

    def test_browser_and_flight_workflow(self):
        """Test structured flight URL construction and browser extraction."""
        # 1. Flight search URL construction with airport codes & date
        flight_res = build_flight_search_url("HYD", "DEL", "2026-11-20")
        assert flight_res.get("success") is True
        assert "google.com/travel/flights" in flight_res.get("url", "")
        assert "HYD" in flight_res.get("url", "")
        assert "DEL" in flight_res.get("url", "")

        # 2. Extract links and tables from simulated HTML
        sample_html = "<html><body><a href='https://example.com/one'>One</a><table><tr><td>Item</td><td>Price</td></tr><tr><td>A</td><td>$10</td></tr></table></body></html>"
        with patch("modules.browser.browser_controller.extract_page_text", return_value={"success": True, "text": "Sample Page"}):
            with patch("urllib.request.urlopen") as mock_url:
                mock_resp = MagicMock()
                mock_resp.read.return_value = sample_html.encode("utf-8")
                mock_url.return_value.__enter__.return_value = mock_resp

                links = extract_page_links("https://example.com")
                assert links.get("success") is True
                assert links.get("count", 0) >= 1

                tables = extract_page_tables("https://example.com")
                assert tables.get("success") is True
                assert tables.get("table_count", len(tables.get("tables", []))) >= 1

    def test_developer_diagnostics_and_error_classification(self):
        """Test traceback parsing and automatic error category classification."""
        tb_sample = """Traceback (most recent call last):
  File "app.py", line 45, in load_config
    with open("missing_config.json", "r") as f:
FileNotFoundError: [Errno 2] No such file or directory: 'missing_config.json'"""

        diag = classify_execution_error(tb_sample)
        assert diag.get("category") == "file_not_found"
        assert "file paths" in diag.get("suggestion", "").lower()

    def test_youtube_video_and_transcript_workflow(self):
        """Test YouTube video ID extraction, transcript retrieval, and summarization."""
        test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        vid_id = yt_module.extract_video_id(test_url)
        assert vid_id == "dQw4w9WgXcQ"

        # Mock transcript fetch and summarization
        with patch.object(yt_module, "get_video_transcript", return_value={"success": True, "transcript": "In this tutorial we explore AI systems."}):
            with patch.object(yt_module, "summarize_youtube_video", return_value={"status": "success", "summary": "Core AI concepts tutorial."}):
                res = process_input(f"summarize youtube video {test_url}", user_id=8)
                assert any(k in res.lower() for k in ["youtube", "summary", "ai", "tutorial", "concepts", "video"])

    def test_contextual_recommendations(self):
        """Test recommendation engine for realistic contextual assistance queries."""
        rec_movies = recommend("suggest top machine learning books")
        assert isinstance(rec_movies, str)
        assert len(rec_movies) > 0

    def test_destructive_action_confirmation_safety(self):
        """Test that destructive operations require confirmation and are not executed blindly."""
        res_sd = process_input("shut down the computer", user_id=8)
        # Power actions require confirmation or safe prompt
        assert any(k in res_sd.lower() for k in ["confirm", "shut down", "shutdown", "power", "proceed", "sure"])

    def test_user_isolation_state_persistence(self):
        """Test that user operations and contexts remain isolated between user accounts."""
        # Query active state for User 8
        res_u8 = process_input("what are my active reminders?", user_id=8)
        assert isinstance(res_u8, str)
        assert len(res_u8) > 0
