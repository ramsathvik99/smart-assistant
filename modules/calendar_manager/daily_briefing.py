"""
Daily Briefing Engine for Nova Smart Assistant.
Aggregates today's date, weather forecast, calendar events, reminders,
and system status into an executive daily morning/briefing report.
"""

import os
import logging
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def get_daily_briefing(user_id: Optional[int] = None, user_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Generate a complete, personalized daily briefing for the user.
    """
    now = datetime.now()
    date_str = now.strftime("%A, %B %d, %Y")
    time_str = now.strftime("%I:%M %p")
    hour = now.hour

    if hour < 12:
        greeting = "Good morning"
    elif hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    name_part = f", {user_name}" if user_name else ""
    sections = []
    speech_parts = []

    speech_parts.append(f"{greeting}{name_part}! Today is {date_str}, and the time is {time_str}.")

    # 1. Weather
    weather_summary = None
    try:
        from extensions.weather_engine import get_weather_for_query
        weather_summary = get_weather_for_query("weather today")
    except Exception:
        try:
            from legacy.skills_utilities import get_weather
            weather_summary = get_weather("weather")
        except Exception:
            pass

    if weather_summary and "unavailable" not in weather_summary.lower():
        speech_parts.append(f"Weather update: {weather_summary.strip()}")
        sections.append(("Weather", weather_summary.strip()))
    else:
        sections.append(("Weather", "Weather data is currently updating."))

    # 2. Calendar Events
    events_summary = "No scheduled calendar events for today."
    try:
        from modules.calendar_manager.calendar_storage import CalendarStorage
        storage = CalendarStorage()
        today_iso = now.strftime("%Y-%m-%d")
        uid = user_id if user_id is not None else 1
        events = storage.get_events(uid, today_iso)
        if events:
            ev_list = [f"• {e.get('title', 'Event')} at {e.get('time', 'all day')}" for e in events]
            events_summary = "\n".join(ev_list)
            speech_parts.append(f"You have {len(events)} event{'s' if len(events) > 1 else ''} scheduled today.")
        else:
            speech_parts.append("Your calendar is clear for today.")
    except Exception as e:
        logger.warning(f"[BRIEFING] Failed to load calendar events: {e}")

    sections.append(("Schedule", events_summary))

    # 3. Active Reminders
    reminders_summary = "No pending reminders."
    try:
        from extensions.database import Database
        db = Database()
        uid = user_id if user_id is not None else 1
        reminders = db.get_user_reminders(uid) if hasattr(db, "get_user_reminders") else []
        if reminders:
            reminders_summary = f"{len(reminders)} active reminder(s) queued."
            speech_parts.append(f"You have {len(reminders)} active reminder{'s' if len(reminders) > 1 else ''}.")
    except Exception as e:
        logger.debug(f"[BRIEFING] Reminders fetch skipped: {e}")

    sections.append(("Reminders", reminders_summary))

    # 4. System Status
    system_summary = ""
    try:
        from modules.system_controller.system_controller import get_battery_status, get_disk_space
        bat = get_battery_status()
        disk = get_disk_space("C:")
        
        stat_parts = []
        if bat.get("available") and bat.get("percent") is not None:
            plugged = "plugged in" if bat.get("charging") else "on battery"
            stat_parts.append(f"Battery: {bat['percent']}% ({plugged})")
        if disk.get("free_gb") is not None:
            stat_parts.append(f"Storage: {disk['free_gb']} GB free on drive C")
            
        if stat_parts:
            system_summary = " | ".join(stat_parts)
            sections.append(("System Status", system_summary))
    except Exception as e:
        logger.debug(f"[BRIEFING] System telemetry skipped: {e}")

    # Build full visual text
    visual_lines = [f"# Daily Briefing — {date_str}"]
    for heading, body in sections:
        visual_lines.append(f"### {heading}\n{body}")

    full_visual = "\n\n".join(visual_lines)
    full_speech = " ".join(speech_parts)

    return {
        "success": True,
        "date": date_str,
        "time": time_str,
        "visual_report": full_visual,
        "speech_text": full_speech,
        "message": full_visual
    }
