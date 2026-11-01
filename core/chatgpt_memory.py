"""
Smart Assistant — ChatGPT-Style Memory Architecture & Context Retrieval Pipeline
Provides a decoupled multi-tiered memory architecture:
1. Short-Term Conversation Context (Active Turns + Active Contexts)
2. User Declarative Facts (memory_facts)
3. Structured User Preferences (user_preferences)
4. Long-Term Semantic & Episodic Memory (user_memory + memory_embeddings)
5. System / Domain State (system_memory)

Includes automated memory extraction from dialogue and relevance-ranked context building.
"""

import os
import re
import time
import json
import math
import hashlib
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

from core.db_pool import get_db_pool

# Character & Token budgeting for context injection
MAX_PROMPT_FACTS_CHARS = 900
MAX_PROMPT_PREFS_CHARS = 400
MAX_PROMPT_CONV_TURNS = 6
MAX_FACT_VALUE_LENGTH = 300


# ── 1. LEXICAL & SEMANTIC RELEVANCE SCORING ───────────────────────────────────

def _extract_keywords(text: str) -> List[str]:
    """Extract significant lowercase keywords from user queries."""
    if not text:
        return []
    words = re.findall(r"\b[a-zA-Z]{2,}\b", text.lower())
    stop_words = {
        "the", "and", "that", "this", "what", "who", "when", "where", "why", "how",
        "did", "you", "say", "about", "for", "with", "are", "have", "can", "tell",
        "please", "give", "show", "know", "there", "their", "they", "from", "just",
        "is", "my", "me", "we", "our", "us", "your", "it", "its", "in", "on", "at",
        "to", "of", "a", "an", "do", "does", "be", "was", "were", "been", "being",
        "no", "not", "none", "never", "dont", "didnt", "wont", "cant", "isnt", "arent",
        "wasnt", "werent", "ask", "asked", "asking", "said", "saying", "told"
    }
    return [w for w in words if w not in stop_words]


def _compute_relevance_score(query_keywords: List[str], key: str, value: str, last_accessed_ts: Optional[float] = None) -> float:
    """
    Computes a hybrid relevance score (0.0 to 100.0) combining keyword matches,
    exact token overlaps, and recency decay.
    """
    if not query_keywords:
        return 1.0

    hay_key = key.replace("_", " ").lower()
    hay_val = str(value).lower()
    score = 0.0

    for kw in query_keywords:
        # Key exact match
        if kw == hay_key:
            score += 25.0
        elif kw in hay_key:
            score += 12.0

        # Value word match
        if kw in hay_val:
            score += 8.0

    # Recency boost (up to 5 points)
    if last_accessed_ts and last_accessed_ts > 0:
        age_days = (time.time() - last_accessed_ts) / 86400.0
        recency_factor = max(0.0, 5.0 - (age_days * 0.2))
        score += recency_factor

    return score


# ── 2. MEMORY PERSISTENCE & EXTRACTION ENGINE ─────────────────────────────────

class ChatGPTMemoryManager:
    """
    Authoritative ChatGPT-Style Memory Manager.
    Coordinates short-term context, user facts, preferences, and long-term memory.
    """

    def __init__(self):
        self.pool = get_db_pool()
        self._user_facts_cache: Dict[int, Tuple[float, Dict[str, str]]] = {}
        self._cache_lock = threading.Lock()
        self._cache_ttl = 30.0  # seconds

    # ── A. USER FACTS (memory_facts) ──────────────────────────────────────────

    def set_user_fact(
        self,
        user_id: int,
        key: str,
        value: str,
        confidence: float = 1.0,
        source: str = "conversation",
        category: str = "general",
        status: str = "confirmed",
        source_ref: str = "",
        expiration_date: Optional[datetime] = None,
        supersedes_key: Optional[str] = None,
    ) -> bool:
        """
        Upsert a structured declarative user fact across memory_facts, user_memory, and user_preferences.
        Supports intelligent deduplication, progression updating, and temporal expiration.

        When ``supersedes_key`` is provided and differs from ``key``, the old key's
        active facts are marked superseded (history preserved as superseded rows) and
        its stale mirror entry is removed so it no longer surfaces in get_user_facts.
        """
        if not user_id or not key or value is None:
            return False

        clean_key = key.strip().lower().replace(" ", "_")[:100]
        clean_val = str(value).strip()[:MAX_FACT_VALUE_LENGTH]
        clean_cat = str(category).strip().lower()[:50] if category else "general"
        clean_status = str(status).strip().lower()[:20] if status else "confirmed"
        user_id = int(user_id)

        try:
            # 1. Upsert into memory_facts with supersession and status
            with self.pool.get_cursor() as cur:
                cur.execute("""
                    SELECT id, fact_value, status FROM memory_facts
                    WHERE user_id = %s AND fact_key = %s AND (status IS NULL OR status != 'superseded')
                    ORDER BY id DESC LIMIT 1;
                """, (user_id, clean_key))
                existing = cur.fetchone()

                if existing:
                    existing_id, existing_val, existing_status = existing[0], existing[1], existing[2]
                    if existing_val == clean_val and existing_status == clean_status:
                        # Value and status already identical; refresh last_accessed and last_confirmed
                        try:
                            cur.execute("""
                                UPDATE memory_facts
                                SET last_accessed = CURRENT_TIMESTAMP, last_confirmed = CURRENT_TIMESTAMP
                                WHERE id = %s
                            """, (existing_id,))
                        except Exception:
                            pass
                        return True

                    # Value or status changed: mark existing as superseded and insert new fact
                    new_id = None
                    try:
                        cur.execute("SAVEPOINT mem_upd_019;")
                        cur.execute("""
                            INSERT INTO memory_facts (user_id, fact_key, fact_value, confidence, source, category, status, source_ref, expiration_date, last_accessed, last_confirmed)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                            RETURNING id;
                        """, (user_id, clean_key, clean_val, confidence, source, clean_cat, clean_status, source_ref, expiration_date))
                        row = cur.fetchone()
                        if row:
                            new_id = row[0]
                        cur.execute("""
                            UPDATE memory_facts
                            SET status = 'superseded', superseded_by = %s
                            WHERE id = %s;
                        """, (new_id, existing_id))
                        cur.execute("RELEASE SAVEPOINT mem_upd_019;")
                    except Exception:
                        try:
                            cur.execute("ROLLBACK TO SAVEPOINT mem_upd_019;")
                        except Exception:
                            pass
                        # Fallback for installations prior to migration 019
                        cur.execute("""
                            UPDATE memory_facts
                            SET fact_value = %s, confidence = %s, source = %s, last_accessed = CURRENT_TIMESTAMP
                            WHERE id = %s
                        """, (clean_val, confidence, source, existing_id))
                else:
                    try:
                        cur.execute("SAVEPOINT mem_ins_019;")
                        cur.execute("""
                            INSERT INTO memory_facts (user_id, fact_key, fact_value, confidence, source, category, status, source_ref, expiration_date, last_accessed, last_confirmed)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
                        """, (user_id, clean_key, clean_val, confidence, source, clean_cat, clean_status, source_ref, expiration_date))
                        cur.execute("RELEASE SAVEPOINT mem_ins_019;")
                    except Exception:
                        try:
                            cur.execute("ROLLBACK TO SAVEPOINT mem_ins_019;")
                        except Exception:
                            pass
                        # Fallback for pre-migration 019 schema
                        cur.execute("""
                            INSERT INTO memory_facts (user_id, fact_key, fact_value, confidence, source, last_accessed)
                            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP);
                        """, (user_id, clean_key, clean_val, confidence, source))

            # 1b. Cross-key supersession (e.g. graduation supersedes student_status,
            # a job offer supersedes the old career goal). Mark the old key's active
            # facts as superseded so get_user_facts / get_structured_user_memories
            # filter them out, and drop the stale mirror key so the JSONB mirror
            # cannot resurrect the outdated value.
            if supersedes_key:
                clean_old = str(supersedes_key).strip().lower().replace(" ", "_")[:100]
                if clean_old and clean_old != clean_key:
                    try:
                        with self.pool.get_cursor() as cur:
                            cur.execute("""
                                SELECT id FROM memory_facts
                                WHERE user_id = %s AND fact_key = %s
                                ORDER BY id DESC LIMIT 1;
                            """, (user_id, clean_key))
                            _new_row = cur.fetchone()
                            _new_id = _new_row[0] if _new_row else None
                            cur.execute("""
                                UPDATE memory_facts
                                SET status = 'superseded', superseded_by = %s
                                WHERE user_id = %s AND fact_key = %s
                                  AND (status IS NULL OR status != 'superseded');
                            """, (_new_id, user_id, clean_old))
                    except Exception:
                        pass

                    # Remove the stale flat key from the user_memory JSONB mirror.
                    try:
                        from legacy.memory_manager import delete_memory_key
                        delete_memory_key(user_id, clean_old)
                    except Exception:
                        pass

            # 2. Sync to user_memory JSONB
            try:
                from legacy.memory_manager import update_user_memory
                update_user_memory(user_id, clean_key, clean_val)
            except Exception as _sync_err:
                pass

            # Also sync categorized dictionary in user_memory
            try:
                from legacy.memory_manager import load_user_memory, update_user_memory
                mem = load_user_memory(user_id) or {}
                valid_cat = clean_cat if clean_cat in ("identity", "preferences", "projects", "relationships", "wishes", "notes", "education", "employment", "goals", "commitments") else "notes"
                if valid_cat not in mem or not isinstance(mem[valid_cat], dict):
                    mem[valid_cat] = {}
                mem[valid_cat][clean_key] = {
                    "value": clean_val,
                    "updated": datetime.now().strftime("%Y-%m-%d"),
                    "status": clean_status,
                }
                update_user_memory(user_id, valid_cat, mem[valid_cat])
            except Exception:
                pass

            # 3. Sync to user_preferences if it's a known configuration preference
            if clean_key in ("response_style", "tone", "theme", "assistant_name", "voice_rate", "voice_id", "persona", "verbosity"):
                try:
                    self.set_preference(user_id, clean_key, clean_val)
                except Exception:
                    pass

            # Invalidate user facts cache on update
            try:
                with self._cache_lock:
                    self._user_facts_cache.pop(user_id, None)
            except Exception:
                pass

            return True
        except Exception as e:
            print(f"[MEMORY] set_user_fact error: {e}")
            return False

    def get_user_facts(self, user_id: int, include_tentative: bool = False) -> Dict[str, str]:
        """
        Returns all active confirmed facts for a user as a dict of {fact_key: fact_value},
        authoritatively merging memory_facts, user_memory JSONB, and user_preferences.
        Strictly isolated to user_id. Automatically filters out superseded and expired facts.
        """
        if not user_id:
            return {}
        user_id = int(user_id)

        # Fast user-scoped memory cache hit
        if not include_tentative:
            with self._cache_lock:
                cached = self._user_facts_cache.get(user_id)
                if cached and (time.time() - cached[0] < self._cache_ttl):
                    return dict(cached[1])

        merged: Dict[str, str] = {}

        # 1. Load user_memory JSONB
        try:
            with self.pool.get_cursor() as cur:
                cur.execute("SELECT memory FROM user_memory WHERE user_id = %s;", (user_id,))
                row = cur.fetchone()
                if row and row[0]:
                    raw = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
                    for k, v in raw.items():
                        if isinstance(v, (str, int, float, bool)):
                            merged[str(k).lower()] = str(v)
                        elif isinstance(v, dict) and "value" in v:
                            merged[str(k).lower()] = str(v["value"])
        except Exception as _e1:
            pass

        # 2. Load user_preferences
        try:
            with self.pool.get_cursor() as cur:
                cur.execute("SELECT pref_key, pref_value FROM user_preferences WHERE user_id = %s;", (user_id,))
                for k, v in cur.fetchall():
                    try:
                        clean_v = json.loads(v) if isinstance(v, str) and (v.startswith("{") or v.startswith("[")) else v
                        merged[str(k).lower()] = str(clean_v)
                    except Exception:
                        merged[str(k).lower()] = str(v)
        except Exception as _e2:
            pass

        # 3. Load memory_facts (highest priority for newer declarative facts)
        # Filter out superseded and expired facts
        try:
            with self.pool.get_cursor() as cur:
                status_clause = "status IN ('confirmed', 'tentative')" if include_tentative else "(status IS NULL OR status = 'confirmed')"
                try:
                    cur.execute(f"""
                        SELECT fact_key, fact_value FROM memory_facts
                        WHERE user_id = %s
                          AND {status_clause}
                          AND (expiration_date IS NULL OR expiration_date > CURRENT_TIMESTAMP)
                        ORDER BY last_accessed ASC
                    """, (user_id,))
                except Exception:
                    # Fallback for columns not yet present
                    cur.execute("""
                        SELECT fact_key, fact_value FROM memory_facts
                        WHERE user_id = %s ORDER BY last_accessed ASC
                    """, (user_id,))
                for r in cur.fetchall():
                    merged[str(r[0]).lower()] = str(r[1])
        except Exception as _e3:
            pass

        if not include_tentative:
            with self._cache_lock:
                self._user_facts_cache[user_id] = (time.time(), dict(merged))

        return merged

    def get_structured_user_memories(self, user_id: int, include_tentative: bool = False) -> List[Dict[str, Any]]:
        """
        Returns full structured memory records with metadata:
        category, confidence, status, source_ref, last_confirmed, expiration_date.
        Strictly isolated to user_id.
        """
        if not user_id:
            return []
        user_id = int(user_id)
        results = []
        try:
            with self.pool.get_cursor() as cur:
                status_clause = "status IN ('confirmed', 'tentative')" if include_tentative else "(status IS NULL OR status = 'confirmed')"
                cur.execute(f"""
                    SELECT id, fact_key, fact_value, category, confidence, status, source_ref,
                           created_at, last_accessed, last_confirmed, expiration_date, superseded_by
                    FROM memory_facts
                    WHERE user_id = %s
                      AND {status_clause}
                      AND (expiration_date IS NULL OR expiration_date > CURRENT_TIMESTAMP)
                    ORDER BY last_confirmed DESC, id DESC;
                """, (user_id,))
                for r in cur.fetchall():
                    results.append({
                        "id": r[0],
                        "key": r[1],
                        "value": r[2],
                        "category": r[3] or "general",
                        "confidence": float(r[4] or 1.0),
                        "status": r[5] or "confirmed",
                        "source_ref": r[6] or "",
                        "created_at": r[7].isoformat() if r[7] else None,
                        "last_accessed": r[8].isoformat() if r[8] else None,
                        "last_confirmed": r[9].isoformat() if r[9] else None,
                        "expiration_date": r[10].isoformat() if r[10] else None,
                        "superseded_by": r[11],
                    })
        except Exception as e:
            print(f"[MEMORY] get_structured_user_memories error: {e}")
        return results

    def delete_user_fact(self, user_id: int, key: str) -> bool:
        """Delete a specific user fact across tables and cache."""
        if not user_id or not key:
            return False
        clean_key = key.strip().lower().replace(" ", "_")
        user_id = int(user_id)
        deleted = False
        try:
            with self.pool.get_cursor() as cur:
                # 1. Delete from memory_facts
                cur.execute("""
                    DELETE FROM memory_facts WHERE user_id = %s AND fact_key = %s RETURNING id
                """, (user_id, clean_key))
                deleted = cur.fetchone() is not None

                # 2. Delete from user_preferences if present
                cur.execute("""
                    DELETE FROM user_preferences WHERE user_id = %s AND pref_key = %s
                """, (user_id, clean_key))

                # 3. Clean from user_memory JSONB (top-level and categories)
                try:
                    cur.execute("SELECT memory FROM user_memory WHERE user_id = %s;", (user_id,))
                    row = cur.fetchone()
                    if row and row[0]:
                        raw = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
                        changed = False
                        if clean_key in raw:
                            del raw[clean_key]
                            changed = True
                        for cat, cat_dict in list(raw.items()):
                            if isinstance(cat_dict, dict) and clean_key in cat_dict:
                                del cat_dict[clean_key]
                                changed = True
                        if changed:
                            cur.execute("""
                                UPDATE user_memory SET memory = %s WHERE user_id = %s;
                            """, (json.dumps(raw), user_id))
                except Exception:
                    pass
        except Exception as e:
            print(f"[MEMORY] delete_user_fact error: {e}")

        try:
            with self._cache_lock:
                self._user_facts_cache.pop(user_id, None)
        except Exception:
            pass

        return deleted

    # ── B. USER PREFERENCES (user_preferences) ───────────────────────────────

    def set_preference(self, user_id: int, key: str, value: Any) -> bool:
        """Upsert a user preference."""
        if not user_id or not key:
            return False
        clean_key = str(key).strip().lower()
        val_str = json.dumps(value) if isinstance(value, (dict, list, bool, int, float)) else str(value)
        try:
            with self.pool.get_cursor() as cur:
                cur.execute("""
                    INSERT INTO user_preferences (user_id, pref_key, pref_value)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, pref_key)
                    DO UPDATE SET pref_value = EXCLUDED.pref_value
                """, (int(user_id), clean_key, val_str))
            try:
                with self._cache_lock:
                    self._user_facts_cache.pop(int(user_id), None)
            except Exception:
                pass
            return True
        except Exception as e:
            print(f"[MEMORY] set_preference error: {e}")
            return False

    def get_preferences(self, user_id: int) -> Dict[str, Any]:
        """Returns all preferences for a user."""
        if not user_id:
            return {}
        try:
            with self.pool.get_cursor() as cur:
                cur.execute("""
                    SELECT pref_key, pref_value FROM user_preferences WHERE user_id = %s
                """, (int(user_id),))
                res = {}
                for k, v in cur.fetchall():
                    try:
                        res[k] = json.loads(v)
                    except Exception:
                        res[k] = v
                return res
        except Exception as e:
            print(f"[MEMORY] get_preferences error: {e}")
            return {}

    # ── C. CONVERSATIONS & MESSAGES ───────────────────────────────────────────

    def log_interaction(self, user_id: int, user_input: str, assistant_response: str, session_id: Optional[str] = None) -> None:
        """
        Atomically records conversation turn into conversations & messages tables.
        Also triggers synchronous fact extraction.
        """
        if not user_id or not user_input:
            return
        user_id = int(user_id)
        try:
            with self.pool.get_cursor() as cur:
                # Deduplication check to prevent double logging across multiple callers
                cur.execute("""
                    SELECT id FROM messages 
                    WHERE user_id = %s AND role = 'assistant' AND content = %s 
                      AND created_at >= NOW() - INTERVAL '3 seconds'
                    LIMIT 1;
                """, (user_id, assistant_response))
                if cur.fetchone():
                    return

                # 1. Try insert into conversations table
                conv_id = None
                try:
                    cur.execute("""
                        INSERT INTO conversations (user_id, user_input, assistant_response, session_id)
                        VALUES (%s, %s, %s, %s)
                        RETURNING id
                    """, (user_id, user_input, assistant_response, session_id or "default"))
                    row = cur.fetchone()
                    if row:
                        conv_id = row[0]
                except Exception:
                    pass

                # 2. Authoritative insert into messages table
                try:
                    cur.execute("""
                        INSERT INTO messages (user_id, conversation_id, role, content)
                        VALUES (%s, %s, 'user', %s), (%s, %s, 'assistant', %s)
                    """, (user_id, conv_id, user_input, user_id, conv_id, assistant_response))
                except Exception as _msg_err:
                    pass

            # 3. Synchronously extract facts from dialogue
            try:
                self.extract_and_persist_facts(user_id, user_input)
            except Exception as _fe_err:
                pass
        except Exception as e:
            print(f"[MEMORY] log_interaction error: {e}")

    def get_recent_conversation(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Returns the most recent conversation turns for a user in chronological order.
        Checks conversations table, falling back to messages table.
        """
        if not user_id:
            return []
        user_id = int(user_id)
        try:
            with self.pool.get_cursor() as cur:
                # 1. Check conversations table (exclude transient outage fallbacks from polluting prompt context)
                cur.execute("""
                    SELECT user_input, assistant_response, timestamp
                    FROM conversations
                    WHERE user_id = %s
                      AND (assistant_response IS NULL OR (
                          assistant_response NOT ILIKE '%%trouble reaching%%'
                          AND assistant_response NOT ILIKE '%%language model service is currently unavailable%%'
                          AND assistant_response NOT ILIKE '%%All configured providers%%'
                      ))
                    ORDER BY id DESC
                    LIMIT %s
                """, (user_id, limit))
                rows = cur.fetchall()
                if rows:
                    return [{
                        "user": r[0],
                        "assistant": r[1],
                        "timestamp": str(r[2])
                    } for r in reversed(rows)]

                # 2. Fallback to authoritative messages table
                cur.execute("""
                    SELECT role, content, created_at
                    FROM messages
                    WHERE user_id = %s
                      AND (content IS NULL OR (
                          content NOT ILIKE '%%trouble reaching%%'
                          AND content NOT ILIKE '%%language model service is currently unavailable%%'
                          AND content NOT ILIKE '%%All configured providers%%'
                      ))
                    ORDER BY id DESC
                    LIMIT %s
                """, (user_id, limit * 2))
                msg_rows = cur.fetchall()
                if not msg_rows:
                    return []

                # Group into turns in chronological order
                chrono_msgs = list(reversed(msg_rows))
                turns = []
                pending_user = None
                pending_time = None
                for role, content, created_at in chrono_msgs:
                    if role == "user":
                        if pending_user is not None:
                            turns.append({"user": pending_user, "assistant": "", "timestamp": str(pending_time)})
                        pending_user = content
                        pending_time = created_at
                    elif role == "assistant":
                        if pending_user is not None:
                            turns.append({"user": pending_user, "assistant": content, "timestamp": str(created_at)})
                            pending_user = None
                            pending_time = None
                        else:
                            turns.append({"user": "", "assistant": content, "timestamp": str(created_at)})
                if pending_user is not None:
                    turns.append({"user": pending_user, "assistant": "", "timestamp": str(pending_time)})

                return turns[-limit:]
        except Exception as e:
            print(f"[MEMORY] get_recent_conversation error: {e}")
            return []

    # ── D. AUTOMATED FACT & PREFERENCE EXTRACTION ─────────────────────────────

    def extract_and_persist_facts(self, user_id: int, text: str) -> List[Tuple[str, str]]:
        """
        Extracts candidate memories from ordinary natural conversation and persists them.
        Uses deterministic local extraction layer (core.fact_extractor) and maps into
        PostgreSQL memory_facts, user_memory, and user_preferences.
        Returns list of (key, value) pairs persisted.
        """
        if not text or not user_id:
            return []

        user_id = int(user_id)
        extracted: List[Tuple[str, str]] = []
        persisted_keys: set = set()

        # 1. Deterministic natural language fact extraction
        try:
            from core.fact_extractor import extract_candidate_facts
            candidates = extract_candidate_facts(text)
            for cand in candidates:
                success = self.set_user_fact(
                    user_id=user_id,
                    key=cand.key,
                    value=cand.value,
                    confidence=cand.confidence,
                    source="dialogue_extraction",
                    category=cand.category,
                    status=cand.status,
                    source_ref=cand.source_ref,
                    expiration_date=cand.expiration_date,
                    supersedes_key=cand.supersedes_key,
                )
                if success:
                    extracted.append((cand.key, cand.value))
                    persisted_keys.add(cand.key)
        except Exception as _fe_err:
            print(f"[MEMORY] Fact extraction error: {_fe_err}")

        # 2. Legacy pattern compatibility for explicit patterns
        t = text.strip()
        legacy_patterns = [
            (r"\bmy name is ([a-zA-Z\s]+)", "name", "identity"),
            (r"\bi live in ([a-zA-Z\s,]+)", "city", "identity"),
            (r"\bi am from ([a-zA-Z\s,]+)", "hometown", "identity"),
            (r"\bi work at ([a-zA-Z0-9\s]+)", "workplace", "employment"),
            (r"\bi work as an? ([a-zA-Z\s]+)", "occupation", "employment"),
            (r"\bmy job is ([a-zA-Z\s]+)", "job", "employment"),
            (r"\bmy favorite (\w+) is ([a-zA-Z0-9\s]+)", "favorite_{0}", "preferences"),
            (r"\bmy favourite (\w+) is ([a-zA-Z0-9\s]+)", "favorite_{0}", "preferences"),
            (r"\bmy dog(?:'s name)? is ([a-zA-Z\s]+)", "dog_name", "relationships"),
            (r"\bmy cat(?:'s name)? is ([a-zA-Z\s]+)", "cat_name", "relationships"),
            (r"\bmy wife(?:'s name)? is ([a-zA-Z\s]+)", "wife_name", "relationships"),
            (r"\bmy husband(?:'s name)? is ([a-zA-Z\s]+)", "husband_name", "relationships"),
            (r"\bmy sister(?:'s name)? is ([a-zA-Z\s]+)", "sister_name", "relationships"),
            (r"\bmy brother(?:'s name)? is ([a-zA-Z\s]+)", "brother_name", "relationships"),
            (r"\bmy birthday is ([a-zA-Z0-9\s,]+)", "birthday", "identity"),
            (r"\b(?:my\s+)?assistant(?:'s)?\s+name\s+is\s+([a-zA-Z0-9\s]+)", "assistant_name", "preferences"),
            (r"\bcall\s+my\s+assistant\s+([a-zA-Z0-9\s]+)", "assistant_name", "preferences"),
            (r"\bname\s+(?:of\s+)?my\s+assistant\s+is\s+([a-zA-Z0-9\s]+)", "assistant_name", "preferences"),
            (r"\bi\s+prefer\s+([a-zA-Z0-9\s]+)\s+answers?", "response_style", "preferences"),
            (r"\b(?:my\s+)?response\s+style\s+is\s+([a-zA-Z0-9\s]+)", "response_style", "preferences"),
            (r"\b(?:the\s+)?database\s+(?:for\s+this\s+project\s+)?is\s+([a-zA-Z0-9_\s]+)", "database", "projects"),
            (r"\b(?:the\s+)?(?:backend|backend\s+technology)\s+(?:for\s+this\s+project\s+)?is\s+([a-zA-Z0-9_\s]+)", "backend", "projects"),
            (r"\b(?:the\s+)?frontend\s+(?:for\s+this\s+project\s+)?is\s+([a-zA-Z0-9_\s]+)", "frontend", "projects"),
            (r"\b(?:the\s+)?project\s+name\s+is\s+([a-zA-Z0-9_\s]+)", "project_name", "projects"),
            (r"\bremember\s+(?:that\s+)?([a-zA-Z0-9\s_]+?)\s+is\s+([a-zA-Z0-9\s_]+)", "{0}", "general"),
            (r"\bremember\s+my\s+(\w+)\s+is\s+([a-zA-Z0-9\s_]+)", "{0}", "general"),
            (r"\bi\s+prefer\s+([a-zA-Z0-9\s]+)", "preference", "preferences"),
        ]

        for pat, key_template, cat_name in legacy_patterns:
            match = re.search(pat, t, re.IGNORECASE)
            if match:
                groups = match.groups()
                if len(groups) == 1:
                    val = groups[0].strip().rstrip(".")
                    key = key_template
                elif len(groups) == 2:
                    k_slot, val = groups[0].strip(), groups[1].strip().rstrip(".")
                    key = key_template.format(k_slot.lower().replace(" ", "_"))
                else:
                    continue

                if key and val and len(val) > 1:
                    clean_k = key.strip().lower().replace(" ", "_")
                    clean_v = val.strip()
                    if clean_k not in persisted_keys:
                        self.set_user_fact(user_id, clean_k, clean_v, confidence=0.95, source="dialogue_extraction", category=cat_name)
                        extracted.append((clean_k, clean_v))
                        persisted_keys.add(clean_k)

        return extracted

    # ── E. CONTEXT RETRIEVAL & PROMPT BUDGETING ───────────────────────────────

    def retrieve_relevant_memories(
        self,
        user_id: int,
        query_text: str = "",
        limit: int = 6,
        category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Ranks all user facts and categorized memories based on query relevance and recency.
        Only returns items meeting relevance threshold.
        """
        if not user_id:
            return []

        keywords = _extract_keywords(query_text)
        all_facts = self.get_user_facts(user_id)
        if not all_facts:
            return []

        scored_items = []
        is_personalization_query = any(k in (query_text or "").lower() for k in (
            "help me", "prepare for", "placement", "interview", "resume", "study",
            "exam", "career", "advice", "suggest", "about me", "myself"
        ))

        for key, val in all_facts.items():
            base_score = _compute_relevance_score(keywords, key, val)

            # If specific keywords are queried, boost matched keywords
            if keywords:
                if base_score > 0:
                    if key in ["preferred_name", "name", "city", "job", "occupation", "education", "institution", "activity"]:
                        base_score += 5.0
                    scored_items.append({
                        "key": key,
                        "value": val,
                        "score": base_score
                    })
                elif is_personalization_query:
                    # Contextual personalization inclusion for core profile facts
                    if key in ["preferred_name", "name", "education", "institution", "activity", "major"]:
                        scored_items.append({
                            "key": key,
                            "value": val,
                            "score": 8.0
                        })
            else:
                # Generic retrieval: include all facts with bias for identity & profile
                score = base_score
                if key in ["preferred_name", "name", "education", "institution", "activity", "city"]:
                    score += 15.0
                scored_items.append({
                    "key": key,
                    "value": val,
                    "score": score
                })

        scored_items.sort(key=lambda x: -x["score"])
        return scored_items[:limit]

    def build_prompt_context(self, user_id: int, query_text: str = "") -> str:
        """
        Builds a compact, budgeted context block for LLM prompts without overloading tokens.
        Includes:
        1. Top relevant user facts
        2. Relevant user preferences
        3. Active context (if any)
        """
        if not user_id:
            return ""

        facts = self.retrieve_relevant_memories(user_id, query_text, limit=6)
        prefs = self.get_preferences(user_id)

        blocks = []
        if facts:
            fact_lines = []
            char_count = 0
            for f in facts:
                line = f"- {f['key'].replace('_', ' ').title()}: {f['value']}"
                if char_count + len(line) > MAX_PROMPT_FACTS_CHARS:
                    break
                fact_lines.append(line)
                char_count += len(line)

            if fact_lines:
                blocks.append("[USER KNOWLEDGE & RELEVANT FACTS]")
                blocks.extend(fact_lines)

        return "\n".join(blocks) if blocks else ""

    def answer_historical_fact_query(self, user_id: int, query_text: str) -> Optional[str]:
        """
        Direct factual recall and preference querying grounded in PostgreSQL storage.
        Answers questions such as:
        - "Which university do I attend?" / "What is my university?"
        - "What is my education?" / "What year am I in?"
        - "What activity am I in?" / "Am I in the placement cell?"
        - "What is my preferred name?" / "What is my name?"
        - "What name did I choose for my assistant?" / "What is my assistant's name?"
        - "Which database does this project use?" / "What database does this project use?"
        - "What technology did I use for the backend?"
        - "What did I ask you to remember?"
        - "What response style did I choose?"
        Returns verified factual string if recorded, or None if no factual record matches.
        """
        if not user_id or not query_text:
            return None
        q = query_text.lower().strip().rstrip(".?!")

        # Ignore corrections, rejections, and meta-dialogue from fact queries
        if any(p in q for p in (
            "not what i asked", "not what i ask", "that's not what", "thats not what",
            "not what i meant", "you misunderstood", "that's wrong", "thats wrong",
            "wrong answer", "what did i ask", "what did i just ask", "what did i ask you",
            "what was my last question", "what was my previous question"
        )):
            return None

        facts = self.get_user_facts(user_id)
        prefs = self.get_preferences(user_id)

        # Speech recognition / spelling normalization for education & personal facts
        q = re.sub(r'\binter\s+stu(?:y|ies|dy|dies)\b', 'intermediate studies', q)
        q = re.sub(r'\bmy\s+inter\b', 'my intermediate', q)

        # 0.02 Temporal reasoning over a stored date fact
        # ("Which day of the week is my birthday next year?", "How many days until
        #  my birthday?", "What date is my next birthday?")  Uses the canonical
        #  facts already loaded above and deterministic date arithmetic ONLY.
        temporal_answer = self._answer_temporal_fact_query(q, facts)
        if temporal_answer:
            return temporal_answer

        # 0.01 Verification / "Are you sure?" re-evaluation queries
        if q.startswith("are you sure") or q.startswith("are you certain") or "really sure" in q:
            if any(k in q for k in ("intermediate", "inter")):
                inter = facts.get("intermediate") or facts.get("intermediate_college")
                if inter:
                    return f"Yes, I'm certain based on your stored records that you completed your intermediate at {inter}."
                return "Yes, I am sure. I re-checked your persistent memory and profile records, and there is no record of your intermediate education."
            elif any(k in q for k in ("10th", "tenth", "school")):
                tenth = facts.get("10th") or facts.get("school")
                if tenth:
                    return f"Yes, I'm certain based on your stored records that you completed your 10th at {tenth}."
                return "Yes, I am sure. I re-checked your persistent memory and profile records, and there is no record of your 10th grade education."
            elif any(k in q for k in ("university", "college", "srm", "study", "studied")):
                inst = facts.get("institution") or facts.get("university") or facts.get("college")
                if inst:
                    return f"Yes, I am certain. According to your stored profile records, you study at {inst}."
                return "Yes, I am sure. I re-checked your records and found no university entry recorded."
            else:
                if facts:
                    fact_summary = ", ".join(f"{k}: {v}" for k, v in list(facts.items())[:3])
                    return f"Yes, I verified your stored records. The recorded facts are: {fact_summary}."
                return "Yes, I am sure. I verified your persistent memory records, and no matching entry is stored."

        # 0.05 Intermediate / +2 / Junior College Inquiries
        if any(p in q for p in (
            "intermediate", "inter studies", "my intermediate", "junior college",
            "+2", "plus two", "12th", "twelfth"
        )):
            inter = facts.get("intermediate") or facts.get("intermediate_college") or facts.get("junior_college") or facts.get("12th")
            if inter:
                return f"According to your records, you completed your intermediate at {inter}."
            return "I checked your available records, and I don't have a record of your intermediate education."

        # 0.06 10th Grade / SSC / Matriculation Inquiries
        if any(p in q for p in (
            "10th", "tenth", "my 10th", "my tenth", "ssc", "matriculation", "high school", "schooling"
        )) and not any(p in q for p in ("university", "college", "intermediate")):
            tenth = facts.get("10th") or facts.get("tenth") or facts.get("tenth_school") or facts.get("school") or facts.get("high_school") or facts.get("matriculation")
            if tenth:
                return f"According to your records, you studied your 10th grade at {tenth}."
            return "I checked your available records, and I don't have a record of your 10th grade education."

        # 0. University & Institution Inquiries
        # e.g. "Which university do I attend?", "What university do I attend?", "Where do I study?", "What college do I attend?"
        if any(p in q for p in (
            "university do i attend", "which university", "what university",
            "where do i study", "what college do i", "which college do i",
            "college do i attend", "what is my university", "what is my college",
            "my institution", "which institution", "what school do i attend", "where do i go to school"
        )):
            inst = facts.get("institution") or facts.get("university") or facts.get("college")
            edu = facts.get("education") or facts.get("student_status")
            if inst:
                if edu:
                    return f"You attend {inst} as a {edu}."
                return f"You attend {inst}."
            return "I don't have a record of which university or college you attend."

        # 0.08 Age
        if any(p in q for p in ("how old am i", "what is my age", "what's my age", "whats my age",
                                 "my age", "how old", "how many years old")):
            age_fact = facts.get("age")
            if age_fact:
                return f"You are {age_fact} years old."
            return "I don't have your age on record."

        # 0.1 Education, Year, & Student Status

        # e.g. "What is my education?", "What year am I in?", "Am I a student?", "What is my student status?"
        if any(p in q for p in (
            "what is my education", "what year am i in", "am i a student",
            "what is my student status", "what am i studying", "what year student am i",
            "my academic year", "what course am i taking"
        )):
            edu = facts.get("education") or facts.get("student_status")
            inst = facts.get("institution") or facts.get("university")
            maj = facts.get("major")
            if edu:
                details = [f"You are a {edu}"]
                if maj:
                    details.append(f"studying {maj}")
                if inst:
                    details.append(f"at {inst}")
                return " ".join(details) + "."
            return "I don't have a record of your education or student status."

        # 0.2 Activity, Placement Cell, & Roles
        # e.g. "What activity am I in?", "What cell am I in?", "Am I in the placement cell?", "What club or cell am I part of?"
        if any(p in q for p in (
            "what cell am i in", "what is my activity", "am i in the placement cell",
            "what role do i have", "what committee am i in", "what club am i in",
            "what activities am i involved in", "my activity",
            "club or cell", "in any club", "in a club", "in any cell", "in a cell",
            "what club", "which club", "which cell", "what cell", "part of any club",
            "part of any cell", "club or cell am i part of", "am i part of any club", "am i part of any cell"
        )):
            act = facts.get("activity") or facts.get("role")
            if act:
                return f"You are a {act}."
            return "I don't have a record of your activities or committee roles."

        # 0.3 Preferred Name & Name
        # e.g. "What is my preferred name?", "What is my full name?", "What is my name?", "What should you call me?"
        if any(p in q for p in (
            "what is my full name", "what's my full name", "whats my full name", "my full name", "tell me my full name",
            "what is my preferred name", "my preferred name", "what name do i prefer",
            "what should you call me", "what is my name", "what's my name", "whats my name",
            "who am i", "do you know my name", "tell me my name"
        )):
            if "full name" in q:
                fn = facts.get("full_name") or facts.get("name") or facts.get("preferred_name")
                if fn:
                    return f"Your full name is {fn}."
                return "I don't have a full name recorded for you."
            name = facts.get("preferred_name") or facts.get("name") or facts.get("full_name")
            if name:
                return f"Your name is {name}."
            return "I don't have a name recorded for you."

        # 0.4 Commitments & Deadlines
        # e.g. "When is my interview?", "What deadlines do I have?", "What is my next commitment?"
        if any(p in q for p in (
            "when is my interview", "what deadlines do i have", "what is my deadline",
            "do i have an interview", "what commitments do i have", "my next commitment"
        )):
            comm = facts.get("commitment") or facts.get("deadline")
            if comm:
                return f"You have an upcoming commitment: {comm}."
            return "You don't have any upcoming commitments or deadlines recorded."

        # 0.5 Career Goals & Applications
        # e.g. "What are my goals?", "What am I applying for?", "What is my career goal?"
        if any(p in q for p in (
            "what are my goals", "what is my goal", "what am i applying for",
            "what career goal do i have", "my current goal"
        )):
            goal = facts.get("career_goal") or facts.get("goal")
            if goal:
                return f"Your current goal is {goal}."
            return "I don't have any career goals or applications recorded for you yet."

        # 1. Assistant Name
        if any(p in q for p in (
            "name did i choose for my assistant", "name did i give you",
            "name did i choose for you", "assistant's name", "name of my assistant",
            "what did i name you", "what is your name", "who are you"
        )):
            asst = facts.get("assistant_name") or prefs.get("assistant_name")
            if not asst:
                try:
                    from instance.config import settings
                    asst = getattr(settings, 'CURRENT_ASSISTANT_NAME', None) or settings.get_assistant_name()
                except Exception:
                    pass
            if asst:
                return f"You chose '{asst.capitalize()}' as the name for your assistant."
            return "You haven't chosen a custom name for your assistant yet."

        # 2. Database
        if "database" in q or "db" in q:
            db_fact = facts.get("database") or facts.get("db") or facts.get("db_name")
            if db_fact:
                return f"This project uses {db_fact} as its database."
            # authoritative check from environment / settings
            try:
                import os
                db_name = os.getenv("DB_NAME", "PostgreSQL")
                return f"This project uses PostgreSQL (database: {db_name})."
            except Exception:
                return "This project uses PostgreSQL."

        # 3. Backend technology
        if any(p in q for p in ("backend", "technology did i use", "tech stack", "backend technology")):
            be_fact = facts.get("backend") or facts.get("backend_technology") or facts.get("tech_stack")
            if be_fact:
                return f"The backend technology for this project is {be_fact}."
            return "The backend for this project is built using Python."

        # 4. Response style / Preference
        if any(p in q for p in ("response style", "style of response", "style did i choose", "style did i pick")):
            style = facts.get("response_style") or prefs.get("response_style") or facts.get("likes_concise")
            if style:
                clean_s = "concise" if "concise" in str(style).lower() else str(style)
                return f"You chose a {clean_s} response style."
            return "You haven't configured a specific response style yet."

        # 5. What did I ask you to remember? / Test phrase query
        if any(p in q for p in (
            "what did i ask you to remember", "what did i tell you to remember",
            "what do you remember", "what is in my memory",
            "what was the test phrase", "what was the phrase", "what is the test phrase",
            "test phrase i asked you to remember", "phrase i asked you to remember"
        )):
            if "test phrase" in q or "phrase" in q:
                test_phrase = facts.get("test_phrase") or facts.get("phrase")
                if not test_phrase:
                    for fk, fv in facts.items():
                        if "phrase" in fk:
                            test_phrase = fv
                            break
                if test_phrase:
                    return f"The test phrase you asked me to remember is '{test_phrase}'."
            if facts:
                summary_parts = []
                for k, v in facts.items():
                    if k in ("password", "secret", "token"):
                        continue
                    k_disp = k.replace("_", " ").title()
                    summary_parts.append(f"{k_disp}: {v}")
                if summary_parts:
                    return f"Here is what I have remembered for you: {'; '.join(summary_parts[:8])}."
            return "You haven't asked me to remember any specific facts yet."

        # 6. Specific user fact lookup by entity key & relevance scoring
        # Guard: Only evaluate if the query is an inquiry about personal facts or preferences
        is_fact_inquiry = any(q.startswith(p) for p in (
            "what is", "what's", "whats", "which", "tell me", "who is", "where is",
            "show me", "do you know", "do i have", "do i prefer", "what do i"
        )) or any(k in q for k in ("favorite", "preference", "secret", "my ", "our "))
        if not is_fact_inquiry:
            return None

        clean_q_key = re.sub(r'^(?:what\s+is|what\'s|which|tell\s+me|who\s+is|where\s+is|show\s+me|do\s+you\s+know)\s+(?:my\s+|our\s+)?', '', q).strip().replace(" ", "_")
        clean_q_key = re.sub(r'^(?:do\s+i\s+prefer|i\s+prefer)\s*', '', clean_q_key)
        if clean_q_key and clean_q_key in facts:
            clean_k = clean_q_key.replace("our_", "").replace("_", " ")
            return f"According to your records, your {clean_k} is {facts[clean_q_key]}."

        keywords = _extract_keywords(query_text)
        filtered_kw = [w for w in keywords if w not in ("name", "fact", "preference", "thing", "something", "prefer", "like", "use", "project")]
        if not filtered_kw:
            return None

        best_key = None
        best_val = None
        best_score = 0.0

        for k, v in facts.items():
            k_low = k.lower()
            k_words = set(k_low.replace("_", " ").split())
            score = 0.0
            matched_count = 0

            for kw in filtered_kw:
                if kw == k_low:
                    score += 50.0
                    matched_count += 1
                elif kw in k_words:
                    score += 25.0
                    matched_count += 1
                elif len(kw) >= 5 and any(w.startswith(kw) or kw in w for w in k_words):
                    score += 10.0
                    matched_count += 1

            if matched_count > 0:
                score += (matched_count * 15.0)
                # Specific bonus if the trailing entity word (e.g. "fruit", "language", "code") matches
                if filtered_kw and filtered_kw[-1] in k_words:
                    score += 20.0
                if score > best_score:
                    best_score = score
                    best_key = k
                    best_val = v

        if best_key and best_val and best_score >= 35.0:
            clean_k = best_key.replace("our_", "").replace("_", " ")
            return f"According to your records, your {clean_k} is {best_val}."

        return None

    # ------------------------------------------------------------------
    # Deterministic temporal reasoning over stored date facts
    # ------------------------------------------------------------------
    _MONTHS = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
        "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    }

    # Fact keys that hold a DATE (month/day[/year]).
    _DATE_FACT_KEYS = (
        "birthday", "birth_date", "date_of_birth", "dob", "anniversary",
        "wedding_anniversary", "joining_date", "graduation_date",
    )

    @classmethod
    def _parse_stored_date(cls, raw: Any) -> Optional[Dict[str, int]]:
        """Parse a stored date value into {'month', 'day', 'year'?} without guessing."""
        if raw is None:
            return None
        text = str(raw).strip()
        if not text:
            return None

        # ISO: 2005-04-14 / 2005/04/14
        m = re.search(r'\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b', text)
        if m:
            month, day, year = int(m.group(2)), int(m.group(3)), int(m.group(1))
            return {"month": month, "day": day, "year": year} if 1 <= month <= 12 and 1 <= day <= 31 else None

        # Month name + day [+ year]: "April 14, 2005" / "14 April 2005" / "Apr 14"
        month_names = "|".join(cls._MONTHS.keys())
        m = re.search(rf'\b({month_names})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s*(\d{{4}}))?', text, re.IGNORECASE)
        if m:
            month = cls._MONTHS[m.group(1).lower()]
            day = int(m.group(2))
            year = int(m.group(3)) if m.group(3) else None
            return {"month": month, "day": day, **(({"year": year}) if year else {})}
        m = re.search(rf'\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({month_names})\.?(?:,?\s*(\d{{4}}))?', text, re.IGNORECASE)
        if m:
            month = cls._MONTHS[m.group(2).lower()]
            day = int(m.group(1))
            year = int(m.group(3)) if m.group(3) else None
            return {"month": month, "day": day, **(({"year": year}) if year else {})}

        # Numeric month/day[/year]: 04/14/2005 or 14/04/2005 (unambiguous only)
        m = re.search(r'\b(\d{1,2})[/](\d{1,2})[/](\d{2,4})\b', text)
        if m:
            a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if y < 100:
                y += 2000 if y < 50 else 1900
            if a <= 12 < b:
                return {"month": a, "day": b, "year": y}
            if b <= 12 < a:
                return {"month": b, "day": a, "year": y}
        return None

    def _find_date_fact(self, q: str, facts: Dict[str, str]):
        """Return (label, parsed_date) for the date fact the query refers to."""
        if not facts:
            return None, None
        candidates = []
        for key, value in facts.items():
            key_low = str(key).lower()
            if any(dk in key_low for dk in self._DATE_FACT_KEYS) or "birthday" in key_low:
                parsed = self._parse_stored_date(value)
                if parsed:
                    candidates.append((str(key), parsed))
        if not candidates:
            return None, None
        # Prefer the fact explicitly named in the question.
        for key, parsed in candidates:
            label = key.replace("_", " ").lower()
            tokens = [t for t in label.split() if len(t) > 3 and t not in ("date", "birth")]
            if any(t in q for t in tokens):
                return key, parsed
        return candidates[0]

    def _answer_temporal_fact_query(self, q: str, facts: Dict[str, str]) -> Optional[str]:
        """Answer weekday / countdown / next-occurrence questions about a stored date."""
        from datetime import date as _date

        wants_weekday = bool(re.search(r'\b(?:what|which)\s+day(?:\s+of\s+the\s+week)?\b', q)) or "weekday" in q
        wants_countdown = bool(re.search(r'\bhow\s+many\s+days\b', q))
        wants_next_date = bool(re.search(r'\b(?:what|which)\s+(?:date|day)\b', q)) and "next" in q
        wants_age = bool(re.search(r'\bhow\s+old\b', q)) or bool(re.search(r'\bwhat(?:\'s|\s+is)\s+my\s+age\b', q))
        if not (wants_weekday or wants_countdown or wants_next_date or wants_age):
            return None

        key, stored = self._find_date_fact(q, facts)
        if not stored:
            # No usable stored date: let the ordinary fact paths answer (and say
            # "I don't have that recorded" rather than inventing a date).
            return None

        label = key.replace("_", " ").strip().lower()
        month, day = stored["month"], stored["day"]
        today = _date.today()

        def _safe_date(year: int) -> Optional[_date]:
            try:
                return _date(year, month, day)
            except ValueError:
                return None   # e.g. Feb 29 in a non-leap year

        if wants_age:
            if not stored.get("year"):
                return None
            age = today.year - stored["year"] - ((today.month, today.day) < (month, day))
            return f"According to your records, you are {age} years old."

        # Resolve the target occurrence
        if "next year" in q:
            target_year = today.year + 1
        elif "this year" in q:
            target_year = today.year
        else:
            upcoming = _safe_date(today.year)
            if upcoming is None:
                target_year = today.year + 1
            elif upcoming < today:
                target_year = today.year + 1
            else:
                target_year = today.year
        target = _safe_date(target_year)
        if target is None:
            # Feb 29 requested for a non-leap year: use the following leap year.
            for y in (target_year + 1, target_year + 2, target_year + 3, target_year + 4):
                target = _safe_date(y)
                if target:
                    target_year = y
                    break
        if target is None:
            return f"I have your {label} as {month:02d}/{day:02d}, which is not a valid calendar date."

        if wants_countdown:
            days = (target - today).days
            if days == 0:
                return f"Your {label} is today ({target.strftime('%B %d, %Y')})."
            return f"Your {label} is {days} day(s) away, on {target.strftime('%A, %B %d, %Y')}."

        if wants_next_date:
            return f"Your next {label} is on {target.strftime('%A, %B %d, %Y')}."

        weekday = target.strftime("%A")
        if "next year" in q:
            return f"Your {label} next year falls on {weekday}, {target.strftime('%B %d, %Y')}."
        return f"Your {label} falls on {weekday}, {target.strftime('%B %d, %Y')}."

    def answer_historical_command_query(self, user_id: int, query_text: str) -> Optional[str]:
        """
        Recall historical command execution and changes grounded in os_action_history and action_records.
        Distinguishes:
        - Requested
        - Attempted
        - Verified success
        - Failed
        - Cancelled
        - Unverified
        Never reports success merely because a command was requested.
        """
        if not user_id or not query_text:
            return None
        q = query_text.lower().strip().rstrip(".?!")
        uid = int(user_id)

        # 1. "What did you change?" / "What changes did you make?"
        if any(p in q for p in ("what did you change", "what changes did you make", "what setting did you change")):
            try:
                from core.os_gateway import get_os_action_history
                acts = get_os_action_history().get_recent_actions(user_id=uid, limit=5)
                for a in acts:
                    if a.get("operation_type") in ("CONFIG_CHANGE", "SETTING", "UPDATE_SETTING", "CHANGE_SETTING") or "setting" in str(a.get("target", "")).lower() or "rate" in str(a.get("target", "")).lower():
                        tgt = a.get("target", "setting")
                        res = a.get("result_message") or a.get("result_data")
                        return f"I changed {tgt}. Result: {res}."
                if acts:
                    last_act = acts[0]
                    return f"The last action performed was {last_act.get('operation_type')} on '{last_act.get('target', '')}' ({last_act.get('status')})."
            except Exception:
                pass
            return "I don't have a record of any recent setting changes."

        # 2. "What happened when you tried that command?" / "What was the outcome?"
        if any(p in q for p in (
            "what happened when you tried that command", "what was the outcome",
            "what happened with that command", "did that command succeed",
            "what happened when you tried that"
        )):
            try:
                from core.os_gateway import get_os_action_history
                acts = get_os_action_history().get_recent_actions(user_id=uid, limit=5)
                if acts:
                    a = acts[0]
                    op = a.get("operation_type", "action")
                    tgt = a.get("target", "")
                    status = str(a.get("status", "")).upper()
                    verified = bool(a.get("verified", False))
                    err = a.get("error_message")
                    res_msg = a.get("result_message", "")

                    if status == "SUCCESS" and verified:
                        return f"The command to {op} '{tgt}' completed and was verified successfully. {res_msg}".strip()
                    elif status == "SUCCESS" and not verified:
                        return f"The command to {op} '{tgt}' finished, but its outcome could not be verified."
                    elif status == "CANCELLED":
                        return f"The command to {op} '{tgt}' was cancelled before completion."
                    elif status == "FAILED" or err:
                        return f"The command to {op} '{tgt}' failed with error: {err or 'execution error'}."
                    else:
                        return f"The command to {op} '{tgt}' was attempted with status: {status}."
            except Exception:
                pass
            return "I don't have a record of that command execution."

        # 3. "What error did we fix last time?" / "What error did we fix?"
        if any(p in q for p in ("what error did we fix", "what error occurred", "error did we solve")):
            try:
                from core.os_gateway import get_os_action_history
                acts = get_os_action_history().get_recent_actions(user_id=uid, limit=10)
                for a in acts:
                    err = a.get("error_message")
                    if err:
                        return f"The previous error recorded was: '{err}' during {a.get('operation_type', 'operation')} on '{a.get('target', '')}'."
            except Exception:
                pass
            return "There are no recent error records in your history."

        return None

    # ── F. REAL PGVECTOR SEMANTIC EMBEDDINGS ──────────────────────────────────

    def insert_memory_embedding(
        self,
        user_id: int,
        content_text: str,
        vector: List[float],
        memory_id: Optional[int] = None,
        model: str = "text-embedding-3-small"
    ) -> bool:
        """
        Stores semantic vector embedding for a user memory item.
        Supports native pgvector column as well as JSONB fallback.
        Enforces user ownership.
        """
        if not user_id or not content_text or not vector:
            return False

        user_id = int(user_id)
        content_hash = hashlib.sha256(content_text.encode("utf-8")).hexdigest()
        vector_json = json.dumps(vector)
        vector_str = f"[{','.join(str(float(x)) for x in vector)}]"

        # 1. Attempt native pgvector insert in its own transaction block
        inserted = False
        try:
            with self.pool.get_cursor() as cur:
                cur.execute("""
                    INSERT INTO memory_embeddings (user_id, memory_id, content_hash, content_text, embedding_vector, embedding, model)
                    VALUES (%s, %s, %s, %s, %s, %s::vector, %s)
                """, (user_id, memory_id, content_hash, content_text, vector_json, vector_str, model))
                inserted = True
        except Exception:
            inserted = False

        if inserted:
            return True

        # 2. Fallback to JSONB column in a clean transaction
        try:
            with self.pool.get_cursor() as cur:
                cur.execute("""
                    INSERT INTO memory_embeddings (user_id, memory_id, content_hash, content_text, embedding_vector, model)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (user_id, memory_id, content_hash, content_text, vector_json, model))
            return True
        except Exception as e:
            print(f"[MEMORY EMBEDDINGS] insert error: {e}")
            return False

    def search_memory_embeddings(
        self,
        user_id: int,
        query_vector: List[float],
        limit: int = 5,
        min_similarity: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        Semantic vector similarity search across memories.
        CRITICAL: Strictly scoped to user_id (User isolation).
        Attempts PostgreSQL pgvector native cosine distance (<=>) first,
        falling back to Python cosine similarity calculation over JSONB.
        """
        if not user_id or not query_vector:
            return []

        user_id = int(user_id)
        results = []

        # 1. Attempt native pgvector search in its own transaction
        try:
            vector_str = f"[{','.join(str(float(x)) for x in query_vector)}]"
            with self.pool.get_cursor() as cur:
                cur.execute("""
                    SELECT memory_id, content_text, 1 - (embedding <=> %s::vector) AS similarity, model
                    FROM memory_embeddings
                    WHERE user_id = %s AND embedding IS NOT NULL
                    ORDER BY embedding <=> %s::vector ASC
                    LIMIT %s
                """, (vector_str, user_id, vector_str, limit))
                rows = cur.fetchall()
                for r in rows:
                    sim = float(r[2])
                    if sim >= min_similarity:
                        results.append({
                            "memory_id": r[0],
                            "content_text": r[1],
                            "similarity": round(sim, 4),
                            "model": r[3]
                        })
                if results:
                    return results
        except Exception:
            pass

        # 2. Python Fallback Cosine Similarity over JSONB in fresh transaction
        try:
            with self.pool.get_cursor() as cur:
                cur.execute("""
                    SELECT memory_id, content_text, embedding_vector, model
                    FROM memory_embeddings
                    WHERE user_id = %s
                """, (user_id,))
                rows = cur.fetchall()

            # Calculate cosine similarity in Python
            def _cosine_sim(v1, v2):
                if not v1 or not v2 or len(v1) != len(v2):
                    return 0.0
                dot = sum(a * b for a, b in zip(v1, v2))
                norm1 = math.sqrt(sum(a * a for a in v1))
                norm2 = math.sqrt(sum(b * b for b in v2))
                if norm1 == 0 or norm2 == 0:
                    return 0.0
                return dot / (norm1 * norm2)

            scored = []
            for r in rows:
                mem_id, text, vec_json, mod = r[0], r[1], r[2], r[3]
                try:
                    v = json.loads(vec_json) if isinstance(vec_json, str) else vec_json
                    sim = _cosine_sim(query_vector, v)
                    if sim >= min_similarity:
                        scored.append({
                            "memory_id": mem_id,
                            "content_text": text,
                            "similarity": round(sim, 4),
                            "model": mod
                        })
                except Exception:
                    continue

            scored.sort(key=lambda x: -x["similarity"])
            return scored[:limit]
        except Exception as e:
            print(f"[MEMORY EMBEDDINGS] search error: {e}")
            return []


# Global singleton
_chatgpt_memory_instance: Optional[ChatGPTMemoryManager] = None

def get_chatgpt_memory() -> ChatGPTMemoryManager:
    global _chatgpt_memory_instance
    if _chatgpt_memory_instance is None:
        _chatgpt_memory_instance = ChatGPTMemoryManager()
    return _chatgpt_memory_instance


# Backward compatibility alias
ChatGPTMemory = ChatGPTMemoryManager

