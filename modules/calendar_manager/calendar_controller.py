import logging
import traceback
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from .calendar_storage import CalendarStorage
from .country_detector import get_user_country
from .intent_handler import extract_calendar_intent
from .special_days_service import get_special_days_service
from .intelligence_engine import explain_holiday_intelligence, plan_week_intelligence


class CalendarController:
    """
    Fully Dynamic Calendar Intelligence System.
    Zero hardcoded logic. Adaptive understanding, conflict detection, and synthesis.
    """
    def __init__(self, storage_path="data/calendar_data.json"):
        self.storage = CalendarStorage(storage_path)
        self.logger = logging.getLogger(__name__)

    def check_event_conflicts(self, user_id: int, event_date: str, event_time: Optional[str]) -> List[Dict[str, Any]]:
        """
        Check for existing events at the same date and time for user isolation.
        """
        try:
            existing = self.storage.get_events(user_id, event_date)
            if not event_time:
                return []
            conflicts = [
                e for e in existing 
                if e.get("time") and e.get("time") == event_time
            ]
            return conflicts
        except Exception as e:
            self.logger.warning(f"[CalendarController] Conflict check warning: {e}")
            return []

    def process_calendar_query(self, text: str, user_id: int = None) -> Dict[str, Any]:
        """Main entry point. Understand -> Analyze -> Compute -> Respond."""
        try:
            # 1. UNDERSTAND: Extract Dynamic Action Map
            data = extract_calendar_intent(text)
            
            action = data.get("action", "unknown")
            if isinstance(action, list): action = action[0] if action else "unknown"
            action = str(action).lower()
            
            subject = data.get("subject", "unknown")
            if isinstance(subject, list): subject = subject[0] if subject else "unknown"
            subject = str(subject).lower()
            
            entities = data.get("entities", {})
            temporal = data.get("temporal_context", {})
            
            # Resolve Country (Auto or Override)
            country = entities.get("location") if entities.get("location") else get_user_country()
            service = get_special_days_service(region=country)
            
            # 2. COMPUTE: Resolve Dates & Ranges
            now = datetime.now()
            target_start = temporal.get("normalized_date")
            duration = temporal.get("duration_days", 0)
            
            if target_start in [None, "null", "None"]: target_start = None
            if duration in [None, "null", "None"]: duration = 0
            else: 
                try: duration = int(duration)
                except Exception as e:
                    self.logger.warning(f"[CalendarController] Could not parse duration '{duration}': {e}")
                    duration = 0

            if not target_start or target_start == "DYNAMIC":
                rel = str(temporal.get("relative_date", "")).lower()
                if "today" in rel: target_start = now.strftime("%Y-%m-%d")
                elif "tomorrow" in rel: target_start = (now + timedelta(days=1)).strftime("%Y-%m-%d")
                elif "next week" in rel: 
                    target_start = now.strftime("%Y-%m-%d")
                    duration = 7
                elif "this month" in rel:
                    target_start = now.strftime("%Y-%m-%d")
                    duration = 30
                else:
                    target_start = now.strftime("%Y-%m-%d")

            start_dt = datetime.strptime(target_start, "%Y-%m-%d")
            end_dt = start_dt + timedelta(days=max(0, duration - 1))
            target_end = end_dt.strftime("%Y-%m-%d")
            
            # Resolve authenticated user
            if user_id is None:
                try:
                    from instance.config import settings
                    user_id = getattr(settings, "CURRENT_USER_ID", None) or settings.get_last_user()
                except Exception:
                    pass
            if user_id is None:
                user_id = 0

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
            
            # Action Mapping
            if action == "clarification":
                results["status"] = "clarification"
                results["speech_response"] = data.get("message") or "Please specify the date and time for the calendar event."
                return results

            if action == "view":
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
                    results["personal_events"] = self.storage.get_events_range(user_id, target_start, target_end)
                    
                    # Synthesize clean speech response
                    total_events = sum(len(evs) for evs in results["personal_events"].values()) if isinstance(results["personal_events"], dict) else len(results["personal_events"])
                    speech_parts = []
                    if total_events > 0:
                        event_names = []
                        if isinstance(results["personal_events"], dict):
                            for d, ev_list in results["personal_events"].items():
                                for ev in ev_list:
                                    event_names.append(f"{ev['title']} at {ev['time'] or 'all day'}")
                        speech_parts.append(f"You have {total_events} event(s): {', '.join(event_names[:3])}")
                    else:
                        speech_parts.append(f"You have no scheduled personal events on {target_start}")

                    if results["holidays"]:
                        h_names = [h.get("name", "Holiday") for h in results["holidays"][:2]]
                        speech_parts.append(f"Holidays: {', '.join(h_names)}")

                    results["speech_response"] = ". ".join(speech_parts) + "."
                
            elif action == "add":
                title = entities.get("event_title", "Untitled Event")
                event_time = entities.get("start_time")
                
                # Conflict detection
                conflicts = self.check_event_conflicts(user_id, target_start, event_time)
                conflict_note = ""
                if conflicts:
                    c_title = conflicts[0].get("title", "Existing event")
                    conflict_note = f" Note: you already have '{c_title}' scheduled at {event_time}."

                event_data = {
                    "title": title,
                    "date": target_start,
                    "time": event_time,
                    "description": f"Added via assistant: {text}"
                }
                event_id = self.storage.add_event(user_id, event_data)
                time_str = f" at {event_time}" if event_time else ""
                results["status"] = f"Event added successfully"
                results["event_id"] = event_id
                results["speech_response"] = f"Added '{title}' to your calendar for {target_start}{time_str}.{conflict_note}"
                
            elif action == "update":
                title = entities.get("event_title")
                event_time = entities.get("start_time")
                existing = self.storage.get_events(user_id, target_start)
                if existing and title:
                    target_ev = next((e for e in existing if title.lower() in e['title'].lower()), existing[0])
                    updates = {}
                    if event_time: updates["time"] = event_time
                    if entities.get("new_title"): updates["title"] = entities.get("new_title")
                    success = self.storage.update_event(user_id, target_ev["id"], updates)
                    results["status"] = "Event updated" if success else "Update failed"
                    results["speech_response"] = f"Updated '{target_ev['title']}' on {target_start}."
                else:
                    results["status"] = "Event not found"
                    results["speech_response"] = f"I couldn't find an event on {target_start} to update."

            elif action == "delete":
                title = entities.get("event_title")
                if title:
                    count = self.storage.delete_events_by_title(user_id, target_start, title)
                    results["status"] = f"Deleted {count} events matching '{title}'"
                    results["speech_response"] = f"Deleted {count} event(s) matching '{title}' from {target_start}."
                else:
                    results["speech_response"] = "Please specify the event title to delete."
                
            elif action == "explain":
                h_name = entities.get("holiday_name") or entities.get("festival_name")
                if h_name:
                    results["explanation"] = explain_holiday_intelligence(h_name, country)
                    results["speech_response"] = str(results["explanation"])
                    
            elif action == "plan":
                results["plan"] = plan_week_intelligence(country)
                results["speech_response"] = str(results["plan"])
                
            elif action == "count":
                end_of_year = f"{now.year}-12-31"
                hdays = service.get_special_days_in_range(target_start, end_of_year)
                results["count"] = len(hdays)
                results["holidays"] = hdays[:5]
                results["speech_response"] = f"There are {len(hdays)} special days and holidays remaining this year."
                
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

