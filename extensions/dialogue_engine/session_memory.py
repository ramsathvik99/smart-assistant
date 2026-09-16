"""
Session Memory Module
Manages short-term conversation history and context.
"""

import threading
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta

@dataclass
class DialogueTurn:
    """Represents a single dialogue turn"""
    user_input: str
    system_response: str
    timestamp: datetime
    intent: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

class SessionMemory:
    """Manages short-term conversation memory with intelligent context tracking"""
    
    def __init__(self, max_history: int = 20, session_timeout: int = 3600):
        self.max_history = max_history
        self.session_timeout = session_timeout  # 1 hour default
        self._history: List[DialogueTurn] = []
        self._lock = threading.Lock()
        self._session_start = datetime.now()
        self._last_interaction = datetime.now()
    
    def add(self, user_input: str, system_response: str, intent: Optional[str] = None, 
            context: Optional[Dict[str, Any]] = None, metadata: Optional[Dict[str, Any]] = None):
        """Add a dialogue turn to memory"""
        with self._lock:
            turn = DialogueTurn(
                user_input=user_input,
                system_response=system_response,
                timestamp=datetime.now(),
                intent=intent,
                context=context or {},
                metadata=metadata or {}
            )
            
            self._history.append(turn)
            self._last_interaction = datetime.now()
            
            # Maintain max history size
            if len(self._history) > self.max_history:
                self._history.pop(0)
    
    def get_last(self) -> Optional[DialogueTurn]:
        """Get the last dialogue turn"""
        with self._lock:
            return self._history[-1] if self._history else None
    
    def get_recent(self, n: int = 5) -> List[DialogueTurn]:
        """Get the last n dialogue turns"""
        with self._lock:
            return self._history[-n:] if self._history else []
    
    def get_all(self) -> List[DialogueTurn]:
        """Get all dialogue turns"""
        with self._lock:
            return self._history.copy()
    
    def get_user_inputs(self, n: int = 5) -> List[str]:
        """Get the last n user inputs"""
        with self._lock:
            return [turn.user_input for turn in self._history[-n:]]
    
    def get_system_responses(self, n: int = 5) -> List[str]:
        """Get the last n system responses"""
        with self._lock:
            return [turn.system_response for turn in self._history[-n:]]
    
    def get_last_user_input(self) -> Optional[str]:
        """Get the last user input"""
        last_turn = self.get_last()
        return last_turn.user_input if last_turn else None
    
    def get_last_system_response(self) -> Optional[str]:
        """Get the last system response"""
        last_turn = self.get_last()
        return last_turn.system_response if last_turn else None
    
    def get_last_intent(self) -> Optional[str]:
        """Get the last intent"""
        last_turn = self.get_last()
        return last_turn.intent if last_turn else None
    
    def get_context_continuity(self) -> Dict[str, Any]:
        """Analyze context continuity for intelligent follow-ups"""
        with self._lock:
            if not self._history:
                return {}
            
            recent_turns = self._history[-3:]  # Last 3 turns
            continuity = {
                "active_intents": [],
                "context_keywords": [],
                "pending_tasks": [],
                "conversation_flow": "normal"
            }
            
            # Track active intents
            for turn in recent_turns:
                if turn.intent and turn.intent not in continuity["active_intents"]:
                    continuity["active_intents"].append(turn.intent)
            
            # Extract context keywords
            for turn in recent_turns:
                words = turn.user_input.lower().split()
                continuity["context_keywords"].extend([w for w in words if len(w) > 3])
            
            # Detect pending tasks
            for turn in recent_turns:
                if "pending" in turn.metadata:
                    continuity["pending_tasks"].extend(turn.metadata["pending"])
            
            # Analyze conversation flow
            if len(self._history) >= 2:
                last_two = self._history[-2:]
                if (last_two[0].intent == last_two[1].intent and 
                    last_two[0].intent in ["search", "open", "play"]):
                    continuity["conversation_flow"] = "continuation"
                elif "?" in last_two[1].system_response:
                    continuity["conversation_flow"] = "clarification_needed"
            
            return continuity
    
    def find_related_context(self, current_input: str) -> Optional[DialogueTurn]:
        """Find related context from history based on current input"""
        with self._lock:
            if not self._history:
                return None
            
            current_words = set(current_input.lower().split())
            
            # Search for related turns
            for turn in reversed(self._history[-5:]):  # Check last 5 turns
                turn_words = set(turn.user_input.lower().split())
                
                # Check for word overlap
                overlap = current_words.intersection(turn_words)
                if len(overlap) >= 2:  # At least 2 overlapping words
                    return turn
            
            return None
    
    def is_session_active(self) -> bool:
        """Check if session is still active (not timed out)"""
        time_since_last = datetime.now() - self._last_interaction
        return time_since_last.total_seconds() < self.session_timeout
    
    def get_session_duration(self) -> timedelta:
        """Get session duration"""
        return datetime.now() - self._session_start
    
    def clear(self):
        """Clear all session memory"""
        with self._lock:
            self._history.clear()
            self._session_start = datetime.now()
            self._last_interaction = datetime.now()
    
    def get_conversation_summary(self) -> Dict[str, Any]:
        """Get a summary of the conversation"""
        with self._lock:
            if not self._history:
                return {"turns": 0, "duration": 0, "intents": []}
            
            intents = [turn.intent for turn in self._history if turn.intent]
            unique_intents = list(set(intents))
            
            return {
                "turns": len(self._history),
                "duration": self.get_session_duration().total_seconds(),
                "intents": unique_intents,
                "last_intent": self.get_last_intent(),
                "session_active": self.is_session_active(),
                "context_continuity": self.get_context_continuity()
            }

# Global session memory instance
_session_memory = None

def get_session_memory() -> SessionMemory:
    """Get the global session memory instance"""
    global _session_memory
    if _session_memory is None:
        _session_memory = SessionMemory()
    return _session_memory

def reset_session_memory():
    """Reset the global session memory instance (for testing)"""
    global _session_memory
    if _session_memory:
        _session_memory.clear()
    _session_memory = None
