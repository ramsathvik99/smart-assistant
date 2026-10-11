"""
Production Hardening, Real pgvector & Multi-User Isolation Test Suite
Validates:
1. Production environment separation: rejection of localhost in prod build, no silent local DB fallback.
2. Complete elimination of plaintext passwords in database: password_hash as canonical authority.
3. Real pgvector / cosine semantic memory search with strict user isolation.
4. Migration versioning and advisory locking safety.
5. Multi-user isolation across 3 separate user instances (User A, User B, User C).
"""

import sys
import os
import time
import json
import unittest

sys.path.insert(0, os.path.abspath("."))

from core.db_pool import get_db_pool
from core.auth_service import (
    register_user,
    authenticate_user_credentials,
    hash_password,
    verify_password
)
from core.user_isolation import (
    enforce_ownership,
    export_user_data,
    delete_user_account_cascading,
    AuthorizationError
)
from core.chatgpt_memory import get_chatgpt_memory
from core.api_client import SmartAssistantApiClient
from core.migration_runner import run_migrations


class TestProductionHardeningAndPgVector(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pool = get_db_pool()
        cls.mem_mgr = get_chatgpt_memory()
        run_migrations()

        # Generate unique test users
        ts = int(time.time() * 1000) % 1000000
        cls.u_a_name = f"prod_alice_{ts}"
        cls.u_b_name = f"prod_bob_{ts}"
        cls.u_c_name = f"prod_charlie_{ts}"
        cls.passw = "ProdSecure@2026!"

        res_a = register_user(cls.u_a_name, cls.passw)
        res_b = register_user(cls.u_b_name, cls.passw)
        res_c = register_user(cls.u_c_name, cls.passw)

        cls.u_a_id = res_a.get("user_id")
        cls.u_b_id = res_b.get("user_id")
        cls.u_c_id = res_c.get("user_id")

        cls.token_a = res_a.get("token")
        cls.token_b = res_b.get("token")
        cls.token_c = res_c.get("token")

    @classmethod
    def tearDownClass(cls):
        if cls.u_a_id:
            delete_user_account_cascading(cls.u_a_id)
        if cls.u_b_id:
            delete_user_account_cascading(cls.u_b_id)
        if cls.u_c_id:
            delete_user_account_cascading(cls.u_c_id)

    # ── 1. PRODUCTION ENVIRONMENT SAFETY & CLIENT GUARDRAILS ──────────────────

    def test_01_production_client_rejects_localhost(self):
        """Production build must disallow pointing to localhost or 127.0.0.1."""
        old_env = os.environ.get("APP_ENV")
        try:
            os.environ["APP_ENV"] = "production"
            # Attempting to initialize client with localhost in production raises ValueError
            with self.assertRaises(ValueError):
                SmartAssistantApiClient(base_url="http://localhost:8000")
        finally:
            if old_env:
                os.environ["APP_ENV"] = old_env
            else:
                os.environ.pop("APP_ENV", None)

    def test_02_production_client_no_silent_local_fallback(self):
        """When remote production API is unreachable, client returns controlled offline error."""
        old_env = os.environ.get("APP_ENV")
        try:
            os.environ["APP_ENV"] = "production"
            os.environ["ALLOW_TEST_LOCAL_PRODUCTION"] = "1"
            # Target an unreachable port
            client = SmartAssistantApiClient(base_url="http://127.0.0.1:59999")
            res = client.execute_command("test status")
            self.assertFalse(res.get("success"))
            self.assertEqual(res.get("code"), "NETWORK_OFFLINE")
            self.assertIn("Smart Assistant Cloud API is unreachable", res.get("error", ""))
        finally:
            os.environ.pop("ALLOW_TEST_LOCAL_PRODUCTION", None)
            if old_env:
                os.environ["APP_ENV"] = old_env
            else:
                os.environ.pop("APP_ENV", None)

    # ── 2. PASSWORD STORAGE SECURITY (PLAINTEXT ELIMINATED) ───────────────────

    def test_03_zero_plaintext_passwords_stored(self):
        """Newly created accounts store ONLY password_hash with sanitized legacy field."""
        with self.pool.get_cursor() as cur:
            cur.execute("SELECT password, password_hash FROM users WHERE id = %s", (self.u_a_id,))
            row = cur.fetchone()
            legacy_pass, pw_hash = row[0], row[1]

            # Canonical password_hash is PBKDF2 format
            self.assertTrue(pw_hash.startswith("$pbkdf2-sha256$100000$"))
            # Legacy password column is sanitized
            self.assertEqual(legacy_pass, "[HASHED_PBKDF2]")

    def test_04_auth_verifies_against_password_hash(self):
        """Authentication authenticates strictly via salted PBKDF2 hash."""
        res = authenticate_user_credentials(self.u_a_name, self.passw)
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("user_id"), self.u_a_id)

        # Wrong password fails
        res_wrong = authenticate_user_credentials(self.u_a_name, "InvalidPassword@123")
        self.assertFalse(res_wrong.get("success"))
        self.assertEqual(res_wrong.get("code"), "WRONG_PASSWORD")

    # ── 3. REAL PGVECTOR SEMANTIC MEMORY & ISOLATION ──────────────────────────

    def test_05_pgvector_embedding_insertion_and_search(self):
        """Insert and search semantic vector embeddings with cosine similarity."""
        # Simulated 8-dimensional normalized vectors for testing
        vec_tech = [0.9, 0.8, 0.1, 0.0, 0.0, 0.2, 0.1, 0.0]
        vec_cooking = [0.0, 0.1, 0.9, 0.8, 0.7, 0.0, 0.1, 0.2]

        self.mem_mgr.insert_memory_embedding(
            user_id=self.u_a_id,
            content_text="Alice is building an autonomous AI assistant.",
            vector=vec_tech
        )
        self.mem_mgr.insert_memory_embedding(
            user_id=self.u_a_id,
            content_text="Alice loves baking homemade sourdough bread.",
            vector=vec_cooking
        )

        # Query vector close to tech
        query_tech = [0.85, 0.75, 0.1, 0.0, 0.0, 0.1, 0.1, 0.0]
        results = self.mem_mgr.search_memory_embeddings(self.u_a_id, query_tech, limit=2)
        self.assertTrue(len(results) > 0)
        self.assertIn("AI assistant", results[0]["content_text"])
        self.assertGreater(results[0]["similarity"], 0.8)

    def test_06_pgvector_multi_user_isolation(self):
        """Vector search by User B must NEVER return User A's vector embeddings."""
        # Query User B with exact vector used by User A
        query_tech = [0.9, 0.8, 0.1, 0.0, 0.0, 0.2, 0.1, 0.0]
        results_b = self.mem_mgr.search_memory_embeddings(self.u_b_id, query_tech, limit=5)

        # Must not find User A's embeddings
        for item in results_b:
            self.assertNotIn("Alice is building", item["content_text"])

    # ── 4. MIGRATION VERSIONING & ADVISORY LOCKING ────────────────────────────

    def test_07_migration_tracking_and_idempotency(self):
        """Migration runner records versions in schema_migrations and runs idempotently."""
        with self.pool.get_cursor() as cur:
            cur.execute("SELECT version FROM schema_migrations ORDER BY version ASC;")
            applied = [r[0] for r in cur.fetchall()]
            self.assertIn("001_multi_user_and_memory_architecture.sql", applied)
            self.assertIn("002_remove_plaintext_password_column.sql", applied)
            self.assertIn("003_pgvector_semantic_memory.sql", applied)

        # Running migrations again must succeed without errors
        run_migrations()

    # ── 5. COMPLETE MULTI-USER ISOLATION SCENARIO (Alice, Bob, Charlie) ───────

    def test_08_full_multi_user_end_to_end_isolation(self):
        """
        Simulate User A, User B, User C across independent sessions:
        Verify total data isolation across all subsystems.
        """
        # 1. Facts
        self.mem_mgr.set_user_fact(self.u_a_id, "project", "Nova Production Hardening")
        self.mem_mgr.set_user_fact(self.u_b_id, "project", "Quantum Computing Simulator")
        self.mem_mgr.set_user_fact(self.u_c_id, "project", "Robotics Navigation")

        # 2. Preferences
        self.mem_mgr.set_preference(self.u_a_id, "voice", "en-us-female")
        self.mem_mgr.set_preference(self.u_b_id, "voice", "en-gb-male")
        self.mem_mgr.set_preference(self.u_c_id, "voice", "ja-jp-neutral")

        # 3. Conversations
        self.mem_mgr.log_interaction(self.u_a_id, "Alice confidential input", "Alice response")
        self.mem_mgr.log_interaction(self.u_b_id, "Bob secret discussion", "Bob response")
        self.mem_mgr.log_interaction(self.u_c_id, "Charlie classified chat", "Charlie response")

        # Verification for User A
        exp_a = export_user_data(self.u_a_id)
        exp_a_str = json.dumps(exp_a)
        self.assertIn("Nova Production Hardening", exp_a_str)
        self.assertNotIn("Quantum Computing Simulator", exp_a_str)
        self.assertNotIn("Robotics Navigation", exp_a_str)
        self.assertNotIn("Bob secret discussion", exp_a_str)
        self.assertNotIn("Charlie classified chat", exp_a_str)

        # Cross-user authorization checks
        with self.assertRaises(AuthorizationError):
            enforce_ownership(self.u_a_id, self.u_b_id)
        with self.assertRaises(AuthorizationError):
            enforce_ownership(self.u_b_id, self.u_c_id)
        with self.assertRaises(AuthorizationError):
            enforce_ownership(self.u_c_id, self.u_a_id)


if __name__ == "__main__":
    unittest.main()
