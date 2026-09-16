import logging
import traceback
from datetime import datetime, timedelta
from .calendar_storage import CalendarStorage
from .country_detector import get_user_country
from .intent_handler import extract_calendar_intent
from .special_days_service import get_special_days_service
from .intelligence_engine import explain_holiday_intelligence, plan_week_intelligence
from .intelligence_engine import explain_holiday_intelligence, plan_week_intelligence
from core.chatbrain import call_openai, call_huggingface, call_groq, call_gemini, call_deepseek

class CalendarController:
    """
    Fully Dynamic Calendar Intelligence System.
    Zero hardcoded logic. Adaptive understanding and synthesis.
    """
    def __init__(self, storage_path="data/calendar_data.json"):
        self.storage = CalendarStorage(storage_path)
        self.logger = logging.getLogger(__name__)

    def process_calendar_query(self, text: str):
        """Main entry point. Understand -> Analyze -> Compute -> Respond."""
        try:
            # 1. UNDERSTAND: Extract Dynamic Action Map
            data = extract_calendar_intent(text)
            
            # Robustly handle different LLM output styles (strings vs lists)
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
            
            # Convert string null/None to real None
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
            
            # 3. ANALYZE & FETCH
            results = {
                "holidays": [],
                "personal_events": [],
                "explanation": None,
                "plan": None,
                "count": 0,
                "status": "success",
                "meta": {"start": target_start, "end": target_end, "country": country}
            }
            
            user_id = 1 # Default or from context
            
            # Action Mapping
            if action == "view":
                if subject == "festival_name" or entities.get("holiday_name"):
                    h_name = entities.get("holiday_name") or entities.get("festival_name")
                    results["holidays"] = service.get_holiday_by_name(h_name)
                else:
                    # Range View
                    results["holidays"] = service.get_special_days_in_range(target_start, target_end)
                    results["personal_events"] = self.storage.get_events_range(user_id, target_start, target_end)
                
            elif action == "add":
                event_data = {
                    "title": entities.get("event_title", "Untitled Event"),
                    "date": target_start,
                    "time": entities.get("start_time"),
                    "description": f"Added via voice: {text}"
                }
                event_id = self.storage.add_event(user_id, event_data)
                results["status"] = f"Event added successfully"
                
            elif action == "delete":
                title = entities.get("event_title")
                if title:
                    count = self.storage.delete_events_by_title(user_id, target_start, title)
                    results["status"] = f"Deleted {count} events matching '{title}'"
                
            elif action == "explain":
                h_name = entities.get("holiday_name") or entities.get("festival_name")
                if h_name:
                    results["explanation"] = explain_holiday_intelligence(h_name, country)
                    
            elif action == "plan":
                results["plan"] = plan_week_intelligence(country)
                
            elif action == "count":
                # Remaining or range count
                end_of_year = f"{now.year}-12-31"
                hdays = service.get_special_days_in_range(target_start, end_of_year)
                results["count"] = len(hdays)
                results["holidays"] = hdays[:5] # Sample for context
                
            # 4. RESPOND: Synthesize with LLM
            # 4. RESPOND: Return raw data for RAG synthesis
            return results

        except Exception as e:
            self.logger.error(f"[CalendarController] Error: {e}")
            traceback.print_exc()
            return "I'm having trouble processing your calendar request. Could you rephrase that?"

            return {"error": "Failed to process calendar query."}

    # Core interface
    def add_event(self, user_id: int, text: str): 
        return True, self.process_calendar_query(text)
    
    def get_events(self, user_id: int, text: str): 
        return True, self.process_calendar_query(text)
    
    def delete_event(self, user_id: int, text: str): 
        return True, self.process_calendar_query(text)
