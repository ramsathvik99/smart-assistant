"""
extensions/memory_store.py
--------------------------
Persistent Memory Store Interface for Friday / Smart Assistant.
Provides high-level methods to:
- Store and update structured memory facts
- Retrieve relevant memories with category and status filtering
- Answer direct memory inquiries
- Forget or delete memory entries
- Automatically extract and persist facts from natural conversational utterances

Integrates directly with core.chatgpt_memory, core.fact_extractor, and PostgreSQL.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)


def store_fact(
    user_id: int,
    key: str,
    value: str,
    category: str = "general",
    confidence: float = 1.0,
    status: str = "confirmed",
    expiration_date: Optional[datetime] = None,
    source_ref: str = "",
) -> bool:
    """Store or update a structured fact in PostgreSQL with multi-user isolation."""
    if not user_id or not key:
        return False
    try:
        from core.chatgpt_memory import get_chatgpt_memory
        return get_chatgpt_memory().set_user_fact(
            user_id=int(user_id),
            key=key,
            value=value,
            confidence=confidence,
            source="memory_store",
            category=category,
            status=status,
            source_ref=source_ref,
            expiration_date=expiration_date,
        )
    except Exception as e:
        logger.error(f"[MEMORY_STORE] store_fact failed: {e}")
        return False


def retrieve_facts(
    user_id: int,
    query: str = "",
    category: Optional[str] = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """Retrieve relevant active facts for user_id with optional query and category filters."""
    if not user_id:
        return []
    try:
        from core.chatgpt_memory import get_chatgpt_memory
        mem_mgr = get_chatgpt_memory()
        return mem_mgr.retrieve_relevant_memories(
            user_id=int(user_id),
            query_text=query,
            limit=limit,
            category=category,
        )
    except Exception as e:
        logger.error(f"[MEMORY_STORE] retrieve_facts failed: {e}")
        return []


def recall_memory(user_id: int, query: str) -> Optional[str]:
    """Deterministically answer a direct memory inquiry from stored PostgreSQL facts."""
    if not user_id or not query:
        return None
    try:
        from core.chatgpt_memory import get_chatgpt_memory
        return get_chatgpt_memory().answer_historical_fact_query(int(user_id), query)
    except Exception as e:
        logger.error(f"[MEMORY_STORE] recall_memory failed: {e}")
        return None


def forget_fact(user_id: int, key: str) -> bool:
    """Delete a memory fact across PostgreSQL tables."""
    if not user_id or not key:
        return False
    try:
        from core.chatgpt_memory import get_chatgpt_memory
        return get_chatgpt_memory().delete_user_fact(int(user_id), key)
    except Exception as e:
        logger.error(f"[MEMORY_STORE] forget_fact failed: {e}")
        return False


def extract_and_store_from_text(user_id: int, text: str) -> List[Dict[str, Any]]:
    """Automatically extract candidate facts from natural language text and persist them."""
    if not user_id or not text:
        return []
    try:
        from core.chatgpt_memory import get_chatgpt_memory
        tuples = get_chatgpt_memory().extract_and_persist_facts(int(user_id), text)
        return [{"key": k, "value": v} for k, v in tuples]
    except Exception as e:
        logger.error(f"[MEMORY_STORE] extract_and_store_from_text failed: {e}")
        return []
