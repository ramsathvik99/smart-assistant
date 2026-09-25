import json
from datetime import datetime, timedelta
from extensions.ai_utils import call_openai, call_huggingface, call_groq, call_gemini, call_deepseek
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
        """Minimal deterministic fallback when LLM is unavailable or disabled."""
        import re
        text_lower = text.lower().strip()
        now = datetime.now()
        
        # Check for event/meeting creation
        is_add_action = bool(
            re.search(r'\b(?:create|add|schedule)\s+(?:an?\s+)?(?:calendar\s+event|event|meeting)\b', text_lower)
            or re.search(r'\badd\s+.+?\s+to\s+(?:my\s+)?calendar\b', text_lower)
            or re.search(r'\bschedule\s+(?:an?\s+)?event\s+for\b', text_lower)
            or re.search(r'\b(?:schedule|add|create)\s+a\s+meeting\b', text_lower)
        )
        
        if is_add_action:
            # Extract date
            rel_date = "today"
            norm_date = now.strftime("%Y-%m-%d")
            has_date = False
            
            if "tomorrow" in text_lower:
                rel_date = "tomorrow"
                norm_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
                has_date = True
            elif "today" in text_lower:
                rel_date = "today"
                norm_date = now.strftime("%Y-%m-%d")
                has_date = True
            else:
                m_d = re.search(r'\b(?:on\s+)?(\d{4}-\d{2}-\d{2})\b', text_lower)
                if m_d:
                    norm_date = m_d.group(1)
                    rel_date = norm_date
                    has_date = True
            
            # Extract time
            m_time = re.search(r'\b(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm))\b', text_lower, re.IGNORECASE)
            if not m_time:
                m_time = re.search(r'\bat\s+(\d{1,2}(?::\d{2})?)\b', text_lower, re.IGNORECASE)
            
            event_time = None
            has_time = False
            if m_time:
                raw_time_str = m_time.group(1).strip()
                event_time = raw_time_str.upper()
                has_time = True
            
            # If neither sufficient date nor time information is provided, ask for clarification
            if not has_date and not has_time:
                return {
                    "action": "clarification",
                    "subject": "personal_event",
                    "message": "Please specify a date and time for the event."
                }
            
            # Extract title
            title = "Meeting" if "meeting" in text_lower else "Event"
            m_quote = re.search(r'["\']([^"\']+)["\']', text)
            if m_quote:
                title = m_quote.group(1).strip()
            else:
                m_called = re.search(r'\bcalled\s+(.+)', text, re.IGNORECASE)
                if m_called:
                    title = m_called.group(1).strip(' .')
                else:
                    m_add_to = re.search(r'\badd\s+(.+?)\s+to\s+(?:my\s+)?calendar\b', text, re.IGNORECASE)
                    if m_add_to:
                        candidate = m_add_to.group(1).strip(' "')
                        # strip out time or date qualifiers if attached
                        candidate = re.sub(r'\b(?:tomorrow|today|at\s+\d{1,2}.*)$', '', candidate, flags=re.IGNORECASE).strip(' "')
                        if candidate:
                            title = candidate
                    else:
                        m_meeting = re.search(r'\b(?:create|add|schedule)\s+(?:an?\s+)?([a-zA-Z0-9_\s]+?\s+meeting)\b', text, re.IGNORECASE)
                        if m_meeting:
                            title = m_meeting.group(1).strip()
            
            return {
                "action": "add",
                "subject": "personal_event",
                "entities": {
                    "event_title": title.title(),
                    "start_time": event_time,
                },
                "temporal_context": {
                    "relative_date": rel_date,
                    "normalized_date": norm_date,
                    "duration_days": 1
                }
            }
        
        # View queries
        if any(w in text_lower for w in ["today", "calendar", "event", "events", "schedule", "plan"]):
            rel_date = "today"
            norm_date = now.strftime("%Y-%m-%d")
            if "tomorrow" in text_lower:
                rel_date = "tomorrow"
                norm_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
            return {
                "action": "view",
                "subject": "personal_event",
                "entities": {},
                "temporal_context": {
                    "relative_date": rel_date,
                    "normalized_date": norm_date
                }
            }
        return {"action": "unknown", "subject": "unknown", "entities": {}, "temporal_context": {}}

def extract_calendar_intent(text: str) -> dict:
    """Convenience function for intent extraction."""
    return CalendarIntentHandler.get_intent(text)
