from datetime import datetime, timedelta
from extensions.ai_utils import call_openai, call_huggingface
from .special_days_service import get_special_days_service

class CalendarIntelligenceEngine:
    """Intelligent logic for creative calendar-related responses."""
    
    @classmethod
    def explain_holiday(cls, holiday_name: str, country: str = "IN") -> str:
        """Explains a holiday using LLM and cached context."""
        
        # Get holiday description from service if available
        service = get_special_days_service()
        # Find the holiday in current year
        year = datetime.now().year
        holidays = service._fetch_holidays_for_year(year) # This will also cache it
        matching = [h for h in holidays if holiday_name.lower() in h['name'].lower()]
        
        context = f"Holiday: {holiday_name}\nCountry: {country}\n"
        if matching:
            context += f"Description from API: {matching[0].get('description', 'No description available.')}"
            
        system_prompt = "You are a Calendar Intelligence Assistant. Explain the history and significance of the given holiday clearly and concisely."
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Explain {holiday_name}. Context: {context}"}
        ]
        
        response = call_openai(messages)
        if not response:
            combined_prompt = f"SYSTEM: {system_prompt}\nUSER: Explain {holiday_name}. Context: {context}\nAI:"
            response = call_huggingface(combined_prompt)
            
        return response if response else f"I couldn't find a detailed explanation for {holiday_name}, but it's an important celebration in {country}."

    @classmethod
    def plan_week(cls, country: str = "IN", user_id: int = 1) -> str:
        """Plans the week based on upcoming holidays and user's scheduled calendar events."""
        from .calendar_storage import CalendarStorage
        storage = CalendarStorage()
        try:
            settings = storage.get_settings(user_id)
            if settings and settings.get('country'):
                country = settings.get('country')
        except Exception:
            pass

        service = get_special_days_service(region=country, user_id=user_id)
        
        # Get current week range
        today = datetime.now()
        end_of_week = today + timedelta(days=7)
        today_str = today.strftime("%Y-%m-%d")
        end_str = end_of_week.strftime("%Y-%m-%d")
        
        holidays = service.get_special_days_in_range(today_str, end_str)
        
        # Retrieve user calendar events for the week
        personal_events = []
        try:
            evs_map = storage.get_events_range(user_id, today_str, end_str)
            if isinstance(evs_map, dict):
                for d, elist in sorted(evs_map.items()):
                    for ev in elist:
                        loc = f" at {ev['location']}" if ev.get('location') else ""
                        dur = f" ({ev['duration_minutes']}m)" if ev.get('duration_minutes') and ev.get('duration_minutes') != 60 else ""
                        personal_events.append(f"{ev['title']}{dur} on {d} at {ev.get('time') or 'all day'}{loc}")
            elif isinstance(evs_map, list):
                for ev in evs_map:
                    loc = f" at {ev['location']}" if ev.get('location') else ""
                    dur = f" ({ev['duration_minutes']}m)" if ev.get('duration_minutes') and ev.get('duration_minutes') != 60 else ""
                    personal_events.append(f"{ev['title']}{dur} at {ev.get('time') or 'all day'}{loc}")
        except Exception:
            pass

        context_lines = []
        if personal_events:
            context_lines.append("Your scheduled meetings and events this week:")
            for pe in personal_events:
                context_lines.append(f"- {pe}")
        else:
            context_lines.append("No personal meetings or events scheduled this week.")
            
        if holidays:
            context_lines.append("Upcoming public holidays this week:")
            for h in holidays:
                context_lines.append(f"- {h['name']} on {h['date']}: {h.get('description', '')}")
        else:
            context_lines.append("No public holidays this week.")
            
        holiday_context = "\n".join(context_lines)
            
        system_prompt = "You are a Personal Planning Assistant. Based on the user's scheduled meetings and upcoming holidays, suggest a structured weekly plan balancing productivity and scheduled commitments."
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Plan my week. Current date: {today.strftime('%A, %Y-%m-%d')}.\n{holiday_context}"}
        ]
        
        response = call_openai(messages)
        if not response:
            combined_prompt = f"SYSTEM: {system_prompt}\nUSER: Plan my week based on:\n{holiday_context}\nAI:"
            response = call_huggingface(combined_prompt)
            
        if response and not response.startswith("❌"):
            return response

        # Deterministic intelligent fallback when LLM is offline or unavailable
        plan_summary = f"Weekly Plan ({today.strftime('%b %d')} - {end_of_week.strftime('%b %d')}):\n"
        if personal_events:
            plan_summary += f"• Scheduled Commitments: {len(personal_events)} event(s) scheduled ({', '.join(personal_events[:3])}). Plan focus blocks around these.\n"
        else:
            plan_summary += "• Schedule: Clear calendar. Ideal for uninterrupted deep work and priority tasks.\n"
        if holidays:
            h_names = [f"{h['name']} ({h['date']})" for h in holidays[:2]]
            plan_summary += f"• Holidays: {', '.join(h_names)}. Account for holiday downtime."
        else:
            plan_summary += "• Holidays: No public holidays this week; standard 5-day work week."
        return plan_summary

def explain_holiday_intelligence(holiday_name: str, country: str = "IN") -> str:
    """Convenience function for holiday explanation."""
    return CalendarIntelligenceEngine.explain_holiday(holiday_name, country)

def plan_week_intelligence(country: str = "IN", user_id: int = 1) -> str:
    """Convenience function for week planning."""
    return CalendarIntelligenceEngine.plan_week(country, user_id=user_id)

