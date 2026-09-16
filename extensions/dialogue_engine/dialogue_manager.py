"""
Dialogue Manager Module
Core logic for managing multi-turn conversations and intelligent follow-ups.
"""

import re
import logging
from typing import Dict, Any, Optional, List, Tuple, Callable
from .session_memory import SessionMemory, get_session_memory
from .state_tracker import StateTracker, get_state_tracker, DialogueState

class DialogueManager:
    """Core dialogue management system for NOVA"""
    
    def __init__(self, session_memory: Optional[SessionMemory] = None, 
                 state_tracker: Optional[StateTracker] = None,
                 logger: Optional[logging.Logger] = None):
        self.session_memory = session_memory or get_session_memory()
        self.state_tracker = state_tracker or get_state_tracker()
        self.logger = logger or logging.getLogger("assistant.dialogue.manager")
        
        # Intent patterns for dialogue detection
        self.intent_patterns = {
            "open_project": [
                r"open my project",
                r"open (?:the )?project",
                r"project.*open",
                r"work on project"
            ],
            "open_youtube": [
                r"open youtube",
                r"youtube.*open",
                r"launch youtube"
            ],
            "search_youtube": [
                r"youtube.*search",
                r"search.*youtube",
                r"find.*youtube",
                r"look up.*youtube"
            ],
            "set_reminder": [
                r"remind me",
                r"set reminder",
                r"remind.*about",
                r"don't let.*forget"
            ],
            "play_music": [
                r"play.*music",
                r"play.*song",
                r"put on.*music",
                r"music.*play"
            ],
            "open_file": [
                r"open.*file",
                r"file.*open",
                r"open.*document",
                r"document.*open"
            ]
        }
        
        # Context linking patterns
        self.context_patterns = {
            "continuation": [
                r"also",
                r"and.*also",
                r"too",
                r"as well",
                r"next",
                r"then"
            ],
            "clarification": [
                r"yes",
                r"no",
                r"correct",
                r"right",
                r"wrong",
                r"that.*one",
                r"the.*one"
            ],
            "modification": [
                r"change",
                r"different",
                r"another",
                r"other",
                r"instead"
            ]
        }
        
        # Slot value extractors
        self.slot_extractors = {
            "project_name": [
                r"(?:project|work)\s+([a-zA-Z0-9_\-\s]+)",
                r"([a-zA-Z0-9_\-\s]+)\s+(?:project|work)",
                r"([a-zA-Z0-9_\-\s]+)"
            ],
            "search_query": [
                r"search\s+for\s+([a-zA-Z0-9_\-\s]+)",
                r"find\s+([a-zA-Z0-9_\-\s]+)",
                r"look\s+up\s+([a-zA-Z0-9_\-\s]+)",
                r"([a-zA-Z0-9_\-\s]+)"
            ],
            "reminder_text": [
                r"remind\s+(?:me\s+)?(?:to\s+)?([a-zA-Z0-9_\-\s]+)",
                r"don't\s+let\s+me\s+forget\s+(?:to\s+)?([a-zA-Z0-9_\-\s]+)",
                r"([a-zA-Z0-9_\-\s]+)"
            ],
            "music_query": [
                r"play\s+(.+)",
                r"put\s+on\s+(.+)",
                r"music\s+(.+)",
                r"song\s+(.+)",
                r"(.+)"
            ],
            "file_name": [
                r"file\s+([a-zA-Z0-9_\-\.\s]+)",
                r"([a-zA-Z0-9_\-\.\s]+)\s+file",
                r"([a-zA-Z0-9_\-\.\s]+)"
            ]
        }
        
        # Follow-up handlers
        self.follow_up_handlers = {
            "open_project": self._handle_open_project_followup,
            "open_youtube": self._handle_open_youtube_followup,
            "search_youtube": self._handle_search_youtube_followup,
            "set_reminder": self._handle_reminder_followup,
            "play_music": self._handle_music_followup,
            "open_file": self._handle_file_followup
        }
    
    def handle(self, user_input: str) -> Optional[str]:
        """
        Handle user input with dialogue management
        
        Args:
            user_input: The user's input
            
        Returns:
            Dialogue response if handled, None if should continue with normal processing
        """
        print(f"[DIALOGUE] Input: '{user_input}'")
        print(f"[DIALOGUE] State: {self.state_tracker.get_dialogue_summary()}")
        
        self.logger.info(f"Dialogue manager handling: '{user_input}'")
        
        # Step 1: Check if waiting for clarification (slot filling)
        if self.state_tracker.is_awaiting_clarification() or self.state_tracker.is_slot_filling():
            response = self._resolve_slot(user_input)
            print(f"[DIALOGUE] Slot Resolution Response: '{response}'")
            return response
        
        # Step 1.5: Check if task execution is ready
        if self.state_tracker.get_state().value == "task_execution":
            response = self._execute_completed_intent()
            print(f"[DIALOGUE] Task Execution Response: '{response}'")
            return response
        
        # Step 2: Check for context linking with previous turns
        context_response = self._handle_context_linking(user_input)
        if context_response:
            print(f"[DIALOGUE] Context Response: '{context_response}'")
            return context_response
        
        # Step 3: Detect incomplete commands that need clarification
        clarification_response = self._detect_incomplete_command(user_input)
        if clarification_response:
            print(f"[DIALOGUE] Clarification Response: '{clarification_response}'")
            return clarification_response
        
        # Step 4: Check for follow-up patterns
        follow_up_response = self._handle_follow_up_patterns(user_input)
        if follow_up_response:
            print(f"[DIALOGUE] Follow-up Response: '{follow_up_response}'")
            return follow_up_response
        
        # Step 5: Normal processing (return None to continue with pipeline)
        print(f"[DIALOGUE] No Dialogue Response - Continuing to Pipeline")
        return None
    
    def _resolve_slot(self, user_input: str) -> str:
        """Resolve a pending slot with user input"""
        pending_slots = self.state_tracker.get_pending_slots()
        print(f"[DIALOGUE] Resolving slot - pending slots: {pending_slots}")
        
        if not pending_slots:
            self.state_tracker.clear_intent()
            return "I'm not sure what you're referring to. Let's start over."
        
        slot_name = pending_slots[0]
        print(f"[DIALOGUE] Resolving slot {slot_name}")
        
        # Try to extract slot value
        value = self._extract_slot_value(slot_name, user_input)
        print(f"[DIALOGUE] Extracted slot value: '{value}'")
        
        if value is None:
            # Use the entire input as value if extraction fails
            value = user_input.strip()
            print(f"[DIALOGUE] Using full input as value: '{value}'")
        
        # Fill the slot
        success = self.state_tracker.fill_slot(slot_name, value)
        print(f"[DIALOGUE] Slot fill result: {success}")
        
        # Small delay to ensure state updates
        import time
        time.sleep(0.01)
        
        # Check if more slots are needed
        if self.state_tracker.has_pending_slots():
            next_slot = self.state_tracker.get_next_pending_slot()
            print(f"[DIALOGUE] Next slot needed: {next_slot.name if next_slot else 'None'}")
            return next_slot.prompt if next_slot else "Got it. What else?"
        else:
            # All slots filled, execute the intent
            print(f"[DIALOGUE] All slots filled, executing intent")
            return self._execute_completed_intent()
    
    def _detect_incomplete_command(self, user_input: str) -> Optional[str]:
        """Detect incomplete commands that need clarification"""
        user_input_lower = user_input.lower().strip()
        
        # Check each intent pattern
        for intent_name, patterns in self.intent_patterns.items():
            for pattern in patterns:
                if re.search(pattern, user_input_lower):
                    # Check if we have enough information
                    if self._is_command_incomplete(intent_name, user_input):
                        self.state_tracker.set_intent(intent_name)
                        next_slot = self.state_tracker.get_next_pending_slot()
                        return next_slot.prompt if next_slot else "What specifically?"
                    else:
                        # Command is complete, execute immediately
                        self.state_tracker.set_intent(intent_name)
                        return self._execute_completed_intent()
                    break
        
        return None
    
    def _is_command_incomplete(self, intent_name: str, user_input: str) -> bool:
        """Check if a command is incomplete and needs clarification"""
        user_input_lower = user_input.lower().strip()
        
        if intent_name == "open_project":
            # Check if project name is specified
            project_patterns = [
                r"project\s+([a-zA-Z0-9_\-\s]+)",
                r"([a-zA-Z0-9_\-\s]+)\s+project",
                r"([a-zA-Z0-9_\-\s]+)\s+project\s+([a-zA-Z0-9_\-\s]+)"
            ]
            
            # If it's "my project" or just "project", it's incomplete
            if re.search(r"my\s+project$|open\s+(?:the\s+)?project$", user_input_lower):
                return True
            
            # If it matches project patterns with a name, it's complete
            return not any(re.search(pattern, user_input_lower) for pattern in project_patterns)
        
        elif intent_name == "open_youtube":
            # open youtube is always complete - no slots needed
            return False
        
        elif intent_name == "search_youtube":
            # Check if search query is specified
            search_patterns = [
                r"search\s+for\s+([a-zA-Z0-9_\-\s]+)",
                r"find\s+([a-zA-Z0-9_\-\s]+)",
                r"look\s+up\s+([a-zA-Z0-9_\-\s]+)"
            ]
            
            # "open youtube" is complete, "search youtube" needs query
            if re.search(r"open\s+youtube$", user_input_lower):
                return False  # Complete command
            
            return not any(re.search(pattern, user_input_lower) for pattern in search_patterns)
        
        elif intent_name == "set_reminder":
            # Check if reminder text and time are specified
            has_text = any(word in user_input_lower for word in ["remind", "reminder", "forget"])
            has_time = any(word in user_input_lower for word in ["minute", "hour", "day", "tomorrow", "today", "at", "in"])
            return has_text and not has_time
        
        elif intent_name == "play_music":
            # Check if music query is specified
            music_patterns = [
                r"play\s+([a-zA-Z0-9_\-\s]+)",
                r"put\s+on\s+([a-zA-Z0-9_\-\s]+)"
            ]
            return not any(re.search(pattern, user_input_lower) for pattern in music_patterns)
        
        elif intent_name == "open_file":
            # Check if file name is specified
            file_patterns = [
                r"file\s+([a-zA-Z0-9_\-\.\s]+)",
                r"([a-zA-Z0-9_\-\.\s]+)\s+file"
            ]
            return not any(re.search(pattern, user_input_lower) for pattern in file_patterns)
        
        return False
    
    def _handle_context_linking(self, user_input: str) -> Optional[str]:
        """Handle context linking with previous conversation turns"""
        last_turn = self.session_memory.get_last()
        if not last_turn:
            return None
        
        user_input_lower = user_input.lower().strip()
        
        # Check for continuation patterns
        for pattern in self.context_patterns["continuation"]:
            if re.search(pattern, user_input_lower):
                return self._handle_continuation(user_input, last_turn)
        
        # Check for clarification patterns
        for pattern in self.context_patterns["clarification"]:
            if re.search(pattern, user_input_lower):
                return self._handle_clarification(user_input, last_turn)
        
        # Check for modification patterns
        for pattern in self.context_patterns["modification"]:
            if re.search(pattern, user_input_lower):
                return self._handle_modification(user_input, last_turn)
        
        # Check for natural context linking
        return self._handle_natural_context_linking(user_input, last_turn)
    
    def _handle_continuation(self, user_input: str, last_turn: Any) -> Optional[str]:
        """Handle continuation of previous intent"""
        if last_turn.intent == "search_youtube" and "search" in user_input.lower():
            # Extract new search query and continue
            query = self._extract_slot_value("search_query", user_input)
            if query:
                return f"Searching YouTube for {query}."
        
        elif last_turn.intent == "play_music" and "play" in user_input.lower():
            # Extract new music query and continue
            query = self._extract_slot_value("music_query", user_input)
            if query:
                return f"Playing {query}."
        
        return None
    
    def _handle_clarification(self, user_input: str, last_turn: Any) -> Optional[str]:
        """Handle clarification of previous response"""
        user_input_lower = user_input.lower().strip()
        
        if user_input_lower in ["yes", "correct", "right", "that one"]:
            # Confirm previous action
            return f"Confirmed. {last_turn.system_response}"
        
        elif user_input_lower in ["no", "wrong", "not that"]:
            # Reject previous action
            return "I understand. Let me try something different."
        
        return None
    
    def _handle_modification(self, user_input: str, last_turn: Any) -> Optional[str]:
        """Handle modification of previous request"""
        if last_turn.intent == "search_youtube":
            # Modify search query
            query = self._extract_slot_value("search_query", user_input)
            if query:
                return f"Changing search to {query}."
        
        return None
    
    def _handle_natural_context_linking(self, user_input: str, last_turn: Any) -> Optional[str]:
        """Handle natural context linking without explicit patterns"""
        user_input_lower = user_input.lower().strip()
        
        # YouTube + search = continue YouTube search
        if (last_turn.intent == "open_youtube" and 
            "search" in user_input_lower and 
            len(user_input.split()) <= 3):
            query = self._extract_slot_value("search_query", user_input)
            if query:
                return f"Searching YouTube for {query}."
        
        # Open + specific = context-aware opening
        elif (last_turn.intent in ["open_youtube", "open_browser"] and
              any(word in user_input_lower for word in ["first", "second", "third", "next", "previous"])):
            return f"Navigating to {user_input}."
        
        # Play + first/one = play first result
        elif (last_turn.intent == "search_youtube" and
              "first" in user_input_lower and "play" in user_input_lower):
            return "Playing the first result."
        
        return None
    
    def _handle_follow_up_patterns(self, user_input: str) -> Optional[str]:
        """Handle follow-up patterns"""
        user_input_lower = user_input.lower().strip()
        
        # Check for follow-up handlers
        active_intent = self.state_tracker.get_active_intent()
        if active_intent and active_intent.name in self.follow_up_handlers:
            handler = self.follow_up_handlers[active_intent.name]
            return handler(user_input)
        
        return None
    
    def _extract_slot_value(self, slot_name: str, user_input: str) -> Optional[str]:
        """Extract slot value from user input"""
        if slot_name not in self.slot_extractors:
            return None
        
        user_input_lower = user_input.lower().strip()
        
        for pattern in self.slot_extractors[slot_name]:
            match = re.search(pattern, user_input_lower)
            if match:
                value = match.group(1).strip()
                # Clean up the value
                value = re.sub(r'\b(the|a|an)\b', '', value).strip()
                print(f"[DIALOGUE] Extracted {slot_name}: '{value}' from '{user_input}' using pattern '{pattern}'")
                return value if value else None
        
        print(f"[DIALOGUE] No match found for {slot_name} in '{user_input}'")
        return None
    
    def _execute_completed_intent(self) -> str:
        """Execute a completed intent with all slots filled"""
        active_intent = self.state_tracker.get_active_intent()
        if not active_intent:
            return "I'm not sure what you want to do."
        
        # Get filled slots
        filled_slots = {name: slot.value for name, slot in active_intent.slots.items() if slot.filled}
        
        # Generate execution response
        if active_intent.name == "open_project":
            project_name = filled_slots.get("project_name", "unknown")
            response = f"Opening project: {project_name}"
        
        elif active_intent.name == "open_youtube":
            response = "Opening YouTube"
        
        elif active_intent.name == "search_youtube":
            query = filled_slots.get("search_query", "unknown")
            response = f"Searching YouTube for: {query}"
        
        elif active_intent.name == "set_reminder":
            text = filled_slots.get("reminder_text", "unknown")
            time = filled_slots.get("reminder_time", "unknown")
            response = f"Setting reminder: {text} at {time}"
        
        elif active_intent.name == "play_music":
            query = filled_slots.get("music_query", "unknown")
            response = f"Playing: {query}"
        
        elif active_intent.name == "open_file":
            file_name = filled_slots.get("file_name", "unknown")
            response = f"Opening file: {file_name}"
        
        else:
            response = f"Executing {active_intent.name}"
        
        # Clear the intent after execution
        self.state_tracker.complete_intent()
        
        print(f"[DIALOGUE] Executing completed intent: {response}")
        return response
    
    def _handle_open_project_followup(self, user_input: str) -> Optional[str]:
        """Handle follow-up for open project intent"""
        return None  # Implementation already covered by slot filling
    
    def _handle_open_youtube_followup(self, user_input: str) -> Optional[str]:
        """Handle follow-up for open YouTube intent"""
        return None  # Implementation already covered by slot filling
    
    def _handle_search_youtube_followup(self, user_input: str) -> Optional[str]:
        """Handle follow-up for YouTube search intent"""
        return None  # Implementation already covered by slot filling
    
    def _handle_reminder_followup(self, user_input: str) -> Optional[str]:
        """Handle follow-up for reminder intent"""
        return None  # Implementation already covered by slot filling
    
    def _handle_music_followup(self, user_input: str) -> Optional[str]:
        """Handle follow-up for music intent"""
        return None  # Implementation already covered by slot filling
    
    def _handle_file_followup(self, user_input: str) -> Optional[str]:
        """Handle follow-up for file intent"""
        return None  # Implementation already covered by slot filling
    
    def get_dialogue_context(self) -> Dict[str, Any]:
        """Get comprehensive dialogue context for other systems"""
        return {
            "session_memory": {
                "last_user_input": self.session_memory.get_last_user_input(),
                "last_system_response": self.session_memory.get_last_system_response(),
                "last_intent": self.session_memory.get_last_intent(),
                "recent_turns": len(self.session_memory.get_recent(5)),
                "context_continuity": self.session_memory.get_context_continuity()
            },
            "state_tracker": self.state_tracker.get_dialogue_summary(),
            "is_awaiting_clarification": self.state_tracker.is_awaiting_clarification(),
            "has_pending_slots": self.state_tracker.has_pending_slots()
        }
    
    def should_continue_dialogue(self) -> bool:
        """Check if dialogue should continue (vs normal processing)"""
        return (self.state_tracker.is_awaiting_clarification() or 
                self.state_tracker.has_pending_slots())
    
    def store_command_in_memory(self, command: str, response: str, intent: Optional[str] = None):
        """Store command in session memory for context"""
        try:
            self.session_memory.add(command, response, intent)
            if self.logger:
                self.logger.debug(f"Stored command in memory: {command}")
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to store command in memory: {e}")
    
    def get_active_context(self) -> Dict[str, Any]:
        """Get current active context"""
        return {
            "active_intent": self.state_tracker.get_active_intent(),
            "pending_slots": self.state_tracker.get_pending_slots(),
            "dialogue_state": self.state_tracker.get_current_state(),
            "session_active": self.state_tracker.is_dialogue_active()
        }

# Global dialogue manager instance
_dialogue_manager = None

def get_dialogue_manager() -> DialogueManager:
    """Get the global dialogue manager instance"""
    global _dialogue_manager
    if _dialogue_manager is None:
        _dialogue_manager = DialogueManager()
    return _dialogue_manager

def reset_dialogue_manager():
    """Reset the global dialogue manager instance (for testing)"""
    global _dialogue_manager
    if _dialogue_manager:
        _dialogue_manager.state_tracker.clear_intent()
        _dialogue_manager.session_memory.clear()
    _dialogue_manager = None

# Convenience functions for module-level access
def store_command_in_memory(command: str, response: str, intent: Optional[str] = None):
    """Convenience function to store command in memory"""
    manager = get_dialogue_manager()
    return manager.store_command_in_memory(command, response, intent)

def get_active_context() -> Dict[str, Any]:
    """Convenience function to get active context"""
    manager = get_dialogue_manager()
    return manager.get_active_context()
