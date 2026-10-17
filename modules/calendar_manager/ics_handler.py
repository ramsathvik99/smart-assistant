"""
iCalendar (.ics) RFC 5545 Import and Export Handler
Supports generating standard .ics files from CalendarStorage events,
and importing external .ics events into user calendar storage.
"""

import re
import uuid
import logging
from datetime import datetime, date, time, timedelta, timezone
from typing import Dict, List, Optional, Any
from .calendar_storage import CalendarStorage

logger = logging.getLogger(__name__)


def _format_ics_datetime(dt: datetime) -> str:
    """Format datetime as iCalendar UTC string: YYYYMMDDTHHMMSSZ."""
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _format_ics_date(d: date) -> str:
    """Format date as iCalendar value: YYYYMMDD."""
    return d.strftime("%Y%m%d")


def _parse_ics_datetime(s: str) -> Optional[datetime]:
    """Parse iCalendar datetime string (UTC or local)."""
    if not s:
        return None
    s = s.strip()
    # Remove parameters like TZID=...:value
    if ":" in s:
        s = s.split(":")[-1]
    
    # 20261102T140000Z or 20261102T140000
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


class ICSHandler:
    """Handles RFC 5545 iCalendar import and export."""

    def __init__(self, storage: Optional[CalendarStorage] = None):
        self.storage = storage or CalendarStorage()

    def export_calendar_to_ics(self, user_id: int, start_date: Optional[str] = None, end_date: Optional[str] = None) -> str:
        """
        Export user's calendar events as a standard RFC 5545 .ics formatted string.
        """
        if not start_date or not end_date:
            now = datetime.now()
            start_date = (now - timedelta(days=90)).strftime("%Y-%m-%d")
            end_date = (now + timedelta(days=180)).strftime("%Y-%m-%d")

        events_map = self.storage.get_events_range(user_id, start_date, end_date)
        all_events = [ev for ev_list in events_map.values() for ev in ev_list]

        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Nova Assistant//Calendar Manager//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH"
        ]

        now_str = _format_ics_datetime(datetime.now(timezone.utc))

        seen_master_ids = set()
        for ev in all_events:
            # For recurring events, if master already exported with RRULE, skip expanded occurrences
            master_id = ev.get('master_id')
            if master_id and master_id in seen_master_ids:
                continue
            if master_id:
                seen_master_ids.add(master_id)

            uid = ev.get('id', str(uuid.uuid4()))
            title = ev.get('title', 'Untitled Event').replace("\n", " ")
            desc = (ev.get('description') or '').replace("\n", "\\n")
            loc = (ev.get('location') or '').replace("\n", " ")
            cat = ev.get('category') or 'General'
            start_dt = ev.get('start_datetime')
            end_dt = ev.get('end_datetime') or (start_dt + timedelta(hours=1))

            lines.append("BEGIN:VEVENT")
            lines.append(f"UID:{uid}")
            lines.append(f"DTSTAMP:{now_str}")
            if ev.get('is_all_day'):
                lines.append(f"DTSTART;VALUE=DATE:{_format_ics_date(start_dt.date())}")
                lines.append(f"DTEND;VALUE=DATE:{_format_ics_date((end_dt + timedelta(days=1)).date())}")
            else:
                lines.append(f"DTSTART:{_format_ics_datetime(start_dt)}")
                lines.append(f"DTEND:{_format_ics_datetime(end_dt)}")
            lines.append(f"SUMMARY:{title}")
            if desc:
                lines.append(f"DESCRIPTION:{desc}")
            if loc:
                lines.append(f"LOCATION:{loc}")
            if cat:
                lines.append(f"CATEGORIES:{cat}")
            lines.append("STATUS:CONFIRMED")
            lines.append("END:VEVENT")

        lines.append("END:VCALENDAR")
        lines.append("")
        return "\r\n".join(lines)

    def import_calendar_from_ics(self, user_id: int, ics_content_or_path: str) -> Dict[str, Any]:
        """
        Parse and import RFC 5545 iCalendar content into the user's database calendar.
        Returns summary dictionary with imported count and event IDs.
        """
        content = ics_content_or_path
        if len(content) < 500 and ("\n" not in content and "\r" not in content):
            # Likely a file path
            try:
                with open(content, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                logger.error(f"[ICSHandler] Could not read file {ics_content_or_path}: {e}")
                return {"success": False, "error": f"Could not read file: {e}", "imported_count": 0}

        # Unfold lines (RFC 5545 line folding starts with space or tab)
        content = re.sub(r'\r?\n[ \t]', '', content)
        raw_events = re.findall(r'BEGIN:VEVENT(.*?)END:VEVENT', content, re.DOTALL | re.IGNORECASE)

        imported_ids = []
        errors = []

        for raw_ev in raw_events:
            try:
                ev_data = self._parse_vevent_block(raw_ev)
                if ev_data and ev_data.get('title') and ev_data.get('date'):
                    ev_id = self.storage.add_event(user_id, ev_data)
                    imported_ids.append(ev_id)
            except Exception as e:
                errors.append(str(e))

        return {
            "success": len(imported_ids) > 0 or len(raw_events) == 0,
            "total_found": len(raw_events),
            "imported_count": len(imported_ids),
            "event_ids": imported_ids,
            "errors": errors
        }

    def _parse_vevent_block(self, raw_ev: str) -> Optional[Dict[str, Any]]:
        """Parse single VEVENT block into CalendarStorage event dict."""
        lines = [line.strip() for line in raw_ev.splitlines() if line.strip()]
        props: Dict[str, str] = {}
        for line in lines:
            if ":" in line:
                key_part, val = line.split(":", 1)
                prop_name = key_part.split(";")[0].upper()
                props[prop_name] = val.strip()

        title = props.get("SUMMARY", "Imported Event")
        desc = props.get("DESCRIPTION", "").replace("\\n", "\n")
        loc = props.get("LOCATION", "")
        cat = props.get("CATEGORIES", "General")

        dtstart_str = props.get("DTSTART")
        dtend_str = props.get("DTEND")

        start_dt = _parse_ics_datetime(dtstart_str)
        if not start_dt:
            return None

        end_dt = _parse_ics_datetime(dtend_str)
        is_all_day = len(dtstart_str.split(":")[-1]) == 8 if dtstart_str else False

        date_str = start_dt.strftime("%Y-%m-%d")
        time_str = start_dt.strftime("%H:%M") if not is_all_day else None
        
        duration_minutes = 60
        if end_dt:
            duration_minutes = max(15, int((end_dt - start_dt).total_seconds() / 60))

        result = {
            "title": title,
            "date": date_str,
            "time": time_str,
            "duration_minutes": duration_minutes,
            "description": desc,
            "location": loc,
            "category": cat,
            "is_all_day": is_all_day
        }

        # Check for RRULE
        rrule_str = props.get("RRULE")
        if rrule_str:
            rrule_dict = self._parse_rrule_string(rrule_str)
            if rrule_dict:
                result["recurrence"] = rrule_dict

        return result

    @staticmethod
    def _parse_rrule_string(rrule: str) -> Optional[Dict[str, Any]]:
        """Parse RRULE string like FREQ=WEEKLY;INTERVAL=1;BYDAY=MO,WE into dict."""
        parts = rrule.split(";")
        rule: Dict[str, Any] = {}
        for p in parts:
            if "=" in p:
                k, v = p.split("=", 1)
                k = k.upper().strip()
                v = v.strip()
                if k == "FREQ":
                    rule["frequency"] = v.lower()
                elif k == "INTERVAL":
                    rule["interval"] = int(v)
                elif k == "BYDAY":
                    rule["days_of_week"] = v
                elif k == "UNTIL":
                    parsed_until = _parse_ics_datetime(v)
                    if parsed_until:
                        rule["end_date"] = parsed_until.strftime("%Y-%m-%d")
                elif k == "COUNT":
                    rule["count"] = int(v)
        return rule if "frequency" in rule else None
