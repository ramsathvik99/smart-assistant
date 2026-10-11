"""
Canonical Temporal Context Provider
Centralized, immutable authority for runtime date, time, and temporal metadata across the assistant.
Ensures RAG, LLM, and execution modules consume identical current clock state.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict


def get_canonical_temporal_context() -> Dict[str, Any]:
    """
    Returns normalized temporal context derived strictly from the canonical system clock.
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


def format_temporal_prompt_block() -> str:
    """
    Formats an authoritative context block to inject into LLM prompts.
    Forces grounding to the canonical runtime clock and blocks hallucinations of past years.
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
