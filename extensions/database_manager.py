import json
import traceback
from contextlib import contextmanager

class DatabaseManager:
    """
    Central Persistence Handler for Nova Extensions.
    Uses existing psycopg2 connection pool.

    SCHEMA CONTRACT (PostgreSQL is the ONLY source of truth):
    - users            : id, username, password, voice_identity_hash, created_at
    - user_preferences : id, user_id, pref_key, pref_value, created_at
                         UNIQUE(user_id, pref_key)
    - system_memory    : id, user_id, key, value, updated_at
                         UNIQUE(user_id, key)
    - user_memory      : id, user_id, memory (JSONB), created_at
    - messages         : id, user_id, role, content, created_at
    - notes            : id, user_id, note, pinned, done, created_at
    - reminders        : id, user_id, task_text, due_at, is_notified, created_at
    - plugins          : id, plugin_id (text, unique), is_enabled, permissions (JSONB), created_at
    - plugin_logs      : id, user_id, plugin_id (int FK→plugins), action, status, error_message, created_at
    - decision_logs    : id, user_id, plugin_id (int FK→plugins, nullable), decision, created_at
    - security_audit_logs : id, user_id, action_name, params, status, created_at
    - active_contexts  : id, user_id, context_data (JSONB), updated_at
    - calendar_events, recurrence_rules, calendar_settings (calendar module)

    DO NOT add CREATE TABLE, ALTER TABLE, or any DDL here.
    All schema changes must go through assistant_production_schema.sql.
    """

    def __init__(self, db_pool):
        self.pool = db_pool
        if not self.pool:
            print("[DB MANAGER] No pool provided. Persistence disabled.")

    @contextmanager
    def _get_cursor(self):
        if not self.pool:
            yield None
            return

        conn = self.pool.getconn()
        try:
            yield conn.cursor()
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self.pool.putconn(conn)

    # =========================================================================
    # USER & AUTHENTICATION
    # Canonical table: users(id SERIAL PK, username TEXT, password TEXT,
    #                        voice_identity_hash TEXT, created_at)
    # =========================================================================

    def get_user_by_username(self, username):
        """Returns (id, username, password) or None."""
        if not self.pool:
            return None
        try:
            with self._get_cursor() as cur:
                cur.execute(
                    "SELECT id, username, password FROM users WHERE username = %s",
                    (username,)
                )
                return cur.fetchone()
        except Exception as e:
            print(f"[DB USER ERROR] get_user_by_username: {e}")
            return None

    def create_user(self, username, password):
        """Inserts a new user and returns their id."""
        if not self.pool:
            return None
        try:
            with self._get_cursor() as cur:
                cur.execute(
                    "INSERT INTO users (username, password) VALUES (%s, %s) RETURNING id",
                    (username, password)
                )
                return cur.fetchone()[0]
        except Exception as e:
            print(f"[DB USER ERROR] create_user: {e}")
            return None

    # =========================================================================
    # USER PREFERENCES
    # Canonical table: user_preferences(id, user_id, pref_key, pref_value, created_at)
    # UNIQUE(user_id, pref_key)
    # =========================================================================

    def get_user_preferences(self, user_id):
        """Returns dict of {pref_key: pref_value} for given user."""
        if not self.pool or not user_id:
            return {}
        try:
            with self._get_cursor() as cur:
                cur.execute(
                    "SELECT pref_key, pref_value FROM user_preferences WHERE user_id = %s",
                    (user_id,)
                )
                rows = cur.fetchall()
                data = {}
                for k, v in rows:
                    try:
                        data[k] = json.loads(v)
                    except Exception:
                        data[k] = v
                return data
        except Exception as e:
            print(f"[DB PREF ERROR] get_user_preferences: {e}")
            return {}

    def set_user_preference(self, user_id, key, value):
        """Upserts a user preference using pref_key/pref_value columns."""
        if not self.pool or not user_id:
            return
        try:
            if isinstance(value, (dict, list, bool, int, float)):
                val_str = json.dumps(value)
            else:
                val_str = str(value)
            with self._get_cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO user_preferences (user_id, pref_key, pref_value)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, pref_key)
                    DO UPDATE SET pref_value = EXCLUDED.pref_value
                    """,
                    (user_id, key, val_str)
                )
        except Exception as e:
            print(f"[DB PREF ERROR] set_user_preference: {e}")

    # =========================================================================
    # CONTEXT PERSISTENCE  (system_memory table)
    # Canonical table: system_memory(id, user_id, key, value, updated_at)
    # UNIQUE(user_id, key)
    # =========================================================================

    def update_context(self, user_id, key, value):
        """Persists a context key-value pair to system_memory."""
        if not self.pool or not user_id:
            return
        try:
            if isinstance(value, (dict, list, bool, int, float)):
                val_str = json.dumps(value)
            else:
                val_str = str(value)
            with self._get_cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO system_memory (user_id, key, value, updated_at)
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id, key)
                    DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP
                    """,
                    (user_id, key, val_str)
                )
        except Exception as e:
            print(f"[DB CONTEXT ERROR] update_context: {e}")

    def load_context(self, user_id):
        """Returns dict of persisted context key-values from system_memory."""
        if not self.pool or not user_id:
            return {}
        try:
            with self._get_cursor() as cur:
                cur.execute(
                    "SELECT key, value FROM system_memory WHERE user_id = %s",
                    (user_id,)
                )
                rows = cur.fetchall()
                data = {}
                for k, v in rows:
                    try:
                        data[k] = json.loads(v)
                    except Exception:
                        data[k] = v
                return data
        except Exception as e:
            print(f"[DB CONTEXT ERROR] load_context: {e}")
            return {}

    # =========================================================================
    # SESSION MANAGEMENT
    # Session state is managed fully in-memory by AssistantOrchestrator.
    # No session_state table exists in PostgreSQL.
    # These stubs prevent AttributeError calls from the rest of the codebase.
    # =========================================================================

    def update_session(self, user_id, is_active=True, device_id="pc_main"):
        """No-op: session state is managed in-memory, not persisted to DB."""
        pass  # session_state table does not exist

    def get_active_session_user(self, device_id="pc_main"):
        """No-op: returns None — session resolution handled by AssistantOrchestrator."""
        return None  # session_state table does not exist

    # =========================================================================
    # LOGGING & TRACKING
    # =========================================================================

    def log_command(self, user_id, command, intent, skill, success, response):
        """
        Logs a user command as an assistant message in the messages table.
        (command_history table does not exist in PostgreSQL schema.)
        """
        if not self.pool or not user_id:
            return
        try:
            log_text = f"[CMD: {intent or 'unknown'} | SKILL: {skill or 'none'} | {'OK' if success else 'FAIL'}] {command}"
            with self._get_cursor() as cur:
                cur.execute(
                    "INSERT INTO messages (user_id, role, content) VALUES (%s, %s, %s)",
                    (user_id, "system", log_text[:2000])
                )
        except Exception as e:
            print(f"[DB LOG ERROR] log_command: {e}")

    def log_error(self, user_id, error_msg, stack_trace=None):
        """
        No-op: error_log table does not exist in PostgreSQL.
        Errors are logged to console only.
        """
        # error_log table does not exist — errors visible in console/stdout
        pass

    def log_ai_interaction(self, user_id, prompt, response, model="unknown"):
        """
        Logs an AI interaction turn to the messages table.
        (ai_conversation_log table does not exist in PostgreSQL schema.)
        """
        if not self.pool or not user_id:
            return
        try:
            with self._get_cursor() as cur:
                cur.execute(
                    "INSERT INTO messages (user_id, role, content) VALUES (%s, %s, %s)",
                    (user_id, "user", str(prompt)[:4000])
                )
                cur.execute(
                    "INSERT INTO messages (user_id, role, content) VALUES (%s, %s, %s)",
                    (user_id, "assistant", str(response)[:4000])
                )
        except Exception as e:
            print(f"[DB AI LOG ERROR] log_ai_interaction: {e}")

    def track_usage(self, user_id, feature_name):
        """
        No-op: usage_patterns table does not exist in PostgreSQL.
        Usage tracking is handled by the plugin_logs table via plugin_manager.
        """
        # usage_patterns table does not exist
        pass
