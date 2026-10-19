"""
extensions/user_profile.py
--------------------------
User Profile Management Layer for Friday / Smart Assistant.
Provides clean, tenant-isolated access to structured user profile attributes:
- Identity (name, preferred_name, city, etc.)
- Education (student status, institution, major, academic year)
- Employment & Activities (occupation, workplace, placement cell, roles)
- Preferences (response_style, tone, hobbies, favorites)

Backed authoritatively by PostgreSQL memory_facts and user_memory.
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def get_user_profile(user_id: int) -> Dict[str, Any]:
    """
    Load the consolidated, tenant-isolated profile for user_id.
    Merges identity, education, employment, and preferences.
    """
    if not user_id:
        return {}
    try:
        from core.chatgpt_memory import get_chatgpt_memory
        mem_mgr = get_chatgpt_memory()
        facts = mem_mgr.get_user_facts(int(user_id))
        prefs = mem_mgr.get_preferences(int(user_id))

        profile = {
            "user_id": int(user_id),
            "name": facts.get("preferred_name") or facts.get("name") or "",
            "preferred_name": facts.get("preferred_name") or facts.get("name") or "",
            "education": facts.get("education") or facts.get("student_status") or "",
            "student_status": facts.get("student_status") or facts.get("education") or "",
            "institution": facts.get("institution") or facts.get("university") or facts.get("college") or "",
            "university": facts.get("university") or facts.get("institution") or "",
            "major": facts.get("major") or "",
            "activity": facts.get("activity") or facts.get("role") or "",
            "role": facts.get("role") or facts.get("activity") or "",
            "city": facts.get("city") or "",
            "occupation": facts.get("occupation") or facts.get("job") or "",
            "response_style": facts.get("response_style") or prefs.get("response_style") or "normal",
            "all_facts": facts,
            "preferences": prefs,
        }
        return profile
    except Exception as e:
        logger.error(f"[USER_PROFILE] Failed to load profile for user {user_id}: {e}")
        return {}


def get_profile_field(user_id: int, field_name: str, default: Any = None) -> Any:
    """Get a specific field from the user profile."""
    prof = get_user_profile(user_id)
    return prof.get(field_name, default)


def get_user_name(user_id: int) -> Optional[str]:
    """Return preferred name or registered name for user."""
    prof = get_user_profile(user_id)
    return prof.get("preferred_name") or prof.get("name") or None


def get_user_institution(user_id: int) -> Optional[str]:
    """Return university or institution for user."""
    prof = get_user_profile(user_id)
    return prof.get("institution") or prof.get("university") or None


def get_user_education(user_id: int) -> Optional[str]:
    """Return education or academic status for user."""
    prof = get_user_profile(user_id)
    return prof.get("education") or prof.get("student_status") or None


def update_profile_field(
    user_id: int,
    field_name: str,
    value: Any,
    category: str = "general",
    confidence: float = 1.0
) -> bool:
    """Update a specific field in the user profile backed by PostgreSQL."""
    if not user_id or not field_name:
        return False
    try:
        from core.chatgpt_memory import get_chatgpt_memory
        mem_mgr = get_chatgpt_memory()
        return mem_mgr.set_user_fact(
            user_id=int(user_id),
            key=field_name,
            value=str(value),
            confidence=confidence,
            source="user_profile",
            category=category,
        )
    except Exception as e:
        logger.error(f"[USER_PROFILE] Failed to update field {field_name} for user {user_id}: {e}")
        return False
