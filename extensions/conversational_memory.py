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
def store_interaction(user_command: str, assistant_response: str, user_id=None):
    """
    Persist a completed interaction to PostgreSQL and push it to the deque.

    Parameters
    ----------
    user_command       : The exact text user spoke / typed.
    assistant_response : The final response Nova produced.
    user_id            : Optional authenticated user ID for multi-user isolation.
    """
    entry = {
        "user_command":       user_command,
        "assistant_response": assistant_response,
        "user_id":            user_id,
    }

    # 1. Update in-memory buffer (thread-safe)
    with _lock:
        recent_memory.append(entry)

    # 2. Persist to PostgreSQL asynchronously
    def _insert_db():
        from instance.config import settings
        target_uid = user_id or getattr(settings, 'CURRENT_USER_ID', None)
        if not target_uid:
            return

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
                    (target_uid, "user", user_command),
                )
                
                # Insert assistant response
                cur.execute(
                    """
                    INSERT INTO messages (user_id, role, content)
                    VALUES (%s, %s, %s);
                    """,
                    (target_uid, "assistant", assistant_response),
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
#  CATEGORIZED MEMORY & PROMPT BUDGETING (PostgreSQL Backed)
# ──────────────────────────────────────────────
MAX_MEMORY_VALUE_LENGTH = 380
PROMPT_CORE_CHARS = 900
PROMPT_INDEX_CHARS = 420
PROMPT_MAX_PER_CATEGORY = 6

_CATEGORY_LABELS = {
    "identity":      "Identity",
    "preferences":   "Preferences",
    "projects":      "Active projects / goals",
    "relationships": "People in their life",
    "wishes":        "Wishes / plans",
    "notes":         "Notes",
}

_IDENTITY_FIELDS = [
    "name", "age", "birthday", "city", "job",
    "language", "school", "nationality"
]


def _truncate_value(val: str, max_len: int = MAX_MEMORY_VALUE_LENGTH) -> str:
    """Protect system prompt and memory budget from single-field runaway lengths."""
    s = str(val or "").strip()
    if len(s) > max_len:
        return s[:max_len].rstrip() + "…"
    return s


def _score_memory_entry(query_words: list[str], cat: str, key: str, value: str) -> int:
    """
    Sub-millisecond lexical relevance scoring.
    No external model round-trip required.
    """
    hay_key = str(key).replace("_", " ").lower()
    hay_val = str(value).lower()
    hay_cat = str(cat).lower()
    score = 0
    for w in query_words:
        if not w:
            continue
        if w == hay_key:
            score += 10
        elif w in hay_key:
            score += 6
        if w in hay_val:
            score += 3
        if w in hay_cat:
            score += 1
    return score


def get_categorized_user_memory(user_id: int) -> dict:
    """
    Load user memory from PostgreSQL and normalize into categorized structure.
    Strictly isolated per user_id.
    """
    if not user_id:
        return {}
    try:
        from legacy.memory_manager import load_user_memory
        raw_mem = load_user_memory(user_id) or {}
    except Exception as e:
        print(f"[CONV_MEMORY] [WARN] Error loading user memory from DB: {e}")
        return {}

    categorized: dict = {
        "identity": {},
        "preferences": {},
        "projects": {},
        "relationships": {},
        "wishes": {},
        "notes": {},
    }

    # Populate categorized memory from PostgreSQL data
    for k, v in raw_mem.items():
        if k in categorized and isinstance(v, dict):
            categorized[k].update(v)
        elif k in _IDENTITY_FIELDS:
            categorized["identity"][k] = v
        elif "pref" in k or k in ("theme", "voice_rate", "tone", "favorite_food", "favourite_food"):
            categorized["preferences"][k] = v
        elif "project" in k or "goal" in k:
            categorized["projects"][k] = v
        elif "relation" in k or "sister" in k or "brother" in k or "friend" in k or "mother" in k or "father" in k:
            categorized["relationships"][k] = v
        elif "wish" in k or "plan" in k:
            categorized["wishes"][k] = v
        else:
            categorized["notes"][k] = v

    return categorized


def remember_user_fact(user_id: int, key: str, value: str, category: str = "notes") -> bool:
    """
    Persist a categorized memory fact for user_id to PostgreSQL.
    Enforces value truncation and user isolation.
    """
    if not user_id or not key or value is None:
        return False
    from datetime import datetime
    clean_key = str(key).strip().lower().replace(" ", "_")
    clean_val = _truncate_value(str(value))
    valid_cats = {"identity", "preferences", "projects", "relationships", "wishes", "notes"}
    if category not in valid_cats:
        category = "notes"

    try:
        from legacy.memory_manager import load_user_memory, update_user_memory
        mem = load_user_memory(user_id) or {}
        if category not in mem or not isinstance(mem[category], dict):
            mem[category] = {}
        mem[category][clean_key] = {
            "value": clean_val,
            "updated": datetime.now().strftime("%Y-%m-%d"),
        }
        # Also store top-level key for backward-compatibility with flat lookups
        mem[clean_key] = clean_val
        update_user_memory(user_id, category, mem[category])
        update_user_memory(user_id, clean_key, clean_val)
        return True
    except Exception as e:
        print(f"[CONV_MEMORY] [ERROR] remember_user_fact: {e}")
        return False


def forget_user_fact(user_id: int, key: str, category: str = "notes") -> bool:
    """
    Delete a memory fact for user_id from PostgreSQL.
    """
    if not user_id or not key:
        return False
    clean_key = str(key).strip().lower().replace(" ", "_")
    try:
        from legacy.memory_manager import load_user_memory, update_user_memory, delete_memory_key
        mem = load_user_memory(user_id) or {}
        changed = False
        if category in mem and isinstance(mem[category], dict) and clean_key in mem[category]:
            del mem[category][clean_key]
            update_user_memory(user_id, category, mem[category])
            changed = True
        if clean_key in mem:
            delete_memory_key(user_id, clean_key)
            changed = True
        return changed
    except Exception as e:
        print(f"[CONV_MEMORY] [ERROR] forget_user_fact: {e}")
        return False


def search_user_memory(user_id: int, query: str, limit: int = 8) -> list[dict]:
    """
    Lexical search across stored user facts in PostgreSQL without requiring LLM round trips.
    Returns ranked matches with scores, category, key, value, and timestamp.
    """
    if not user_id:
        return []
    import re
    categorized = get_categorized_user_memory(user_id)
    words = [w for w in re.split(r"[^\w]+", (query or "").lower()) if len(w) > 1]

    rows = []
    for cat, items in categorized.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            if isinstance(entry, dict) and "value" in entry:
                val = str(entry.get("value", ""))
                updated = str(entry.get("updated", ""))
            else:
                val = str(entry or "")
                updated = ""
            if not val:
                continue
            s = _score_memory_entry(words, cat, key, val) if words else 1
            if s > 0:
                rows.append({
                    "score": s,
                    "category": cat,
                    "key": key,
                    "value": val,
                    "updated": updated,
                })

    rows.sort(key=lambda r: (-r["score"], r["key"]))
    return rows[:max(1, limit)]


def format_memory_for_prompt(user_id: int) -> str:
    """
    Constructs an optimized, prompt-budgeted memory block for LLM prompts from PostgreSQL.
    Features:
      1. Full identity block.
      2. Recency-prioritized core entries with per-category caps.
      3. Index table-of-contents of remaining entries on disk/DB for lexical recall.
    """
    if not user_id:
        return ""
    categorized = get_categorized_user_memory(user_id)
    if not categorized:
        return ""

    core_lines: list[str] = []

    # 1. Identity section
    identity = categorized.get("identity", {})
    for field in _IDENTITY_FIELDS:
        raw = identity.get(field)
        val = raw.get("value") if isinstance(raw, dict) else raw
        if val:
            core_lines.append(f"{field.title()}: {val}")
    for k, raw in identity.items():
        if k in _IDENTITY_FIELDS:
            continue
        val = raw.get("value") if isinstance(raw, dict) else raw
        if val:
            core_lines.append(f"{k.replace('_', ' ').title()}: {val}")

    # 2. Category entries with prompt budget and caps
    rest: list[tuple[str, str, str, str]] = []
    for cat in _CATEGORY_LABELS:
        if cat == "identity":
            continue
        items = categorized.get(cat, {})
        for key, raw in items.items():
            if isinstance(raw, dict):
                val = str(raw.get("value", ""))
                updated = str(raw.get("updated", "") or "0000-00-00")
            else:
                val = str(raw or "")
                updated = "0000-00-00"
            if val:
                rest.append((updated, cat, key, val))

    rest.sort(key=lambda t: t[0], reverse=True)

    used = sum(len(l) + 1 for l in core_lines)
    shown: dict[str, list[str]] = {}
    overflow: dict[str, list[str]] = {}
    per_cat_used: dict[str, int] = {}

    for _updated, cat, key, val in rest:
        line = f"  - {key.replace('_', ' ').title()}: {val}"
        if (per_cat_used.get(cat, 0) < PROMPT_MAX_PER_CATEGORY and used + len(line) + 1 <= PROMPT_CORE_CHARS):
            shown.setdefault(cat, []).append(line)
            per_cat_used[cat] = per_cat_used.get(cat, 0) + 1
            used += len(line) + 1
        else:
            overflow.setdefault(cat, []).append(key.replace("_", " "))

    for cat, label in _CATEGORY_LABELS.items():
        if shown.get(cat):
            core_lines.append("")
            core_lines.append(f"{label}:")
            core_lines.extend(shown[cat])

    indexed: list[str] = []
    if overflow:
        cats = [c for c in _CATEGORY_LABELS if overflow.get(c)]
        cursor = {c: 0 for c in cats}
        while cats:
            for cat in list(cats):
                i = cursor[cat]
                if i >= len(overflow[cat]):
                    cats.remove(cat)
                    continue
                indexed.append(overflow[cat][i])
                cursor[cat] = i + 1

    if not core_lines and not indexed:
        return ""

    out = [
        "[WHAT YOU KNOW ABOUT THIS USER — use naturally, never recite like a list]",
        *core_lines,
    ]

    if indexed:
        budget, names = PROMPT_INDEX_CHARS, []
        for n in indexed:
            if budget - len(n) - 2 < 0:
                break
            names.append(n)
            budget -= len(n) + 2
        if names:
            out.append("")
            out.append("[ALSO REMEMBERED — recall on demand with keyword search]")
            out.append(", ".join(names) + (f" (+{len(indexed) - len(names)} more)" if len(indexed) > len(names) else ""))

    return "\n".join(out) + "\n"


def get_all_memory_entries_for_ui(user_id: int) -> list[dict]:
    """
    Returns flat list of memory entries for UI panels / dashboards, sorted by newest updated.
    """
    if not user_id:
        return []
    categorized = get_categorized_user_memory(user_id)
    rows = []
    for cat, items in categorized.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            if isinstance(entry, dict) and "value" in entry:
                val = str(entry.get("value", ""))
                updated = str(entry.get("updated", "") or "")
            else:
                val = str(entry or "")
                updated = ""
            if val:
                rows.append({
                    "category": cat,
                    "key": key,
                    "value": val,
                    "updated": updated,
                })
    rows.sort(key=lambda r: (r["updated"] or "0000-00-00"), reverse=True)
    return rows


# ──────────────────────────────────────────────
#  AUTO-RESTORE ON MODULE IMPORT
# ──────────────────────────────────────────────
# This ensures that as soon as any part of Nova imports this module,
# the deque is pre-populated from PostgreSQL.
restore_memory_on_startup()

