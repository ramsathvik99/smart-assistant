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

    # =========================================================================
    # REMINDERS
    # Canonical table: reminders(id, user_id, task_text, due_at, is_notified, created_at)
    # =========================================================================

    def add_reminder(self, user_id, task_text, due_at):
        """Add a new reminder to the database."""
        if not self.pool or not user_id:
            return None
        try:
            with self._get_cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO reminders (user_id, task_text, due_at, is_notified)
                    VALUES (%s, %s, %s, FALSE)
                    RETURNING id
                    """,
                    (user_id, task_text, due_at)
                )
                return cur.fetchone()[0]
        except Exception as e:
            print(f"[DB REMINDER ERROR] add_reminder: {e}")
            return None

    def get_reminders(self, user_id, start_date=None, end_date=None):
        """Get reminders for a user, optionally filtered by date range."""
        if not self.pool or not user_id:
            return []
        try:
            with self._get_cursor() as cur:
                if start_date and end_date:
                    cur.execute(
                        """
                        SELECT id, task_text, due_at, is_notified, created_at
                        FROM reminders
                        WHERE user_id = %s
                          AND due_at BETWEEN %s AND %s
                        ORDER BY due_at ASC
                        """,
                        (user_id, start_date, end_date)
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, task_text, due_at, is_notified, created_at
                        FROM reminders
                        WHERE user_id = %s
                        ORDER BY due_at ASC
                        """,
                        (user_id,)
                    )
                rows = cur.fetchall()
                return [
                    {
                        "id": row[0],
                        "task_text": row[1],
                        "due_at": row[2],
                        "is_notified": row[3],
                        "created_at": row[4]
                    }
                    for row in rows
                ]
        except Exception as e:
            print(f"[DB REMINDER ERROR] get_reminders: {e}")
            return []

    def get_reminder_by_id(self, user_id, reminder_id):
        """Get a specific reminder by ID."""
        if not self.pool or not user_id:
            return None
        try:
            with self._get_cursor() as cur:
                cur.execute(
                    """
                    SELECT id, task_text, due_at, is_notified, created_at
                    FROM reminders
                    WHERE user_id = %s AND id = %s
                    """,
                    (user_id, reminder_id)
                )
                row = cur.fetchone()
                if row:
                    return {
                        "id": row[0],
                        "task_text": row[1],
                        "due_at": row[2],
                        "is_notified": row[3],
                        "created_at": row[4]
                    }
                return None
        except Exception as e:
            print(f"[DB REMINDER ERROR] get_reminder_by_id: {e}")
            return None

    def update_reminder(self, user_id, reminder_id, task_text=None, due_at=None):
        """Update an existing reminder."""
        if not self.pool or not user_id:
            return False
        try:
            with self._get_cursor() as cur:
                if task_text and due_at:
                    cur.execute(
                        """
                        UPDATE reminders
                        SET task_text = %s, due_at = %s
                        WHERE user_id = %s AND id = %s
                        """,
                        (task_text, due_at, user_id, reminder_id)
                    )
                elif task_text:
                    cur.execute(
                        """
                        UPDATE reminders
                        SET task_text = %s
                        WHERE user_id = %s AND id = %s
                        """,
                        (task_text, user_id, reminder_id)
                    )
                elif due_at:
                    cur.execute(
                        """
                        UPDATE reminders
                        SET due_at = %s
                        WHERE user_id = %s AND id = %s
                        """,
                        (due_at, user_id, reminder_id)
                    )
                else:
                    return False
                return cur.rowcount > 0
        except Exception as e:
            print(f"[DB REMINDER ERROR] update_reminder: {e}")
            return False

    def delete_reminder(self, user_id, reminder_id):
        """Delete a reminder."""
        if not self.pool or not user_id:
            return False
        try:
            with self._get_cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM reminders
                    WHERE user_id = %s AND id = %s
                    """,
                    (user_id, reminder_id)
                )
                return cur.rowcount > 0
        except Exception as e:
            print(f"[DB REMINDER ERROR] delete_reminder: {e}")
            return False

    def mark_reminder_notified(self, reminder_id):
        """Mark a reminder as notified."""
        if not self.pool:
            return False
        try:
            with self._get_cursor() as cur:
                cur.execute(
                    """
                    UPDATE reminders
                    SET is_notified = TRUE
                    WHERE id = %s
                    """,
                    (reminder_id,)
                )
                return cur.rowcount > 0
        except Exception as e:
            print(f"[DB REMINDER ERROR] mark_reminder_notified: {e}")
            return False

    def get_pending_reminders(self, user_id=None):
        """Get all reminders that haven't been notified yet."""
        if not self.pool:
            return []
        try:
            with self._get_cursor() as cur:
                if user_id:
                    cur.execute(
                        """
                        SELECT id, user_id, task_text, due_at, created_at
                        FROM reminders
                        WHERE user_id = %s AND is_notified = FALSE
                        ORDER BY due_at ASC
                        """,
                        (user_id,)
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, user_id, task_text, due_at, created_at
                        FROM reminders
                        WHERE is_notified = FALSE
                        ORDER BY due_at ASC
                        """,
                    )
                rows = cur.fetchall()
                return [
                    {
                        "id": row[0],
                        "user_id": row[1],
                        "task_text": row[2],
                        "due_at": row[3],
                        "created_at": row[4]
                    }
                    for row in rows
                ]
        except Exception as e:
            print(f"[DB REMINDER ERROR] get_pending_reminders: {e}")
            return []

    def check_reminder_conflicts(self, user_id, due_at, exclude_id=None):
        """Check for existing reminders at the same time."""
        if not self.pool or not user_id:
            return []
        try:
            with self._get_cursor() as cur:
                if exclude_id:
                    cur.execute(
                        """
                        SELECT id, task_text, due_at
                        FROM reminders
                        WHERE user_id = %s
                          AND due_at = %s
                          AND id != %s
                          AND is_notified = FALSE
                        """,
                        (user_id, due_at, exclude_id)
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, task_text, due_at
                        FROM reminders
                        WHERE user_id = %s
                          AND due_at = %s
                          AND is_notified = FALSE
                        """,
                        (user_id, due_at)
                    )
                rows = cur.fetchall()
                return [
                    {
                        "id": row[0],
                        "task_text": row[1],
                        "due_at": row[2]
                    }
                    for row in rows
                ]
        except Exception as e:
            print(f"[DB REMINDER ERROR] check_reminder_conflicts: {e}")
            return []

    # =========================================================================
    # PHASE 9: PERSISTENT GOALS (CROSS-SESSION CONTINUITY)
    # Canonical persistence layer: PostgreSQL active_contexts
    # =========================================================================

    def _resolve_user_id_int(self, user_id):
        """Resolves user_id (int or str username) to users(id) int."""
        if not self.pool or user_id is None:
            return None
        if isinstance(user_id, int):
            return user_id
        if str(user_id).isdigit():
            return int(user_id)
        # Search by username
        user_row = self.get_user_by_username(str(user_id))
        if user_row:
            return user_row[0]
        # Auto-create user record so foreign key constraint is satisfied
        return self.create_user(str(user_id), "cross_session_auth")

    def save_persistent_goal(self, user_id, goal_data: dict) -> bool:
        """
        Persists an eligible goal to PostgreSQL active_contexts.
        Privacy: Never stores raw audio, screenshots, passwords, tokens, or credentials.
        """
        if not self.pool or not goal_data:
            return False
        uid_int = self._resolve_user_id_int(user_id)
        if uid_int is None:
            return False
        
        goal_id = goal_data.get("goal_id")
        if not goal_id:
            return False

        payload = dict(goal_data)
        payload["context_type"] = "persistent_goal"
        payload["persisted_user_id"] = str(user_id)
        
        # Privacy filter: Strip any accidental sensitive keys
        for sensitive_key in ["password", "token", "auth_token", "secret", "credentials", "audio_data", "screenshot"]:
            payload.pop(sensitive_key, None)
            if "entities" in payload and isinstance(payload["entities"], dict):
                payload["entities"].pop(sensitive_key, None)

        try:
            with self._get_cursor() as cur:
                cur.execute(
                    """
                    SELECT id FROM active_contexts
                    WHERE user_id = %s AND (context_data->>'goal_id') = %s
                    LIMIT 1
                    """,
                    (uid_int, goal_id)
                )
                row = cur.fetchone()
                if row:
                    cur.execute(
                        """
                        UPDATE active_contexts
                        SET context_data = %s, updated_at = NOW()
                        WHERE id = %s
                        """,
                        (json.dumps(payload, default=str), row[0])
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO active_contexts (user_id, context_data, updated_at)
                        VALUES (%s, %s, NOW())
                        """,
                        (uid_int, json.dumps(payload, default=str))
                    )
                return True
        except Exception as e:
            print(f"[DB PERSISTENT GOAL ERROR] save_persistent_goal: {e}")
            return False

    def get_persistent_goals(self, user_id, only_resumable: bool = True) -> list:
        """
        Retrieves persistent goals for user from PostgreSQL active_contexts.
        Filters out terminal goals (COMPLETED, FAILED, CANCELLED) if only_resumable=True.
        """
        if not self.pool:
            return []
        uid_int = self._resolve_user_id_int(user_id)
        if uid_int is None:
            return []
        try:
            with self._get_cursor() as cur:
                cur.execute(
                    """
                    SELECT id, context_data, updated_at
                    FROM active_contexts
                    WHERE user_id = %s AND (context_data->>'context_type') = 'persistent_goal'
                    ORDER BY id ASC
                    """,
                    (uid_int,)
                )
                rows = cur.fetchall()
                results = []
                for cid, cdata, updated_at in rows:
                    if not isinstance(cdata, dict):
                        continue
                    status = str(cdata.get("goal_status", "")).upper()
                    resumable = bool(cdata.get("resumable", True))
                    if only_resumable:
                        if not resumable or status in ["COMPLETED", "FAILED", "CANCELLED"]:
                            continue
                    cdata["_db_id"] = cid
                    results.append(cdata)
                return results
        except Exception as e:
            print(f"[DB PERSISTENT GOAL ERROR] get_persistent_goals: {e}")
            return []

    def update_persistent_goal_status(self, user_id, goal_id: str, new_status: str, resumable: bool = None, last_known_result: str = None) -> bool:
        """Updates status of a persistent goal in PostgreSQL active_contexts."""
        if not self.pool or not goal_id:
            return False
        uid_int = self._resolve_user_id_int(user_id)
        if uid_int is None:
            return False
        import time as _time
        try:
            with self._get_cursor() as cur:
                cur.execute(
                    """
                    SELECT id, context_data FROM active_contexts
                    WHERE user_id = %s AND (context_data->>'goal_id') = %s
                    LIMIT 1
                    """,
                    (uid_int, goal_id)
                )
                row = cur.fetchone()
                if not row:
                    return False
                cid, cdata = row
                cdata["goal_status"] = new_status
                if resumable is not None:
                    cdata["resumable"] = resumable
                if last_known_result is not None:
                    cdata["last_known_result"] = last_known_result
                if new_status in ["COMPLETED", "FAILED", "CANCELLED"]:
                    cdata["resumable"] = False
                cdata["updated_at"] = _time.time()
                cur.execute(
                    """
                    UPDATE active_contexts
                    SET context_data = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (json.dumps(cdata, default=str), cid)
                )
                return True
        except Exception as e:
            print(f"[DB PERSISTENT GOAL ERROR] update_persistent_goal_status: {e}")
            return False

    def delete_persistent_goal(self, user_id, goal_id: str) -> bool:
        """Deletes persistent goal from PostgreSQL active_contexts."""
        if not self.pool or not goal_id:
            return False
        uid_int = self._resolve_user_id_int(user_id)
        if uid_int is None:
            return False
        try:
            with self._get_cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM active_contexts
                    WHERE user_id = %s AND (context_data->>'goal_id') = %s
                    """,
                    (uid_int, goal_id)
                )
                return cur.rowcount > 0
        except Exception as e:
            print(f"[DB PERSISTENT GOAL ERROR] delete_persistent_goal: {e}")
            return False


_default_db_manager = None

def get_db():
    """Returns canonical singleton DatabaseManager connected via PostgreSQL connection pool."""
    global _default_db_manager
    if _default_db_manager is None:
        try:
            from legacy.memory_manager import get_connection
            class SimplePoolWrapper:
                def __init__(self, connection_func):
                    self.get_connection = connection_func
                def getconn(self):
                    return self.get_connection()
                def putconn(self, conn):
                    try:
                        conn.close()
                    except Exception:
                        pass
            _default_db_manager = DatabaseManager(SimplePoolWrapper(get_connection))
        except Exception as e:
            print(f"[DB MANAGER] get_db init error: {e}")
            return None
    return _default_db_manager

