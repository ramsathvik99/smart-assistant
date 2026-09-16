# conversational_memory.py
"""
Conversational Memory Engine
----------------------------------
Stores every interaction in PostgreSQL (command_history) and maintains
a fast in-memory deque of the last 30 interactions.

Capabilities:
  - store_interaction(cmd, resp)  → persist to DB + update deque
  - handle_repeat(text)           → detect repeat phrases, return last response
  - handle_keyword_recall(text)   → search deque for keyword, return matching response
  - restore_memory_on_startup()   → called once at import to pre-load deque from DB
  - close_connection()            → clean shutdown of psycopg2 connection
"""

import os
import threading
from collections import deque
from dotenv import load_dotenv

# Load .env to ensure DB credentials are available regardless of import order
load_dotenv()

# ──────────────────────────────────────────────
#  CONFIGURATION
# ──────────────────────────────────────────────
_DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", "5432")),
    "dbname":   os.getenv("DB_NAME", "nova_assistant"),
    "user":     os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", "ramsathvik"),
}

MEMORY_LIMIT = 30   # max entries in the in-memory deque

# ──────────────────────────────────────────────
#  REPEAT / RECALL TRIGGER PHRASES
# ──────────────────────────────────────────────
REPEAT_TRIGGERS = [
    "repeat",
    "repeat that",
    "what did you say",
    "say that again",
    "i didn't understand",
    "i did not understand",
    "say it again",
    "what was that",
]

# Phrases that signal a keyword recall request
RECALL_TRIGGERS = [
    "what did you say about",
    "what was the",
    "tell me again about",
    "what was that about",
    "recall",
    "remind me about",
]

# ──────────────────────────────────────────────
#  IN-MEMORY BUFFER
# ──────────────────────────────────────────────
recent_memory: deque = deque(maxlen=MEMORY_LIMIT)
_lock = threading.Lock()   # protect deque writes from concurrent threads

# ──────────────────────────────────────────────
#  DATABASE CONNECTION
# ──────────────────────────────────────────────
_conn = None

def _get_connection():
    """Return a cached psycopg2 connection, creating it if needed."""
    global _conn
    if _conn is None or _conn.closed:
        try:
            import psycopg2
            _conn = psycopg2.connect(**_DB_CONFIG)
            _conn.autocommit = True
            print("[CONV_MEMORY] PostgreSQL connection established.")
        except Exception as e:
            print(f"[CONV_MEMORY] [WARN] Could not connect to PostgreSQL: {e}")
            _conn = None
    return _conn


def close_connection():
    """Gracefully close the database connection (call on Nova shutdown)."""
    global _conn
    if _conn and not _conn.closed:
        try:
            _conn.close()
            print("[CONV_MEMORY] PostgreSQL connection closed.")
        except Exception as e:
            print(f"[CONV_MEMORY] Error closing DB connection: {e}")
    _conn = None


# ──────────────────────────────────────────────
#  STARTUP — RESTORE MEMORY FROM DB
# ──────────────────────────────────────────────
def restore_memory_on_startup():
    """
    Load most recent MEMORY_LIMIT interactions from PostgreSQL into
    in-memory deque. Called once automatically when this module is imported.
    """
    conn = _get_connection()
    if conn is None:
        print("[CONV_MEMORY] [WARN] Skipping memory restore -- no DB connection.")
        return

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT role, content
                FROM messages
                ORDER BY id DESC
                LIMIT %s;
            """, (MEMORY_LIMIT,))
            rows = cur.fetchall()

        # Rows are DESC (newest first) — reverse to get chronological order
        for role, content in reversed(rows):
            recent_memory.append({
                "user_command":       content if role == "user" else "",
                "assistant_response": content if role == "assistant" else "",
            })

        print(f"[CONV_MEMORY] [OK] Restored {len(rows)} interaction(s) from PostgreSQL.")

    except Exception as e:
        print(f"[CONV_MEMORY] [WARN] Error restoring memory from DB: {e}")


# ──────────────────────────────────────────────
#  STORE INTERACTION
# ──────────────────────────────────────────────
def store_interaction(user_command: str, assistant_response: str):
    """
    Persist a completed interaction to PostgreSQL and push it to the deque.

    Parameters
    ----------
    user_command       : The exact text user spoke / typed.
    assistant_response : The final response Nova produced.
    """
    entry = {
        "user_command":       user_command,
        "assistant_response": assistant_response,
    }

    # 1. Update in-memory buffer (thread-safe)
    with _lock:
        recent_memory.append(entry)

    # 2. Persist to PostgreSQL asynchronously
    def _insert_db():
        conn = _get_connection()
        if conn is None:
            print("[CONV_MEMORY] [WARN] DB unavailable -- interaction stored in memory only.")
            return

        try:
            with conn.cursor() as cur:
                # Insert user message
                cur.execute(
                    """
                    INSERT INTO messages (user_id, role, content)
                    VALUES (%s, %s, %s);
                    """,
                    (1, "user", user_command),
                )
                
                # Insert assistant response
                cur.execute(
                    """
                    INSERT INTO messages (user_id, role, content)
                    VALUES (%s, %s, %s);
                    """,
                    (1, "assistant", assistant_response),
                )
                
        except Exception as e:
            print(f"[CONV_MEMORY] [WARN] Failed to insert interaction into DB: {e}")

    threading.Thread(target=_insert_db, daemon=True).start()


# ──────────────────────────────────────────────
#  REPEAT HANDLER
# ──────────────────────────────────────────────
def handle_repeat(text: str):
    """
    Detect if the user is asking Nova to repeat its last response.

    Returns
    -------
    str  — The previous assistant_response if detected, or None if not a repeat request.
    """
    t = text.lower().strip()

    # Exact / substring match against repeat phrases
    for trigger in REPEAT_TRIGGERS:
        if t == trigger or t.startswith(trigger):
            if recent_memory:
                return recent_memory[-1]["assistant_response"]
            else:
                return "I don't have any previous response to repeat yet."

    return None   # Not a repeat request


# ──────────────────────────────────────────────
#  KEYWORD RECALL HANDLER
# ──────────────────────────────────────────────
def handle_keyword_recall(text: str):
    """
    Detect keyword-based recall requests (e.g. "what did you say about camera")
    and return the most recent matching response from the deque.

    Returns
    -------
    str  — Matched assistant_response, an "I can't find" message, or None if
           this is not a recall request at all.
    """
    t = text.lower().strip()

    # Identify which recall trigger (if any) fired and extract the keyword
    keyword = None
    for trigger in RECALL_TRIGGERS:
        if trigger in t:
            # Everything after the trigger phrase is the keyword
            keyword = t.split(trigger, 1)[-1].strip()
            break

    if keyword is None:
        return None   # Not a recall request

    if not keyword:
        return "What topic would you like me to recall?"

    # Search deque in reverse (most-recent first)
    with _lock:
        snapshot = list(recent_memory)

    for entry in reversed(snapshot):
        cmd  = entry["user_command"].lower()
        resp = entry["assistant_response"].lower()
        if keyword in cmd or keyword in resp:
            return entry["assistant_response"]

    return f"I couldn't find anything in my recent memory about '{keyword}'."


# ──────────────────────────────────────────────
#  KEYWORD SEARCH HANDLER (Fallback for generic queries)
# ──────────────────────────────────────────────
def search_recent_memory_for_keywords(text: str):
    """
    Search the last 30 interactions for significant keywords from the user's query.
    Used as a fallback right before ask_ai() in assistant.py.
    """
    import re
    
    # 1. Clean and tokenize text
    t = text.lower().strip()
    words = re.findall(r'\b[a-z]{3,}\b', t)
    
    # Stop words to ignore
    stop_words = {"what", "who", "when", "where", "why", "how", "did", "you", "say", "earlier", "about", "the", "and", "that", "this", "was", "for", "with", "are", "have"}
    keywords = [w for w in words if w not in stop_words]
    
    if not keywords:
        return None
        
    keyword_set = frozenset(keywords)
    
    # Search deque in reverse (most-recent first)
    with _lock:
        snapshot = list(recent_memory)
        
    for entry in reversed(snapshot):
        cmd_words = set(re.findall(r'\b[a-z]{3,}\b', entry["user_command"].lower()))
        resp_words = set(re.findall(r'\b[a-z]{3,}\b', entry["assistant_response"].lower()))
        
        # If any keyword matches the user command or assistant response
        if keyword_set.intersection(cmd_words) or keyword_set.intersection(resp_words):
            return entry["assistant_response"]
            
    return None

# ──────────────────────────────────────────────
#  AUTO-RESTORE ON MODULE IMPORT
# ──────────────────────────────────────────────
# This ensures that as soon as any part of Nova imports this module,
# the deque is pre-populated from PostgreSQL.
restore_memory_on_startup()
