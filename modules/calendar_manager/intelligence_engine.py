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
    def plan_week(cls, country: str = "IN") -> str:
        """Plans the week based on upcoming holidays."""
        service = get_special_days_service()
        
        # Get current week range
        today = datetime.now()
        end_of_week = today + timedelta(days=7)
        
        holidays = service.get_special_days_in_range(
            today.strftime("%Y-%m-%d"),
            end_of_week.strftime("%Y-%m-%d")
        )
        
        holiday_context = ""
        if holidays:
            holiday_context = "Upcoming holidays this week:\n"
            for h in holidays:
                holiday_context += f"- {h['name']} on {h['date']}: {h['description']}\n"
        else:
            holiday_context = "No public holidays this week."
            
        system_prompt = "You are a Personal Planning Assistant. Based on upcoming holidays, suggest a light week plan. If no holidays, suggest focus on productivity."
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Plan my week. Current date: {today.strftime('%A, %Y-%m-%d')}. {holiday_context}"}
        ]
        
        response = call_openai(messages)
        if not response:
            combined_prompt = f"SYSTEM: {system_prompt}\nUSER: Plan my week based on: {holiday_context}\nAI:"
            response = call_huggingface(combined_prompt)
            
        return response if response else "I couldn't generate a specific plan, but I recommend checking your calendar for any personal commitments."

def explain_holiday_intelligence(holiday_name: str, country: str = "IN") -> str:
    """Convenience function for holiday explanation."""
    return CalendarIntelligenceEngine.explain_holiday(holiday_name, country)

def plan_week_intelligence(country: str = "IN") -> str:
    """Convenience function for week planning."""
    return CalendarIntelligenceEngine.plan_week(country)
