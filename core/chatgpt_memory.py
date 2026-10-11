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
        "please", "give", "show", "know", "there", "their", "they", "from", "just"
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

    # ── A. USER FACTS (memory_facts) ──────────────────────────────────────────

    def set_user_fact(self, user_id: int, key: str, value: str, confidence: float = 1.0, source: str = "conversation") -> bool:
        """Upsert a declarative user fact."""
        if not user_id or not key or value is None:
            return False

        clean_key = key.strip().lower().replace(" ", "_")[:100]
        clean_val = str(value).strip()[:MAX_FACT_VALUE_LENGTH]
        user_id = int(user_id)

        try:
            with self.pool.get_cursor() as cur:
                # Check if fact already exists
                cur.execute("""
                    SELECT id FROM memory_facts WHERE user_id = %s AND fact_key = %s
                """, (user_id, clean_key))
                existing = cur.fetchone()

                if existing:
                    cur.execute("""
                        UPDATE memory_facts
                        SET fact_value = %s, confidence = %s, source = %s, last_accessed = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (clean_val, confidence, source, existing[0]))
                else:
                    cur.execute("""
                        INSERT INTO memory_facts (user_id, fact_key, fact_value, confidence, source, last_accessed)
                        VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    """, (user_id, clean_key, clean_val, confidence, source))
            return True
        except Exception as e:
            print(f"[MEMORY] set_user_fact error: {e}")
            return False

    def get_user_facts(self, user_id: int) -> Dict[str, str]:
        """Returns all facts for a user as a dict of {fact_key: fact_value}."""
        if not user_id:
            return {}
        try:
            with self.pool.get_cursor() as cur:
                cur.execute("""
                    SELECT fact_key, fact_value FROM memory_facts
                    WHERE user_id = %s ORDER BY last_accessed DESC
                """, (int(user_id),))
                return {r[0]: r[1] for r in cur.fetchall()}
        except Exception as e:
            print(f"[MEMORY] get_user_facts error: {e}")
            return {}

    def delete_user_fact(self, user_id: int, key: str) -> bool:
        """Delete a specific user fact."""
        if not user_id or not key:
            return False
        clean_key = key.strip().lower().replace(" ", "_")
        try:
            with self.pool.get_cursor() as cur:
                cur.execute("""
                    DELETE FROM memory_facts WHERE user_id = %s AND fact_key = %s RETURNING id
                """, (int(user_id), clean_key))
                return cur.fetchone() is not None
        except Exception as e:
            print(f"[MEMORY] delete_user_fact error: {e}")
            return False

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
        Also triggers async automatic fact extraction.
        """
        if not user_id or not user_input:
            return
        user_id = int(user_id)
        try:
            with self.pool.get_cursor() as cur:
                # 1. Insert into conversations
                cur.execute("""
                    INSERT INTO conversations (user_id, user_input, assistant_response, session_id)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id
                """, (user_id, user_input, assistant_response, session_id or "default"))
                conv_id = cur.fetchone()[0]

                # 2. Insert into messages for user and assistant
                cur.execute("""
                    INSERT INTO messages (user_id, conversation_id, role, content)
                    VALUES (%s, %s, 'user', %s), (%s, %s, 'assistant', %s)
                """, (user_id, conv_id, user_input, user_id, conv_id, assistant_response))

            # 3. Extract facts from dialogue
            self.extract_and_persist_facts(user_id, user_input)
        except Exception as e:
            print(f"[MEMORY] log_interaction error: {e}")

    def get_recent_conversation(self, user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Returns the most recent conversation turns for a user."""
        if not user_id:
            return []
        try:
            with self.pool.get_cursor() as cur:
                cur.execute("""
                    SELECT user_input, assistant_response, timestamp
                    FROM conversations
                    WHERE user_id = %s
                    ORDER BY id DESC
                    LIMIT %s
                """, (int(user_id), limit))
                rows = cur.fetchall()
                # Return in chronological order
                return [{
                    "user": r[0],
                    "assistant": r[1],
                    "timestamp": str(r[2])
                } for r in reversed(rows)]
        except Exception as e:
            print(f"[MEMORY] get_recent_conversation error: {e}")
            return []

    # ── D. AUTOMATED FACT & PREFERENCE EXTRACTION ─────────────────────────────

    def extract_and_persist_facts(self, user_id: int, text: str) -> List[Tuple[str, str]]:
        """
        Regex and heuristic fact extraction for fast, zero-latency declarative fact learning.
        Extracts patterns such as:
        - "my name is X", "i live in X", "my job is X", "i work at X", "my wife is X", "my dog is X"
        - "remember that X is Y", "my favorite X is Y", "i prefer X"
        """
        if not text or not user_id:
            return []

        extracted = []
        t = text.strip()

        patterns = [
            (r"\bmy name is ([a-zA-Z\s]+)", "name"),
            (r"\bi live in ([a-zA-Z\s,]+)", "city"),
            (r"\bi am from ([a-zA-Z\s,]+)", "hometown"),
            (r"\bi work at ([a-zA-Z0-9\s]+)", "workplace"),
            (r"\bi work as an? ([a-zA-Z\s]+)", "occupation"),
            (r"\bmy job is ([a-zA-Z\s]+)", "job"),
            (r"\bmy favorite (\w+) is ([a-zA-Z0-9\s]+)", "favorite_{0}"),
            (r"\bmy favourite (\w+) is ([a-zA-Z0-9\s]+)", "favorite_{0}"),
            (r"\bmy dog(?:'s name)? is ([a-zA-Z\s]+)", "dog_name"),
            (r"\bmy cat(?:'s name)? is ([a-zA-Z\s]+)", "cat_name"),
            (r"\bmy wife(?:'s name)? is ([a-zA-Z\s]+)", "wife_name"),
            (r"\bmy husband(?:'s name)? is ([a-zA-Z\s]+)", "husband_name"),
            (r"\bmy sister(?:'s name)? is ([a-zA-Z\s]+)", "sister_name"),
            (r"\bmy brother(?:'s name)? is ([a-zA-Z\s]+)", "brother_name"),
            (r"\bmy birthday is ([a-zA-Z0-9\s,]+)", "birthday"),
            (r"\bremember that ([a-zA-Z0-9\s_]+) is ([a-zA-Z0-9\s_]+)", "{0}"),
            (r"\bremember my (\w+) is ([a-zA-Z0-9\s_]+)", "{0}"),
            (r"\bi prefer ([a-zA-Z0-9\s]+)", "preference"),
        ]

        for pat, key_template in patterns:
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
                    self.set_user_fact(user_id, key, val, confidence=0.95, source="dialogue_extraction")
                    extracted.append((key, val))

        return extracted

    # ── E. CONTEXT RETRIEVAL & PROMPT BUDGETING ───────────────────────────────

    def retrieve_relevant_memories(self, user_id: int, query_text: str, limit: int = 6) -> List[Dict[str, Any]]:
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
        for key, val in all_facts.items():
            base_score = _compute_relevance_score(keywords, key, val)
            
            # If specific keywords are queried, require relevance
            if keywords:
                if base_score > 0:
                    if key in ["name", "city", "job", "occupation", "language"]:
                        base_score += 5.0
                    scored_items.append({
                        "key": key,
                        "value": val,
                        "score": base_score
                    })
            else:
                # Generic retrieval: include all facts
                score = base_score
                if key in ["name", "city", "job", "occupation", "language"]:
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
