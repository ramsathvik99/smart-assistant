import json
from datetime import datetime
from core.chatbrain import call_openai, call_huggingface, call_groq, call_gemini, call_deepseek
from core.config import CONFIG

class CalendarIntentHandler:
    """Extracts intent and entities from NL calendar queries."""
    
    SYSTEM_PROMPT = """
    You are a Dynamic Calendar Intelligence Assistant. Your task is to analyze user queries and extract a structured ACTION MAP.
    Do NOT use fixed categories if they don't fit. Be adaptive.
    
    Return ONLY a JSON object with:
    - "action": (view, add, delete, explain, plan, count, compare)
    - "subject": (holiday, personal_event, festival_name, calendar_summary)
    - "entities": {{
        "holiday_name": "official name or 'Festival of Lights' etc.",
        "event_title": "for personal events",
        "location": "country or city (extract 'India' from 'in India')",
        "start_time": "HH:MM",
        "end_time": "HH:MM"
      }}
    - "temporal_context": {{
        "relative_date": "yesterday, today, tomorrow, next week, etc.",
        "normalized_date": "YYYY-MM-DD",
        "duration_days": "number of days for range"
      }}
    
    Examples:
    - 'When is the Festival of Lights in India?' -> {{"action": "view", "subject": "festival_name", "entities": {{"holiday_name": "Festival of Lights", "location": "India"}}, "temporal_context": {{"relative_date": "any", "normalized_date": null}}}}
    - 'What is today?' -> {{"action": "view", "subject": "holiday", "entities": {{}}, "temporal_context": {{"relative_date": "today", "normalized_date": "{current_date}"}}}}
    
    Current System Date: {current_date}
    """

    @classmethod
    def get_intent(cls, user_input: str) -> dict:
        """Processes user input and returns structured intent and entities."""
        current_date_str = datetime.now().strftime("%Y-%m-%d")
        
        messages = [
            {"role": "system", "content": cls.SYSTEM_PROMPT.format(current_date=current_date_str)},
            {"role": "user", "content": user_input}
        ]
        
        # Try Multi-LLM Routing
        response = call_openai(messages)
        if not response: response = call_gemini(messages)
        if not response: response = call_groq(messages)
        if not response: response = call_deepseek(messages)
        
        # Fallback to HuggingFace
        if not response:
            combined_prompt = f"SYSTEM: {cls.SYSTEM_PROMPT.format(current_date=current_date_str)}\nUSER: {user_input}\nJSON:"
            response = call_huggingface(combined_prompt)
            
        try:
            # Clean response if LLM added markdown or extra text
            start = response.find("{")
            end = response.rfind("}") + 1
            if start != -1 and end != 0:
                json_str = response[start:end]
                parsed = json.loads(json_str)
                return parsed
        except Exception:
            pass
            
        return cls._keyword_fallback(user_input)

    @classmethod
    def _keyword_fallback(cls, text: str) -> dict:
        """Minimal fallback."""
        text = text.lower()
        if "today" in text:
            return {"action": "view", "subject": "today", "entities": {}, "temporal_context": {"relative_date": "today"}}
        return {"action": "unknown", "subject": "unknown", "entities": {}, "temporal_context": {}}

def extract_calendar_intent(text: str) -> dict:
    """Convenience function for intent extraction."""
    return CalendarIntentHandler.get_intent(text)
