"""
Enhanced Reminder Handler
Comprehensive reminder management with natural language understanding,
conflict detection, and database persistence.
"""

import re
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum

class ReminderAction(Enum):
    """Types of reminder actions"""
    CREATE = "create"
    LIST = "list"
    DELETE = "delete"
    UPDATE = "update"
    CANCEL = "cancel"
    CANCEL_ALL = "cancel_all"
    DELETE_ALL = "delete_all"
    RESCHEDULE = "reschedule"
    PAUSE = "pause"
    RESUME = "resume"
    SNOOZE = "snooze"
    COMPLETE = "complete"
    DISMISS = "dismiss"
    CLEAR_HISTORY = "clear_history"
    QUERY = "query"

class ReminderHandler:
    """
    Enhanced reminder handler with natural language understanding,
    conflict detection, and database persistence.
    """
    
    def __init__(self, db_manager=None):
        """
        Initialize the reminder handler.
        
        Args:
            db_manager: DatabaseManager instance for persistence (optional)
        """
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__)
        
        # Compile regex patterns for performance
        self._compile_patterns()

    def parse_reminder_input(self, user_input: str, user_id: int = 1) -> Dict[str, Any]:
        """Convenience alias for parse_reminder_command."""
        return self.parse_reminder_command(user_input, user_id)
    
    def _compile_patterns(self):
        """Compile regex patterns for natural language parsing."""
        
        # Time patterns
        self.time_patterns = {
            # Relative time: "in 10 seconds", "in 5 minutes", "for 1 min", "in 2 hours", "in half an hour"
            'relative': re.compile(r'\b(?:in|for|after)\s+(\d+|half\s+an?)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?)\b', re.IGNORECASE),
            
            # Specific time: "at 6 PM", "at 14:30", "at 2pm", "1:00 pm", "1 pm"
            'specific': re.compile(r'(?:\bat\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b|\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b', re.IGNORECASE),
            
            # Today/tomorrow/tonight: "today at 5 PM", "tomorrow at 9 AM", "tomorrow 1:00 pm", "tonight", "tomorrow morning"
            'today_tomorrow': re.compile(r'\b(today|tomorrow|tonight)\s*(?:(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?|(?:in\s+the\s+)?(morning|afternoon|evening|night))?\b', re.IGNORECASE),
            
            # Weekdays: "Monday at 10 AM", "next Friday"
            'weekday': re.compile(r'\b(?:next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*(?:(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?)?\b', re.IGNORECASE),
            
            # Meeting reminder: "remind me 15 minutes before my meeting"
            'meeting_before': re.compile(r'\b(\d+)\s+minutes?\s+before\s+(?:my\s+)?(.+?)\s*(?:meeting|event|appointment)\b', re.IGNORECASE),
        }
        
        # Recurrence patterns
        self.recurrence_patterns = {
            'daily': re.compile(r'\b(?:every\s+day|daily)\b', re.IGNORECASE),
            'weekly': re.compile(r'\b(?:every\s+week|weekly|every\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b', re.IGNORECASE),
            'weekdays': re.compile(r'\b(?:every\s+weekday|on\s+weekdays|weekdays|workdays)\b', re.IGNORECASE),
            'weekends': re.compile(r'\b(?:every\s+weekend|on\s+weekends|weekends)\b', re.IGNORECASE),
            'monthly': re.compile(r'\b(?:every\s+month|monthly)\b', re.IGNORECASE),
            'yearly': re.compile(r'\b(?:every\s+year|yearly|annually)\b', re.IGNORECASE),
        }
    
    def _normalize_input(self, text: str) -> str:
        """Normalize common speech recognition typos, shorthand, and punctuation in times."""
        try:
            from core.unified_command_router import normalize_scheduling_text
            t = normalize_scheduling_text(text)
        except Exception:
            t = text
        _WORD_NUMS = {
            "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
            "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
            "fifteen": "15", "twenty": "20", "thirty": "30", "forty": "40",
            "forty-five": "45", "fifty": "50", "sixty": "60"
        }
        for w, n in _WORD_NUMS.items():
            t = re.sub(rf'\b{w}\b', n, t, flags=re.IGNORECASE)
        t = re.sub(r'\bshedule\b', 'schedule', t, flags=re.IGNORECASE)
        t = re.sub(r'\bshedules\b', 'schedules', t, flags=re.IGNORECASE)
        t = re.sub(r'\bmeting\b', 'meeting', t, flags=re.IGNORECASE)
        t = re.sub(r'\bmeet\b', 'meeting', t, flags=re.IGNORECASE)
        t = re.sub(r'(\d+)\s*p\.m\.', r'\1 pm', t, flags=re.IGNORECASE)
        t = re.sub(r'(\d+)\s*a\.m\.', r'\1 am', t, flags=re.IGNORECASE)
        return t

    def parse_reminder_command(self, user_input: str, user_id: int) -> Dict[str, Any]:
        """
        Parse a natural language reminder command.
        
        Args:
            user_input: The user's natural language command
            user_id: The current user's ID
            
        Returns:
            Dict with action, parameters, and any conflicts found
        """
        user_input_norm = self._normalize_input(user_input)
        user_input_lower = user_input_norm.lower().strip()
        
        # Detect the action type
        action = self._detect_action(user_input_lower)
        
        # Parse based on action type
        if action == ReminderAction.CANCEL_ALL or action == ReminderAction.DELETE_ALL:
            return self._parse_bulk_delete_command(user_input, user_input_lower, user_id)
        elif action == ReminderAction.CLEAR_HISTORY:
            return self._parse_clear_history_command(user_input, user_input_lower, user_id)
        elif action == ReminderAction.PAUSE:
            return self._parse_pause_command(user_input, user_input_lower, user_id)
        elif action == ReminderAction.RESUME:
            return self._parse_resume_command(user_input, user_input_lower, user_id)
        elif action == ReminderAction.SNOOZE:
            return self._parse_snooze_command(user_input, user_input_lower, user_id)
        elif action in (ReminderAction.COMPLETE, ReminderAction.DISMISS):
            return self._parse_complete_command(user_input, user_input_lower, user_id, action)
        elif action == ReminderAction.CREATE:
            return self._parse_create_command(user_input, user_input_lower, user_id)
        elif action == ReminderAction.LIST:
            return self._parse_list_command(user_input, user_input_lower, user_id)
        elif action == ReminderAction.DELETE or action == ReminderAction.CANCEL:
            return self._parse_delete_command(user_input, user_input_lower, user_id)
        elif action == ReminderAction.UPDATE or action == ReminderAction.RESCHEDULE:
            return self._parse_update_command(user_input, user_input_lower, user_id)
        else:
            return {
                "status": "error",
                "message": "I couldn't understand what you want to do with reminders. Try phrases like 'remind me to call Mom at 6 PM' or 'show my reminders'.",
                "action": None
            }
    
    def _detect_action(self, text: str) -> Optional[ReminderAction]:
        """Detect the type of reminder action from text."""
        # 1. Clear history / completed / missed
        if re.search(r'\b(?:clear|delete|remove|purge)\s+(?:all\s+)?(?:of\s+)?(?:the\s+|my\s+)?(?:reminder\s+history|history|completed\s+reminders|missed\s+reminders|overdue\s+reminders)\b', text):
            return ReminderAction.CLEAR_HISTORY
        
        # 2. Bulk cancellation / deletion ("cancel all my reminders", "cancel all my schedules", "remove all the reminders", "delete all reminders", "cancel all meeting reminders", "cancel all reminders for today")
        if re.search(r'\b(?:cancel|delete|remove|clear|purge)\b', text) and re.search(r'\b(?:reminders?|schedules?)\b', text):
            if re.search(r'\b(?:all|every)\b', text) or text.startswith(('cancel all', 'delete all', 'remove all', 'clear all')):
                return ReminderAction.CANCEL_ALL
            if re.search(r'\b(?:reminders|schedules)\b', text) and not re.search(r'#\d+|\bnumber\s+\d+', text):
                if not re.search(r'\bto\s+[a-zA-Z]', text):
                    return ReminderAction.CANCEL_ALL

        # 3. Single cancel / delete
        if re.search(r'\b(?:delete|remove|cancel)\s+(?:my\s+)?(?:the\s+)?(?:reminder|schedule)', text):
            return ReminderAction.DELETE
        if re.search(r'\b(?:delete|remove|cancel)\s+(?:reminder\s+)?(?:#\d+|number\s+\d+|\d+)\b', text):
            return ReminderAction.DELETE

        # 4. Pause / Resume
        if re.search(r'\bpause\s+(?:all\s+)?(?:my\s+)?(?:the\s+)?(?:reminders?|schedules?)\b', text) or text in ("pause reminders", "pause my reminders", "pause schedules"):
            return ReminderAction.PAUSE
        if re.search(r'\bresume\s+(?:all\s+)?(?:my\s+)?(?:the\s+)?(?:reminders?|schedules?)\b', text) or text in ("resume reminders", "resume my reminders", "resume schedules"):
            return ReminderAction.RESUME

        # 5. Snooze
        if re.search(r'\bsnooze\b', text):
            return ReminderAction.SNOOZE

        # 6. Complete / Dismiss
        if re.search(r'\b(?:mark\s+(?:the\s+|this\s+|my\s+)?(?:reminder|schedule)?(?:\s*#?\d+)?\s*(?:as\s+)?(?:done|complete|completed|finished)|complete\s+(?:the\s+|this\s+|my\s+)?(?:reminder|schedule)|dismiss\s+(?:the\s+|this\s+|my\s+)?(?:reminder|schedule))\b', text):
            return ReminderAction.COMPLETE

        # 7. Update / Reschedule / Postpone / Move
        if re.search(r'\b(?:change|update|modify|move|reschedule|postpone|delay|defer)\b', text) and re.search(r'\b(?:reminder|schedule|#\d+|that|it)\b', text):
            return ReminderAction.UPDATE

        # 8. List / Query
        if re.search(r'^\s*(?:my\s+|the\s+)?(?:reminders|schedules)\s*$', text):
            return ReminderAction.LIST
        if re.search(r'\b(?:show|list|get|view|check|what)\b', text) and re.search(r'\b(?:reminders?|schedules?|scheduled)\b', text):
            return ReminderAction.LIST
        if re.search(r'\bdo\s+i\s+have\s+(?:any\s+)?(?:reminders|schedules|anything\s+scheduled)\b', text):
            return ReminderAction.LIST
        if re.search(r'\bwhat\s+do\s+i\s+have\s+(?:tomorrow|today|this\s+week)', text):
            return ReminderAction.LIST
        if re.search(r'\b(?:all\s+)?my\s+(?:reminders|schedules)\b', text):
            return ReminderAction.LIST
        if re.search(r'\b(?:show|list|check)\s+(?:my\s+)?(?:overdue|missed|completed|history)\b', text):
            return ReminderAction.LIST
        if re.search(r'\b(?:search|find)\s+(?:reminders?|schedules?)\b', text):
            return ReminderAction.LIST

        # 9. Create
        if re.search(r'^\s*(?:can\s+you\s+|please\s+)?(?:schedule|shedule)\b(?!\s+(?:phone|call\s+to\b))', text):
            return ReminderAction.CREATE
        if re.search(r'\b(?:schedule|book|set\s+up)\s+(?:a\s+|an\s+)?(?:reminder|meeting|call|task|appointment|event|something|session)\b', text):
            return ReminderAction.CREATE
        if re.search(r'\bset\s+(?:a\s+)?(?:reminder|meeting|appointment|schedule)\s+(?:to|for|at)?\b', text):
            return ReminderAction.CREATE
        if re.search(r'\bremind\s+me\s+(?:to\s+)?', text):
            return ReminderAction.CREATE
        if re.search(r'\balert\s+me\s+(?:to\s+)?', text):
            return ReminderAction.CREATE
        if re.search(r'\breminder\s+(?:to\s+)?', text):
            return ReminderAction.CREATE
        if re.search(r'\bremember\s+to\s+', text):
            return ReminderAction.CREATE

        return None
    
    def _parse_create_command(self, original_input: str, text: str, user_id: int) -> Dict[str, Any]:
        """Parse a reminder creation command."""
        result = {
            "action": ReminderAction.CREATE,
            "task_text": None,
            "due_at": None,
            "recurrence": None,
            "description": None,
            "conflicts": [],
            "status": "pending"
        }
        
        # Check for explicit description / note
        m_desc = re.search(r'\b(?:with\s+description|with\s+note|description:|note:)\s+(.+)$', original_input.strip(), re.IGNORECASE)
        clean_input = original_input.strip()
        clean_text = text
        if m_desc:
            result["description"] = m_desc.group(1).strip()
            clean_input = re.sub(r'\b(?:with\s+description|with\s+note|description:|note:)\s+.+$', '', clean_input, flags=re.IGNORECASE).strip()
            clean_text = re.sub(r'\b(?:with\s+description|with\s+note|description:|note:)\s+.+$', '', clean_text, flags=re.IGNORECASE).strip()

        # 1. Contextual reminder pattern (e.g. "tomorrow i have to go to movie at 3pm so can you remind me at 2pm")
        m_context = re.search(r'^(.*?)(?:,\s*|\s+so\s+(?:can\s+you\s+|could\s+you\s+|please\s+)?|\s+can\s+you\s+|\s+could\s+you\s+|\s+please\s+)remind\s+me\s+(?:at\s+|in\s+|before\s+|to\s+)(.+)$', clean_input, re.IGNORECASE)
        if m_context and m_context.group(1).strip():
            pre_clause = m_context.group(1).strip()
            reminder_directive = m_context.group(2).strip()
            
            is_tomorrow = 'tomorrow' in pre_clause.lower() or 'tomorrow' in reminder_directive.lower()
            now = datetime.now()
            base_date = now + timedelta(days=1) if is_tomorrow else now
            
            clean_task = re.sub(r'^(?:tomorrow|today)\s*,?\s*', '', pre_clause, flags=re.IGNORECASE)
            clean_task = re.sub(r'^(?:i\s+have\s+to|i\s+need\s+to|i\s+must|i\'m\s+going\s+to|i\s+plan\s+to)\s+', '', clean_task, flags=re.IGNORECASE).strip()
            
            due_at = None
            m_rel = re.search(r'\bin\s+(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?)\b', reminder_directive, re.IGNORECASE)
            if not m_rel:
                m_rel = re.search(r'\b(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?)\b', reminder_directive, re.IGNORECASE)
            
            if m_rel:
                amt = int(m_rel.group(1))
                u = m_rel.group(2).lower()
                if 'sec' in u: delta = timedelta(seconds=amt)
                elif 'min' in u: delta = timedelta(minutes=amt)
                elif 'hour' in u or 'hr' in u: delta = timedelta(hours=amt)
                elif 'day' in u: delta = timedelta(days=amt)
                else: delta = timedelta(weeks=amt)
                due_at = now + delta
            else:
                m_time = re.search(r'\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b', reminder_directive, re.IGNORECASE)
                if m_time:
                    hour = int(m_time.group(1))
                    minute = int(m_time.group(2)) if m_time.group(2) else 0
                    ampm = (m_time.group(3) or 'am').lower()
                    if ampm == 'pm' and hour != 12: hour += 12
                    elif ampm == 'am' and hour == 12: hour = 0
                    due_at = base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            if due_at:
                result["task_text"] = clean_task or "go to movie at 3pm"
                result["due_at"] = due_at.strftime("%Y-%m-%d %H:%M:%S")
                if self.db_manager:
                    conflicts = self.db_manager.check_reminder_conflicts(user_id, result["due_at"])
                    if conflicts:
                        result["conflicts"] = conflicts
                        result["status"] = "conflict"
                        conflict_texts = [f"'{c['task_text']}' at {c['due_at']}" for c in conflicts]
                        return {
                            "status": "conflict",
                            "message": f"You already have {', '.join(conflict_texts)}. Would you like to reschedule one of them?",
                            "action": ReminderAction.CREATE,
                            "proposed_reminder": result,
                            "conflicts": conflicts
                        }
                result["status"] = "ready"
                return result

        # Extract task text
        result["task_text"] = self._extract_task_text(clean_input, clean_text)
        
        if not result["task_text"]:
            return {
                "status": "error",
                "message": "What would you like me to remind you about?",
                "action": ReminderAction.CREATE
            }
        
        # Parse time
        time_result = self._parse_time(clean_text)
        if not time_result:
            return {
                "status": "error",
                "message": "When should I remind you? Please specify a time like 'at 6 PM' or 'in 30 minutes'.",
                "action": ReminderAction.CREATE
            }
        if time_result.get("is_past"):
            return {
                "status": "error",
                "error_type": "temporal_failure",
                "message": time_result.get("error_message", "The requested time has already passed today."),
                "action": ReminderAction.CREATE
            }
        
        result["due_at"] = time_result["due_at"]
        
        # Check for conflicts
        if self.db_manager:
            conflicts = self.db_manager.check_reminder_conflicts(user_id, result["due_at"])
            if conflicts:
                result["conflicts"] = conflicts
                result["status"] = "conflict"
                conflict_texts = [f"'{c['task_text']}' at {c['due_at']}" for c in conflicts]
                return {
                    "status": "conflict",
                    "message": f"You already have {', '.join(conflict_texts)}. Would you like to reschedule one of them?",
                    "action": ReminderAction.CREATE,
                    "proposed_reminder": result,
                    "conflicts": conflicts
                }
        
        # Check for recurrence
        result["recurrence"] = self._parse_recurrence(clean_text)
        
        due_str = result.get("due_at") or ""
        time_formatted = None
        if len(due_str) >= 16:
            try:
                time_formatted = datetime.strptime(due_str[11:16], "%H:%M").strftime("%I:%M %p")
            except Exception:
                time_formatted = due_str[11:]
        result["operation"] = "create"
        result["action"] = ReminderAction.CREATE
        result["task"] = result["task_text"]
        result["subject"] = result["task_text"]
        result["date"] = due_str[:10] if due_str else None
        result["time"] = time_formatted or (due_str[11:] if due_str else None)
        result["timezone"] = "Asia/Kolkata"
        result["structured"] = {
            "operation": "create",
            "subject": result["task_text"],
            "date": result["date"],
            "time": time_formatted or result["time"],
            "recurrence": result.get("recurrence"),
            "description": result.get("description"),
            "timezone": result["timezone"]
        }
        
        result["status"] = "ready"
        return result
    
    def _parse_list_command(self, original_input: str, text: str, user_id: int) -> Dict[str, Any]:
        """Parse a reminder list/query command."""
        result = {
            "action": ReminderAction.LIST,
            "scope": "upcoming",
            "start_date": None,
            "end_date": None,
            "query": None,
            "status": "ready"
        }
        
        # Detect scope
        if "overdue" in text or "missed" in text:
            result["scope"] = "missed"
        elif "completed" in text or "history" in text or "past" in text:
            result["scope"] = "completed"
        elif "paused" in text:
            result["scope"] = "paused"
        elif "tomorrow" in text:
            result["scope"] = "tomorrow"
            tomorrow = datetime.now() + timedelta(days=1)
            result["start_date"] = tomorrow.date()
            result["end_date"] = tomorrow.date()
        elif "today" in text:
            result["scope"] = "today"
            today = datetime.now().date()
            result["start_date"] = today
            result["end_date"] = today
        elif "this week" in text:
            result["scope"] = "this_week"
            today = datetime.now().date()
            result["start_date"] = today
            result["end_date"] = today + timedelta(days=7)
        elif "recurring" in text:
            result["scope"] = "recurring"
        elif "all" in text and ("every" in text or "everything" in text or "including" in text):
            result["scope"] = "all"
        else:
            result["scope"] = "upcoming"
            
        # Detect search keyword if any
        m_search = re.search(r'\b(?:search|find|about)\s+(?:reminders?\s+(?:about|for)\s+)?([a-zA-Z0-9_\-]+)\b', text)
        if not m_search and result["scope"] == "upcoming":
            m_search = re.search(r'\bfor\s+([a-zA-Z0-9_\-]+)\b', text)
        if m_search:
            kw = m_search.group(1).lower()
            if kw not in ("reminders", "schedules", "all", "my", "the", "upcoming", "future", "today", "tomorrow", "this", "next", "week", "month", "year", "history", "missed", "overdue", "recurring", "active", "paused", "completed"):
                result["query"] = kw

        return result
    
    def _parse_bulk_delete_command(self, original_input: str, text: str, user_id: int) -> Dict[str, Any]:
        """Parse bulk deletion command e.g. 'cancel all my reminders' with confirmation guard."""
        scope = "upcoming"
        if "today" in text:
            scope = "today"
        elif "this week" in text:
            scope = "this_week"
        elif "tomorrow" in text:
            scope = "tomorrow"
        elif "completed" in text:
            scope = "completed"
        elif "missed" in text or "overdue" in text:
            scope = "missed"
        elif "recurring" in text:
            scope = "recurring"
        elif "including history" in text or "all reminders and history" in text:
            scope = "all"

        filter_text = None
        m_topic = re.search(r'\b(?:all\s+)?([a-zA-Z0-9_\-]+)\s+(?:reminders|schedules)\b', text)
        if m_topic:
            w = m_topic.group(1).lower()
            if w not in ("my", "the", "all", "our", "upcoming", "future", "today", "tomorrow", "this", "active"):
                filter_text = w

        count = 0
        if self.db_manager:
            rems = self.db_manager.get_reminders(user_id, scope=scope)
            if filter_text:
                rems = [r for r in rems if filter_text.lower() in r.get("task_text", "").lower()]
            count = len(rems)

        if count == 0:
            scope_desc = f"{scope} " if scope != "upcoming" else "upcoming "
            if filter_text:
                scope_desc += f"'{filter_text}' "
            return {
                "status": "ready",
                "action": ReminderAction.CANCEL_ALL,
                "scope": scope,
                "filter_text": filter_text,
                "count": 0,
                "message": f"You have no {scope_desc}reminders to cancel."
            }

        is_confirmed = bool(
            re.search(r'\b(?:yes|confirm|confirmed|force|i am sure)\b', text)
            or text.endswith('--force')
        )

        if is_confirmed:
            return {
                "status": "ready",
                "action": ReminderAction.CANCEL_ALL,
                "scope": scope,
                "filter_text": filter_text,
                "count": count
            }

        scope_str = f" for {scope}" if scope in ("today", "tomorrow", "this_week") else f" {scope}" if scope != "upcoming" else " upcoming"
        item_str = f"'{filter_text}' " if filter_text else ""
        msg = f"You have {count}{scope_str} {item_str}reminder{'s' if count != 1 else ''}. Are you sure you want to cancel all of them?"

        return {
            "status": "needs_confirmation",
            "action": ReminderAction.CANCEL_ALL,
            "scope": scope,
            "filter_text": filter_text,
            "count": count,
            "message": msg
        }

    def _parse_clear_history_command(self, original_input: str, text: str, user_id: int) -> Dict[str, Any]:
        """Parse clear history command with confirmation guard."""
        count = 0
        if self.db_manager:
            completed = self.db_manager.get_reminders(user_id, scope="completed")
            missed = self.db_manager.get_reminders(user_id, scope="missed")
            count = len(completed) + len(missed)

        if count == 0:
            return {
                "status": "ready",
                "action": ReminderAction.CLEAR_HISTORY,
                "count": 0,
                "message": "Your reminder history is already empty."
            }

        is_confirmed = bool(re.search(r'\b(?:yes|confirm|confirmed|force)\b', text))
        if is_confirmed:
            return {
                "status": "ready",
                "action": ReminderAction.CLEAR_HISTORY,
                "count": count
            }

        return {
            "status": "needs_confirmation",
            "action": ReminderAction.CLEAR_HISTORY,
            "count": count,
            "message": f"Are you sure you want to clear your reminder history ({count} item{'s' if count != 1 else ''})?"
        }

    def _parse_pause_command(self, original_input: str, text: str, user_id: int) -> Dict[str, Any]:
        """Parse pause reminder command."""
        is_all = bool(re.search(r'\b(?:all|every)\b', text) or text in ("pause reminders", "pause my reminders", "pause schedules"))
        reminder_id = None
        id_match = re.search(r'#(\d+)', text) or re.search(r'number\s+(\d+)', text)
        if id_match:
            reminder_id = int(id_match.group(1))

        return {
            "status": "ready",
            "action": ReminderAction.PAUSE,
            "is_all": is_all,
            "reminder_id": reminder_id
        }

    def _parse_resume_command(self, original_input: str, text: str, user_id: int) -> Dict[str, Any]:
        """Parse resume reminder command."""
        is_all = bool(re.search(r'\b(?:all|every)\b', text) or text in ("resume reminders", "resume my reminders", "resume schedules"))
        reminder_id = None
        id_match = re.search(r'#(\d+)', text) or re.search(r'number\s+(\d+)', text)
        if id_match:
            reminder_id = int(id_match.group(1))

        return {
            "status": "ready",
            "action": ReminderAction.RESUME,
            "is_all": is_all,
            "reminder_id": reminder_id
        }

    def _parse_snooze_command(self, original_input: str, text: str, user_id: int) -> Dict[str, Any]:
        """Parse snooze reminder command."""
        minutes = 10
        m_rel = re.search(r'\b(\d+)\s*(?:minutes?|mins?)\b', text)
        if m_rel:
            minutes = int(m_rel.group(1))
        elif "half an hour" in text or "30 minutes" in text:
            minutes = 30
        elif "hour" in text:
            minutes = 60

        reminder_id = None
        id_match = re.search(r'#(\d+)', text) or re.search(r'number\s+(\d+)', text)
        if id_match:
            reminder_id = int(id_match.group(1))

        return {
            "status": "ready",
            "action": ReminderAction.SNOOZE,
            "minutes": minutes,
            "reminder_id": reminder_id
        }

    def _parse_complete_command(self, original_input: str, text: str, user_id: int, action: ReminderAction) -> Dict[str, Any]:
        """Parse complete or dismiss command."""
        reminder_id = None
        id_match = re.search(r'#(\d+)', text) or re.search(r'number\s+(\d+)', text) or re.search(r'\b(\d+)\b', text)
        if id_match:
            reminder_id = int(id_match.group(1))

        return {
            "status": "ready",
            "action": action,
            "reminder_id": reminder_id,
            "task_text": self._extract_task_text(original_input, text)
        }

    def _parse_delete_command(self, original_input: str, text: str, user_id: int) -> Dict[str, Any]:
        """Parse a single reminder deletion command."""
        result = {
            "action": ReminderAction.DELETE,
            "reminder_id": None,
            "task_text": None,
            "time_filter": None,
            "candidates": [],
            "status": "pending"
        }
        
        # Try to extract reminder ID (if user specifies it)
        id_match = re.search(r'#(\d+)', text)
        if not id_match:
            id_match = re.search(r'number\s+(\d+)', text)
        if not id_match:
            id_match = re.search(r'\breminder\s+(\d+)\b', text)
        if id_match:
            result["reminder_id"] = int(id_match.group(1))
            result["status"] = "ready"
            return result
        
        # Try to extract task text for matching
        result["task_text"] = self._extract_task_text(original_input, text)
        
        # Try to extract time filter
        time_result = self._parse_time(text)
        if time_result:
            result["time_filter"] = time_result["due_at"]
        
        # Find matching upcoming reminders
        reminders = self.db_manager.get_reminders(user_id, scope="upcoming") if self.db_manager else []
        
        # Filter by task text if provided
        if result["task_text"]:
            reminders = [r for r in reminders if result["task_text"].lower() in r["task_text"].lower()]
        
        # Filter by time if provided
        if result["time_filter"]:
            reminders = [r for r in reminders if str(r["due_at"]) == str(result["time_filter"])]
        
        result["candidates"] = reminders
        
        if len(reminders) == 0:
            return {
                "status": "error",
                "message": "I couldn't find any upcoming reminder matching that description.",
                "action": ReminderAction.DELETE
            }
        elif len(reminders) == 1:
            result["reminder_id"] = reminders[0]["id"]
            result["task_text"] = reminders[0]["task_text"]
            result["status"] = "ready"
        else:
            result["status"] = "ambiguous"
            candidate_list = [f"#{r['id']}: '{r['task_text']}' at {r['due_at']}" for r in reminders]
            result["message"] = f"I found {len(reminders)} matching reminders: {'; '.join(candidate_list)}. Which one would you like to cancel?"
        
        return result
    
    def _parse_update_command(self, original_input: str, text: str, user_id: int) -> Dict[str, Any]:
        """Parse a reminder update/reschedule command."""
        result = {
            "action": ReminderAction.UPDATE,
            "reminder_id": None,
            "new_task_text": None,
            "new_due_at": None,
            "candidates": [],
            "conflicts": [],
            "status": "pending"
        }
        
        # Try to extract reminder ID
        id_match = re.search(r'#(\d+)', text) or re.search(r'number\s+(\d+)', text) or re.search(r'\breminder\s+(\d+)\b', text)
        if id_match:
            result["reminder_id"] = int(id_match.group(1))
        
        # Extract new time - remove the ID part first to avoid interference
        text_for_time = re.sub(r'number\s+\d+', '', text)
        text_for_time = re.sub(r'#\d+', '', text_for_time)
        time_result = self._parse_time(text_for_time)
        if time_result:
            result["new_due_at"] = time_result["due_at"]
        
        # Extract new task text (if any)
        result["new_task_text"] = self._extract_task_text(original_input, text)
        if result["new_task_text"]:
            clean_t = re.sub(r'#\d+|number\s+\d+|\b(?:to|at|for|tomorrow|today|tonight)\b', '', result["new_task_text"], flags=re.IGNORECASE).strip()
            if not clean_t or len(clean_t) < 3 or clean_t.lower() in ("tomorrow", "today", "pm", "am"):
                result["new_task_text"] = None
            else:
                result["new_task_text"] = clean_t
        
        # If no reminder ID specified, try to find matching upcoming reminder
        if not result["reminder_id"] and self.db_manager:
            upcoming = self.db_manager.get_reminders(user_id, scope="upcoming")
            if result["new_task_text"]:
                matches = [r for r in upcoming if result["new_task_text"].lower() in r["task_text"].lower()]
                if len(matches) == 1:
                    result["reminder_id"] = matches[0]["id"]
            if not result["reminder_id"] and len(upcoming) == 1:
                result["reminder_id"] = upcoming[0]["id"]

        if result["reminder_id"]:
            result["status"] = "ready"
        else:
            result["status"] = "ambiguous"
            result["message"] = "Which reminder would you like to reschedule?"
        
        return result

    def _extract_task_text(self, original_input: str, text: str) -> Optional[str]:
        """Extract clean task or event title from a reminder command."""
        orig = original_input.strip()
        t = orig
        
        # Normalize speech errors
        t = re.sub(r'\b(?:shedule|scedule|skedule)\b', 'schedule', t, flags=re.I)
        
        # 1. Clean directive prefixes while preserving event descriptions
        if re.match(r'^\s*(?:can\s+you\s+|please\s+|could\s+you\s+)?remind\s+me\s+to\s+', t, re.I):
            t = re.sub(r'^\s*(?:can\s+you\s+|please\s+|could\s+you\s+)?remind\s+me\s+to\s+', '', t, flags=re.I)
        elif re.match(r'^\s*(?:can\s+you\s+|please\s+|could\s+you\s+)?(?:remind\s+me|remember\s+to|alert\s+me\s+to|alert\s+me)\s+', t, re.I):
            t = re.sub(r'^\s*(?:can\s+you\s+|please\s+|could\s+you\s+)?(?:remind\s+me|remember\s+to|alert\s+me\s+to|alert\s+me)\s+', '', t, flags=re.I)
        elif re.match(r'^\s*(?:can\s+you\s+|please\s+|could\s+you\s+)?(?:schedule|set\s+up|book|create|add|set)\s+(?:a\s+|an\s+)?(?:meeting|meet|call|appointment|session|discussion)\s+with\s+', t, re.I):
            t = re.sub(r'^\s*(?:can\s+you\s+|please\s+|could\s+you\s+)?(?:schedule|set\s+up|book|create|add|set)\s+(?:a\s+|an\s+)?', '', t, flags=re.I)
        elif re.match(r'^\s*(?:can\s+you\s+|please\s+|could\s+you\s+)?(?:schedule|set\s+up|book|create|add|set)\s+(?:a\s+|an\s+)?(?:reminder|schedule)\s+(?:to\s+|for\s+)?', t, re.I):
            t = re.sub(r'^\s*(?:can\s+you\s+|please\s+|could\s+you\s+)?(?:schedule|set\s+up|book|create|add|set)\s+(?:a\s+|an\s+)?(?:reminder|schedule)\s+(?:to\s+|for\s+)?', '', t, flags=re.I)
        elif re.match(r'^\s*(?:can\s+you\s+|please\s+|could\s+you\s+)?(?:schedule|set\s+up|book|create|add|set)\s+', t, re.I):
            t = re.sub(r'^\s*(?:can\s+you\s+|please\s+|could\s+you\s+)?(?:schedule|set\s+up|book|create|add|set)\s+(?:a\s+|an\s+)?', '', t, flags=re.I)
        elif re.match(r'^\s*(?:delete|remove|cancel|change|update|modify|move)\s+(?:all\s+)?(?:my\s+)?(?:the\s+)?(?:reminders?|schedules?|meetings?)\s*(?:to\s+|for\s+|about\s+)?', t, re.I):
            t = re.sub(r'^\s*(?:delete|remove|cancel|change|update|modify|move)\s+(?:all\s+)?(?:my\s+)?(?:the\s+)?(?:reminders?|schedules?|meetings?)\s*(?:to\s+|for\s+|about\s+)?', '', t, flags=re.I)
        
        # 2. Time and temporal removals
        time_removals = [
            r'\b(?:on|for|at|after|in)\s+(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*\d{4})?\b',
            r'\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*\d{4})?\b',
            r'\b(?:at\s+)?\d{1,2}(?::\d{2})?\s*(?:am|pm)\b',
            r'\b(?:at\s+)?\d{1,2}(?::\d{2})?\s+(?:in\s+the\s+)?(?:morning|afternoon|evening|night)\b',
            r'\b(?:on\s+)?(?:the\s+)?(?:first|second|third|fourth|last)\s+(?:day|monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+of\s+[^,.]+)?\b',
            r'\b(?:every\s+day|daily|every\s+week|weekly|every\s+month|monthly|every\s+year|yearly|annually)\b',
            r'\b(?:every\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
            r'\b(?:next\s+|this\s+)(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
            r'\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b',
            r'\b(?:two|three|\d+)\s*(?:weeks?|days?|months?)\s+(?:from\s+now|later)\b',
            r'\b(?:in|after)\s+\d+\s*(?:minutes?|mins?|hours?|hrs?|days?|weeks?|months?)\b',
            r'\bfor\s+(?:tomorrow|today|tonight)\b',
            r'\b(?:today|tomorrow|tonight)\b',
            r'\bfor\s+\d{4}-\d{2}-\d{2}\b',
            r'\b\d{4}-\d{2}-\d{2}\b',
        ]
        for tr in time_removals:
            t = re.sub(tr, '', t, flags=re.I)
            
        t = re.sub(r'^\s*(?:to|for|at|on)\s+', '', t, flags=re.I)
        t = re.sub(r'\s+(?:at|for|on|to|next|this)\s*$', '', t, flags=re.I)
        t = t.strip()
        
        if not t:
            if re.search(r'\b(?:meeting|meet)\b', orig, re.I):
                return "Meeting"
            elif re.search(r'\b(?:schedule)\b', orig, re.I):
                return "Scheduled event"
            else:
                return "Reminder"
                
        # Preserve acronyms like UROP
        t = re.sub(r'\burop\b', 'UROP', t, flags=re.I)
        return t[:1].upper() + t[1:]

    def _extract_clock_time(self, text: str) -> Optional[Tuple[int, int]]:
        """Extract hour and minute (24h) from text."""
        # 1. 'at 8 in the morning', 'at 5 in the evening'
        m_mod = re.search(r'\bat\s+(\d{1,2})(?::(\d{2}))?\s+(?:in\s+the\s+)?(morning|afternoon|evening|night)\b', text, re.I)
        if m_mod:
            h = int(m_mod.group(1))
            m = int(m_mod.group(2)) if m_mod.group(2) else 0
            part = m_mod.group(3).lower()
            if part in ('evening', 'night') and h < 12: h += 12
            elif part == 'afternoon' and h < 12 and h != 12: h += 12
            elif part == 'morning' and h == 12: h = 0
            return (h, m)

        # 2. 12-hour: 3 PM, 3:30 pm, 7:30 am, 11:59 pm
        m12 = re.search(r'\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b', text, re.I)
        if m12:
            h = int(m12.group(1))
            m = int(m12.group(2)) if m12.group(2) else 0
            ampm = m12.group(3).lower()
            if ampm == 'pm' and h != 12: h += 12
            elif ampm == 'am' and h == 12: h = 0
            return (h, m)

        # 3. 24-hour: 18:45, 14:30
        m24 = re.search(r'\b(?:at\s+)?([01]?\d|2[0-3]):([0-5]\d)\b', text, re.I)
        if m24:
            return (int(m24.group(1)), int(m24.group(2)))

        # 4. part of day alone: morning -> 9am, afternoon -> 2pm, evening -> 6pm, night -> 8pm
        if 'in the morning' in text or 'morning' in text: return (9, 0)
        if 'in the afternoon' in text or 'afternoon' in text: return (14, 0)
        if 'in the evening' in text or 'evening' in text: return (18, 0)
        if 'at night' in text or 'tonight' in text: return (20, 0)
        return None

    def _parse_time(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse time from text and return due_at timestamp."""
        now = datetime.now()

        # ISO date: YYYY-MM-DD (e.g. 2026-11-07)
        m_iso = re.search(r'\b(\d{4})-(\d{2})-(\d{2})\b', text)
        if m_iso:
            try:
                y, m, d = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
                clock = self._extract_clock_time(text)
                hour, minute = clock if clock else (9, 0)
                due_at = datetime(y, m, d, hour, minute)
                return {"due_at": due_at.strftime("%Y-%m-%d %H:%M:%S"), "type": "specific_date"}
            except Exception:
                pass
        
        # 1. Relative from now: 'two weeks from now', 'in 3 days', 'after 45 minutes'
        m_from_now = re.search(r'\b(\d+|two|three|four|five|six|half\s+an?)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?|months?)\s+(?:from\s+now|later)\b', text, re.I)
        if m_from_now:
            amt_str = m_from_now.group(1).lower()
            u = m_from_now.group(2).lower()
            amt = 2 if amt_str == 'two' else 3 if amt_str == 'three' else 4 if amt_str == 'four' else 5 if amt_str == 'five' else 6 if amt_str == 'six' else int(amt_str) if amt_str.isdigit() else 1
            if 'sec' in u: due_at = now + timedelta(seconds=amt)
            elif 'min' in u: due_at = now + timedelta(minutes=amt)
            elif 'hour' in u or 'hr' in u: due_at = now + timedelta(hours=amt)
            elif 'day' in u: due_at = now + timedelta(days=amt)
            elif 'week' in u: due_at = now + timedelta(weeks=amt)
            elif 'month' in u: due_at = now + timedelta(days=amt*30)
            else: due_at = now + timedelta(minutes=amt)
            return {"due_at": due_at.strftime("%Y-%m-%d %H:%M:%S"), "type": "relative"}

        relative_match = re.search(r'\b(?:in|for|after)\s+(\d+|half\s+an?)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?|months?)\b', text, re.I)
        if relative_match:
            amount_str = relative_match.group(1).lower()
            unit = relative_match.group(2).lower()
            amount = 30 if 'half' in amount_str else int(amount_str)
            if 'sec' in unit: due_at = now + timedelta(seconds=amount)
            elif 'min' in unit: due_at = now + timedelta(minutes=amount)
            elif 'hour' in unit or 'hr' in unit: due_at = now + timedelta(hours=amount)
            elif 'day' in unit: due_at = now + timedelta(days=amount)
            elif 'week' in unit: due_at = now + timedelta(weeks=amount)
            elif 'month' in unit: due_at = now + timedelta(days=amount*30)
            else: due_at = now + timedelta(minutes=amount)
            return {"due_at": due_at.strftime("%Y-%m-%d %H:%M:%S"), "type": "relative"}
        
        # 2. Month-positional expressions: "the last Friday of December", "the first day of every month"
        m_pos = re.search(r'\b(?:the\s+)?(first|second|third|fourth|last)\s+(day|monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+of\s+(?:every\s+month|each\s+month|next\s+month|(january|february|march|april|may|june|july|august|september|october|november|december)))?', text, re.I)
        if m_pos:
            order = m_pos.group(1).lower()
            target_dow = m_pos.group(2).lower()
            target_month_name = m_pos.group(3).lower() if m_pos.group(3) else None
            
            target_year = now.year
            if target_month_name:
                month_names = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december']
                target_month = month_names.index(target_month_name) + 1
                if target_month < now.month:
                    target_year += 1
            else:
                target_month = now.month if now.day == 1 else (now.month % 12) + 1
                if target_month == 1 and now.month == 12:
                    target_year += 1
                    
            import calendar
            _, num_days = calendar.monthrange(target_year, target_month)
            
            if target_dow == "day":
                target_day = 1 if order == "first" else num_days if order == "last" else 2 if order == "second" else 3
            else:
                weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
                target_dow_num = weekdays.index(target_dow)
                matching_days = [
                    d for d in range(1, num_days + 1)
                    if datetime(target_year, target_month, d).weekday() == target_dow_num
                ]
                if order == "first": target_day = matching_days[0]
                elif order == "second": target_day = matching_days[1]
                elif order == "third": target_day = matching_days[2]
                elif order == "fourth": target_day = matching_days[3]
                elif order == "last": target_day = matching_days[-1]
                else: target_day = matching_days[0]
                
            due_at = datetime(target_year, target_month, target_day, 9, 0, 0)
            spec_time = self._extract_clock_time(text)
            if spec_time:
                due_at = due_at.replace(hour=spec_time[0], minute=spec_time[1], second=0)
            return {"due_at": due_at.strftime("%Y-%m-%d %H:%M:%S"), "type": "calendar_date"}

        # 3. Calendar dates: "November 15 at 3 PM", "January 12, 2027", "December 10 at 8 PM"
        m_cal = re.search(r'\b(?:on\s+)?(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{4}))?\b', text, re.I)
        if not m_cal:
            m_cal2 = re.search(r'\b(?:on\s+the\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)(?:\s*,?\s*(\d{4}))?\b', text, re.I)
            if m_cal2:
                m_day = int(m_cal2.group(1))
                m_month_str = m_cal2.group(2).lower()
                m_year_str = m_cal2.group(3)
            else:
                m_day = None
        else:
            m_month_str = m_cal.group(1).lower()
            m_day = int(m_cal.group(2))
            m_year_str = m_cal.group(3)

        if m_day is not None:
            month_map = {
                'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
                'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
                'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'jun': 6, 'jul': 7, 'aug': 8,
                'sep': 9, 'sept': 9, 'oct': 10, 'nov': 11, 'dec': 12
            }
            m_month = month_map.get(m_month_str, 1)
            target_year = int(m_year_str) if m_year_str else now.year
            if not m_year_str and (m_month < now.month or (m_month == now.month and m_day < now.day)):
                target_year += 1
            
            due_at = datetime(target_year, m_month, m_day, 9, 0, 0)
            spec_time = self._extract_clock_time(text)
            if spec_time:
                due_at = due_at.replace(hour=spec_time[0], minute=spec_time[1], second=0)
            return {"due_at": due_at.strftime("%Y-%m-%d %H:%M:%S"), "type": "calendar_date"}

        # 4. Day of month: "on the 5th of every month"
        m_dom = re.search(r'\b(?:on\s+the\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+(?:day\s+)?of\s+(?:every\s+month|each\s+month)\b', text, re.I)
        if m_dom:
            dom = int(m_dom.group(1))
            t_month = now.month if now.day < dom else (now.month % 12) + 1
            t_year = now.year if t_month >= now.month else now.year + 1
            due_at = datetime(t_year, t_month, min(dom, 28), 9, 0, 0)
            spec_time = self._extract_clock_time(text)
            if spec_time:
                due_at = due_at.replace(hour=spec_time[0], minute=spec_time[1], second=0)
            return {"due_at": due_at.strftime("%Y-%m-%d %H:%M:%S"), "type": "calendar_date"}

        # 5. Today / tomorrow / tonight
        today_tomorrow_match = self.time_patterns['today_tomorrow'].search(text)
        if today_tomorrow_match:
            day_ref = today_tomorrow_match.group(1).lower()
            base_date = now + timedelta(days=1) if day_ref == "tomorrow" else now
            spec_time = self._extract_clock_time(text)
            if spec_time:
                due_at = base_date.replace(hour=spec_time[0], minute=spec_time[1], second=0, microsecond=0)
            else:
                hour = 20 if day_ref == "tonight" else 9
                due_at = base_date.replace(hour=hour, minute=0, second=0, microsecond=0)
            
            if due_at <= now and day_ref == "today":
                return {
                    "due_at": due_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "type": "today_tomorrow",
                    "is_past": True,
                    "error_message": f"The requested time ({due_at.strftime('%I:%M %p')}) has already passed today."
                }
            return {"due_at": due_at.strftime("%Y-%m-%d %H:%M:%S"), "type": "today_tomorrow"}
        
        # 6. Weekday: "Monday at 10 AM", "next Friday", "every Wednesday at 8 in the morning"
        weekday_match = self.time_patterns['weekday'].search(text)
        if weekday_match:
            target_weekday = weekday_match.group(1).lower()
            weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
            target_idx = weekdays.index(target_weekday)
            current_idx = now.weekday()
            days_ahead = target_idx - current_idx
            if days_ahead <= 0:
                days_ahead += 7
            base_date = now + timedelta(days=days_ahead)
            spec_time = self._extract_clock_time(text)
            if spec_time:
                due_at = base_date.replace(hour=spec_time[0], minute=spec_time[1], second=0, microsecond=0)
            else:
                due_at = base_date.replace(hour=9, minute=0, second=0, microsecond=0)
            return {"due_at": due_at.strftime("%Y-%m-%d %H:%M:%S"), "type": "weekday"}
        
        # 7. Standalone specific time: "at 6 PM", "at 14:30"
        spec_time = self._extract_clock_time(text)
        if spec_time:
            due_at = now.replace(hour=spec_time[0], minute=spec_time[1], second=0, microsecond=0)
            if due_at <= now:
                due_at += timedelta(days=1)
            return {"due_at": due_at.strftime("%Y-%m-%d %H:%M:%S"), "type": "specific"}
        
        return None
    
    def _parse_recurrence(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse recurrence pattern from text."""
        # 1. Custom intervals: every 2 weeks, every 3 days
        m_int = re.search(r'\bevery\s+(\d+|two|three|four)\s+(weeks?|days?|months?)\b', text, re.I)
        if m_int:
            n_str = m_int.group(1).lower()
            u_str = m_int.group(2).lower()
            n = 2 if n_str == 'two' else 3 if n_str == 'three' else 4 if n_str == 'four' else int(n_str)
            return {"frequency": f"every {n} {u_str}"}

        # 2. Weekdays: Mon-Fri
        if re.search(r'\b(?:every\s+weekday|on\s+weekdays|weekdays|workdays|mon-fri)\b', text, re.I):
            return {"frequency": "weekdays"}

        # 3. Weekends: Sat-Sun
        if re.search(r'\b(?:every\s+weekend|on\s+weekends|weekends|sat-sun)\b', text, re.I):
            return {"frequency": "weekends"}

        # 4. Weekly
        if re.search(r'\b(?:every\s+week|weekly|every\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b', text, re.I):
            return {"frequency": "weekly"}

        # 5. Monthly
        if re.search(r'\b(?:every\s+month|monthly|first\s+day\s+of\s+every\s+month|\d+(?:st|nd|rd|th)?\s+of\s+every\s+month)\b', text, re.I):
            return {"frequency": "monthly"}

        # 6. Yearly / annually / birthday
        if re.search(r'\b(?:every\s+year|yearly|annually|every\s+year\s+on\s+my\s+birthday)\b', text, re.I):
            return {"frequency": "yearly"}

        # 7. Daily
        if re.search(r'\b(?:every\s+day|daily)\b', text, re.I):
            return {"frequency": "daily"}

        return None


# Global handler instance
_handler = None

def get_handler(db_manager) -> ReminderHandler:
    """Get the global reminder handler instance."""
    global _handler
    if _handler is None:
        _handler = ReminderHandler(db_manager)
    else:
        _handler.db_manager = db_manager
    return _handler


EnhancedReminderHandler = ReminderHandler
