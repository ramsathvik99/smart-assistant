import json
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
from extensions.ai_utils import call_openai, call_huggingface, call_groq, call_gemini, call_deepseek
from core.config import CONFIG

class CalendarIntentHandler:
    """Extracts intent and entities from NL calendar queries."""
    
    SYSTEM_PROMPT = """
    You are a Dynamic Calendar Intelligence Assistant. Your task is to analyze user queries and extract a structured ACTION MAP.
    Do NOT use fixed categories if they don't fit. Be adaptive.
    
    Return ONLY a JSON object with:
    - "action": (view, add, update, delete, explain, plan, count, free_slots, busy_time, analytics, search, add_note, add_agenda, add_checklist, ics_export, ics_import, sync, snooze, clarification)
    - "subject": (holiday, personal_event, festival_name, calendar_summary, analytics)
    - "entities": {{
        "holiday_name": "official name or 'Festival of Lights' etc.",
        "event_title": "for personal events",
        "new_title": "new title if renaming",
        "location": "location/room/link",
        "category": "Work, Personal, etc.",
        "start_time": "HH:MM",
        "end_time": "HH:MM",
        "duration_minutes": 60,
        "recurrence": {{"frequency": "daily/weekly/monthly", "interval": 1, "days_of_week": "MO,WE"}},
        "notes": "notes content",
        "agenda": ["item1", "item2"]
      }}
    - "temporal_context": {{
        "relative_date": "yesterday, today, tomorrow, next week, etc.",
        "normalized_date": "YYYY-MM-DD",
        "normalized_end_date": "YYYY-MM-DD",
        "duration_days": "number of days for range"
      }}
    
    Current System Date: {current_date}
    """

    @classmethod
    def get_intent(cls, user_input: str) -> dict:
        """Processes user input and returns structured intent and entities."""
        # Strip leading assistant name / wake word so day-of-week names like "Friday" are never misinterpreted as dates
        cleaned = re.sub(r'^(?:hey\s+|hi\s+|ok\s+|okay\s+)?(?:friday|nova|trevon|jarvis|assistant|computer)\b[:,]?\s*', '', user_input.strip(), flags=re.IGNORECASE)
        user_input_norm = re.sub(r'\bshedule\b', 'schedule', cleaned, flags=re.IGNORECASE)
        user_input_norm = re.sub(r'\bmeting\b', 'meeting', user_input_norm, flags=re.IGNORECASE)
        user_input_norm = re.sub(r'\bmeet\b', 'meeting', user_input_norm, flags=re.IGNORECASE)
        
        # Check deterministic keyword fallback first for high speed and offline reliability
        fast_intent = cls._keyword_fallback(user_input_norm)
        if fast_intent.get("action") not in ("unknown", None):
            return fast_intent

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
            start = response.find("{")
            end = response.rfind("}") + 1
            if start != -1 and end != 0:
                json_str = response[start:end]
                parsed = json.loads(json_str)
                return parsed
        except Exception:
            pass
            
        return cls._keyword_fallback(user_input)

    MONTHS = {
        'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
        'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'jun': 6, 'jul': 7, 'aug': 8,
        'sep': 9, 'sept': 9, 'oct': 10, 'nov': 11, 'dec': 12
    }

    WEEKDAYS = {
        'monday': 'MO', 'tuesday': 'TU', 'wednesday': 'WE', 'thursday': 'TH',
        'friday': 'FR', 'saturday': 'SA', 'sunday': 'SU',
        'mon': 'MO', 'tue': 'TU', 'wed': 'WE', 'thu': 'TH', 'fri': 'FR', 'sat': 'SA', 'sun': 'SU'
    }

    @classmethod
    def _parse_date_str(cls, s: str, fallback_year: int = None) -> Optional[str]:
        if not s: return None
        # Strip leading wake words before attempting date extraction
        s = re.sub(r'^(?:hey\s+|hi\s+|ok\s+|okay\s+)?(?:friday|nova|trevon|jarvis|assistant|computer)\b[:,]?\s*', '', s.strip(), flags=re.IGNORECASE)
        s = s.strip().lower()
        now = datetime.now()
        if re.search(r'\btomorrow\b', s):
            return (now + timedelta(days=1)).strftime("%Y-%m-%d")
        if re.search(r'\btoday\b', s):
            return now.strftime("%Y-%m-%d")
        if re.search(r'\byesterday\b', s):
            return (now - timedelta(days=1)).strftime("%Y-%m-%d")
            
        m_iso = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', s)
        if m_iso: return m_iso.group(1)

        # Explicit month + day e.g. "October 20, 2026" or "20th of October"
        pattern = r'\b(' + '|'.join(cls.MONTHS.keys()) + r')\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b'
        m = re.search(pattern, s, re.IGNORECASE)
        if m:
            month = cls.MONTHS[m.group(1).lower()]
            day = int(m.group(2))
            year = int(m.group(3)) if m.group(3) else (fallback_year or now.year)
            return f"{year:04d}-{month:02d}-{day:02d}"

        pattern_rev = r'\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(' + '|'.join(cls.MONTHS.keys()) + r')(?:,?\s+(\d{4}))?\b'
        m_rev = re.search(pattern_rev, s, re.IGNORECASE)
        if m_rev:
            day = int(m_rev.group(1))
            month = cls.MONTHS[m_rev.group(2).lower()]
            year = int(m_rev.group(3)) if m_rev.group(3) else (fallback_year or now.year)
            return f"{year:04d}-{month:02d}-{day:02d}"

        # Check weekday reference e.g. "this friday", "next monday", "on wednesday"
        # Require explicit preposition or standalone weekday to prevent wake-word collision
        for w_name, w_code in cls.WEEKDAYS.items():
            m_wd = re.search(r'\b(?:this\s+|next\s+|on\s+)' + w_name + r'\b', s)
            if not m_wd and (s == w_name or re.fullmatch(r'(?:this\s+|next\s+|on\s+)?' + w_name, s)):
                m_wd = True
            if m_wd:
                target_wd = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}[w_code]
                cur_wd = now.weekday()
                days_ahead = (target_wd - cur_wd) % 7
                if days_ahead == 0 and "next" in s:
                    days_ahead = 7
                elif days_ahead == 0 and not ("today" in s or "this" in s):
                    days_ahead = 7
                return (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

        return None

    @classmethod
    def _parse_time_str(cls, s: str) -> Optional[str]:
        if not s: return None
        # Handle formats like 3:00 p.m., 3:00pm, 3pm, 3:00
        m_time = re.search(r'\b(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?))\b', s, re.IGNORECASE)
        if m_time:
            t_str = m_time.group(1).strip().upper()
            t_str = re.sub(r'P\.?M\.?', 'PM', t_str)
            t_str = re.sub(r'A\.?M\.?', 'AM', t_str)
            return t_str
        m_time_num = re.search(r'\bat\s+(\d{1,2}(?::\d{2})?)\b', s, re.IGNORECASE)
        if m_time_num:
            return m_time_num.group(1).strip().upper()
        return None

    @classmethod
    def _parse_duration(cls, text: str) -> Optional[int]:
        """Extract duration in minutes from natural speech."""
        m_hrs = re.search(r'\bfor\s+(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\b', text, re.IGNORECASE)
        if m_hrs:
            return int(float(m_hrs.group(1)) * 60)
        m_mins = re.search(r'\bfor\s+(\d+)\s*(?:minutes?|mins?)\b', text, re.IGNORECASE)
        if m_mins:
            return int(m_mins.group(1))
        m_half = re.search(r'\bfor\s+half\s+an?\s+hour\b', text, re.IGNORECASE)
        if m_half:
            return 30
        return None

    @classmethod
    def _parse_location(cls, text: str) -> Optional[str]:
        """Extract meeting location or virtual link from text."""
        m_loc = re.search(r'\b(?:in|at|on)\s+(room\s+[a-zA-Z0-9_\-]+|conference\s+room\s+[a-zA-Z0-9_\-]+|zoom|google\s+meet|teams|microsoft\s+teams|starbucks|office|building\s+[a-zA-Z0-9_\-]+)\b', text, re.IGNORECASE)
        if m_loc:
            return m_loc.group(1).strip()
        m_at = re.search(r'\blocation\s+(?:is\s+|as\s+)?([a-zA-Z0-9_\-\s]+?)(?:\s+(?:for|on|at|with|duration)|$)', text, re.IGNORECASE)
        if m_at:
            return m_at.group(1).strip()
        return None

    @classmethod
    def _parse_category(cls, text: str) -> Optional[str]:
        """Extract category (Work, Personal, Health, Family, etc.)."""
        m_cat = re.search(r'\bcategory\s+([a-zA-Z]+)\b', text, re.IGNORECASE)
        if m_cat:
            return m_cat.group(1).capitalize()
        if re.search(r'\b(work|professional)\s+(?:meeting|sync|event|call)\b', text, re.IGNORECASE):
            return "Work"
        if re.search(r'\b(personal|family|doctor|dentist|health)\s+(?:event|appointment|meeting)\b', text, re.IGNORECASE):
            return "Personal"
        return None

    @classmethod
    def _parse_recurrence(cls, text: str) -> Optional[Dict[str, Any]]:
        """Extract recurrence pattern (daily, weekly, monthly, yearly, weekdays)."""
        text_low = text.lower()
        if re.search(r'\b(?:every\s+day|daily)\b', text_low):
            return {"frequency": "daily", "interval": 1}
        if re.search(r'\b(?:every\s+weekday|on\s+weekdays)\b', text_low):
            return {"frequency": "weekly", "interval": 1, "days_of_week": "MO,TU,WE,TH,FR"}
        
        # Check specific days of week e.g. "every Monday", "every Mon and Wed"
        found_days = []
        for w_name, w_code in cls.WEEKDAYS.items():
            if re.search(r'\bevery\s+(?:other\s+)?' + w_name + r'\b', text_low) or \
               re.search(r'\bon\s+' + w_name + r's?\b', text_low) and "every" in text_low:
                if w_code not in found_days:
                    found_days.append(w_code)
        
        if found_days:
            interval = 2 if "every other" in text_low else 1
            return {"frequency": "weekly", "interval": interval, "days_of_week": ",".join(found_days)}

        if re.search(r'\b(?:every\s+week|weekly)\b', text_low):
            interval = 2 if "every other week" in text_low else 1
            return {"frequency": "weekly", "interval": interval}

        if re.search(r'\b(?:every\s+month|monthly)\b', text_low):
            return {"frequency": "monthly", "interval": 1}

        if re.search(r'\b(?:every\s+year|yearly|annually)\b', text_low):
            return {"frequency": "yearly", "interval": 1}

        return None

    @classmethod
    def _keyword_fallback(cls, text: str) -> dict:
        """Deterministic keyword fallback for high-speed, accurate calendar understanding."""
        text_clean = re.sub(r'^(?:hey\s+|hi\s+|ok\s+|okay\s+)?(?:friday|nova|trevon|jarvis|assistant|computer)\b[:,]?\s*', '', text.strip(), flags=re.IGNORECASE)
        text_clean = re.sub(r'\bshedule\b', 'schedule', text_clean, flags=re.IGNORECASE)
        text_clean = re.sub(r'\bmeting\b', 'meeting', text_clean, flags=re.IGNORECASE)
        text_clean = re.sub(r'\bmeet\b', 'meeting', text_clean, flags=re.IGNORECASE).strip()
        text_lower = text_clean.lower()
        now = datetime.now()

        # 0. Conflict Resolution Follow-ups
        # Keep both / schedule anyway
        if re.search(r'\b(?:keep\s+both(?:\s+events?)?|schedule\s+(?:it\s+)?anyway|both\s+events?|yes\s+keep\s+both|keep\s+both\s+at\s+that\s+time)\b', text_lower) or text_lower in ("keep both", "both", "keep", "yes keep"):
            return {
                "action": "conflict_resolution",
                "subject": "personal_event",
                "entities": {"resolution": "keep_both"},
                "temporal_context": {}
            }
        
        # Move to new time as resolution e.g. "move the new meeting to 4 PM", "move to 4 PM", "make it 4 PM", "at 4 PM", "4 PM"
        m_cr_time = re.search(r'^(?:move\s+(?:the\s+new\s+(?:meeting|event)\s+)?to\s+|change\s+(?:the\s+time\s+)?to\s+|make\s+it\s+|at\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)$', text_clean.strip(), re.IGNORECASE)
        if m_cr_time and ("move" in text_lower or "change" in text_lower or "make it" in text_lower or "pm" in text_lower or "am" in text_lower):
            raw_t = cls._parse_time_str(m_cr_time.group(1)) or m_cr_time.group(1).strip().upper()
            return {
                "action": "conflict_resolution",
                "subject": "personal_event",
                "entities": {"resolution": "change_time", "time": raw_t, "start_time": raw_t},
                "temporal_context": {}
            }

        # Change date as resolution e.g. "change the date to Friday", "move to Friday", "make it Friday", "change date to October 21"
        m_cr_date = re.search(r'^(?:change\s+(?:the\s+)?date\s+to\s+|move\s+(?:the\s+new\s+(?:meeting|event)\s+)?to\s+|make\s+it\s+)(.+)$', text_clean.strip(), re.IGNORECASE)
        if m_cr_date and any(w in text_lower for w in ["friday", "monday", "tuesday", "wednesday", "thursday", "saturday", "sunday", "tomorrow", "october", "november", "december", "january", "date"]):
            parsed_d = cls._parse_date_str(m_cr_date.group(1))
            if parsed_d:
                return {
                    "action": "conflict_resolution",
                    "subject": "personal_event",
                    "entities": {"resolution": "change_date", "new_date": parsed_d},
                    "temporal_context": {"normalized_date": parsed_d}
                }

        # Cancel request as resolution
        if re.search(r'^(?:cancel(?:\s+the\s+new\s+request|\s+the\s+request|\s+the\s+change|\s+change|\s+it)?|never\s+mind|don\'?t\s+schedule(?:\s+it)?|drop\s+it)$', text_lower):
            return {
                "action": "conflict_resolution",
                "subject": "personal_event",
                "entities": {"resolution": "cancel"},
                "temporal_context": {}
            }

        # 1. External Calendar Sync
        if re.search(r'\b(?:sync|synchronize)\s+(?:my\s+)?(?:calendar|events|google\s+calendar|outlook)\b', text_lower):
            prov = "google" if "google" in text_lower else ("outlook" if "outlook" in text_lower else None)
            return {
                "action": "sync",
                "subject": "calendar_summary",
                "entities": {"provider": prov},
                "temporal_context": {}
            }

        # 2. iCalendar Export / Import
        if re.search(r'\bexport\s+(?:my\s+)?(?:calendar|events)\s*(?:to\s+ics|\.ics)?\b', text_lower):
            return {
                "action": "ics_export",
                "subject": "personal_event",
                "entities": {},
                "temporal_context": {}
            }
        m_imp = re.search(r'\bimport\s+(?:calendar|events)\s+(?:from\s+)?(.+)', text_clean, re.IGNORECASE)
        if m_imp and not any(k in text_lower for k in ["python", "module", "library"]):
            src = m_imp.group(1).strip(" '\". ")
            return {
                "action": "ics_import",
                "subject": "personal_event",
                "entities": {"source": src},
                "temporal_context": {}
            }

        # 3. Calendar Analytics
        if re.search(r'\b(?:calendar\s+analytics|meeting\s+statistics|meeting\s+stats|schedule\s+utilization|how\s+much\s+time\s+did\s+i\s+spend\s+in\s+meetings)\b', text_lower):
            target_start = now.strftime("%Y-%m-%d")
            duration_days = 7
            if "month" in text_lower:
                duration_days = 30
            return {
                "action": "analytics",
                "subject": "analytics",
                "entities": {},
                "temporal_context": {
                    "normalized_date": target_start,
                    "duration_days": duration_days
                }
            }

        # 4. Free Time / Open Slot Discovery
        if re.search(r'\b(?:when\s+am\s+i\s+free|find\s+(?:a\s+)?free\s+slot|free\s+time|open\s+slots?|suggest\s+(?:a\s+)?time|available\s+slots?|am\s+i\s+free)\b', text_lower):
            rel_date = "today"
            norm_date = now.strftime("%Y-%m-%d")
            if "tomorrow" in text_lower:
                rel_date = "tomorrow"
                norm_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                p_date = cls._parse_date_str(text_clean)
                if p_date:
                    norm_date = p_date
                    rel_date = p_date
            
            dur = cls._parse_duration(text_clean) or 30
            pref_time = cls._parse_time_str(text_clean)
            return {
                "action": "free_slots",
                "subject": "personal_event",
                "entities": {
                    "duration_minutes": dur,
                    "preferred_time": pref_time
                },
                "temporal_context": {
                    "relative_date": rel_date,
                    "normalized_date": norm_date
                }
            }

        # 5. Busy Time Query
        if re.search(r'\b(?:when\s+am\s+i\s+busy|am\s+i\s+busy|busy\s+(?:time|schedule|periods?))\b', text_lower):
            rel_date = "today"
            norm_date = now.strftime("%Y-%m-%d")
            if "tomorrow" in text_lower:
                rel_date = "tomorrow"
                norm_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                p_date = cls._parse_date_str(text_clean)
                if p_date:
                    norm_date = p_date
                    rel_date = p_date
            return {
                "action": "busy_time",
                "subject": "personal_event",
                "entities": {},
                "temporal_context": {
                    "relative_date": rel_date,
                    "normalized_date": norm_date
                }
            }

        # 6. Meeting Notes, Agendas, Checklists & Document Associations
        m_notes = re.search(r'\badd\s+(?:meeting\s+)?notes?\s+(?:to|for)\s+(.+?)(?::|\s+saying|\s+as)\s+(.+)', text_clean, re.IGNORECASE)
        if m_notes:
            title = m_notes.group(1).strip(" '\". ")
            notes_body = m_notes.group(2).strip(" '\". ")
            return {
                "action": "add_note",
                "subject": "personal_event",
                "entities": {"event_title": title, "notes": notes_body},
                "temporal_context": {}
            }
        m_agenda = re.search(r'\badd\s+(?:meeting\s+)?agenda(?:\s+items?)?\s+(?:to|for)\s+(.+?)(?::|\s+with|\s+items?|\s+saying)\s+(.+)', text_clean, re.IGNORECASE)
        if m_agenda:
            title = m_agenda.group(1).strip(" '\". ")
            raw_items = m_agenda.group(2).strip(" '\". ")
            items = [it.strip() for it in re.split(r'[,;]|\band\b|\d+\.', raw_items) if it.strip()]
            return {
                "action": "add_agenda",
                "subject": "personal_event",
                "entities": {"event_title": title, "agenda": items},
                "temporal_context": {}
            }

        # 7. Snooze Calendar Reminder
        m_snooze = re.search(r'\bsnooze\s+(?:calendar\s+|meeting\s+)?reminder(?:\s+for\s+(\d+)\s*(?:minutes?|mins?))?\b', text_lower)
        if m_snooze:
            s_mins = int(m_snooze.group(1)) if m_snooze.group(1) else 10
            return {
                "action": "snooze",
                "subject": "personal_event",
                "entities": {"snooze_minutes": s_mins},
                "temporal_context": {}
            }

        # 8. Event Search
        m_search = re.search(r'\b(?:search|find)\s+(?:calendar|events|meetings)\s+(?:for|about)\s+(.+)', text_clean, re.IGNORECASE)
        if m_search and not any(k in text_lower for k in ["google", "web", "internet", "online"]):
            q = m_search.group(1).strip(" '\". ")
            return {
                "action": "search",
                "subject": "personal_event",
                "entities": {"query": q},
                "temporal_context": {}
            }

        # 9. Next appointment query
        if re.search(r'\b(?:what(?:\'s|\s+is)\s+(?:my\s+)?(?:next|upcoming)\s+(?:appointment|meeting|event)|next\s+(?:appointment|meeting|event)|when\s+is\s+(?:my\s+)?(?:next|upcoming)\s+(?:appointment|meeting|event))\b', text_lower):
            cat = cls._parse_category(text_clean)
            return {
                "action": "next",
                "subject": "personal_event",
                "entities": {"category": cat} if cat else {},
                "temporal_context": {}
            }

        # 10. Weekly planning query
        if re.search(r'\b(?:plan\s+(?:my\s+)?(?:week|schedule|days?)|weekly\s+plan(?:ning)?)\b', text_lower):
            return {
                "action": "plan",
                "subject": "calendar_summary",
                "entities": {},
                "temporal_context": {"relative_date": "week"}
            }

        # 11. Holiday count query ("How many public holidays are there in Russia in 2027?")
        m_count = re.search(r'\b(?:how\s+many\s+(?:public\s+)?holidays|count\s+(?:the\s+)?(?:public\s+)?holidays|number\s+of\s+(?:public\s+)?holidays)\b', text_lower)
        if m_count:
            country = None
            if "russia" in text_lower: country = "RU"
            elif "united states" in text_lower or "us" in text_lower or "usa" in text_lower: country = "US"
            elif "india" in text_lower: country = "IN"

            m_yr = re.search(r'\b(20\d{2})\b', text_lower)
            target_yr = int(m_yr.group(1)) if m_yr else now.year

            return {
                "action": "count",
                "subject": "holiday",
                "entities": {"location": country, "year": target_yr},
                "temporal_context": {"normalized_date": f"{target_yr}-01-01", "end_date": f"{target_yr}-12-31"}
            }

        # Next public holiday query ("What is the next public holiday where I live?")
        if re.search(r'\b(?:what(?:\'s|\s+is)\s+(?:the\s+)?next\s+(?:public\s+)?holiday|upcoming\s+(?:public\s+)?holiday|when\s+is\s+(?:the\s+)?next\s+(?:public\s+)?holiday)\b', text_lower):
            country = None
            if "where i live" in text_lower or "my country" in text_lower or "my state" in text_lower:
                country = "USER_LOCATION"
            elif "russia" in text_lower: country = "RU"
            elif "united states" in text_lower or "us" in text_lower or "usa" in text_lower: country = "US"
            elif "india" in text_lower: country = "IN"

            return {
                "action": "next_holiday",
                "subject": "holiday",
                "entities": {"location": country},
                "temporal_context": {"normalized_date": now.strftime("%Y-%m-%d")}
            }

        # Specific holiday / festival date query ("When is Diwali this year?", "When is Christmas?", "What date is Thanksgiving?")
        m_fest = re.search(r'\b(?:when\s+is|what\s+date\s+is|date\s+for)\s+(?:the\s+)?([a-zA-Z\s]+?)(?:\s+(?:this\s+year|in\s+\d{4}))?[?]?$', text_clean, re.IGNORECASE)
        if m_fest:
            fest_candidate = m_fest.group(1).strip(" '\". ")
            fest_low = fest_candidate.lower()
            if any(k in fest_low for k in ["diwali", "deepavali", "holi", "christmas", "easter", "thanksgiving", "republic day", "independence day", "eid", "halloween", "new year", "labor day", "memorial day", "gandhi", "shivratri"]):
                m_yr = re.search(r'\b(20\d{2})\b', text_clean)
                target_yr = int(m_yr.group(1)) if m_yr else now.year
                return {
                    "action": "view",
                    "subject": "festival_name",
                    "entities": {"holiday_name": fest_candidate.title(), "year": target_yr},
                    "temporal_context": {}
                }

        # 12. Holiday explanation
        m_exp = re.search(r'\b(?:explain|tell\s+me\s+about)\s+(?:the\s+holiday\s+|holiday\s+)?([a-zA-Z\s]+?)(?:\s+holiday|\s+festival|\s+significance|\s+history|$)', text_lower)
        if m_exp and any(k in text_lower for k in ["holiday", "festival", "diwali", "christmas", "easter", "thanksgiving"]):
            h_name = m_exp.group(1).strip()
            return {
                "action": "explain",
                "subject": "holiday",
                "entities": {"holiday_name": h_name.title()},
                "temporal_context": {}
            }

        # Duration modification ("make the meeting 30 minutes longer", "extend the meeting by 30 minutes")
        m_dur_chg = re.search(r'\b(?:make|extend|shorten|change)\s+(?:the\s+)?(.+?)\s+(\d+)\s*(?:minutes?|mins?)\s*(longer|shorter|more|less)\b', text_clean, re.IGNORECASE)
        if m_dur_chg:
            target_title = m_dur_chg.group(1).strip(" '\". ")
            delta_mins = int(m_dur_chg.group(2))
            direction = m_dur_chg.group(3).lower()
            if direction in ("shorter", "less"):
                delta_mins = -delta_mins
            return {
                "action": "update",
                "subject": "personal_event",
                "entities": {
                    "event_title": target_title,
                    "duration_delta": delta_mins
                },
                "temporal_context": {}
            }

        # 13. Rename event
        m_ren = re.search(r'\brename\s+(?:the\s+)?(?:event|meeting|appointment|sync|standup)?\s*(.+?)\s+to\s+(.+)', text_clean, re.IGNORECASE)
        if m_ren and not any(k in text_lower for k in ["file", "folder", "directory"]):
            old_title = m_ren.group(1).strip(" '\". ")
            old_title = re.sub(r'^(?:the\s+|my\s+)?(?:calendar\s+)?', '', old_title, flags=re.IGNORECASE).strip(" '\". ")
            new_title = m_ren.group(2).strip(" '\". ")
            return {
                "action": "update",
                "subject": "personal_event",
                "entities": {
                    "event_title": old_title,
                    "new_title": new_title
                },
                "temporal_context": {}
            }

        # 14. Change time of event (supporting "time of" and "time for")
        m_time_chg = re.search(r'\b(?:change|update|reschedule|move|shift)\s+(?:the\s+)?time\s+(?:of|for)\s+(.+?)\s+to\s+(\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?)\b', text_clean, re.IGNORECASE)
        if m_time_chg:
            title = m_time_chg.group(1).strip(" '\". ")
            title = re.sub(r'^(?:the\s+|my\s+)?(?:calendar\s+)?', '', title, flags=re.IGNORECASE).strip(" '\". ")
            new_time = cls._parse_time_str(m_time_chg.group(2)) or m_time_chg.group(2).strip(" '\". ").upper()
            return {
                "action": "update",
                "subject": "personal_event",
                "entities": {
                    "event_title": title,
                    "start_time": new_time
                },
                "temporal_context": {}
            }

        # 15. Move / Reschedule event to date and/or time
        m_move = re.search(r'\b(?:move|reschedule|shift|postpone)\s+(.+?)\s+to\s+(.+)', text_clean, re.IGNORECASE)
        if m_move and not any(k in text_lower for k in ["file", "folder", "directory"]):
            title = m_move.group(1).strip(" '\". ")
            title = re.sub(r'^(?:the\s+|my\s+)?(?:calendar\s+)?', '', title, flags=re.IGNORECASE).strip(" '\". ")
            dest_str = m_move.group(2).strip(" '\". ")
            dest_time = cls._parse_time_str(dest_str)
            dest_date = cls._parse_date_str(dest_str)
            if dest_date or dest_time:
                return {
                    "action": "update",
                    "subject": "personal_event",
                    "entities": {
                        "event_title": title,
                        "start_time": dest_time,
                        "new_date": dest_date
                    },
                    "temporal_context": {
                        "normalized_date": dest_date,
                        "has_explicit_date": bool(dest_date)
                    }
                }

        # 16. Cancel / Delete event (supporting occurrence-specific vs series)
        m_cancel = re.search(r'\b(?:cancel|delete|remove|drop)\s+(?:my\s+|the\s+)?(?:calendar\s+event|event|meeting|appointment)?\s*(.+)', text_clean, re.IGNORECASE)
        if m_cancel and not any(k in text_lower for k in ["file", "folder", "directory", "download", "alarm", "timer", "reminder", "note"]):
            raw_target = m_cancel.group(1).strip(" '\". ")
            rel_date = "today"
            norm_date = now.strftime("%Y-%m-%d")
            
            has_explicit_date = False
            if "tomorrow" in raw_target.lower():
                rel_date = "tomorrow"
                norm_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
                raw_target = re.sub(r'\btomorrow\b', '', raw_target, flags=re.IGNORECASE).strip(" '\". ")
                has_explicit_date = True
            elif "today" in raw_target.lower():
                rel_date = "today"
                norm_date = now.strftime("%Y-%m-%d")
                raw_target = re.sub(r'\btoday\b', '', raw_target, flags=re.IGNORECASE).strip(" '\". ")
                has_explicit_date = True
            else:
                m_d = cls._parse_date_str(raw_target)
                if m_d:
                    norm_date = m_d
                    rel_date = m_d
                    has_explicit_date = True

            # Clean explicit date tokens from raw_target
            raw_target = re.sub(r'\b(?:on|for|at)?\s*\d{4}-\d{2}-\d{2}\b', '', raw_target, flags=re.IGNORECASE)
            for m_name in cls.MONTHS.keys():
                raw_target = re.sub(rf'\b(?:on|for)?\s*{m_name}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:\s*,\s*\d{{4}})?\b', '', raw_target, flags=re.IGNORECASE)
                raw_target = re.sub(rf'\b(?:on|for)?\s*\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?{m_name}(?:\s*,\s*\d{{4}})?\b', '', raw_target, flags=re.IGNORECASE)

            # Check for occurrence vs series scope
            if any(w in text_lower for w in ["all occurrences", "series", "entire series", "every occurrence", "all instances"]):
                scope = "series"
            elif any(w in text_lower for w in ["this occurrence", "this instance", "single occurrence", "just this one", "only the", "occurrence of"]) or has_explicit_date:
                scope = "occurrence"
            else:
                scope = "series"

            # Time filter inside delete command (e.g. "Cancel the one at 3 PM, not the one at 5 PM")
            filter_time = None
            m_filter_time = re.search(r'\b(?:the\s+one\s+at|at)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b', raw_target, re.IGNORECASE)
            if m_filter_time:
                filter_time = cls._parse_time_str(m_filter_time.group(1)) or m_filter_time.group(1).strip()

            # Clean trailing instructions like "not the one at 5 PM" or "I created yesterday"
            raw_target = re.split(r'\bnot\s+the\s+one\b', raw_target, flags=re.IGNORECASE)[0]
            raw_target = re.sub(r'\b(?:i\s+created|i\s+scheduled|i\s+added)\b', '', raw_target, flags=re.IGNORECASE)

            if filter_time:
                raw_target = re.sub(r'\b(?:the\s+one|one)?\s*(?:at\s+)?\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b', '', raw_target, flags=re.IGNORECASE)

            raw_target = re.sub(r'\b(?:only\s+the|the|only|single|this)?\s*(?:occurrence\s+of|instance\s+of)\b', '', raw_target, flags=re.IGNORECASE)
            raw_target = re.sub(r'\b(?:occurrence|instance)\b', '', raw_target, flags=re.IGNORECASE)
            raw_target = re.sub(r'\b(?:called|named)\s+', '', raw_target, flags=re.IGNORECASE)
            if not re.search(r'\b(?:one[- ]on[- ]one|1[- ]on[- ]1)\b', raw_target, re.IGNORECASE):
                raw_target = re.sub(r'\b(?:the\s+one|one)\b', '', raw_target, flags=re.IGNORECASE)
            raw_target = re.sub(r'[\s,\.]+', ' ', raw_target).strip(" '\". ,")
            title = raw_target if raw_target else "meeting"
            return {
                "action": "delete",
                "subject": "personal_event",
                "entities": {
                    "event_title": title,
                    "scope": scope,
                    "filter_time": filter_time
                },
                "temporal_context": {
                    "relative_date": rel_date if has_explicit_date else None,
                    "normalized_date": norm_date if has_explicit_date else None,
                    "has_explicit_date": has_explicit_date
                }
            }

        # 17. Date Range View
        m_range = re.search(r'\b(?:from|between)\s+(.+?)\s+(?:to|and|-)\s+(.+)', text_clean, re.IGNORECASE)
        if m_range and any(k in text_lower for k in ["event", "events", "calendar", "schedule", "meeting", "meetings"]):
            part1, part2 = m_range.group(1), m_range.group(2)
            m_y = re.search(r'\b(\d{4})\b', part2) or re.search(r'\b(\d{4})\b', part1)
            yr = int(m_y.group(1)) if m_y else now.year
            d1 = cls._parse_date_str(part1, fallback_year=yr)
            d2 = cls._parse_date_str(part2, fallback_year=yr)
            if d1 and d2:
                dt1 = datetime.strptime(d1, "%Y-%m-%d")
                dt2 = datetime.strptime(d2, "%Y-%m-%d")
                duration = max(1, (dt2 - dt1).days + 1)
                cat = cls._parse_category(text_clean)
                return {
                    "action": "view",
                    "subject": "personal_event",
                    "entities": {"category": cat} if cat else {},
                    "temporal_context": {
                        "relative_date": "range",
                        "normalized_date": d1,
                        "end_date": d2,
                        "normalized_end_date": d2,
                        "duration_days": duration
                    }
                }

        # 18. View / Agenda / Schedule listing queries
        is_view_query = bool(
            re.search(r'\b(?:show|list|view|display|check|get|see|read|tell\s+me)\b.+?\b(?:schedule|calendar|agenda|events?|appointments?|meetings?)\b', text_lower)
            or re.search(r'\b(?:what(?:\'s|\s+is)\s+(?:on|in)\s+(?:my\s+)?(?:schedule|calendar|agenda))\b', text_lower)
            or re.search(r'\bwhat\s+(?:do\s+i|do\s+we)\s+have\s+scheduled\b', text_lower)
            or re.search(r'\b(?:all\s+)?upcoming\s+(?:events?|meetings?|appointments?|schedule)\b', text_lower)
            or re.search(r'\b(?:show\s+(?:all\s+)?(?:my\s+)?upcoming\s+events?)\b', text_lower)
            or re.search(r'\b(?:my\s+)?schedule\s+calendar\b', text_lower)
            or (any(w in text_lower for w in ["calendar", "agenda"]) and not any(w in text_lower for w in ["create", "add", "book", "set up", "schedule a", "schedule an", "schedule another"]))
        )
        if is_view_query:
            rel_date = "today"
            norm_date = now.strftime("%Y-%m-%d")
            duration_days = 1
            if "tomorrow" in text_lower:
                rel_date = "tomorrow"
                norm_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
                duration_days = 1
            elif "week" in text_lower:
                rel_date = "week"
                duration_days = 7
            elif "month" in text_lower:
                rel_date = "month"
                duration_days = 30
            elif "upcoming" in text_lower or "all" in text_lower:
                rel_date = "upcoming"
                duration_days = 30
            else:
                p_date = cls._parse_date_str(text_clean)
                if p_date:
                    norm_date = p_date
                    rel_date = p_date
                    duration_days = 1
                elif "today" not in text_lower and any(k in text_lower for k in ["schedule", "calendar", "agenda", "events"]):
                    rel_date = "week"
                    duration_days = 7
            
            cat = cls._parse_category(text_clean)
            return {
                "action": "view",
                "subject": "personal_event",
                "entities": {"category": cat} if cat else {},
                "temporal_context": {
                    "relative_date": rel_date,
                    "normalized_date": norm_date,
                    "duration_days": duration_days
                }
            }

        # 19. Add / Schedule Event (with Recurrence, Duration, Location, Category)
        is_add = (not is_view_query) and bool(
            re.search(r'\b(?:create|add|schedule|shedule|book|set\s+up)\s+', text_lower)
            or re.search(r'\badd\s+.+?\s+to\s+(?:my\s+)?calendar\b', text_lower)
        )
        is_event_reminder = bool(re.search(r'\b(?:with\s+(?:a\s+)?reminder|remind(?:er)?\s+\d+\s*(?:minutes?|mins?|hours?)\s+before)\b', text_lower))
        is_pure_reminder = ("reminder" in text_lower or "remind" in text_lower) and not is_event_reminder
        if is_add and not is_pure_reminder and not any(k in text_lower for k in ["folder", "file", "directory", "note", "alarm", "timer"]):
            m_time = cls._parse_time_str(text_clean)
            has_time = bool(m_time)
            
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
                parsed_d = cls._parse_date_str(text_clean)
                if parsed_d:
                    norm_date = parsed_d
                    rel_date = parsed_d
                    has_date = True
            
            # Recurrence parsing
            recurrence = cls._parse_recurrence(text_clean)
            duration_minutes = cls._parse_duration(text_clean)
            location = cls._parse_location(text_clean)
            category = cls._parse_category(text_clean)

            # Reminder offset parsing
            reminder_minutes = None
            m_rem = re.search(r'\b(?:with\s+(?:a\s+)?reminder|remind(?:er)?)\s+(\d+)\s*(minutes?|mins?|hours?|hrs?)\s*(?:before)?\b', text_clean, re.IGNORECASE)
            if m_rem:
                val = int(m_rem.group(1))
                unit = m_rem.group(2).lower()
                if "hour" in unit or "hr" in unit:
                    val *= 60
                reminder_minutes = val
            elif is_event_reminder:
                reminder_minutes = 15

            # Check relative reference e.g. "at the same time as project review"
            m_rel = re.search(r'\b(?:at\s+the\s+same\s+time\s+as|same\s+time\s+as|at\s+the\s+time\s+of)\s+(.+)', text_clean, re.IGNORECASE)
            reference_event = None
            if m_rel:
                raw_ref = m_rel.group(1).strip(" '\". ")
                raw_ref = re.sub(r'^(?:the\s+|my\s+|our\s+)?(?:event\s+|meeting\s+)?', '', raw_ref, flags=re.IGNORECASE).strip(" '\". ")
                reference_event = raw_ref
            
            # Extract title
            title = None
            title_stopwords = {
                "a", "an", "the", "my", "our", "calendar", "event", "events", "meeting", "meetings",
                "appointment", "appointments", "today", "tomorrow", "yesterday", "monday", "tuesday",
                "wednesday", "thursday", "friday", "saturday", "sunday", "call", "review"
            }
            m_quote = re.search(r'["\']([^"\']+)["\']', text_clean)
            if m_quote:
                title = m_quote.group(1).strip()
            elif re.search(r'\b(?:called|call|named|name|titled|title|with\s+title)\s+(.+?)(?:\s+(?:on|at|for|every|tomorrow|today|\d{4}-\d{2}-\d{2})\b|$)', text_clean, re.IGNORECASE):
                m_c = re.search(r'\b(?:called|call|named|name|titled|title|with\s+title)\s+(.+?)(?:\s+(?:on|at|for|every|tomorrow|today|\d{4}-\d{2}-\d{2})\b|$)', text_clean, re.IGNORECASE)
                cand = m_c.group(1).strip(" '\". ")
                if cand.lower() not in title_stopwords:
                    title = cand
            elif re.search(r'\badd\s+(.+?)\s+to\s+(?:my\s+)?calendar\b', text_clean, re.IGNORECASE):
                m_a = re.search(r'\badd\s+(.+?)\s+to\s+(?:my\s+)?calendar\b', text_clean, re.IGNORECASE)
                cand = m_a.group(1).strip(" '\". ")
                cand = re.sub(r'\b(?:tomorrow|today|at\s+\d{1,2}.*)$', '', cand, flags=re.IGNORECASE).strip(" '\". ")
                if cand and cand.lower() not in title_stopwords:
                    title = cand
            elif re.search(r'\b(?:create|add|schedule|shedule|book|set\s+up)\s+(?:an?\s+)?(?:calendar\s+event|event|meeting|appointment)?\s*(?:called|named|titled)?\s*(.+?)\s+(?:on|at|for|every|daily\s+at|weekly\s+at|tomorrow|today|\d{4}-\d{2}-\d{2})\b', text_clean, re.IGNORECASE):
                m_s = re.search(r'\b(?:create|add|schedule|shedule|book|set\s+up)\s+(?:an?\s+)?(?:calendar\s+event|event|meeting|appointment)?\s*(?:called|named|titled)?\s*(.+?)\s+(?:on|at|for|every|daily\s+at|weekly\s+at|tomorrow|today|\d{4}-\d{2}-\d{2})\b', text_clean, re.IGNORECASE)
                cand = m_s.group(1).strip(" '\". ")
                cand = re.sub(r'\s*\b(?:daily|weekly|monthly|yearly|every\s+(?:day|week|month|year))\s*$', '', cand, flags=re.IGNORECASE).strip(" '\". ")
                # Strip relative time phrases from candidate title
                cand = re.sub(r'\b(?:at\s+the\s+same\s+time\s+as|same\s+time\s+as).*$', '', cand, flags=re.IGNORECASE).strip(" '\". ")
                if cand and cand.lower() not in title_stopwords:
                    title = cand

            if not title:
                if "meeting" in text_lower:
                    title = "Meeting"
                elif "event" in text_lower:
                    title = "Event"
                else:
                    return {
                        "action": "clarification",
                        "subject": "personal_event",
                        "message": "Please specify a title for the event."
                    }
            elif title.lower().strip() in ("syn", "team syn"):
                return {
                    "action": "clarification",
                    "subject": "personal_event",
                    "message": f"The event title '{title}' appears incomplete or ambiguous. Did you mean 'Team Sync', or please clarify the exact title."
                }

            if not has_date and not has_time and not recurrence and not reference_event:
                return {
                    "action": "clarification",
                    "subject": "personal_event",
                    "message": "Please specify a date and time for the event."
                }

            return {
                "action": "add",
                "subject": "personal_event",
                "entities": {
                    "event_title": title.title() if len(title) > 3 else title,
                    "start_time": m_time,
                    "duration_minutes": duration_minutes,
                    "location": location,
                    "category": category,
                    "recurrence": recurrence,
                    "reminder_minutes": reminder_minutes,
                    "reference_event": reference_event
                },
                "temporal_context": {
                    "relative_date": rel_date if has_date else None,
                    "normalized_date": norm_date if has_date else None,
                    "duration_days": 1,
                    "has_explicit_date": has_date
                }
            }

        # 19. Generic View / Agenda queries
        if any(w in text_lower for w in ["today", "calendar", "event", "events", "schedule", "agenda"]):
            rel_date = "today"
            norm_date = now.strftime("%Y-%m-%d")
            duration_days = 1
            if "tomorrow" in text_lower:
                rel_date = "tomorrow"
                norm_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
            elif "week" in text_lower:
                rel_date = "week"
                duration_days = 7
            elif "month" in text_lower:
                rel_date = "month"
                duration_days = 30
            else:
                p_date = cls._parse_date_str(text_clean)
                if p_date:
                    norm_date = p_date
                    rel_date = p_date
            
            cat = cls._parse_category(text_clean)
            return {
                "action": "view",
                "subject": "personal_event",
                "entities": {"category": cat} if cat else {},
                "temporal_context": {
                    "relative_date": rel_date,
                    "normalized_date": norm_date,
                    "duration_days": duration_days
                }
            }

        return {"action": "unknown", "subject": "unknown", "entities": {}, "temporal_context": {}}

def extract_calendar_intent(text: str) -> dict:
    """Convenience function for intent extraction."""
    return CalendarIntentHandler.get_intent(text)
