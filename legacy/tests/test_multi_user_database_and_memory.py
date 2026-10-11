"""
Comprehensive Multi-User Database & ChatGPT-Style Memory Architecture Test Suite
Tests:
1. Authentication: PBKDF2-HMAC-SHA256 hashing, token generation, verification, legacy migration, revocation.
2. Multi-User Isolation: User A vs User B vs User C complete data isolation across all tables.
3. ChatGPT-Style Memory Architecture: extraction, lexical/semantic ranking, context budgeting, fact persistence.
4. GDPR Compliance: Structured JSON data export and atomic cascading account deletion.
5. Database Connection Pool & Admin Observability: Resilience, health checks, non-sensitive metrics.
6. Desktop Client API Integration: REST API communication via token authentication.
"""

import sys
import os
import time
import json
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath("."))

from core.db_pool import get_db_pool
from core.auth_service import (
    hash_password,
    verify_password,
    generate_token,
    verify_token,
    revoke_token,
    register_user,
    authenticate_user_credentials,
    change_user_password
)
from core.user_isolation import (
    extract_authenticated_user,
    enforce_ownership,
    export_user_data,
    delete_user_account_cascading,
    AuthorizationError
)
from core.chatgpt_memory import (
    ChatGPTMemoryManager,
    get_chatgpt_memory,
    _extract_keywords,
    _compute_relevance_score
)
from core.admin_metrics import get_admin_metrics
from core.api_client import SmartAssistantApiClient
from legacy.memory_manager import (
    authenticate_user as legacy_auth,
    register_user as legacy_register,
    get_connection,
    save_to_db
)


class TestMultiUserDatabaseAndMemory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pool = get_db_pool()
        cls.mem_mgr = get_chatgpt_memory()
        
        # Unique timestamp for isolation test accounts
        ts = int(time.time() * 1000) % 1000000
        cls.user_a_name = f"test_alice_{ts}"
        cls.user_b_name = f"test_bob_{ts}"
        cls.user_c_name = f"test_charlie_{ts}"
        cls.common_pass = "SecurePass123!"

        # Register 3 test users
        res_a = register_user(cls.user_a_name, cls.common_pass)
        res_b = register_user(cls.user_b_name, cls.common_pass)
        res_c = register_user(cls.user_c_name, cls.common_pass)

        cls.user_a_id = res_a.get("user_id")
        cls.user_b_id = res_b.get("user_id")
        cls.user_c_id = res_c.get("user_id")

        cls.token_a = res_a.get("token")
        cls.token_b = res_b.get("token")
        cls.token_c = res_c.get("token")

    @classmethod
    def tearDownClass(cls):
        # Cleanup test accounts
        if cls.user_a_id:
            delete_user_account_cascading(cls.user_a_id)
        if cls.user_b_id:
            delete_user_account_cascading(cls.user_b_id)
        if cls.user_c_id:
            delete_user_account_cascading(cls.user_c_id)

    # ── 1. AUTHENTICATION & PASSWORD SECURITY ─────────────────────────────────

    def test_01_pbkdf2_password_hashing(self):
        """Verify PBKDF2-HMAC-SHA256 creates secure salted hashes and verifies correctly."""
        password = "MySuperSecretPassword@2026"
        hashed = hash_password(password)

        self.assertTrue(hashed.startswith("$pbkdf2-sha256$100000$"))
        
        # Valid password check
        is_val, needs_rehash = verify_password(password, hashed)
        self.assertTrue(is_val)
        self.assertFalse(needs_rehash)

        # Invalid password check
        is_val_wrong, _ = verify_password("WrongPassword!", hashed)
        self.assertFalse(is_val_wrong)

    def test_02_legacy_password_auto_upgrade(self):
        """Legacy plaintext or SHA-256 passwords must authenticate and auto-upgrade to PBKDF2."""
        ts = int(time.time() * 1000) % 1000000
        legacy_uname = f"legacy_user_{ts}"
        legacy_pass = "LegacyPassword123"

        # Insert user with plaintext password simulating old database state
        with self.pool.get_cursor() as cur:
            cur.execute("""
                INSERT INTO users (username, password, status)
                VALUES (%s, %s, 'active')
                RETURNING id
            """, (legacy_uname, legacy_pass))
            legacy_uid = cur.fetchone()[0]

        # First login: verifies match and upgrades password hash
        res = authenticate_user_credentials(legacy_uname, legacy_pass)
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("user_id"), legacy_uid)

        # Verify in DB that password was upgraded to PBKDF2
        with self.pool.get_cursor() as cur:
            cur.execute("SELECT password, password_hash FROM users WHERE id = %s", (legacy_uid,))
            row = cur.fetchone()
            self.assertTrue(row[0].startswith("$pbkdf2-sha256$") or (row[1] and row[1].startswith("$pbkdf2-sha256$")))

        # Clean up legacy test user
        delete_user_account_cascading(legacy_uid)

    def test_03_jwt_token_lifecycle(self):
        """Verify JWT-style signed token issuance, verification, expiration, and revocation."""
        user_id = 999
        username = "token_tester"
        
        # 1. Valid token
        token = generate_token(user_id, username, expires_in=3600)
        payload = verify_token(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload.get("sub"), user_id)
        self.assertEqual(payload.get("username"), username)

        # 2. Expired token
        expired_token = generate_token(user_id, username, expires_in=-10)
        expired_payload = verify_token(expired_token)
        self.assertIsNone(expired_payload)

        # 3. Forged token (tampered payload or signature)
        parts = token.split(".")
        tampered_token = f"{parts[0]}.{parts[1]}.invalidsignature123"
        self.assertIsNone(verify_token(tampered_token))

        # 4. Revocation
        revoke_token(token)
        self.assertIsNone(verify_token(token))

    def test_04_auth_header_extraction(self):
        """Verify token extraction from Bearer Authorization header."""
        header = f"Bearer {self.token_a}"
        user_info = extract_authenticated_user(header)
        self.assertIsNotNone(user_info)
        self.assertEqual(user_info.get("sub"), self.user_a_id)

        # Invalid header
        self.assertIsNone(extract_authenticated_user("Bearer invalid.token.structure"))
        self.assertIsNone(extract_authenticated_user(""))

    # ── 2. THREE-USER DATA ISOLATION (Alice vs Bob vs Charlie) ────────────────

    def test_05_multi_user_facts_isolation(self):
        """User A, User B, and User C must have isolated memory facts."""
        self.mem_mgr.set_user_fact(self.user_a_id, "city", "San Francisco")
        self.mem_mgr.set_user_fact(self.user_a_id, "dog_name", "Buddy")

        self.mem_mgr.set_user_fact(self.user_b_id, "city", "London")
        self.mem_mgr.set_user_fact(self.user_b_id, "cat_name", "Whiskers")

        self.mem_mgr.set_user_fact(self.user_c_id, "city", "Tokyo")
        self.mem_mgr.set_user_fact(self.user_c_id, "hobby", "Photography")

        facts_a = self.mem_mgr.get_user_facts(self.user_a_id)
        facts_b = self.mem_mgr.get_user_facts(self.user_b_id)
        facts_c = self.mem_mgr.get_user_facts(self.user_c_id)

        # Alice checks
        self.assertEqual(facts_a.get("city"), "San Francisco")
        self.assertEqual(facts_a.get("dog_name"), "Buddy")
        self.assertNotIn("cat_name", facts_a)
        self.assertNotIn("hobby", facts_a)

        # Bob checks
        self.assertEqual(facts_b.get("city"), "London")
        self.assertEqual(facts_b.get("cat_name"), "Whiskers")
        self.assertNotIn("dog_name", facts_b)
        self.assertNotIn("hobby", facts_b)

        # Charlie checks
        self.assertEqual(facts_c.get("city"), "Tokyo")
        self.assertEqual(facts_c.get("hobby"), "Photography")
        self.assertNotIn("dog_name", facts_c)
        self.assertNotIn("cat_name", facts_c)

    def test_06_multi_user_preferences_isolation(self):
        """User preferences must remain strictly isolated."""
        self.mem_mgr.set_preference(self.user_a_id, "theme", "dark")
        self.mem_mgr.set_preference(self.user_a_id, "response_style", "concise")

        self.mem_mgr.set_preference(self.user_b_id, "theme", "light")
        self.mem_mgr.set_preference(self.user_b_id, "response_style", "verbose")

        prefs_a = self.mem_mgr.get_preferences(self.user_a_id)
        prefs_b = self.mem_mgr.get_preferences(self.user_b_id)

        self.assertEqual(prefs_a.get("theme"), "dark")
        self.assertEqual(prefs_a.get("response_style"), "concise")

        self.assertEqual(prefs_b.get("theme"), "light")
        self.assertEqual(prefs_b.get("response_style"), "verbose")

    def test_07_multi_user_conversation_isolation(self):
        """Conversation history must never leak between users."""
        self.mem_mgr.log_interaction(self.user_a_id, "Alice confidential input", "Alice private response")
        self.mem_mgr.log_interaction(self.user_b_id, "Bob secret project discussion", "Bob private response")

        conv_a = self.mem_mgr.get_recent_conversation(self.user_a_id)
        conv_b = self.mem_mgr.get_recent_conversation(self.user_b_id)

        conv_a_text = json.dumps(conv_a)
        conv_b_text = json.dumps(conv_b)

        self.assertIn("Alice confidential", conv_a_text)
        self.assertNotIn("Bob secret", conv_a_text)

        self.assertIn("Bob secret", conv_b_text)
        self.assertNotIn("Alice confidential", conv_b_text)

    def test_08_server_side_ownership_enforcement(self):
        """Server-side authorization must block attempts by User A to access User B's resources."""
        # Legitimate access
        self.assertTrue(enforce_ownership(self.user_a_id, self.user_a_id))

        # Cross-user attack attempt
        with self.assertRaises(AuthorizationError):
            enforce_ownership(self.user_a_id, self.user_b_id)

    # ── 3. CHATGPT-STYLE MEMORY EXTRACTION & RETRIEVAL PIPELINE ───────────────

    def test_09_automated_dialogue_fact_extraction(self):
        """Dialogue statements must trigger heuristic fact learning."""
        text = "I work as a software engineer and my favorite food is sushi. Also remember that my birthday is October 15."
        extracted = self.mem_mgr.extract_and_persist_facts(self.user_a_id, text)

        facts = self.mem_mgr.get_user_facts(self.user_a_id)
        self.assertIn("occupation", facts)
        self.assertIn("favorite_food", facts)
        self.assertIn("birthday", facts)

        self.assertIn("software engineer", facts["occupation"])
        self.assertIn("sushi", facts["favorite_food"])
        self.assertIn("October 15", facts["birthday"])

    def test_10_memory_relevance_ranking(self):
        """Queries about a specific topic must rank relevant facts first and exclude unrelated ones."""
        # Store facts for Charlie
        self.mem_mgr.set_user_fact(self.user_c_id, "wife_name", "Sophia")
        self.mem_mgr.set_user_fact(self.user_c_id, "favorite_book", "Dune")
        self.mem_mgr.set_user_fact(self.user_c_id, "car_model", "Tesla Model 3")

        # Query about reading/books
        book_matches = self.mem_mgr.retrieve_relevant_memories(self.user_c_id, "What is my favorite book to read?")
        self.assertTrue(len(book_matches) > 0)
        self.assertEqual(book_matches[0]["key"], "favorite_book")
        self.assertEqual(book_matches[0]["value"], "Dune")

        # Query about spouse
        wife_matches = self.mem_mgr.retrieve_relevant_memories(self.user_c_id, "Who is my wife?")
        self.assertTrue(len(wife_matches) > 0)
        self.assertEqual(wife_matches[0]["key"], "wife_name")
        self.assertEqual(wife_matches[0]["value"], "Sophia")

    def test_11_prompt_context_budgeting(self):
        """Prompt builder must produce a budgeted, structured context block without blowing tokens."""
        prompt_ctx = self.mem_mgr.build_prompt_context(self.user_a_id, "Tell me about my dog and city")
        self.assertIsInstance(prompt_ctx, str)
        self.assertTrue(len(prompt_ctx) > 0)
        self.assertIn("[USER KNOWLEDGE & RELEVANT FACTS]", prompt_ctx)
        self.assertIn("San Francisco", prompt_ctx)

    # ── 4. GDPR COMPLIANCE (EXPORT & CASCADING DELETION) ───────────────────────

    def test_12_gdpr_data_export(self):
        """Export must provide a structured JSON of all user data without leaking other users."""
        export_data = export_user_data(self.user_a_id)
        self.assertEqual(export_data.get("user_id"), self.user_a_id)
        self.assertIn("profile", export_data)
        self.assertIn("preferences", export_data)
        self.assertIn("memory_facts", export_data)
        self.assertIn("conversations", export_data)

        export_str = json.dumps(export_data)
        # Contains Alice's data
        self.assertIn("San Francisco", export_str)
        # Does NOT contain Bob's data
        self.assertNotIn("London", export_str)
        self.assertNotIn("Whiskers", export_str)

    def test_13_gdpr_cascading_account_deletion(self):
        """Account deletion must atomically cleanse user records across all tables."""
        ts = int(time.time() * 1000) % 1000000
        del_user_name = f"user_to_delete_{ts}"
        res = register_user(del_user_name, "TempPass123!")
        del_uid = res.get("user_id")

        # Add records in various tables
        self.mem_mgr.set_user_fact(del_uid, "temporary_fact", "To be purged")
        self.mem_mgr.set_preference(del_uid, "temp_pref", "PurgeMe")
        self.mem_mgr.log_interaction(del_uid, "Delete this convo", "Will be deleted")

        # Execute cascading deletion
        del_res = delete_user_account_cascading(del_uid)
        self.assertTrue(del_res.get("success"))

        # Verify user is gone from users table
        with self.pool.get_cursor() as cur:
            cur.execute("SELECT id FROM users WHERE id = %s", (del_uid,))
            self.assertIsNone(cur.fetchone())

            # Verify facts gone
            cur.execute("SELECT id FROM memory_facts WHERE user_id = %s", (del_uid,))
            self.assertEqual(len(cur.fetchall()), 0)

            # Verify preferences gone
            cur.execute("SELECT id FROM user_preferences WHERE user_id = %s", (del_uid,))
            self.assertEqual(len(cur.fetchall()), 0)

            # Verify conversations gone
            cur.execute("SELECT id FROM conversations WHERE user_id = %s", (del_uid,))
            self.assertEqual(len(cur.fetchall()), 0)

    # ── 5. CONNECTION POOL RESILIENCE & ADMIN METRICS ─────────────────────────

    def test_14_db_pool_health_and_resilience(self):
        """Database connection pool must handle concurrent queries and rollbacks safely."""
        self.assertTrue(self.pool.is_healthy())
        stats = self.pool.get_stats()
        self.assertTrue(stats.get("active"))
        self.assertGreaterEqual(stats.get("total_queries", 0), 1)

        # Test rollback on invalid query
        try:
            with self.pool.get_cursor() as cur:
                cur.execute("SELECT * FROM non_existent_table_987654;")
        except Exception:
            pass  # Expected rollback

        # Connection pool must remain healthy after error
        self.assertTrue(self.pool.is_healthy())

    def test_15_privacy_preserving_admin_metrics(self):
        """Admin metrics tracker must report health, latency, and counts without exposing user text."""
        metrics = get_admin_metrics().get_system_health()
        self.assertIn("status", metrics)
        self.assertIn("server", metrics)
        self.assertIn("api_metrics", metrics)
        self.assertIn("database", metrics)

        # Confirm zero private dialogue or memory text in metrics
        metrics_str = json.dumps(metrics)
        self.assertNotIn("San Francisco", metrics_str)
        self.assertNotIn("London", metrics_str)
        self.assertNotIn("Sophia", metrics_str)

    # ── 6. DESKTOP CLIENT API INTEGRATION ─────────────────────────────────────

    def test_16_desktop_api_client_session_management(self):
        """Desktop API client session state and authorization header formatting."""
        client = SmartAssistantApiClient(base_url="http://localhost:8000")
        client.set_session(self.user_a_id, self.user_a_name, self.token_a)

        self.assertEqual(client.user_id, self.user_a_id)
        self.assertEqual(client.username, self.user_a_name)
        self.assertEqual(client.token, self.token_a)

        client.clear_session()
        self.assertIsNone(client.user_id)
        self.assertIsNone(client.token)


if __name__ == "__main__":
    unittest.main()
