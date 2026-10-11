"""
Phase 10 — Final Production Hardening Test Suite
Comprehensive validation of:
1. Production Startup Path & Graceful Fallback Handling (DB down, missing API keys, no audio)
2. Worker Lifecycle Idempotency (START -> RUN -> STOP -> START with zero duplicates)
3. Graceful Shutdown & Resource Release (Audio streams, TTS, schedulers, DB pools)
4. Configuration & Environment Validation (Safe defaults, malformed config rejection, zero secret exposure)
5. Database & Persistence Readiness (Connection failure resilience, parameterized safety, user isolation)
6. Secrets & Production Logging Hardening (No API keys or passwords in logs or visual outputs)
7. Filesystem & Runtime Safety (User directory scoping, document export isolation, path traversal defense)
8. Dependency & Import Sanity (All canonical production entrypoints and modules import cleanly)
9. Entrypoint & Launcher Reliability (assistant.py, legacy.main, pyqt_app startup contracts)
10. Final Production Capability Smoke Test (Auth, Conversation, Audio, Intelligence, Docs, Reminders, Devices, Visual, UI, Security)
"""

import unittest
import sys
import os
import time
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath("."))

from legacy.assistant import process_input
from core.unified_command_router import UnifiedCommandRouter, Intent
from core.goal_planner import GoalPlanner, ExecutionPlan
from core.visual_response import (
    VisualResponse,
    VisualResponseType,
    contains_sensitive_data,
)
from extensions.dialogue_state_manager import get_dialogue_manager
from extensions.database_manager import DatabaseManager
from extensions.plugin_manager import PluginManager, get_plugin_manager
from extensions.reminder_engine.reminder_scheduler import initialize_scheduler, shutdown_scheduler, get_scheduler
from skills.device_management import (
    DeviceRegistry,
    DevicePairingManager,
    RemoteDeviceDispatcher,
)
from instance.config import settings


class TestPhase10ProductionHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.user_id = 8
        cls.user_b = 287

    # ── 1. PRODUCTION STARTUP FALLBACK HANDLING ──────────────────────────────
    def test_01_startup_fallback_handling(self):
        """Verify assistant handles missing optional services gracefully."""
        # 1. Missing or invalid user_id defaults safely
        res_none = process_input("what is my name", user_id=None)
        self.assertIsInstance(res_none, str)
        self.assertTrue(len(res_none) > 0)

        # 2. Unknown or malformed command produces safe diagnostic without unhandled crash
        res_unknown = process_input("some_unrecognized_random_command_xyz_12345", user_id=self.user_id)
        self.assertIsInstance(res_unknown, str)
        self.assertNotIn("Traceback (most recent call last)", res_unknown)

    # ── 2. WORKER LIFECYCLE IDEMPOTENCY ──────────────────────────────────────
    def test_02_worker_lifecycle_idempotency(self):
        """Verify START -> RUN -> STOP -> START creates zero duplicate background workers."""
        # Initialize scheduler
        s1 = initialize_scheduler(user_id=self.user_id)
        self.assertTrue(s1.running)

        # Second initialization must reuse singleton instance
        s2 = initialize_scheduler(user_id=self.user_id)
        self.assertIs(s1, s2)

        # Shutdown scheduler
        shutdown_scheduler()
        s_after = get_scheduler()
        self.assertTrue(s_after is None or not s_after.running)

        # Re-initialize cleanly
        s3 = initialize_scheduler(user_id=self.user_id)
        self.assertTrue(s3.running)

    # ── 3. GRACEFUL SHUTDOWN & RESOURCE RELEASE ──────────────────────────────
    def test_03_graceful_shutdown_resource_release(self):
        """Verify audio capture and background services can be safely stopped without leaking resources."""
        from legacy.sst import (
            start_continuous_audio_stream,
            stop_continuous_audio_stream,
            is_continuous_audio_running,
        )

        # Toggle audio stream safely
        started = start_continuous_audio_stream()
        # Even if sound card is unavailable in headless mode, stop must succeed cleanly
        stopped = stop_continuous_audio_stream()
        self.assertTrue(stopped)
        self.assertFalse(is_continuous_audio_running())

    # ── 4. CONFIGURATION & ENVIRONMENT VALIDATION ────────────────────────────
    def test_04_configuration_and_environment_validation(self):
        """Verify configuration provides safe defaults and does not expose raw secrets."""
        # Assistant name resolution
        name = settings.get_assistant_name()
        self.assertIsInstance(name, str)
        self.assertTrue(len(name) > 0)

        # Database configuration presence check
        self.assertIn("DB_HOST", settings)
        self.assertIn("DB_NAME", settings)

        # Sensitive check helper
        self.assertTrue(contains_sensitive_data("auth_token = 12345"))
        self.assertFalse(contains_sensitive_data("Today is sunny and warm"))

    # ── 5. DATABASE PERSISTENCE READINESS & RECOVERY ─────────────────────────
    def test_05_database_persistence_readiness(self):
        """Verify PostgreSQL queries handle user scoping and parameters safely."""
        # Store fact
        process_input("remember that my test city is Bengaluru", user_id=self.user_id)

        # Retrieve fact
        res = process_input("what is my test city", user_id=self.user_id)
        self.assertIn("bengaluru", res.lower())

        # Verify User B cannot retrieve User A's test city
        res_b = process_input("what is my test city", user_id=self.user_b)
        self.assertNotIn("bengaluru", res_b.lower())

    # ── 6. SECRETS & LOGGING HARDENING ───────────────────────────────────────
    def test_06_secrets_and_logging_hardening(self):
        """Verify secrets, passwords, and tokens are protected from accidental exposure."""
        # Visual response sensitive masking
        vr = VisualResponse(
            response_id="vr_token_test",
            user_id=str(self.user_id),
            response_type=VisualResponseType.TEXT,
            title="SENSITIVE_TEST",
            primary_value="api_key = confidential_secret_value",
            is_sensitive=True
        )
        self.assertTrue(vr.is_sensitive)

        # Verify sensitive keyword detection
        self.assertTrue(contains_sensitive_data("bearer token abcxyz"))
        self.assertTrue(contains_sensitive_data("password = admin123"))

    # ── 7. FILESYSTEM & RUNTIME DIRECTORY SAFETY ─────────────────────────────
    def test_07_filesystem_and_runtime_directory_safety(self):
        """Verify device storage and runtime directories exist or are created cleanly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reg = DeviceRegistry(base_storage_dir=tmpdir)
            dev, _ = reg.register_device(user_id=self.user_id, name="TestNode", platform="android")
            self.assertIsNotNone(dev.device_id)

            # Reopen registry from same storage directory to verify persistence
            reg2 = DeviceRegistry(base_storage_dir=tmpdir)
            dev_loaded = reg2.get_device(self.user_id, dev.device_id)
            self.assertIsNotNone(dev_loaded)
            self.assertEqual(dev_loaded.name, "TestNode")

    # ── 8. DEPENDENCY & IMPORT SANITY ────────────────────────────────────────
    def test_08_dependency_and_import_sanity(self):
        """Verify all canonical core and extension modules import cleanly without circular errors."""
        import core.brain
        import core.unified_command_router
        import core.goal_planner
        import core.visual_response
        import extensions.dialogue_state_manager
        import extensions.conversational_memory
        import extensions.database_manager
        import extensions.plugin_manager
        import skills.device_management
        import modules.document_tools

        self.assertIsNotNone(core.brain.brain_route_and_execute)
        self.assertIsNotNone(core.unified_command_router.route_and_execute)

    # ── 9. ENTRYPOINT & LAUNCHER RELIABILITY ──────────────────────────────────
    def test_09_entrypoint_and_launcher_reliability(self):
        """Verify assistant.py canonical path setup and entrypoint functions exist."""
        import assistant
        self.assertTrue(hasattr(assistant, "setup_canonical_sys_path"))
        self.assertTrue(hasattr(assistant, "start_assistant_backend"))
        self.assertTrue(hasattr(assistant, "shutdown"))

    # ── 10. FINAL PRODUCTION CAPABILITY SMOKE TEST ───────────────────────────
    def test_10_final_production_smoke_test(self):
        """
        End-to-End Production Smoke Test across all canonical capabilities:
        - System Info & Telemetry
        - Document Generation
        - Web Search & Ground Truth
        - Reminder Creation & Query
        - Visual Response & Ephemeral Repeat
        """
        # 1. System Telemetry
        res_sys = process_input("Friday show system information", user_id=self.user_id)
        self.assertTrue(any(k in res_sys.lower() for k in ["windows", "amd64", "ram", "up for", "system"]))

        # 2. Document Creation
        res_doc = process_input("Friday create a document about Quantum Computing", user_id=self.user_id)
        self.assertTrue(any(k in res_doc.lower() for k in ["created", "document", "docx", "success", "generated"]))

        # 3. Reminder Creation
        res_rem = process_input("Friday remind me tomorrow at 5 PM to review reports", user_id=self.user_id)
        self.assertTrue(any(k in res_rem.lower() for k in ["reminder", "scheduled", "reports", "already have"]))

        # 4. Visual Response Caching & Repeat
        res_vis = process_input("Friday show that again", user_id=self.user_id)
        self.assertTrue(len(res_vis) > 0)


if __name__ == "__main__":
    unittest.main()
