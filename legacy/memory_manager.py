import psycopg2
import psycopg2.extras
import json
import hashlib
from instance.config import settings as CONFIG


# ---------------- DB CONNECTION ---------------- #
def get_connection():
    conn = psycopg2.connect(
        host=CONFIG["DB_HOST"],
        database=CONFIG["DB_NAME"],
        user=CONFIG["DB_USER"],
        password=CONFIG["DB_PASSWORD"],
        port=CONFIG["DB_PORT"]
    )
    return conn

def get_username_by_id(user_id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT username FROM users WHERE id=%s", (user_id,))
    row = cur.fetchone()

    cur.close()
    conn.close()

    if row:
        return row[0]
    return None

def user_exists(user_id):
    """Check if a user_id exists in the users table."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE id = %s", (user_id,))
    exists = cur.fetchone() is not None
    cur.close()
    conn.close()
    return exists

# ---------------- DATABASE WRAPPER ---------------- #
def save_to_db(query_or_callable, params=None):
    """
    Mandatory wrapper for all database writes.
    Accepts:
      - A SQL string + optional params tuple: save_to_db("INSERT ...", (val1, val2))
      - A callable that takes a cursor: save_to_db(lambda cur: cur.execute(...))
    Ensures commit and handles rollback on error.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        if callable(query_or_callable):
            query_or_callable(cur)
        else:
            cur.execute(query_or_callable, params)
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print("[DB ERROR]", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def log_interaction(user_id, role, content):
    """
    Log every user input and assistant response to the messages table.
    Safe wrapper — never raises, always logs errors.
    """
    if not user_id:
        return
    try:
        save_to_db(
            "INSERT INTO messages (user_id, role, content) VALUES (%s, %s, %s)",
            (user_id, role, content)
        )
    except Exception as e:
        print(f"[DB ERROR] log_interaction failed: {e}")


def safe_execute(query, params=None):
    """
    Executes a query with strict commit/rollback safety.
    Replaces loose cursor calls.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        print(f"[DB ERROR] Query failed: {query} | Error: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

# ---------------- USER HANDLING ---------------- #
def get_or_create_user(username, password):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT id, password FROM users WHERE username=%s", (username,))
    row = cur.fetchone()

    if row:
        user_id, stored_pass = row

        # Hash the entered password and compare
        entered_hash = hashlib.sha256(password.encode()).hexdigest()
        print("[AUTH] Password verification completed")
        
        if stored_pass != entered_hash:
            cur.close()
            conn.close()
            return None, "WRONG_PASSWORD"

        cur.close()
        conn.close()
        return user_id, "LOGIN_SUCCESS"

    # New user - hash the password before storing
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    cur.execute(
        "INSERT INTO users (username, password) VALUES (%s, %s) RETURNING id",
        (username, password_hash)
    )
    user_id = cur.fetchone()[0]
    conn.commit()

    cur.execute("INSERT INTO user_memory (user_id, memory) VALUES (%s, '{}'::jsonb)", (user_id,))
    conn.commit()

    cur.close()
    conn.close()

    return user_id, "NEW_USER"



# ---------------- CHAT HISTORY ---------------- #
def add_history(user_id, role, content):
    """Store each chat message in PostgreSQL."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO messages (user_id, role, content) VALUES (%s, %s, %s)",
        (user_id, role, content)
    )

    conn.commit()
    
    cur.close()
    conn.close()


def get_chat_history(user_id, limit=20):
    """Fetch last messages for AI context."""
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute(
        "SELECT id, role, content FROM messages WHERE user_id=%s ORDER BY id DESC LIMIT %s",
        (user_id, limit)
    )

    rows = cur.fetchall()[::-1]  # oldest → new

    cur.close()
    conn.close()

    return [{"id": r["id"], "role": r["role"], "content": r["content"]} for r in rows]


# ---------------- USER MEMORY (long-term) ---------------- #
def load_memory(user_id):
    """Load user's long-term memory (JSONB)."""
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT memory FROM user_memory WHERE user_id=%s", (user_id,))
    row = cur.fetchone()

    cur.close()
    conn.close()

    return row["memory"] if row else {}


def update_memory(user_id, new_data: dict):
    """
    [DEPRECATED] Merge new memory fields.
    Legacy writes disabled. Use memory_agent.
    """
    print(f"[MEMORY WARN] Legacy update_memory called. Ignoring.")
    pass


# ---------------- NOTES ---------------- #
def add_note_db(user_id, note):
    safe_execute("INSERT INTO notes (user_id, note) VALUES (%s, %s)", (user_id, note))


def get_notes_db(user_id):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT note FROM notes WHERE user_id=%s ORDER BY id DESC", (user_id,))
    notes = [row["note"] for row in cur.fetchall()]

    cur.close()
    conn.close()
    return notes


def delete_note_db(user_id, note_id):
    safe_execute("DELETE FROM notes WHERE id=%s AND user_id=%s", (note_id, user_id))


def clear_notes_db(user_id):
    safe_execute("DELETE FROM notes WHERE user_id=%s", (user_id,))


def update_note_db(user_id, note_id, new_text):
    safe_execute(
        "UPDATE notes SET note=%s WHERE id=%s AND user_id=%s",
        (new_text, note_id, user_id)
    )


def get_notes_with_ids_db(user_id):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT id, note FROM notes WHERE user_id=%s ORDER BY id ASC", (user_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def pin_note_db(user_id, note_id):
    safe_execute("UPDATE notes SET pinned=%s WHERE id=%s AND user_id=%s", (True, note_id, user_id))


def unpin_note_db(user_id, note_id):
    safe_execute("UPDATE notes SET pinned=%s WHERE id=%s AND user_id=%s", (False, note_id, user_id))


def mark_note_done_db(user_id, note_id):
    safe_execute("UPDATE notes SET done=%s WHERE id=%s AND user_id=%s", (True, note_id, user_id))


def search_notes_db(user_id, keyword):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT id, note FROM notes WHERE user_id=%s AND LOWER(note) LIKE %s",
                (user_id, f"%{keyword.lower()}%"))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_pinned_notes_db(user_id):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT id, note FROM notes WHERE user_id=%s AND pinned=%s", (user_id, True))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_done_notes_db(user_id):
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT id, note FROM notes WHERE user_id=%s AND done=%s", (user_id, True))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


# ---------------- USER MEMORY (long-term) ---------------- #
def load_user_memory(user_id):
    import re
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    cur.execute("SELECT memory FROM user_memory WHERE user_id=%s", (user_id,))
    row = cur.fetchone()
    
    cur.close()
    conn.close()
    
    memory_data = dict(row["memory"]) if row and row["memory"] else {}
    
    # Non-destructive normalization on read
    # 1. Height extraction from existing records
    if "height" not in memory_data:
        for k in list(memory_data.keys()):
            if "height" in k:
                m = re.search(r'(\d+)\s*(?:ft|feet)', k + ' ' + str(memory_data[k]), re.IGNORECASE)
                if m:
                    memory_data["height"] = f"{m.group(1)} feet"
                    break

    # 2. Age cleanup
    if "age" in memory_data:
        m = re.search(r'(\d+)\s*(?:years?)?', str(memory_data["age"]), re.IGNORECASE)
        if m:
            memory_data["age"] = f"{m.group(1)} years"

    # 3. Synchronize favorite/favourite food
    latest_food = memory_data.get("favorite_food") or memory_data.get("favourite_food")
    if latest_food:
        memory_data["favorite_food"] = latest_food
        memory_data["favourite_food"] = latest_food

    return memory_data


def update_user_memory(user_id, key, value):
    """
    Store a single memory field in user_memory JSONB.
    Re-enabled for deterministic memory storage.
    """
    print(f"[DEBUG] update_user_memory: user_id={user_id}, key={key}, value={value}")
    
    conn = get_connection()
    cur = conn.cursor()
    
    # Ensure user_memory row exists
    cur.execute("SELECT memory FROM user_memory WHERE user_id=%s", (user_id,))
    row = cur.fetchone()
    
    if not row:
        # Create new row with empty JSONB
        print(f"[DEBUG] Creating new user_memory row for user_id={user_id}")
        cur.execute("INSERT INTO user_memory (user_id, memory) VALUES (%s, '{}'::jsonb)", (user_id,))
    
    # Update memory with new key-value
    cur.execute(
        "UPDATE user_memory SET memory = jsonb_set(memory, %s, %s) WHERE user_id=%s",
        ([key], json.dumps(value), user_id)
    )
    
    conn.commit()
    print(f"[DEBUG] Memory updated and committed")
    
    cur.close()
    conn.close()



def delete_memory_key(user_id, key):
    """Delete a memory entry."""
    safe_execute(
        "UPDATE user_memory SET memory = memory - %s WHERE user_id=%s",
        (key, user_id)
    )

# ---------------- INTELLIGENCE LOGS (Phase 4) ---------------- #

def get_activity_logs_db(user_id, limit=30):
    """Fetches combined activity logs from plugins and decisions."""
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    # Union of plugin logs and decision logs
    query = """
    (SELECT 'PLUGIN' as type, plugin_id::text as target, action as content, status, created_at 
     FROM plugin_logs WHERE user_id = %s)
    UNION ALL
    (SELECT 'DECISION' as type, plugin_id::text as target, decision as content, 'INFO' as status, created_at 
     FROM decision_logs WHERE user_id = %s)
    ORDER BY created_at DESC LIMIT %s
    """
    cur.execute(query, (user_id, user_id, limit))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def get_latest_decision_db(user_id):
    """Fetches the very last decision for explainability."""
    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("SELECT * FROM decision_logs WHERE user_id = %s ORDER BY created_at DESC LIMIT 1", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


# ---------------- ASSISTANT NAME (per-user) ---------------- #

def get_assistant_name_db(user_id):
    """
    Load the assistant name for a given user from user_preferences.
    Returns the name string, or None if not configured yet.
    """
    if not user_id:
        return None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT pref_value FROM user_preferences WHERE user_id = %s AND pref_key = 'assistant_name'",
            (user_id,)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0] and row[0].strip():
            return row[0].strip()
        return None
    except Exception as e:
        print(f"[DB ERROR] get_assistant_name_db: {e}")
        return None


def set_assistant_name_db(user_id, name):
    """
    Persist the assistant name for a given user into user_preferences.
    Uses INSERT ... ON CONFLICT DO UPDATE so it works for new and existing rows.
    """
    if not user_id or not name or not name.strip():
        return False
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_preferences (user_id, pref_key, pref_value)
            VALUES (%s, 'assistant_name', %s)
            ON CONFLICT (user_id, pref_key) DO UPDATE SET pref_value = EXCLUDED.pref_value
            """,
            (user_id, name.strip())
        )
        conn.commit()
        cur.close()
        conn.close()
        print(f"[DB] Assistant name saved for user {user_id}: {name.strip()}")
        return True
    except Exception as e:
        print(f"[DB ERROR] set_assistant_name_db: {e}")
        return False


def get_user_preference_db(user_id, key: str, default=None):
    """
    Retrieve a user-specific preference from PostgreSQL user_preferences table,
    falling back to data/user_preferences.json if offline.
    """
    if not user_id or not key:
        return default

    # 1. Try PostgreSQL canonical storage
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT pref_value FROM user_preferences WHERE user_id = %s AND pref_key = %s",
            (user_id, key)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0] is not None:
            val = str(row[0]).strip()
            if val:
                return val
    except Exception as e:
        print(f"[DB PREF ERROR] get_user_preference_db ({key}): {e}")

    # 2. Fallback to local JSON store
    try:
        import os, json
        json_path = os.path.join(os.path.dirname(__file__), "..", "data", "user_preferences.json")
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            user_sec = data.get("ui_preferences", {}).get(str(user_id), {})
            if key in user_sec:
                return user_sec[key]
    except Exception:
        pass

    return default


def set_user_preference_db(user_id, key: str, value) -> bool:
    """
    Persist a user-specific preference into PostgreSQL user_preferences table,
    with automatic JSON backup mirroring.
    """
    if not user_id or not key:
        return False

    val_str = str(value).strip()
    db_success = False

    # 1. Persist to PostgreSQL
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_preferences (user_id, pref_key, pref_value)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, pref_key) DO UPDATE SET pref_value = EXCLUDED.pref_value
            """,
            (user_id, key, val_str)
        )
        conn.commit()
        cur.close()
        conn.close()
        db_success = True
    except Exception as e:
        print(f"[DB PREF ERROR] set_user_preference_db ({key}): {e}")

    # 2. Mirror into data/user_preferences.json for offline resilience
    try:
        import os, json
        json_path = os.path.join(os.path.dirname(__file__), "..", "data", "user_preferences.json")
        os.makedirs(os.path.dirname(json_path), exist_ok=True)
        data = {}
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}

        if "ui_preferences" not in data or not isinstance(data["ui_preferences"], dict):
            data["ui_preferences"] = {}
        uid_key = str(user_id)
        if uid_key not in data["ui_preferences"]:
            data["ui_preferences"][uid_key] = {}
        data["ui_preferences"][uid_key][key] = val_str

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[JSON PREF ERROR] mirror to json: {e}")

    return db_success or True


# ─────────────────────────────────────────────────────────────────────────────
# VOICE IDENTITY (per-user)
# Keys stored in user_preferences:
#   assistant_voice_id       — SAPI5 voice id string (pyttsx3)
#   assistant_voice_gender   — "male" | "female"
#   assistant_voice_tone     — "calm" | "professional" | "friendly" | "energetic" | "soft"
#   assistant_voice_rate     — int (words-per-minute)
#   assistant_voice_volume   — float string e.g. "1.0"
# ─────────────────────────────────────────────────────────────────────────────

_VOICE_KEYS = [
    "assistant_voice_id",
    "assistant_voice_gender",
    "assistant_voice_tone",
    "assistant_voice_rate",
    "assistant_voice_volume",
]

_TONE_PARAMS = {
    "calm":         {"rate": 130, "volume": 0.9},
    "professional": {"rate": 155, "volume": 1.0},
    "friendly":     {"rate": 165, "volume": 1.0},
    "energetic":    {"rate": 185, "volume": 1.0},
    "soft":         {"rate": 125, "volume": 0.75},
}


def has_voice_profile_db(user_id) -> bool:
    """Return True if this user has already configured a voice identity."""
    if not user_id:
        return False
    val = get_user_preference_db(user_id, "assistant_voice_id", None)
    return bool(val and str(val).strip())


def get_voice_profile_db(user_id) -> dict:
    """
    Load the full voice profile for a user from user_preferences.
    Returns a dict with keys: voice_id, voice_gender, voice_tone, voice_rate, voice_volume, voice_provider.
    Missing keys fall back to safe defaults.
    """
    if not user_id:
        return {}
    profile = {}
    profile["voice_id"]       = get_user_preference_db(user_id, "assistant_voice_id",       None)
    profile["voice_gender"]   = get_user_preference_db(user_id, "assistant_voice_gender",   "male")
    profile["voice_tone"]     = get_user_preference_db(user_id, "assistant_voice_tone",     "professional")
    profile["voice_provider"] = get_user_preference_db(user_id, "assistant_voice_provider", "windows")
    rate_str                  = get_user_preference_db(user_id, "assistant_voice_rate",     "155")
    vol_str                   = get_user_preference_db(user_id, "assistant_voice_volume",   "1.0")
    try:
        profile["voice_rate"] = int(rate_str)
    except (TypeError, ValueError):
        profile["voice_rate"] = 155
    try:
        profile["voice_volume"] = float(vol_str)
    except (TypeError, ValueError):
        profile["voice_volume"] = 1.0
    return profile


def set_voice_profile_db(user_id, voice_id: str, voice_gender: str,
                          voice_tone: str, voice_rate: int, voice_volume: float,
                          voice_provider: str = "windows") -> bool:
    """
    Persist a complete voice profile for the given user.
    Raises no exceptions — returns True on success, False otherwise.
    """
    if not user_id:
        return False
    ok = True
    ok &= set_user_preference_db(user_id, "assistant_voice_id",       str(voice_id))
    ok &= set_user_preference_db(user_id, "assistant_voice_gender",   str(voice_gender))
    ok &= set_user_preference_db(user_id, "assistant_voice_tone",     str(voice_tone))
    ok &= set_user_preference_db(user_id, "assistant_voice_rate",     str(voice_rate))
    ok &= set_user_preference_db(user_id, "assistant_voice_volume",   str(voice_volume))
    ok &= set_user_preference_db(user_id, "assistant_voice_provider", str(voice_provider))
    print(f"[DB] Voice profile saved for user {user_id}: gender={voice_gender}, "
          f"tone={voice_tone}, rate={voice_rate}, volume={voice_volume}, provider={voice_provider}")
    return ok

