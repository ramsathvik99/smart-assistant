"""
Canonical Temporal Context Provider
Centralized, immutable authority for runtime date, time, and temporal metadata across the assistant.
Ensures RAG, LLM, and execution modules consume identical current clock state.

Timezone support (new, backward-compatible additions):
- get_canonical_temporal_context()         -- original, preserved unchanged
- format_temporal_prompt_block()           -- original, preserved unchanged
- get_user_local_date(timezone_str)        -- user's actual local date for milestone comparisons
- get_user_local_now(timezone_str)         -- user's actual local datetime
- get_canonical_temporal_context_for_user  -- timezone-aware context block per user
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone, date
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def get_canonical_temporal_context() -> Dict[str, Any]:
    """
    Returns normalized temporal context derived strictly from the canonical system clock.
    Preserved unchanged for backward compatibility.
    """
    now = datetime.now()
    tz_name = time.tzname[time.daylight] if (time.daylight and time.tzname) else (time.tzname[0] if time.tzname else "Local")

    return {
        "current_datetime": now.isoformat(),
        "current_date": now.strftime("%Y-%m-%d"),
        "current_date_formatted": now.strftime("%B %d, %Y"),
        "current_time": now.strftime("%I:%M %p").lstrip("0"),
        "timezone": tz_name,
        "current_day": now.strftime("%A"),
        "current_year": str(now.year),
        "current_month": now.strftime("%B"),
        "current_timestamp": now.timestamp(),
        "iso_timestamp": now.isoformat(),
    }


def get_user_local_date(timezone_str: str = "UTC") -> date:
    """
    Returns the current calendar date in the specified IANA timezone string.
    Falls back to the system local date if the timezone is invalid or
    neither zoneinfo nor pytz is available.

    Used by milestone engine for correct per-user birthday/deadline comparisons.
    """
    if not timezone_str or timezone_str in ("UTC", "utc"):
        return datetime.now(tz=timezone.utc).date()

    # Try zoneinfo (Python 3.9+ stdlib)
    try:
        from zoneinfo import ZoneInfo  # type: ignore
        return datetime.now(tz=ZoneInfo(timezone_str)).date()
    except Exception:
        pass

    # Try pytz as fallback
    try:
        import pytz  # type: ignore
        tz = pytz.timezone(timezone_str)
        return datetime.now(tz=tz).date()
    except Exception:
        pass

    logger.debug("[TEMPORAL] Could not resolve timezone '%s'; using system local date.", timezone_str)
    return datetime.now().date()


def get_user_local_now(timezone_str: str = "UTC") -> datetime:
    """
    Returns the current datetime in the specified IANA timezone.
    Falls back to system local time if the timezone cannot be resolved.
    """
    if not timezone_str or timezone_str in ("UTC", "utc"):
        return datetime.now(tz=timezone.utc)

    try:
        from zoneinfo import ZoneInfo  # type: ignore
        return datetime.now(tz=ZoneInfo(timezone_str))
    except Exception:
        pass

    try:
        import pytz  # type: ignore
        tz = pytz.timezone(timezone_str)
        return datetime.now(tz=tz)
    except Exception:
        pass

    return datetime.now()


def get_canonical_temporal_context_for_user(user_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Returns a timezone-aware temporal context dict for a specific user.
    Loads the user's 'timezone' preference from ConfigurationService.
    Falls back to get_canonical_temporal_context() if user_id is None or
    the timezone preference is unset / invalid.
    """
    tz_str = "UTC"
    if user_id:
        try:
            from core.configuration_service import get_configuration_service
            cfg = get_configuration_service()
            tz_pref = cfg.get_preference(user_id, "timezone")
            if tz_pref:
                tz_str = str(tz_pref)
        except Exception:
            pass

    now_local = get_user_local_now(tz_str)
    return {
        "current_datetime": now_local.isoformat(),
        "current_date": now_local.strftime("%Y-%m-%d"),
        "current_date_formatted": now_local.strftime("%B %d, %Y"),
        "current_time": now_local.strftime("%I:%M %p").lstrip("0"),
        "timezone": tz_str,
        "current_day": now_local.strftime("%A"),
        "current_year": str(now_local.year),
        "current_month": now_local.strftime("%B"),
        "current_timestamp": now_local.timestamp(),
        "iso_timestamp": now_local.isoformat(),
        "user_id": user_id,
    }


def format_temporal_prompt_block() -> str:
    """
    Formats an authoritative context block to inject into LLM prompts.
    Forces grounding to the canonical runtime clock and blocks hallucinations of past years.
    Preserved unchanged for backward compatibility.
    """
    ctx = get_canonical_temporal_context()
    return (
        "=== CANONICAL RUNTIME TEMPORAL CONTEXT ===\n"
        f"Today's Date: {ctx['current_date_formatted']} ({ctx['current_date']})\n"
        f"Current Time: {ctx['current_time']} ({ctx['timezone']})\n"
        f"Day of the Week: {ctx['current_day']}\n"
        f"Current Year: {ctx['current_year']}\n"
        f"ISO Timestamp: {ctx['current_datetime']}\n"
        f"CRITICAL TEMPORAL RULE: The authoritative current date is {ctx['current_date_formatted']}. "
        "Do NOT invent, assume, or substitute a different date or year. Any questions asking about 'today', "
        f"'now', 'current', 'tonight', or 'this week' must strictly use {ctx['current_date_formatted']} as the present anchor."
    )
