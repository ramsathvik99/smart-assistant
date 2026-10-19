"""
Calendar Controller Layer
Orchestrates dynamic intent dispatch, conflict detection, free/busy discovery,
recurrence lifecycle, analytics, synchronization, and natural speech synthesis.
"""

import re
import difflib
import logging
import traceback
from datetime import datetime, date, time, timedelta
from typing import Dict, Any, List, Optional
from .calendar_storage import CalendarStorage
from .country_detector import get_user_country
from .intent_handler import extract_calendar_intent
from .special_days_service import get_special_days_service
from .intelligence_engine import explain_holiday_intelligence, plan_week_intelligence
from .ics_handler import ICSHandler
from .sync_adapters import calendar_sync_manager

logger = logging.getLogger(__name__)


def format_time_12hr(time_val: Optional[str]) -> str:
    """Format time string into user-friendly 12-hour format e.g. '3:00 PM'."""
    if not time_val:
        return ""
    t_str = str(time_val).strip()
    if re.search(r'\b[AP]M\b', t_str, re.I):
        return t_str
    try:
        parts = t_str.split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        ampm = "PM" if h >= 12 else "AM"
        h12 = h % 12
        if h12 == 0:
            h12 = 12
        return f"{h12}:{m:02d} {ampm}"
    except Exception:
        return t_str


class CalendarController:
    """
    Fully Dynamic Calendar Intelligence System.
    Reuses existing storage, PostgreSQL database, and scheduler.
    """
    def __init__(self, storage_path=None):
        self.storage = CalendarStorage(storage_path)
        self.ics_handler = ICSHandler(self.storage)
        self.logger = logging.getLogger(__name__)
        self._pending_conflicts: Dict[int, Dict[str, Any]] = {}
        self._last_event: Dict[int, Dict[str, Any]] = {}

    def get_pending_conflict(self, user_id: int) -> Optional[Dict[str, Any]]:
        return self._pending_conflicts.get(user_id)

    def set_pending_conflict(self, user_id: int, conflict_data: Dict[str, Any]):
        self._pending_conflicts[user_id] = conflict_data

    def clear_pending_conflict(self, user_id: int):
        self._pending_conflicts.pop(user_id, None)

    def get_last_event(self, user_id: int) -> Optional[Dict[str, Any]]:
        return self._last_event.get(user_id)

    def set_last_event(self, user_id: int, event_data: Dict[str, Any]):
        self._last_event[user_id] = event_data

    def check_event_conflicts(self, user_id: int, start_dt: datetime, end_dt: datetime,
                              exclude_event_id: Optional[str] = None,
                              buffer_minutes: int = 0) -> List[Dict[str, Any]]:
        """Check for existing events overlapping the interval for user isolation."""
        try:
            return self.storage.check_conflicts(
                user_id, start_dt, end_dt,
                exclude_event_id=exclude_event_id,
                buffer_minutes=buffer_minutes
            )
        except Exception as e:
            self.logger.warning(f"[CalendarController] Conflict check warning: {e}")
            return []

    def process_calendar_query(self, text: str, user_id: int = None) -> Dict[str, Any]:
        """Main entry point. Understand -> Analyze -> Compute -> Respond."""
        try:
            # 1. Resolve authenticated user
            if user_id is None:
                try:
                    from instance.config import settings
                    user_id = getattr(settings, "CURRENT_USER_ID", None) or settings.get_last_user()
                except Exception:
                    pass
            try:
                user_id = int(user_id) if user_id is not None else 0
            except (ValueError, TypeError):
                user_id = 0

            # 2. UNDERSTAND: Extract Dynamic Action Map
            data = extract_calendar_intent(text)
            
            action = data.get("action", "unknown")
            if isinstance(action, list): action = action[0] if action else "unknown"
            action = str(action).lower()
            
            subject = data.get("subject", "unknown")
            if isinstance(subject, list): subject = subject[0] if subject else "unknown"
            subject = str(subject).lower()
            
            entities = data.get("entities", {})
            temporal = data.get("temporal_context", {})
            
            # Resolve Country / Region
            loc_ent = entities.get("location")
            if loc_ent:
                loc_clean = str(loc_ent).upper().strip()
                if loc_clean in ("US", "USA", "UNITED STATES", "AMERICA"):
                    country = "US"
                elif loc_clean in ("RU", "RUSSIA"):
                    country = "RU"
                elif loc_clean in ("IN", "INDIA"):
                    country = "IN"
                elif loc_clean in ("GB", "UK", "UNITED KINGDOM", "BRITAIN"):
                    country = "GB"
                elif len(loc_clean) == 2:
                    country = loc_clean
                else:
                    country = get_user_country()
            else:
                country = get_user_country()
            service = get_special_days_service(region=country, user_id=user_id)
            
            # 3. Resolve Dates & Ranges
            now = datetime.now()
            target_start = temporal.get("normalized_date")
            duration = temporal.get("duration_days", 0)
            
            if target_start in [None, "null", "None"]: target_start = None
            if duration in [None, "null", "None"]: duration = 0
            else: 
                try: duration = int(duration)
                except Exception: duration = 0

            if not target_start or target_start == "DYNAMIC":
                rel = str(temporal.get("relative_date", "")).lower()
                if "today" in rel: target_start = now.strftime("%Y-%m-%d")
                elif "tomorrow" in rel: target_start = (now + timedelta(days=1)).strftime("%Y-%m-%d")
                elif "next week" in rel or "week" in rel: 
                    target_start = now.strftime("%Y-%m-%d")
                    duration = 7
                elif "this month" in rel or "month" in rel:
                    target_start = now.strftime("%Y-%m-%d")
                    duration = 30
                else:
                    target_start = now.strftime("%Y-%m-%d")

            start_dt = datetime.strptime(target_start, "%Y-%m-%d")
            target_end_spec = temporal.get("normalized_end_date") or temporal.get("end_date")
            if target_end_spec and target_end_spec not in [None, "null", "None"]:
                try:
                    datetime.strptime(target_end_spec, "%Y-%m-%d")
                    target_end = target_end_spec
                except Exception:
                    end_dt = start_dt + timedelta(days=max(0, duration - 1))
                    target_end = end_dt.strftime("%Y-%m-%d")
            else:
                end_dt = start_dt + timedelta(days=max(0, duration - 1))
                target_end = end_dt.strftime("%Y-%m-%d")

            results = {
                "success": True,
                "holidays": [],
                "personal_events": [],
                "explanation": None,
                "plan": None,
                "count": 0,
                "status": "success",
                "speech_response": "",
                "meta": {"start": target_start, "end": target_end, "country": country}
            }

            # ─────────────────────────────────────────────────────────────────
            # Clarification
            # ─────────────────────────────────────────────────────────────────
            if action == "clarification":
                results["status"] = "clarification"
                results["speech_response"] = data.get("message") or "Please specify the date and time for the calendar event."
                return results

            # ─────────────────────────────────────────────────────────────────
            # Next Appointment Query
            # ─────────────────────────────────────────────────────────────────
            elif action == "next":
                cat = entities.get("category")
                next_ev = self.storage.get_next_event(user_id, category=cat)
                if next_ev:
                    results["personal_events"] = [next_ev]
                    time_part = f" at {next_ev.get('time')}" if next_ev.get('time') else ""
                    loc_part = f" in {next_ev.get('location')}" if next_ev.get('location') else ""
                    results["speech_response"] = f"Your next appointment is '{next_ev.get('title')}' on {next_ev.get('date')}{time_part}{loc_part}."
                else:
                    results["personal_events"] = []
                    cat_note = f" in category '{cat}'" if cat else ""
                    results["speech_response"] = f"You have no upcoming appointments scheduled{cat_note}."

            # ─────────────────────────────────────────────────────────────────
            # Conflict Resolution Follow-up
            # ─────────────────────────────────────────────────────────────────
            elif action == "conflict_resolution":
                pending = self._pending_conflicts.get(user_id)
                if not pending:
                    results["status"] = "no_pending_conflict"
                    results["speech_response"] = "There is no pending calendar conflict to resolve."
                    return results

                resolution = entities.get("resolution", "unknown")
                pending_ev = dict(pending.get("event_data", {}))
                conflicting_ev = pending.get("conflicting_event", {})
                pending_action = pending.get("action", "add")

                if resolution == "keep_both" or any(w in text.lower() for w in ["keep both", "schedule anyway", "proceed anyway", "keep it"]):
                    if pending_action == "update":
                        target_id = pending.get("target_event_id")
                        updates = pending.get("updates", {})
                        success = self.storage.update_event(user_id, target_id, updates)
                        self._last_event[user_id] = {**pending_ev, "id": target_id}
                        self._pending_conflicts.pop(user_id, None)
                        results["status"] = "Event updated"
                        results["speech_response"] = f"Updated '{pending_ev.get('title')}' alongside '{conflicting_ev.get('title')}' as requested."
                        return results
                    else:
                        event_id = self.storage.add_event(user_id, pending_ev)
                        self._last_event[user_id] = {**pending_ev, "id": event_id}
                        self._pending_conflicts.pop(user_id, None)
                        results["status"] = "Event added successfully (overlap preserved)"
                        results["event_id"] = event_id
                        time_part = f" at {pending_ev.get('time')}" if pending_ev.get('time') else ""
                        results["speech_response"] = f"Scheduled '{pending_ev['title']}' for {pending_ev['date']}{time_part} alongside '{conflicting_ev.get('title', 'existing event')}'."
                        return results

                elif resolution == "cancel" or any(w in text.lower() for w in ["cancel", "don't schedule", "drop", "nevermind", "never mind"]):
                    title = pending_ev.get("title", "event")
                    self._pending_conflicts.pop(user_id, None)
                    results["status"] = "Cancelled"
                    results["speech_response"] = f"Cancelled the request to schedule '{title}'."
                    return results

                elif resolution == "change_time" or entities.get("start_time") or entities.get("time"):
                    new_time = entities.get("start_time") or entities.get("time")
                    if not new_time:
                        from .intent_handler import CalendarIntentHandler
                        new_time = CalendarIntentHandler._parse_time_str(text)
                    if not new_time:
                        results["status"] = "clarification"
                        results["speech_response"] = "What time would you like to move the new meeting to?"
                        return results

                    pending_ev["time"] = new_time
                    t_obj = CalendarStorage._parse_time(new_time)
                    s_dt = datetime.combine(datetime.strptime(pending_ev["date"], "%Y-%m-%d").date(), t_obj)
                    e_dt = s_dt + timedelta(minutes=pending_ev.get("duration_minutes", 60))
                    exclude_id = pending.get("target_event_id") if pending_action == "update" else None
                    new_conflicts = self.check_event_conflicts(user_id, s_dt, e_dt, exclude_event_id=exclude_id)
                    if new_conflicts:
                        c = new_conflicts[0]
                        pending["conflicting_event"] = c
                        pending["all_conflicts"] = new_conflicts
                        pending["event_data"] = pending_ev
                        time_phrase = f"from {c.get('time')} to {c.get('end_time')}" if (c.get('time') and c.get('end_time')) else f"at {c.get('time')}"
                        results["status"] = "conflict_detected"
                        results["conflict"] = True
                        results["speech_response"] = (
                            f"You also have {c.get('title')} {time_phrase} on {pending_ev['date']}. "
                            f"The meeting at {new_time} would still overlap. "
                            f"Would you like to keep both events, pick another time, change its date, or cancel?"
                        )
                        return results
                    else:
                        if pending_action == "update":
                            target_id = pending.get("target_event_id")
                            updates = dict(pending.get("updates", {}))
                            updates["time"] = new_time
                            self.storage.update_event(user_id, target_id, updates)
                            self._last_event[user_id] = {**pending_ev, "id": target_id}
                            self._pending_conflicts.pop(user_id, None)
                            results["status"] = "Event updated"
                            results["speech_response"] = f"Rescheduled '{pending_ev['title']}' to {new_time} on {pending_ev['date']}."
                            return results
                        else:
                            event_id = self.storage.add_event(user_id, pending_ev)
                            self._last_event[user_id] = {**pending_ev, "id": event_id}
                            self._pending_conflicts.pop(user_id, None)
                            results["status"] = "Event added successfully"
                            results["event_id"] = event_id
                            results["speech_response"] = f"Scheduled '{pending_ev['title']}' for {pending_ev['date']} at {new_time}."
                            return results

                elif resolution == "change_date" or entities.get("new_date") or temporal.get("normalized_date"):
                    new_date = entities.get("new_date") or temporal.get("normalized_date")
                    if not new_date:
                        results["status"] = "clarification"
                        results["speech_response"] = "What date would you like to move the new meeting to?"
                        return results

                    pending_ev["date"] = new_date
                    t_obj = CalendarStorage._parse_time(pending_ev.get("time", "09:00"))
                    s_dt = datetime.combine(datetime.strptime(new_date, "%Y-%m-%d").date(), t_obj)
                    e_dt = s_dt + timedelta(minutes=pending_ev.get("duration_minutes", 60))
                    exclude_id = pending.get("target_event_id") if pending_action == "update" else None
                    new_conflicts = self.check_event_conflicts(user_id, s_dt, e_dt, exclude_event_id=exclude_id)
                    if new_conflicts:
                        c = new_conflicts[0]
                        pending["conflicting_event"] = c
                        pending["all_conflicts"] = new_conflicts
                        pending["event_data"] = pending_ev
                        results["status"] = "conflict_detected"
                        results["conflict"] = True
                        results["speech_response"] = (
                            f"You have a conflict on {new_date} with {c.get('title')} at {c.get('time')}. "
                            f"Would you like to keep both, choose another date or time, or cancel?"
                        )
                        return results
                    else:
                        if pending_action == "update":
                            target_id = pending.get("target_event_id")
                            updates = dict(pending.get("updates", {}))
                            updates["date"] = new_date
                            self.storage.update_event(user_id, target_id, updates)
                            self._last_event[user_id] = {**pending_ev, "id": target_id}
                            self._pending_conflicts.pop(user_id, None)
                            results["status"] = "Event updated"
                            results["speech_response"] = f"Moved '{pending_ev['title']}' to {new_date}."
                            return results
                        else:
                            event_id = self.storage.add_event(user_id, pending_ev)
                            self._last_event[user_id] = {**pending_ev, "id": event_id}
                            self._pending_conflicts.pop(user_id, None)
                            results["status"] = "Event added successfully"
                            results["event_id"] = event_id
                            results["speech_response"] = f"Scheduled '{pending_ev['title']}' for {new_date} at {pending_ev['time']}."
                            return results

                elif resolution == "change_duration" or entities.get("duration_minutes"):
                    new_dur = entities.get("duration_minutes") or 30
                    pending_ev["duration_minutes"] = new_dur
                    t_obj = CalendarStorage._parse_time(pending_ev.get("time", "09:00"))
                    s_dt = datetime.combine(datetime.strptime(pending_ev["date"], "%Y-%m-%d").date(), t_obj)
                    e_dt = s_dt + timedelta(minutes=new_dur)
                    exclude_id = pending.get("target_event_id") if pending_action == "update" else None
                    new_conflicts = self.check_event_conflicts(user_id, s_dt, e_dt, exclude_event_id=exclude_id)
                    if new_conflicts:
                        results["status"] = "conflict_detected"
                        results["conflict"] = True
                        results["speech_response"] = f"Even with {new_dur} minutes, '{pending_ev['title']}' still overlaps with '{new_conflicts[0].get('title')}'. Would you like to keep both or choose another time?"
                        return results
                    else:
                        if pending_action == "update":
                            target_id = pending.get("target_event_id")
                            updates = dict(pending.get("updates", {}))
                            updates["duration_minutes"] = new_dur
                            self.storage.update_event(user_id, target_id, updates)
                            self._last_event[user_id] = {**pending_ev, "id": target_id}
                            self._pending_conflicts.pop(user_id, None)
                            results["status"] = "Event updated"
                            results["speech_response"] = f"Updated duration of '{pending_ev['title']}' to {new_dur} minutes."
                            return results
                        else:
                            event_id = self.storage.add_event(user_id, pending_ev)
                            self._last_event[user_id] = {**pending_ev, "id": event_id}
                            self._pending_conflicts.pop(user_id, None)
                            results["status"] = "Event added successfully"
                            results["event_id"] = event_id
                            results["speech_response"] = f"Scheduled '{pending_ev['title']}' for {pending_ev['date']} at {pending_ev['time']} ({new_dur} minutes)."
                            return results

                elif resolution == "reschedule_existing":
                    c_title = conflicting_ev.get("title", "existing event")
                    results["status"] = "clarification"
                    results["speech_response"] = f"To reschedule '{c_title}', what new date or time would you like to move it to?"
                    return results

                else:
                    results["status"] = "clarification"
                    results["speech_response"] = "Would you like to keep both events, move the new meeting to another time, change its date, or cancel the new request?"
                    return results

            # ─────────────────────────────────────────────────────────────────
            # Check Public Holiday / Working Day Status
            # ─────────────────────────────────────────────────────────────────
            elif action == "check_holiday":
                t_dt = datetime.strptime(target_start, "%Y-%m-%d")
                weekday_name = t_dt.strftime("%A")
                is_weekend = t_dt.weekday() >= 5
                date_label = "today" if target_start == now.strftime("%Y-%m-%d") else ("tomorrow" if target_start == (now + timedelta(days=1)).strftime("%Y-%m-%d") else f"{weekday_name} ({target_start})")
                is_public_q = bool(entities.get("is_public_holiday_query"))
                check_work_q = bool(entities.get("check_working_day"))
                inquire_name = bool(entities.get("inquire_name"))
                country_name = "India" if country == "IN" else ("the United States" if country == "US" else ("Russia" if country == "RU" else country))

                # Weekday ambiguity check (e.g. "Is Monday a public holiday?" when today is Monday)
                if entities.get("is_ambiguous_weekday"):
                    results["status"] = "clarification"
                    results["speech_response"] = f"Did you mean today ({weekday_name}, {target_start}) or next {weekday_name}?"
                    return results

                try:
                    h = service.get_special_day(target_start)
                except Exception as ex:
                    self.logger.warning(f"[CalendarController] Holiday service error: {ex}")
                    results["status"] = "service_unavailable"
                    results["speech_response"] = f"Holiday verification is currently unavailable for {country_name}. Unable to confirm holiday status at this time."
                    return results

                if h:
                    h_name = h.get("name", "Holiday")
                    h_type = h.get("type", "Holiday")
                    results["holidays"] = [h]
                    h_type_low = str(h_type).lower()
                    is_official_public = any(p in h_type_low for p in ("public holiday", "gazetted national holiday", "federal holiday")) and not any(p in h_type_low for p in ("observance", "optional", "restricted"))
                    results["is_public_holiday"] = is_official_public
                    results["is_holiday"] = True

                    if is_official_public:
                        if check_work_q:
                            results["speech_response"] = f"No, {date_label} is not a regular working day; it is an official public holiday in {country_name}: {h_name}."
                        else:
                            results["speech_response"] = f"Yes, {date_label} is an official public holiday: {h_name}."
                    elif inquire_name:
                        results["speech_response"] = f"Today is observed as {h_name} ({h_type}), but it is not an official public holiday."
                    elif is_public_q:
                        weekend_note = f" (falling on a weekend, {weekday_name})" if is_weekend else ""
                        results["speech_response"] = f"No, {date_label} is not an official public holiday. It is observed as {h_name} ({h_type}){weekend_note}, so it is a regular working day for most offices and services."
                    elif check_work_q:
                        if is_weekend:
                            results["speech_response"] = f"{date_label.capitalize()} is observed as {h_name} ({h_type}), but it is not an official public holiday. Since it falls on a weekend ({weekday_name}), it is not a regular working day."
                        else:
                            results["speech_response"] = f"No, {date_label} is not an official public holiday. It is observed as {h_name} ({h_type}), so it is a regular working day for most offices and services."
                    else:
                        weekend_note = f" on {weekday_name}" if is_weekend else ""
                        results["speech_response"] = f"{date_label.capitalize()} is observed as {h_name} ({h_type}){weekend_note}, but it is not an official gazetted public holiday."
                else:
                    results["is_public_holiday"] = False
                    results["is_holiday"] = False
                    if inquire_name:
                        results["speech_response"] = f"There are no official public holidays or special observances for {date_label} in {country_name}."
                    elif is_weekend:
                        results["speech_response"] = f"No, {date_label} is not a public holiday; it is a regular weekend ({weekday_name})."
                    else:
                        results["speech_response"] = f"No, {date_label} is not a public holiday; it is a regular working day ({weekday_name})."

            # ─────────────────────────────────────────────────────────────────
            # View Holidays in Range
            # ─────────────────────────────────────────────────────────────────
            elif action == "view_holidays":
                try:
                    h_list = service.get_special_days_in_range(target_start, target_end, region=country)
                except Exception as ex:
                    self.logger.warning(f"[CalendarController] Range holidays error: {ex}")
                    h_list = []

                results["holidays"] = h_list
                country_name = "India" if country == "IN" else ("the United States" if country == "US" else ("Russia" if country == "RU" else country))
                range_label = f"from {target_start} to {target_end}" if target_start != target_end else f"on {target_start}"
                if not h_list:
                    results["speech_response"] = f"There are no public holidays or observances scheduled in {country_name} {range_label}."
                else:
                    pub_holidays = [
                        h for h in h_list 
                        if any(p in str(h.get('type', '')).lower() for p in ("public", "gazetted national", "federal")) 
                        and not any(p in str(h.get('type', '')).lower() for p in ("observance", "optional", "restricted"))
                    ]
                    observances = [h for h in h_list if h not in pub_holidays]
                    
                    parts = []
                    if pub_holidays:
                        pub_strs = [f"{h['name']} ({h['date']})" for h in pub_holidays]
                        parts.append(f"Public Holidays: {', '.join(pub_strs)}")
                    if observances:
                        obs_strs = [f"{h['name']} ({h['date']}, {h.get('type', 'Observance')})" for h in observances]
                        parts.append(f"Cultural Observances: {', '.join(obs_strs)}")
                        
                    results["speech_response"] = f"Holidays in {country_name} {range_label}: " + "; ".join(parts) + "."

            # ─────────────────────────────────────────────────────────────────
            # Next Public Holiday Query
            # ─────────────────────────────────────────────────────────────────
            elif action == "next_holiday":
                h = service.get_next_holiday(now.strftime("%Y-%m-%d"), country=country)
                if h:
                    country_name = "India" if country == "IN" else ("the United States" if country == "US" else ("Russia" if country == "RU" else country))
                    results["holidays"] = [h]
                    results["speech_response"] = f"The next public holiday in {country_name} is {h['name']} on {h['date']}."
                else:
                    results["speech_response"] = f"No upcoming public holidays found for {country}."

            # ─────────────────────────────────────────────────────────────────
            # Free Slots Discovery
            # ─────────────────────────────────────────────────────────────────
            elif action == "free_slots":
                slot_dur = entities.get("duration_minutes") or 30
                free_slots = self.storage.find_free_slots(user_id, target_start, slot_duration_minutes=slot_dur)
                pref_time = entities.get("preferred_time")
                date_display = "today" if target_start == now.strftime("%Y-%m-%d") else ("tomorrow" if target_start == (now + timedelta(days=1)).strftime("%Y-%m-%d") else f"on {target_start}")

                if free_slots:
                    slot_strs = [f"{s['start']} to {s['end']}" for s in free_slots[:4]]
                    resp = f"You have free time {date_display}: {', '.join(slot_strs)}."
                    if pref_time:
                        alt = self.storage.suggest_alternative_slot(user_id, target_start, preferred_time=pref_time, duration_minutes=slot_dur)
                        if alt:
                            resp += f" The best available slot near {pref_time} is from {alt['start']} to {alt['end']}."
                    results["speech_response"] = resp
                    results["free_slots"] = free_slots
                else:
                    alt = self.storage.suggest_alternative_slot(user_id, target_start, preferred_time=pref_time, duration_minutes=slot_dur)
                    if alt and alt.get('date'):
                        results["speech_response"] = f"You have no open {slot_dur}-minute slots {date_display}. The earliest available slot is on {alt['date']} from {alt['start']} to {alt['end']}."
                    else:
                        results["speech_response"] = f"Your schedule is completely booked {date_display}."

            # ─────────────────────────────────────────────────────────────────
            # Busy Time Query
            # ─────────────────────────────────────────────────────────────────
            elif action == "busy_time":
                day_events = self.storage.get_events(user_id, target_start)
                date_display = "today" if target_start == now.strftime("%Y-%m-%d") else ("tomorrow" if target_start == (now + timedelta(days=1)).strftime("%Y-%m-%d") else f"on {target_start}")
                timed_events = [e for e in day_events if not e.get('is_all_day')]
                if timed_events:
                    busy_parts = [f"'{e['title']}' from {e['time']} to {e.get('end_time') or 'conclusion'}" for e in timed_events]
                    results["speech_response"] = f"You are busy {date_display} with: {', '.join(busy_parts)}."
                elif day_events:
                    all_day_titles = [f"'{e['title']}'" for e in day_events]
                    results["speech_response"] = f"You have all-day events {date_display}: {', '.join(all_day_titles)}."
                else:
                    results["speech_response"] = f"You have no meetings scheduled {date_display}; your calendar is completely free."

            # ─────────────────────────────────────────────────────────────────
            # Calendar Analytics
            # ─────────────────────────────────────────────────────────────────
            elif action == "analytics":
                analytics = self.storage.get_calendar_analytics(user_id, target_start, target_end)
                results["analytics"] = analytics
                total_m = analytics["total_meetings"]
                total_h = analytics["total_meeting_hours"]
                util = analytics["utilization_percent"]
                avg = analytics["average_meeting_minutes"]
                conflicts = analytics["conflicts_detected"]
                results["speech_response"] = (
                    f"Calendar analytics from {target_start} to {target_end}: "
                    f"You have {total_m} meetings totaling {total_h} hours. "
                    f"Schedule utilization is {util}%, with an average meeting length of {avg} minutes. "
                    f"{'No schedule conflicts detected.' if conflicts == 0 else f'Detected {conflicts} schedule conflict(s).'}"
                )

            # ─────────────────────────────────────────────────────────────────
            # Event Search
            # ─────────────────────────────────────────────────────────────────
            elif action == "search":
                q = entities.get("query", "").strip()
                matches = self.storage.search_events(user_id, q)
                results["personal_events"] = matches
                if matches:
                    items = [f"'{m['title']}' on {m['date']}" + (f" at {m['time']}" if m.get('time') else "") for m in matches[:4]]
                    results["speech_response"] = f"Found {len(matches)} event(s) matching '{q}': {', '.join(items)}."
                else:
                    results["speech_response"] = f"I couldn't find any calendar events matching '{q}'."

            # ─────────────────────────────────────────────────────────────────
            # Meeting Notes, Agendas, Checklists
            # ─────────────────────────────────────────────────────────────────
            elif action == "add_note":
                title = entities.get("event_title")
                notes = entities.get("notes", "")
                cands = self.storage.find_events_by_title(user_id, title) if title else []
                if not cands:
                    results["speech_response"] = f"I couldn't find a meeting matching '{title}' to add notes to."
                else:
                    target_ev = cands[0]
                    self.storage.add_meeting_notes(user_id, target_ev["id"], notes)
                    results["speech_response"] = f"Added notes to '{target_ev['title']}'."

            elif action == "add_agenda":
                title = entities.get("event_title")
                agenda_items = entities.get("agenda", [])
                cands = self.storage.find_events_by_title(user_id, title) if title else []
                if not cands:
                    results["speech_response"] = f"I couldn't find a meeting matching '{title}' to add an agenda to."
                else:
                    target_ev = cands[0]
                    self.storage.add_meeting_agenda(user_id, target_ev["id"], agenda_items)
                    results["speech_response"] = f"Added {len(agenda_items)} agenda item(s) to '{target_ev['title']}'."

            # ─────────────────────────────────────────────────────────────────
            # iCalendar Export / Import
            # ─────────────────────────────────────────────────────────────────
            elif action == "ics_export":
                ics_str = self.ics_handler.export_calendar_to_ics(user_id, target_start, target_end)
                results["ics_data"] = ics_str
                try:
                    from core.semantic_file_naming import get_semantic_file_naming_service
                    namer = get_semantic_file_naming_service()
                    ics_path, ics_name = namer.resolve_output_path(
                        task_description=f"export calendar {text or 'events'}",
                        artifact_type="calendar",
                        extension=".ics",
                    )
                    with open(ics_path, "w", encoding="utf-8") as f:
                        f.write(ics_str)
                    results["exported_filepath"] = ics_path
                    results["speech_response"] = f"Your calendar events from {target_start} to {target_end} have been exported to {ics_name} in RFC 5545 iCalendar format."
                except Exception as ex:
                    self.logger.warning(f"Error saving ICS export to disk: {ex}")
                    results["speech_response"] = f"Your calendar events from {target_start} to {target_end} have been exported in RFC 5545 iCalendar format."

            elif action == "ics_import":
                src = entities.get("source", "")
                imp_res = self.ics_handler.import_calendar_from_ics(user_id, src)
                results["import_result"] = imp_res
                if imp_res.get("success"):
                    results["speech_response"] = f"Successfully imported {imp_res.get('imported_count', 0)} event(s) into your calendar."
                else:
                    results["speech_response"] = f"Could not import iCalendar events: {imp_res.get('error', 'invalid file or format')}."

            # ─────────────────────────────────────────────────────────────────
            # External Synchronization
            # ─────────────────────────────────────────────────────────────────
            elif action == "sync":
                prov = entities.get("provider")
                sync_out = calendar_sync_manager.sync(user_id, provider=prov)
                results["sync_result"] = sync_out
                results["speech_response"] = sync_out.get("message", "Calendar sync finished.")

            # ─────────────────────────────────────────────────────────────────
            # Snooze Event Reminder
            # ─────────────────────────────────────────────────────────────────
            elif action == "snooze":
                s_mins = entities.get("snooze_minutes", 10)
                next_ev = self.storage.get_next_event(user_id)
                if next_ev:
                    self.storage.snooze_event_reminder(user_id, next_ev["id"], snooze_minutes=s_mins)
                    results["speech_response"] = f"Snoozed reminder for '{next_ev['title']}' by {s_mins} minutes."
                else:
                    results["speech_response"] = f"No active upcoming appointment to snooze."

            # ─────────────────────────────────────────────────────────────────
            # View / Agenda
            # ─────────────────────────────────────────────────────────────────
            elif action == "view":
                cat = entities.get("category")
                if subject == "festival_name" or entities.get("holiday_name"):
                    h_name = entities.get("holiday_name") or entities.get("festival_name")
                    results["holidays"] = service.get_holiday_by_name(h_name)
                    if results["holidays"]:
                        h = results["holidays"][0]
                        results["speech_response"] = f"{h.get('name', h_name)} is on {h.get('date')}."
                    else:
                        results["speech_response"] = f"I couldn't find a holiday matching '{h_name}'."
                else:
                    # Range View
                    results["holidays"] = service.get_special_days_in_range(target_start, target_end)
                    results["personal_events"] = self.storage.get_events_range(user_id, target_start, target_end, category=cat)
                    
                    total_events = sum(len(evs) for evs in results["personal_events"].values()) if isinstance(results["personal_events"], dict) else len(results["personal_events"])
                    is_meeting_query = any(w in text.lower() for w in ["meeting", "meetings", "appointment", "appointments", "event", "events", "agenda"])
                    speech_parts = []
                    date_range_str = f"from {target_start} to {target_end}" if target_start != target_end else f"on {target_start}"
                    cat_str = f" in '{cat}'" if cat else ""

                    if total_events > 0:
                        event_names = []
                        if isinstance(results["personal_events"], dict):
                            for d, ev_list in sorted(results["personal_events"].items()):
                                for ev in ev_list:
                                    t12 = format_time_12hr(ev.get('time'))
                                    time_str = f" at {t12}" if t12 else " (all day)"
                                    loc_str = f" ({ev['location']})" if ev.get('location') else ""
                                    dur_str = f" [{ev['duration_minutes']}m]" if ev.get('duration_minutes') and not ev.get('is_all_day') else ""
                                    if target_start != target_end:
                                        event_names.append(f"'{ev['title']}' on {d}{time_str}{loc_str}{dur_str}")
                                    else:
                                        event_names.append(f"'{ev['title']}'{time_str}{loc_str}{dur_str}")
                        elif isinstance(results["personal_events"], list):
                            for ev in results["personal_events"]:
                                t12 = format_time_12hr(ev.get('time'))
                                time_str = f" at {t12}" if t12 else " (all day)"
                                event_names.append(f"'{ev['title']}'{time_str}")
                        speech_parts.append(f"You have {total_events} event(s){cat_str} {date_range_str}: {', '.join(event_names[:5])}")
                    else:
                        if is_meeting_query:
                            speech_parts.append(f"You don't have any events{cat_str} scheduled {date_range_str}")
                        else:
                            speech_parts.append(f"You have no scheduled personal events{cat_str} {date_range_str}")

                    if results["holidays"] and not any(w in text.lower() for w in ["meeting", "meetings", "appointment", "appointments", "agenda", "events", "event"]):
                        h_names = [h.get("name", "Holiday") for h in results["holidays"][:2]]
                        speech_parts.append(f"Holidays: {', '.join(h_names)}")

                    results["speech_response"] = ". ".join(speech_parts) + "."

            # ─────────────────────────────────────────────────────────────────
            # Add / Schedule Event
            # ─────────────────────────────────────────────────────────────────
            elif action == "add":
                title = entities.get("event_title", "Untitled Event")
                event_time = entities.get("start_time")
                duration_minutes = entities.get("duration_minutes") or 60
                location = entities.get("location")
                category = entities.get("category", "General")
                recurrence = entities.get("recurrence")
                reminder_minutes = entities.get("reminder_minutes")
                ref_event_name = entities.get("reference_event")
                has_explicit_date = bool(temporal.get("has_explicit_date"))

                # Resolve relative time reference e.g. "at the same time as project review"
                if ref_event_name:
                    ref_candidates = self.storage.find_events_by_title(user_id, ref_event_name)
                    if not ref_candidates:
                        results["status"] = "clarification"
                        results["speech_response"] = f"I couldn't find an event matching '{ref_event_name}' to determine the time. What time would you like to schedule '{title}'?"
                        return results
                    elif len(ref_candidates) > 1:
                        matches_str = ", ".join([f"'{c['title']}' on {c['date']} at {c.get('time') or 'all day'}" for c in ref_candidates[:3]])
                        results["status"] = "clarification"
                        results["speech_response"] = f"Multiple events match '{ref_event_name}': {matches_str}. Which one do you mean?"
                        return results
                    else:
                        ref_ev = ref_candidates[0]
                        if not ref_ev.get("time"):
                            results["status"] = "clarification"
                            results["speech_response"] = f"'{ref_ev['title']}' is an all-day event without a specific time. What time would you like to schedule '{title}'?"
                            return results
                        event_time = ref_ev["time"]
                        if not has_explicit_date:
                            target_start = ref_ev["date"]
                            target_end = ref_ev["date"]
                
                # Check if event is in the past
                now = datetime.now()
                today_str = str(now.date())
                roll_forward_note = ""
                if target_start < today_str and not recurrence:
                    results["status"] = "error"
                    results["error_type"] = "temporal_failure"
                    results["speech_response"] = f"Cannot schedule '{title}' on {target_start} because that date has already passed."
                    return results

                if target_start == today_str and event_time:
                    t_obj = CalendarStorage._parse_time(event_time)
                    if t_obj:
                        event_dt = datetime.combine(now.date(), t_obj)
                        if event_dt < now:
                            if recurrence:
                                target_start = str((now + timedelta(days=1)).date())
                                roll_forward_note = " (starting tomorrow since today's time has passed)"
                            else:
                                results["status"] = "error"
                                results["error_type"] = "temporal_failure"
                                results["speech_response"] = f"Cannot schedule '{title}' because {event_time} has already passed today."
                                return results

                # Conflict detection with explicit user prompt
                allow_overlap = bool(
                    "anyway" in text.lower() or "keep both" in text.lower() or "despite" in text.lower()
                )
                conflict_note = ""
                if event_time and not recurrence:
                    t_obj = CalendarStorage._parse_time(event_time)
                    if t_obj:
                        s_dt = datetime.combine(datetime.strptime(target_start, "%Y-%m-%d").date(), t_obj)
                        e_dt = s_dt + timedelta(minutes=duration_minutes)
                        conflicts = self.check_event_conflicts(user_id, s_dt, e_dt)
                        if conflicts:
                            c = conflicts[0]
                            c_title = c.get("title", "Existing event")
                            c_time = c.get("time", "")
                            c_end = c.get("end_time") or ""
                            tz_name = self.storage.timezone_str

                            if not allow_overlap:
                                date_phrase = "tomorrow" if target_start == (now + timedelta(days=1)).strftime("%Y-%m-%d") else ("today" if target_start == now.strftime("%Y-%m-%d") else f"on {target_start}")
                                time_phrase = f"from {c_time} to {c_end}" if (c_time and c_end) else (f"at {c_time}" if c_time else "")

                                event_data = {
                                    "title": title,
                                    "date": target_start,
                                    "time": event_time,
                                    "duration_minutes": duration_minutes,
                                    "location": location,
                                    "category": category,
                                    "recurrence": recurrence,
                                    "reminder_minutes": reminder_minutes,
                                    "description": f"Added via assistant: {text}"
                                }

                                self._pending_conflicts[user_id] = {
                                    "action": "add",
                                    "event_data": event_data,
                                    "conflicting_event": c,
                                    "all_conflicts": conflicts,
                                    "target_start": target_start,
                                    "event_time": event_time,
                                    "duration_minutes": duration_minutes,
                                    "timezone": tz_name,
                                    "created_at": datetime.now()
                                }

                                results["status"] = "conflict_detected"
                                results["conflict"] = True
                                results["conflicting_event"] = c
                                results["pending_event"] = event_data
                                results["speech_response"] = (
                                    f"You already have {c_title} {time_phrase} {date_phrase}. "
                                    f"The new {title} would overlap. "
                                    f"Would you like to keep both events, move the new meeting to another time, change its date, or cancel the new request?"
                                )
                                return results
                            else:
                                conflict_note = f" Note: this overlaps with '{c_title}' as requested."

                is_all_day = bool(entities.get("is_all_day")) or (event_time is None)
                attendees = entities.get("attendees") or []
                explicit_desc = entities.get("description")
                final_desc = explicit_desc if explicit_desc else f"Added via assistant: {text}"
                metadata = {"attendees": attendees} if attendees else {}

                event_data = {
                    "title": title,
                    "date": target_start,
                    "time": event_time,
                    "duration_minutes": None if is_all_day else duration_minutes,
                    "is_all_day": is_all_day,
                    "location": location,
                    "category": category,
                    "recurrence": recurrence,
                    "reminder_minutes": reminder_minutes,
                    "description": final_desc,
                    "metadata": metadata
                }
                event_id = self.storage.add_event(user_id, event_data)
                self._last_event[user_id] = {**event_data, "id": event_id}
                
                time_str = f" at {event_time}" if event_time else (" (all day)" if is_all_day else "")
                loc_str = f" in {location}" if location else ""
                att_str = f" with {', '.join(attendees)}" if attendees else ""
                dur_str = f" for {duration_minutes} minutes" if duration_minutes and duration_minutes != 60 and event_time and not is_all_day else ""
                rec_str = f" (recurring {recurrence['frequency']})" if recurrence else ""
                
                results["status"] = "Event added successfully" if not conflict_note else "Event added successfully (overlap preserved)"
                results["event_id"] = event_id
                results["speech_response"] = f"Added '{title}' to your calendar for {target_start}{time_str}{dur_str}{loc_str}{att_str}{rec_str}{roll_forward_note}.{conflict_note}"

            # ─────────────────────────────────────────────────────────────────
            # Update / Reschedule / Rename
            # ─────────────────────────────────────────────────────────────────
            elif action == "update":
                title = entities.get("event_title")
                new_title = entities.get("new_title")
                start_time = entities.get("start_time")
                new_date = entities.get("new_date")
                duration_minutes = entities.get("duration_minutes")
                duration_delta = entities.get("duration_delta")
                location = entities.get("location")
                category = entities.get("category")
                
                # Only use temporal normalized_date if the query explicitly specified a date
                has_explicit_date = bool(temporal.get("has_explicit_date")) or any(
                    w in text.lower() for w in ["tomorrow", "today", "yesterday", "october", "november", "december", "january", "february", "march", "april", "may", "june", "july", "august", "september"]
                ) or bool(re.search(r'\b\d{4}-\d{2}-\d{2}\b', text))
                if not new_date and has_explicit_date and temporal.get("normalized_date"):
                    new_date = temporal.get("normalized_date")

                clean_title = re.sub(r'^(?:the\s+|my\s+)?(?:calendar\s+)?', '', title, flags=re.IGNORECASE).strip() if title else ""
                candidates = []
                is_pronoun_or_generic = not clean_title or clean_title.lower() in ["it", "that", "the meeting", "that meeting", "the event", "meeting", "event"]
                
                if not is_pronoun_or_generic:
                    candidates = self.storage.find_events_by_title(user_id, clean_title or title)
                else:
                    last_ev = self._last_event.get(user_id)
                    if last_ev:
                        candidates = [last_ev]
                    else:
                        next_ev = self.storage.get_next_event(user_id)
                        if next_ev:
                            candidates = [next_ev]

                if not candidates and (clean_title or title) and not is_pronoun_or_generic:
                    # Check fuzzy match across upcoming events
                    all_evs = self.storage.get_events_range(
                        user_id,
                        (now - timedelta(days=14)).strftime("%Y-%m-%d"),
                        (now + timedelta(days=60)).strftime("%Y-%m-%d")
                    )
                    flattened = []
                    if isinstance(all_evs, dict):
                        for dl in all_evs.values(): flattened.extend(dl)
                    elif isinstance(all_evs, list):
                        flattened = all_evs

                    best_match = None
                    best_ratio = 0.0
                    for ev in flattened:
                        ratio = difflib.SequenceMatcher(None, (clean_title or title).lower(), ev['title'].lower()).ratio()
                        if ratio > best_ratio:
                            best_ratio = ratio
                            best_match = ev

                    if best_match and best_ratio >= 0.75:
                        candidates = [best_match]

                if not candidates:
                    results["status"] = "Event not found"
                    results["speech_response"] = f"I couldn't find an event matching '{title or 'the specified criteria'}' to update."
                elif len(candidates) > 1:
                    matches_str = ", ".join([f"'{c['title']}' on {c['date']} at {c.get('time') or 'all day'}" for c in candidates[:3]])
                    results["status"] = "clarification"
                    results["speech_response"] = f"Multiple events match '{title}': {matches_str}. Which one would you like to update?"
                else:
                    target_ev = candidates[0]
                    updates = {}
                    final_date = new_date or target_ev["date"]
                    final_time = start_time or target_ev.get("time")
                    current_dur = target_ev.get("duration_minutes", 60)
                    
                    if duration_delta:
                        final_dur = max(5, current_dur + duration_delta)
                        updates["duration_minutes"] = final_dur
                    elif duration_minutes:
                        final_dur = duration_minutes
                        updates["duration_minutes"] = duration_minutes
                    else:
                        final_dur = current_dur

                    # Conflict check when time, date, or duration is updated
                    allow_overlap = bool("anyway" in text.lower() or "keep both" in text.lower())
                    if (start_time or new_date or duration_minutes or duration_delta) and final_time:
                        t_obj = CalendarStorage._parse_time(final_time)
                        if t_obj:
                            s_dt = datetime.combine(datetime.strptime(final_date, "%Y-%m-%d").date(), t_obj)
                            e_dt = s_dt + timedelta(minutes=final_dur)
                            conflicts = self.check_event_conflicts(user_id, s_dt, e_dt, exclude_event_id=target_ev["id"])
                            if conflicts and not allow_overlap:
                                c = conflicts[0]
                                c_title = c.get("title", "Existing event")
                                c_time = c.get("time", "")
                                c_end = c.get("end_time") or ""
                                time_phrase = f"from {c_time} to {c_end}" if (c_time and c_end) else f"at {c_time}"

                                if start_time: updates["time"] = start_time
                                if new_date: updates["date"] = new_date
                                if new_title: updates["title"] = new_title
                                if location: updates["location"] = location
                                if category: updates["category"] = category

                                self._pending_conflicts[user_id] = {
                                    "action": "update",
                                    "target_event_id": target_ev["id"],
                                    "updates": updates,
                                    "event_data": {**target_ev, **updates},
                                    "conflicting_event": c,
                                    "all_conflicts": conflicts,
                                    "target_start": final_date,
                                    "event_time": final_time,
                                    "duration_minutes": final_dur,
                                    "timezone": self.storage.timezone_str,
                                    "created_at": datetime.now()
                                }

                                results["status"] = "conflict_detected"
                                results["conflict"] = True
                                results["conflicting_event"] = c
                                results["speech_response"] = (
                                    f"You already have {c_title} {time_phrase} on {final_date}. "
                                    f"Rescheduling '{target_ev['title']}' would overlap. "
                                    f"Would you like to keep both events, move to another time, change its date, or cancel the change?"
                                )
                                return results

                    if start_time: updates["time"] = start_time
                    if new_date: updates["date"] = new_date
                    if new_title: updates["title"] = new_title
                    if location: updates["location"] = location
                    if category: updates["category"] = category

                    scope = entities.get("scope")
                    if scope == "occurrence" and target_ev.get("is_recurring"):
                        updates["occurrence_date"] = target_ev.get("date")

                    success = self.storage.update_event(user_id, target_ev["id"], updates)
                    if success:
                        self._last_event[user_id] = {**target_ev, **updates}
                        results["status"] = "Event updated"
                        if scope == "occurrence" and target_ev.get("is_recurring"):
                            results["speech_response"] = f"Updated this occurrence of '{target_ev['title']}' on {target_ev.get('date')}."
                        elif duration_delta:
                            dir_str = "longer" if duration_delta > 0 else "shorter"
                            results["speech_response"] = f"Made '{target_ev['title']}' {abs(duration_delta)} minutes {dir_str} (now {final_dur} minutes)."
                        elif new_title and not start_time and not new_date:
                            results["speech_response"] = f"Renamed '{target_ev['title']}' to '{new_title}'."
                        elif new_date and start_time:
                            results["speech_response"] = f"Moved '{target_ev['title']}' to {new_date} at {start_time}."
                        elif new_date:
                            results["speech_response"] = f"Moved '{target_ev['title']}' to {new_date}."
                        elif start_time:
                            results["speech_response"] = f"Changed the time of '{target_ev['title']}' to {start_time} on {target_ev['date']}."
                        elif duration_minutes:
                            results["speech_response"] = f"Changed the duration of '{target_ev['title']}' to {duration_minutes} minutes."
                        else:
                            results["speech_response"] = f"Updated '{target_ev['title']}'."
                    else:
                        results["status"] = "Update failed"
                        results["speech_response"] = f"Failed to update '{target_ev['title']}' in the database."

            # ─────────────────────────────────────────────────────────────────
            # Delete / Cancel
            # ─────────────────────────────────────────────────────────────────
            elif action == "delete":
                title = entities.get("event_title")
                scope = entities.get("scope", "series")
                has_explicit_date = bool(temporal.get("has_explicit_date")) or ("tomorrow" in text.lower() or "today" in text.lower())
                search_date = target_start if has_explicit_date else None

                clean_title = re.sub(r'^(?:the\s+|my\s+)?(?:calendar\s+)?', '', title, flags=re.IGNORECASE).strip(" '\". ,") if title else ""
                
                # Check if cancelling a pending conflict
                if clean_title and clean_title.lower() in ["change", "the change", "request", "the request", "new request", "it", "that"] and self._pending_conflicts.get(user_id):
                    pending = self._pending_conflicts.pop(user_id, None)
                    results["status"] = "Cancelled"
                    p_title = pending.get("event_data", {}).get("title", "event")
                    results["speech_response"] = f"Cancelled the requested change to '{p_title}'."
                    return results

                is_pronoun_or_generic = not clean_title or clean_title.lower() in [
                    "it", "that", "the meeting", "that meeting", "the event", "that event",
                    "meeting", "appointment", "event", "my meeting", "the meeting", "my appointment",
                    "all meetings", "one", "the one", "the one at", "one at", ""
                ]

                candidates = []
                if not is_pronoun_or_generic:
                    candidates = self.storage.find_events_by_title(user_id, clean_title, event_date=search_date)
                    if not candidates and not search_date:
                        candidates = self.storage.find_events_by_title(user_id, clean_title)
                else:
                    last_ev = self._last_event.get(user_id)
                    if last_ev:
                        candidates = [last_ev]
                    elif search_date:
                        candidates = self.storage.get_events(user_id, search_date)
                    else:
                        next_ev = self.storage.get_next_event(user_id)
                        if next_ev:
                            candidates = [next_ev]
                    
                    if not candidates:
                        # Check fuzzy match against events to avoid silently deleting or failing
                        all_evs = self.storage.get_events(user_id, search_date) if search_date else self.storage.get_events_range(
                            user_id, (now - timedelta(days=7)).strftime("%Y-%m-%d"), (now + timedelta(days=30)).strftime("%Y-%m-%d")
                        )
                        flattened = []
                        if isinstance(all_evs, dict):
                            for dl in all_evs.values(): flattened.extend(dl)
                        elif isinstance(all_evs, list):
                            flattened = all_evs

                        best_match = None
                        best_ratio = 0.0
                        for ev in flattened:
                            ratio = difflib.SequenceMatcher(None, clean_title.lower(), ev['title'].lower()).ratio()
                            if ratio > best_ratio:
                                best_ratio = ratio
                                best_match = ev

                        if best_match and best_ratio >= 0.75:
                            results["status"] = "confirmation_required"
                            time_part = f" at {best_match['time']}" if best_match.get('time') else ""
                            results["speech_response"] = f"Did you mean to cancel '{best_match['title']}' on {best_match['date']}{time_part}? Please confirm."
                            return results
                        else:
                            date_str = f" on {search_date}" if search_date else ""
                            results["status"] = "Event not found"
                            results["speech_response"] = f"I couldn't find an event matching '{title}'{date_str} to cancel."
                            return results

                if not candidates:
                    date_str = f" on {search_date}" if search_date else ""
                    results["status"] = "Event not found"
                    results["speech_response"] = f"No matching events found{date_str} to cancel."
                elif len(candidates) > 1:
                    if entities.get("filter_time"):
                        f_time = entities.get("filter_time")
                        t_cand = CalendarStorage._parse_time(f_time)
                        if t_cand:
                            matched = [c for c in candidates if CalendarStorage._parse_time(c.get("time")) == t_cand]
                            if len(matched) == 1:
                                candidates = matched

                    if len(candidates) > 1:
                        matches_str = ", ".join([f"'{c['title']}' on {c['date']} at {c.get('time') or 'all day'}" for c in candidates[:3]])
                        results["status"] = "clarification"
                        results["speech_response"] = f"Multiple events match your request: {matches_str}. Which one would you like to cancel?"
                        return results

                if candidates:
                    target_ev = candidates[0]
                    # Occurrence vs series
                    if scope == "occurrence" and target_ev.get("is_recurring"):
                        success = self.storage.delete_occurrence(user_id, target_ev.get("master_id") or target_ev["id"], target_ev["date"])
                        results["speech_response"] = f"Cancelled this occurrence of '{target_ev['title']}' on {target_ev['date']}."
                    else:
                        success = self.storage.delete_event(user_id, target_ev["id"])
                        time_part = f" at {target_ev['time']}" if target_ev.get('time') else ""
                        results["speech_response"] = f"Cancelled '{target_ev['title']}' scheduled for {target_ev['date']}{time_part}."
                    
                    if user_id in self._last_event and self._last_event[user_id].get("id") == target_ev["id"]:
                        self._last_event.pop(user_id, None)
                    
                    results["status"] = "Event cancelled" if success else "Delete failed"

            # ─────────────────────────────────────────────────────────────────
            # Explain / Holiday / Plan / Count
            # ─────────────────────────────────────────────────────────────────
            elif action == "explain":
                h_name = entities.get("holiday_name") or entities.get("festival_name")
                target_date = entities.get("target_date")
                if not h_name or target_date == "today":
                    h = service.get_special_day(target_start)
                    if h:
                        h_name = h.get("name")
                        h_desc = h.get("description")
                        results["explanation"] = h_desc
                        results["speech_response"] = f"Today is observed as {h_name}: {h_desc}."
                    else:
                        results["speech_response"] = "There is no special holiday or cultural observance recorded for today."
                else:
                    results["explanation"] = explain_holiday_intelligence(h_name, country)
                    results["speech_response"] = str(results["explanation"])
                    
            elif action == "plan":
                results["plan"] = plan_week_intelligence(country, user_id=user_id)
                results["speech_response"] = str(results["plan"])
                
            elif action == "count":
                year = entities.get("year") or now.year
                try:
                    year = int(year)
                except Exception:
                    year = now.year
                c_count, h_list = service.get_holidays_count(year, country=country)
                country_name = "India" if country == "IN" else ("the United States" if country == "US" else ("Russia" if country == "RU" else country))
                is_rem = bool(entities.get("is_remaining"))
                if is_rem and year == now.year:
                    today_iso = now.strftime("%Y-%m-%d")
                    rem_holidays = [h for h in h_list if h['date'] >= today_iso]
                    c_count = len(rem_holidays)
                    h_list = rem_holidays
                    results["count"] = c_count
                    results["holidays"] = h_list
                    sample_names = ", ".join([h["name"] for h in h_list[:4]]) if h_list else "None"
                    results["speech_response"] = f"There are {c_count} official public holiday(s) remaining in {country_name} in {year}" + (f", including {sample_names}." if h_list else ".")
                else:
                    results["count"] = c_count
                    results["holidays"] = h_list
                    sample_names = ", ".join([h["name"] for h in h_list[:4]]) if h_list else "None"
                    results["speech_response"] = f"There are {c_count} official public holidays in {country_name} in {year}, including {sample_names}."
            if not results.get("speech_response"):
                results["speech_response"] = "I checked your calendar, but there are no matching events or details for that request."
            return results

        except Exception as e:
            self.logger.error(f"[CalendarController] Error: {e}")
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e),
                "speech_response": "I'm having trouble processing your calendar request. Could you please rephrase that?"
            }

    # Core interface
    def add_event(self, user_id: int, text: str): 
        res = self.process_calendar_query(text, user_id=user_id)
        return res.get("success", False), res
    
    def get_events(self, user_id: int, text: str): 
        res = self.process_calendar_query(text, user_id=user_id)
        return res.get("success", False), res
    
    def delete_event(self, user_id: int, text: str): 
        res = self.process_calendar_query(text, user_id=user_id)
        return res.get("success", False), res


calendar_controller = CalendarController()
