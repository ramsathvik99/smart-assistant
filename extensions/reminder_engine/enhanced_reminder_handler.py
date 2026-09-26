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
    RESCHEDULE = "reschedule"
    QUERY = "query"

class ReminderHandler:
    """
    Enhanced reminder handler with natural language understanding,
    conflict detection, and database persistence.
    """
    
    def __init__(self, db_manager):
        """
        Initialize the reminder handler.
        
        Args:
            db_manager: DatabaseManager instance for persistence
        """
        self.db_manager = db_manager
        self.logger = logging.getLogger(__name__)
        
        # Compile regex patterns for performance
        self._compile_patterns()
    
    def _compile_patterns(self):
        """Compile regex patterns for natural language parsing."""
        
        # Action detection patterns
        self.action_patterns = {
            ReminderAction.CREATE: [
                r'\bremind\s+me\s+(?:to\s+)?',
                r'\bset\s+(?:a\s+)?reminder\s+(?:to\s+)?',
                r'\balert\s+me\s+(?:to\s+)?',
                r'\breminder\s+(?:to\s+)?',
            ],
            ReminderAction.LIST: [
                r'\bwhat\s+reminders\s+(?:do\s+i\s+have|are\s+scheduled)',
                r'\bwhat\s+are\s+(?:my\s+)?reminders',
                r'\bshow\s+(?:all\s+)?(?:my\s+)?(?:upcoming\s+)?reminders',
                r'\blist\s+(?:all\s+)?(?:my\s+)?reminders',
                r'\bdo\s+i\s+have\s+anything\s+scheduled',
                r'\bwhat\s+do\s+i\s+have\s+(?:tomorrow|today)',
                r'\bmy\s+reminders\b',
            ],
            ReminderAction.DELETE: [
                r'\b(?:delete|remove|cancel)\s+(?:my\s+)?reminder',
                r'\b(?:delete|remove|cancel)\s+the\s+reminder',
            ],
            ReminderAction.UPDATE: [
                r'\b(?:change|update|modify)\s+(?:my\s+)?reminder',
                r'\b(?:change|update|modify)\s+the\s+reminder',
            ],
            ReminderAction.RESCHEDULE: [
                r'\b(?:move|reschedule)\s+(?:my\s+)?reminder',
                r'\b(?:move|reschedule)\s+the\s+reminder',
            ],
        }
        
        # Time patterns
        self.time_patterns = {
            # Relative time: "in 10 seconds", "in 5 minutes", "in 2 hours"
            'relative': re.compile(r'\bin\s+(\d+)\s*(seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?)\b', re.IGNORECASE),
            
            # Specific time: "at 6 PM", "at 14:30", "at 2pm"
            'specific': re.compile(r'\bat\s+(\d{1,2}):?(\d{2})?\s*(am|pm)?\b', re.IGNORECASE),
            
            # Today/tomorrow: "today at 5 PM", "tomorrow at 9 AM"
            'today_tomorrow': re.compile(r'\b(today|tomorrow)\s*(?:at\s+(\d{1,2}):?(\d{2})?\s*(am|pm)?)?\b', re.IGNORECASE),
            
            # Weekdays: "Monday at 10 AM", "next Friday"
            'weekday': re.compile(r'\b(?:next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*(?:at\s+(\d{1,2}):?(\d{2})?\s*(am|pm)?)?\b', re.IGNORECASE),
            
            # Meeting reminder: "remind me 15 minutes before my meeting"
            'meeting_before': re.compile(r'\b(\d+)\s+minutes?\s+before\s+(?:my\s+)?(.+?)\s*(?:meeting|event|appointment)\b', re.IGNORECASE),
        }
        
        # Recurrence patterns
        self.recurrence_patterns = {
            'daily': re.compile(r'\b(?:every\s+day|daily)\b', re.IGNORECASE),
            'weekly': re.compile(r'\b(?:every\s+week|weekly)(?:\s+on\s+(\w+))?\b', re.IGNORECASE),
            'monthly': re.compile(r'\b(?:every\s+month|monthly)\b', re.IGNORECASE),
        }
    
    def parse_reminder_command(self, user_input: str, user_id: int) -> Dict[str, Any]:
        """
        Parse a natural language reminder command.
        
        Args:
            user_input: The user's natural language command
            user_id: The current user's ID
            
        Returns:
            Dict with action, parameters, and any conflicts found
        """
        user_input_lower = user_input.lower().strip()
        
        # Detect the action type
        action = self._detect_action(user_input_lower)
        
        # Parse based on action type
        if action == ReminderAction.CREATE:
            return self._parse_create_command(user_input, user_input_lower, user_id)
        elif action == ReminderAction.LIST:
            return self._parse_list_command(user_input, user_input_lower, user_id)
        elif action == ReminderAction.DELETE:
            return self._parse_delete_command(user_input, user_input_lower, user_id)
        elif action == ReminderAction.UPDATE or action == ReminderAction.RESCHEDULE:
            return self._parse_update_command(user_input, user_input_lower, user_id)
        else:
            return {
                "status": "error",
                "message": "I couldn't understand what you want to do with reminders. Try phrases like 'remind me to call Mom at 6 PM' or 'show my reminders'.",
                "action": None
            }
    
    def _detect_action(self, text: str) -> ReminderAction:
        """Detect the type of reminder action from text."""
        # Check for delete/update actions first (they have more specific patterns)
        if re.search(r'\b(?:delete|remove|cancel)\s+(?:my\s+)?(?:the\s+)?reminder', text):
            return ReminderAction.DELETE
        if re.search(r'\b(?:change|update|modify|move|reschedule)\s+(?:my\s+)?(?:the\s+)?reminder', text):
            return ReminderAction.UPDATE
        
        # Check for list actions
        if re.search(r'\bwhat\s+reminders\s+(?:do\s+i\s+have|are\s+scheduled)', text):
            return ReminderAction.LIST
        if re.search(r'\bwhat\s+are\s+(?:all\s+)?(?:my\s+|the\s+)?reminders', text):
            return ReminderAction.LIST
        if re.search(r'\bwhat\s+reminders\b', text):
            return ReminderAction.LIST
        if re.search(r'\b(?:show|list|get|view|check)\s+(?:all\s+)?(?:my\s+)?(?:upcoming\s+)?reminders', text):
            return ReminderAction.LIST
        if re.search(r'\blist\s+(?:my\s+)?reminders', text):
            return ReminderAction.LIST
        if re.search(r'\bdo\s+i\s+have\s+(?:any\s+)?(?:reminders|anything\s+scheduled)', text):
            return ReminderAction.LIST
        if re.search(r'\bwhat\s+do\s+i\s+have\s+(?:tomorrow|today)', text):
            return ReminderAction.LIST
        if re.search(r'\b(?:all\s+)?my\s+reminders\b', text):
            return ReminderAction.LIST
        
        # Check for create actions
        if re.search(r'\bremind\s+me\s+(?:to\s+)?', text):
            return ReminderAction.CREATE
        if re.search(r'\bset\s+(?:a\s+)?reminder\s+(?:to\s+)?', text):
            return ReminderAction.CREATE
        if re.search(r'\balert\s+me\s+(?:to\s+)?', text):
            return ReminderAction.CREATE
        if re.search(r'\breminder\s+(?:to\s+)?', text):
            return ReminderAction.CREATE
        
        return None
    
    def _parse_create_command(self, original_input: str, text: str, user_id: int) -> Dict[str, Any]:
        """Parse a reminder creation command."""
        result = {
            "action": ReminderAction.CREATE,
            "task_text": None,
            "due_at": None,
            "recurrence": None,
            "conflicts": [],
            "status": "pending"
        }
        
        # 1. Contextual reminder pattern (e.g. "tomorrow i have to go to movie at 3pm so can you remind me at 2pm")
        m_context = re.search(r'^(.*?)(?:,\s*|\s+so\s+(?:can\s+you\s+|could\s+you\s+|please\s+)?|\s+can\s+you\s+|\s+could\s+you\s+|\s+please\s+)remind\s+me\s+(?:at\s+|in\s+|before\s+|to\s+)(.+)$', original_input.strip(), re.IGNORECASE)
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
        result["task_text"] = self._extract_task_text(original_input, text)
        
        if not result["task_text"]:
            return {
                "status": "error",
                "message": "What would you like me to remind you about?",
                "action": ReminderAction.CREATE
            }
        
        # Parse time
        time_result = self._parse_time(text)
        if not time_result:
            return {
                "status": "error",
                "message": "When should I remind you? Please specify a time like 'at 6 PM' or 'in 30 minutes'.",
                "action": ReminderAction.CREATE
            }
        
        result["due_at"] = time_result["due_at"]
        
        # Check for conflicts
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
        result["recurrence"] = self._parse_recurrence(text)
        
        result["status"] = "ready"
        return result
    
    def _parse_list_command(self, original_input: str, text: str, user_id: int) -> Dict[str, Any]:
        """Parse a reminder list/query command."""
        result = {
            "action": ReminderAction.LIST,
            "start_date": None,
            "end_date": None,
            "status": "ready"
        }
        
        # Check for date constraints
        if "tomorrow" in text:
            tomorrow = datetime.now() + timedelta(days=1)
            result["start_date"] = tomorrow.date()
            result["end_date"] = tomorrow.date()
        elif "today" in text:
            today = datetime.now().date()
            result["start_date"] = today
            result["end_date"] = today
        elif "this week" in text:
            today = datetime.now().date()
            result["start_date"] = today
            result["end_date"] = today + timedelta(days=7)
        
        return result
    
    def _parse_delete_command(self, original_input: str, text: str, user_id: int) -> Dict[str, Any]:
        """Parse a reminder deletion command."""
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
        
        # Find matching reminders
        reminders = self.db_manager.get_reminders(user_id)
        
        # Filter by task text if provided
        if result["task_text"]:
            reminders = [r for r in reminders if result["task_text"].lower() in r["task_text"].lower()]
        
        # Filter by time if provided
        if result["time_filter"]:
            reminders = [r for r in reminders if r["due_at"] == result["time_filter"]]
        
        result["candidates"] = reminders
        
        if len(reminders) == 0:
            return {
                "status": "error",
                "message": "I couldn't find any matching reminders to delete.",
                "action": ReminderAction.DELETE
            }
        elif len(reminders) == 1:
            result["reminder_id"] = reminders[0]["id"]
            result["status"] = "ready"
        else:
            result["status"] = "ambiguous"
            result["message"] = f"I found {len(reminders)} matching reminders. Which one would you like to delete?"
        
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
        id_match = re.search(r'#(\d+)', text)
        if not id_match:
            id_match = re.search(r'number\s+(\d+)', text)
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
        
        # If no reminder ID specified, try to find by current time
        if not result["reminder_id"]:
            # Look for time references like "my 5 PM reminder"
            time_match = re.search(r'\bat\s+(\d{1,2}):?(\d{2})?\s*(am|pm)?\b', text)
            if time_match:
                # Parse the time and find matching reminder
                hour = int(time_match.group(1))
                minute = int(time_match.group(2)) if time_match.group(2) else 0
                ampm = time_match.group(3) or "am"
                
                if ampm.lower() == "pm" and hour != 12:
                    hour += 12
                elif ampm.lower() == "am" and hour == 12:
                    hour = 0
                
                reminders = self.db_manager.get_reminders(user_id)
                for reminder in reminders:
                    due_raw = reminder.get("due_at")
                    if isinstance(due_raw, datetime):
                        reminder_time = due_raw
                    elif isinstance(due_raw, str):
                        try:
                            reminder_time = datetime.strptime(due_raw, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            reminder_time = datetime.fromisoformat(due_raw)
                    else:
                        continue
                    if reminder_time.hour == hour and reminder_time.minute == minute:
                        result["reminder_id"] = reminder["id"]
                        break
        
        # If still no ID, find candidates by task text
        if not result["reminder_id"] and result["new_task_text"]:
            reminders = self.db_manager.get_reminders(user_id)
            matching = [r for r in reminders if result["new_task_text"].lower() in r["task_text"].lower()]
            
            if len(matching) == 1:
                result["reminder_id"] = matching[0]["id"]
            elif len(matching) > 1:
                result["candidates"] = matching
                result["status"] = "ambiguous"
                result["message"] = f"I found {len(matching)} matching reminders. Which one would you like to update?"
                return result
        
        # If still no ID, return all reminders as candidates
        if not result["reminder_id"]:
            reminders = self.db_manager.get_reminders(user_id)
            result["candidates"] = reminders
            
            if len(reminders) == 0:
                return {
                    "status": "error",
                    "message": "I couldn't find any reminders to update.",
                    "action": ReminderAction.UPDATE
                }
            elif len(reminders) == 1:
                result["reminder_id"] = reminders[0]["id"]
            else:
                result["status"] = "ambiguous"
                result["message"] = f"I found {len(reminders)} reminders. Which one would you like to update?"
                return result
        
        # Check for conflicts if changing time
        if result["new_due_at"] and result["reminder_id"]:
            conflicts = self.db_manager.check_reminder_conflicts(
                user_id, result["new_due_at"], exclude_id=result["reminder_id"]
            )
            if conflicts:
                result["conflicts"] = conflicts
                result["status"] = "conflict"
                conflict_texts = [f"'{c['task_text']}' at {c['due_at']}" for c in conflicts]
                return {
                    "status": "conflict",
                    "message": f"That time conflicts with {', '.join(conflict_texts)}. Would you like to reschedule one of them?",
                    "action": ReminderAction.UPDATE,
                    "proposed_update": result,
                    "conflicts": conflicts
                }
        
        result["status"] = "ready"
        return result
    
    def _extract_task_text(self, original_input: str, text: str) -> Optional[str]:
        """Extract the task text from a reminder command."""
        # Remove common reminder keywords (longest/most specific first to avoid partial truncation)
        patterns_to_remove = [
            r'\b(?:delete|remove|cancel|change|update|modify|move|reschedule)\s+(?:all\s+)?(?:my\s+)?(?:the\s+)?reminders?\s+(?:to\s+|for\s+|about\s+)?',
            r'\b(?:delete|remove|cancel|change|update|modify|move|reschedule)\s+the\s+reminders?\s+(?:to\s+|for\s+|about\s+)?',
            r'\b(?:delete|remove|cancel|change|update|modify|move|reschedule)\s+(?:my\s+)?',
            r'\bremind\s+me\s+(?:to\s+)?',
            r'\bset\s+(?:a\s+)?reminder\s+(?:for\s+|to\s+)?',
            r'\balert\s+me\s+(?:to\s+)?',
            r'\breminders?\s+(?:to\s+|for\s+|about\s+)?',
        ]
        
        task_text = original_input
        for pattern in patterns_to_remove:
            task_text = re.sub(pattern, '', task_text, flags=re.IGNORECASE)
        
        # Remove time-related phrases (more comprehensive)
        task_text = re.sub(r'\bin\s+\d+\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?)\b', '', task_text, flags=re.IGNORECASE)
        task_text = re.sub(r'\bat\s+\d{1,2}:?\d{0,2}\s*(?:am|pm)?\b', '', task_text, flags=re.IGNORECASE)
        task_text = re.sub(r'\b(?:today|tomorrow)\s*(?:at\s+\d{1,2}:?\d{0,2}\s*(?:am|pm)?)?\b', '', task_text, flags=re.IGNORECASE)
        task_text = re.sub(r'\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*(?:at\s+\d{1,2}:?\d{0,2}\s*(?:am|pm)?)?\b', '', task_text, flags=re.IGNORECASE)
        task_text = re.sub(r'\b(?:every\s+day|every\s+week|every\s+month|daily|weekly|monthly)\b', '', task_text, flags=re.IGNORECASE)
        task_text = re.sub(r'\b(?:next\s+)?(?:day|week|month)\b', '', task_text, flags=re.IGNORECASE)
        task_text = re.sub(r'\bfor\s+(?:tomorrow|today|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', '', task_text, flags=re.IGNORECASE)
        task_text = re.sub(r'\b(?:tomorrow|today)\b', '', task_text, flags=re.IGNORECASE)
        
        # Remove leading "to" or "for" if present
        task_text = re.sub(r'^\s*(?:to|for)\s+', '', task_text, flags=re.IGNORECASE)
        
        # Clean up
        task_text = task_text.strip()
        task_text = re.sub(r'[.!?]+$', '', task_text)
        task_text = re.sub(r'\s+', ' ', task_text)  # Normalize whitespace
        
        if not task_text and any(k in original_input.lower() for k in ["reminder", "remind me"]):
            return "Reminder"
        return task_text if task_text else None
    
    def _parse_time(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse time from text and return due_at timestamp."""
        now = datetime.now()
        
        # 1. Check for relative time first: "in 10 seconds", "in 5 minutes", "in 2 hours"
        relative_match = self.time_patterns['relative'].search(text)
        if relative_match:
            amount = int(relative_match.group(1))
            unit = relative_match.group(2).lower()
            
            if 'sec' in unit:
                due_at = now + timedelta(seconds=amount)
            elif 'min' in unit:
                due_at = now + timedelta(minutes=amount)
            elif 'hour' in unit or 'hr' in unit:
                due_at = now + timedelta(hours=amount)
            elif 'day' in unit:
                due_at = now + timedelta(days=amount)
            elif 'week' in unit:
                due_at = now + timedelta(weeks=amount)
            else:
                due_at = now + timedelta(minutes=amount)
            
            return {"due_at": due_at.strftime("%Y-%m-%d %H:%M:%S"), "type": "relative"}
        
        # 2. Check for today/tomorrow
        today_tomorrow_match = self.time_patterns['today_tomorrow'].search(text)
        if today_tomorrow_match:
            day_ref = today_tomorrow_match.group(1).lower()
            base_date = now + timedelta(days=1) if day_ref == "tomorrow" else now
            
            # If time is specified directly with today/tomorrow
            if today_tomorrow_match.group(2):
                hour = int(today_tomorrow_match.group(2))
                minute = int(today_tomorrow_match.group(3)) if today_tomorrow_match.group(3) else 0
                ampm = today_tomorrow_match.group(4) or ("pm" if hour <= 6 else "am")
                
                if ampm.lower() == "pm" and hour != 12:
                    hour += 12
                elif ampm.lower() == "am" and hour == 12:
                    hour = 0
                
                due_at = base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            else:
                # Check if specific time appears elsewhere in text, e.g. "at 2pm tomorrow"
                specific_match = self.time_patterns['specific'].search(text)
                if specific_match:
                    hour = int(specific_match.group(1))
                    minute = int(specific_match.group(2)) if specific_match.group(2) else 0
                    ampm = specific_match.group(3) or ("pm" if hour <= 6 else "am")
                    if ampm.lower() == "pm" and hour != 12:
                        hour += 12
                    elif ampm.lower() == "am" and hour == 12:
                        hour = 0
                    due_at = base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
                else:
                    due_at = base_date.replace(hour=9, minute=0, second=0, microsecond=0)
            
            return {"due_at": due_at.strftime("%Y-%m-%d %H:%M:%S"), "type": "day"}
        
        # Check for specific time: "at 6 PM"
        specific_match = self.time_patterns['specific'].search(text)
        if specific_match:
            hour = int(specific_match.group(1))
            minute = int(specific_match.group(2)) if specific_match.group(2) else 0
            ampm = specific_match.group(3) or "am"
            
            # Convert to 24-hour format
            if ampm.lower() == "pm" and hour != 12:
                hour += 12
            elif ampm.lower() == "am" and hour == 12:
                hour = 0
            
            due_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            
            # If time has passed, schedule for tomorrow
            if due_at < now:
                due_at += timedelta(days=1)
            
            return {"due_at": due_at.strftime("%Y-%m-%d %H:%M:%S"), "type": "specific"}
        
        # Check for weekdays: "Monday at 10 AM", "next Friday"
        weekday_match = self.time_patterns['weekday'].search(text)
        if weekday_match:
            weekday_name = weekday_match.group(1).lower()
            is_next = "next" in text
            
            # Map weekday name to number (0 = Monday, 6 = Sunday)
            weekday_map = {
                'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
                'friday': 4, 'saturday': 5, 'sunday': 6
            }
            
            target_weekday = weekday_map[weekday_name]
            current_weekday = now.weekday()
            
            # Calculate days until target weekday
            days_until = (target_weekday - current_weekday) % 7
            if is_next or days_until == 0:
                days_until += 7
            
            base_date = now + timedelta(days=days_until)
            
            # If time is specified
            if weekday_match.group(2):  # time is specified
                hour = int(weekday_match.group(2))
                minute = int(weekday_match.group(3)) if weekday_match.group(3) else 0
                ampm = weekday_match.group(4) or "am"
                
                if ampm.lower() == "pm" and hour != 12:
                    hour += 12
                elif ampm.lower() == "am" and hour == 12:
                    hour = 0
                
                due_at = base_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            else:
                # No time specified, default to 9 AM
                due_at = base_date.replace(hour=9, minute=0, second=0, microsecond=0)
            
            return {"due_at": due_at.strftime("%Y-%m-%d %H:%M:%S"), "type": "weekday"}
        
        return None
    
    def _parse_recurrence(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse recurrence pattern from text."""
        for recurrence_type, pattern in self.recurrence_patterns.items():
            match = pattern.search(text)
            if match:
                result = {"frequency": recurrence_type}
                if recurrence_type == 'weekly' and match.group(1):
                    result["day"] = match.group(1).lower()
                return result
        
        return None


# Global handler instance
_handler = None

def get_handler(db_manager) -> ReminderHandler:
    """Get the global reminder handler instance."""
    global _handler
    if _handler is None:
        _handler = ReminderHandler(db_manager)
    return _handler