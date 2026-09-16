"""
State Tracker Module
Tracks conversation state, pending slots, and dialogue flow.
"""

import threading
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum

class DialogueState(Enum):
    """Dialogue state enumeration"""
    IDLE = "idle"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    SLOT_FILLING = "slot_filling"
    TASK_EXECUTION = "task_execution"
    FOLLOW_UP = "follow_up"
    ERROR_RECOVERY = "error_recovery"

@dataclass
class SlotInfo:
    """Information about a pending slot"""
    name: str
    prompt: str
    required: bool = True
    filled: bool = False
    value: Any = None
    validation_func: Optional[Callable[[Any], bool]] = None
    error_message: str = ""

@dataclass
class IntentInfo:
    """Information about an active intent"""
    name: str
    slots: Dict[str, SlotInfo] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=lambda: __import__('time').time())
    confidence: float = 0.0

class StateTracker:
    """Tracks conversation state and manages slot filling"""
    
    def __init__(self):
        self._lock = threading.Lock()
        self._state = DialogueState.IDLE
        self._active_intent: Optional[IntentInfo] = None
        self._pending_slots: List[str] = []
        self._context_data: Dict[str, Any] = {}
        self._dialogue_stack: List[IntentInfo] = []
        self._error_count = 0
        self._max_errors = 3
        
        # Slot definitions for common intents
        self._slot_definitions = {
            "open_project": {
                "project_name": SlotInfo("project_name", "Which project would you like to open?"),
                "project_type": SlotInfo("project_type", "What type of project is it?", required=False)
            },
            "open_youtube": {
                # No slots needed - complete command
            },
            "search_youtube": {
                "search_query": SlotInfo("search_query", "What would you like to search for?"),
                "filter_type": SlotInfo("filter_type", "Any specific filters?", required=False)
            },
            "set_reminder": {
                "reminder_text": SlotInfo("reminder_text", "What should I remind you about?"),
                "reminder_time": SlotInfo("reminder_time", "When should I remind you?"),
                "reminder_priority": SlotInfo("reminder_priority", "How important is this?", required=False)
            },
            "play_music": {
                "music_query": SlotInfo("music_query", "What would you like to listen to?"),
                "music_genre": SlotInfo("music_genre", "Any specific genre?", required=False),
                "music_mood": SlotInfo("music_mood", "What mood are you in?", required=False)
            },
            "open_file": {
                "file_name": SlotInfo("file_name", "Which file would you like to open?"),
                "file_path": SlotInfo("file_path", "Where is the file located?", required=False)
            }
        }
    
    def set_state(self, state: DialogueState):
        """Set the current dialogue state"""
        with self._lock:
            self._state = state
    
    def get_state(self) -> DialogueState:
        """Get the current dialogue state"""
        with self._lock:
            return self._state
    
    def set_intent(self, intent_name: str, confidence: float = 0.0):
        """Set active intent"""
        with self._lock:
            print(f"[DIALOGUE] Setting intent: {intent_name} (confidence: {confidence})")
            
            # Save current intent to stack if it exists
            if self._active_intent and self._state != DialogueState.ERROR_RECOVERY:
                self._dialogue_stack.append(self._active_intent)
            
            # Create new intent info
            self._active_intent = IntentInfo(
                name=intent_name,
                confidence=confidence
            )
            
            # Initialize slots for this intent
            if intent_name in self._slot_definitions:
                self._active_intent.slots = self._slot_definitions[intent_name].copy()
            
            self._state = DialogueState.SLOT_FILLING
            self._pending_slots = [name for name, slot in self._active_intent.slots.items() 
                                 if not slot.filled and slot.required]
            
            print(f"[DIALOGUE] New state: {self._state.value}")
            print(f"[DIALOGUE] Pending slots: {self._pending_slots}")
    
    def get_active_intent(self) -> Optional[IntentInfo]:
        """Get the current active intent"""
        with self._lock:
            return self._active_intent
    
    def set_pending_slot(self, slot_name: str):
        """Set a slot as pending for clarification"""
        with self._lock:
            if self._active_intent and slot_name in self._active_intent.slots:
                self._pending_slots = [slot_name]
                self._state = DialogueState.AWAITING_CLARIFICATION
    
    def fill_slot(self, slot_name: str, value: Any) -> bool:
        """Fill a slot with a value"""
        with self._lock:
            print(f"[DIALOGUE] Filling slot {slot_name} with value: {value}")
            
            if not self._active_intent or slot_name not in self._active_intent.slots:
                print(f"[DIALOGUE] Slot fill failed - no active intent or unknown slot")
                return False
            
            slot = self._active_intent.slots[slot_name]
            
            print(f"[DIALOGUE] About to fill slot {slot_name}:")
            print(f"[DIALOGUE] Slot object: {slot}")
            print(f"[DIALOGUE] Slot value to set: {value}")
            
            # Validate value if validation function exists
            if slot.validation_func and not slot.validation_func(value):
                slot.error_message = f"Invalid value for {slot_name}"
                print(f"[DIALOGUE] Slot validation failed: {slot.error_message}")
                return False
            
            print(f"[DIALOGUE] Setting slot.value to: {value}")
            slot.value = value
            slot.filled = True
            
            print(f"[DIALOGUE] Slot after fill: {slot}")
            
            # Remove from pending slots
            if slot_name in self._pending_slots:
                self._pending_slots.remove(slot_name)
                print(f"[DIALOGUE] Removed {slot_name} from pending slots")
            
            # Check if all required slots are filled
            required_slots = [name for name, slot in self._active_intent.slots.items() 
                           if slot.required and not slot.filled]
            
            print(f"[DIALOGUE] Required slots still needed: {required_slots}")
            
            if not required_slots:
                self._state = DialogueState.TASK_EXECUTION
                print(f"[DIALOGUE] All required slots filled - moving to TASK_EXECUTION")
            
            print(f"[DIALOGUE] Updated pending slots: {self._pending_slots}")
            return True
    
    def get_pending_slots(self) -> List[str]:
        """Get list of pending slots"""
        with self._lock:
            return self._pending_slots.copy()
    
    def get_next_pending_slot(self) -> Optional[SlotInfo]:
        """Get the next slot that needs to be filled"""
        with self._lock:
            if not self._pending_slots or not self._active_intent:
                return None
            
            slot_name = self._pending_slots[0]
            return self._active_intent.slots.get(slot_name)
    
    def get_slot_prompt(self) -> Optional[str]:
        """Get the prompt for the next pending slot"""
        slot = self.get_next_pending_slot()
        return slot.prompt if slot else None
    
    def set_context_data(self, key: str, value: Any):
        """Set context data"""
        with self._lock:
            self._context_data[key] = value
    
    def get_context_data(self, key: str) -> Any:
        """Get context data"""
        with self._lock:
            return self._context_data.get(key)
    
    def get_all_context_data(self) -> Dict[str, Any]:
        """Get all context data"""
        with self._lock:
            return self._context_data.copy()
    
    def clear_intent(self):
        """Clear the current intent and reset state"""
        with self._lock:
            self._active_intent = None
            self._pending_slots.clear()
            self._context_data.clear()
            self._state = DialogueState.IDLE
            self._error_count = 0
    
    def complete_intent(self):
        """Mark the current intent as completed"""
        with self._lock:
            if self._active_intent:
                # Move to completed stack
                self._dialogue_stack.append(self._active_intent)
            
            self._active_intent = None
            self._pending_slots.clear()
            self._state = DialogueState.IDLE
            self._error_count = 0
    
    def handle_error(self, error_message: str = ""):
        """Handle an error in dialogue processing"""
        with self._lock:
            self._error_count += 1
            
            if self._error_count >= self._max_errors:
                # Too many errors, reset
                self.clear_intent()
                self._state = DialogueState.ERROR_RECOVERY
                return False
            else:
                self._state = DialogueState.ERROR_RECOVERY
                return True
    
    def get_dialogue_summary(self) -> Dict[str, Any]:
        """Get a summary of the current dialogue state"""
        with self._lock:
            summary = {
                "state": self._state.value,
                "active_intent": self._active_intent.name if self._active_intent else None,
                "pending_slots": self._pending_slots.copy(),
                "context_data": self._context_data.copy(),
                "error_count": self._error_count,
                "dialogue_stack_depth": len(self._dialogue_stack)
            }
            
            if self._active_intent:
                summary["intent_confidence"] = self._active_intent.confidence
                summary["filled_slots"] = {name: slot.value for name, slot in self._active_intent.slots.items() if slot.filled}
            
            return summary
    
    def is_awaiting_clarification(self) -> bool:
        """Check if system is waiting for user clarification"""
        with self._lock:
            return self._state == DialogueState.AWAITING_CLARIFICATION
    
    def is_slot_filling(self) -> bool:
        """Check if system is in slot filling mode"""
        with self._lock:
            return self._state == DialogueState.SLOT_FILLING
    
    def has_pending_slots(self) -> bool:
        """Check if there are pending slots"""
        with self._lock:
            return len(self._pending_slots) > 0
    
    def restore_previous_intent(self) -> bool:
        """Restore the previous intent from the stack"""
        with self._lock:
            if not self._dialogue_stack:
                return False
            
            self._active_intent = self._dialogue_stack.pop()
            self._state = DialogueState.SLOT_FILLING
            self._pending_slots = [name for name, slot in self._active_intent.slots.items() 
                                 if not slot.filled and slot.required]
            return True

# Global state tracker instance
_state_tracker = None

def get_state_tracker() -> StateTracker:
    """Get the global state tracker instance"""
    global _state_tracker
    if _state_tracker is None:
        _state_tracker = StateTracker()
    return _state_tracker

def reset_state_tracker():
    """Reset the global state tracker instance (for testing)"""
    global _state_tracker
    if _state_tracker:
        _state_tracker.clear_intent()
    _state_tracker = None
