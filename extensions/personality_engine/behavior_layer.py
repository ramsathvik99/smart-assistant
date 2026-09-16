"""
NOVA Behavior Layer
Implements personality-driven behavior logic and proactive interactions.
"""

import logging
import time
from typing import Dict, Any, List, Optional
from .personality_core import get_personality

class BehaviorLayer:
    """Implements NOVA's personality-driven behavior"""
    
    def __init__(self, logger: logging.Logger | None = None):
        self.logger = logger or logging.getLogger("assistant.personality.behavior")
        self.personality = get_personality()
        
        # User behavior tracking
        self.user_patterns = {}
        self.command_history = []
        self.last_interaction_time = time.time()
        self.idle_start_time = time.time()
        
        # Behavior rules
        self.behavior_rules = {
            "fatigue_detection": {
                "threshold": 3600,  # 1 hour of continuous use
                "response": "You've been active for a while. Maybe take a short break."
            },
            "idle_proactive": {
                "threshold": 1200,  # 20 minutes idle
                "enabled": True
            },
            "repetition_detection": {
                "threshold": 3,  # Same command 3 times
                "response": "You've been doing that frequently. Want me to help with something else?"
            },
            "context_switch": {
                "enabled": True,
                "response": "Switching contexts for you."
            }
        }
        
        # Proactive suggestion patterns
        self.proactive_patterns = {
            "frequent_youtube": {
                "pattern": "youtube",
                "frequency_threshold": 3,
                "suggestion": "You use YouTube often. Want me to open it?"
            },
            "frequent_music": {
                "pattern": "music",
                "frequency_threshold": 3,
                "suggestion": "Time for some music?"
            },
            "frequent_search": {
                "pattern": "search",
                "frequency_threshold": 3,
                "suggestion": "Need help finding something specific?"
            },
            "frequent_reminders": {
                "pattern": "remind",
                "frequency_threshold": 2,
                "suggestion": "You're setting reminders frequently. Want me to organize your schedule?"
            }
        }
    
    def adjust_behavior(self, command: str, context: Dict[str, Any] | None, memory: List[str] | None = None) -> Optional[str]:
        """
        Adjust behavior based on command, context, and memory.
        Returns personality-driven message or None.
        """
        # Update tracking
        self._update_tracking(command, context)
        
        # Check for fatigue
        fatigue_msg = self._check_fatigue()
        if fatigue_msg:
            return fatigue_msg
        
        # Check for repetition patterns
        repetition_msg = self._check_repetition_patterns(command)
        if repetition_msg:
            return repetition_msg
        
        # Check for context-based behavior
        context_msg = self._check_context_behavior(command, context)
        if context_msg:
            return context_msg
        
        # Check memory-based behavior
        memory_msg = self._check_memory_behavior(command, memory)
        if memory_msg:
            return memory_msg
        
        return None
    
    def get_proactive_suggestion(self, current_context: Dict[str, Any] | None = None) -> Optional[str]:
        """Get proactive personality-driven suggestion"""
        current_time = time.time()
        idle_time = current_time - self.last_interaction_time
        
        # Check if should be proactive
        if not self.personality.should_be_proactive(idle_time):
            return None
        
        # Check for personalized suggestions based on patterns
        pattern_suggestion = self._get_pattern_based_suggestion()
        if pattern_suggestion:
            return pattern_suggestion
        
        # Check context-based suggestions
        context_suggestion = self._get_context_based_suggestion(current_context)
        if context_suggestion:
            return context_suggestion
        
        # Default proactive suggestion
        return self.personality.get_proactive_suggestion(current_context or {})
    
    def update_interaction(self, command: str, context: Dict[str, Any] | None = None):
        """Update interaction tracking"""
        self.last_interaction_time = time.time()
        self.command_history.append({
            "command": command,
            "context": context,
            "timestamp": time.time()
        })
        
        # Keep history manageable
        if len(self.command_history) > 100:
            self.command_history = self.command_history[-50:]
    
    def _update_tracking(self, command: str, context: Dict[str, Any] | None):
        """Update internal tracking data"""
        # Update user patterns
        command_lower = command.lower()
        
        for pattern_name, pattern_config in self.proactive_patterns.items():
            pattern = pattern_config["pattern"]
            if pattern in command_lower:
                if pattern_name not in self.user_patterns:
                    self.user_patterns[pattern_name] = {
                        "count": 0,
                        "last_seen": time.time()
                    }
                
                self.user_patterns[pattern_name]["count"] += 1
                self.user_patterns[pattern_name]["last_seen"] = time.time()
    
    def _check_fatigue(self) -> Optional[str]:
        """Check for user fatigue and suggest break"""
        if len(self.command_history) < 10:
            return None
        
        # Calculate session duration
        first_command = self.command_history[0]
        session_duration = time.time() - first_command["timestamp"]
        
        if session_duration > self.behavior_rules["fatigue_detection"]["threshold"]:
            return self.behavior_rules["fatigue_detection"]["response"]
        
        return None
    
    def _check_repetition_patterns(self, command: str) -> Optional[str]:
        """Check for repetitive command patterns"""
        if len(self.command_history) < 3:
            return None
        
        # Check last 3 commands
        recent_commands = [cmd["command"] for cmd in self.command_history[-3:]]
        
        if recent_commands.count(command) >= self.behavior_rules["repetition_detection"]["threshold"]:
            return self.behavior_rules["repetition_detection"]["response"]
        
        return None
    
    def _check_context_behavior(self, command: str, context: Dict[str, Any] | None) -> Optional[str]:
        """Check for context-based behavior adjustments"""
        if not context:
            return None
        
        command_lower = command.lower()
        
        # Check for context-specific behaviors
        if "tired" in command_lower or "fatigue" in command_lower:
            return "You've been active for a while. Maybe take a short break."
        
        if "help" in command_lower and "confused" in command_lower:
            return "Let me clarify that for you step by step."
        
        if context.get("type") == "error" and "again" in command_lower:
            return "Let me try a different approach this time."
        
        return None
    
    def _check_memory_behavior(self, command: str, memory: List[str] | None) -> Optional[str]:
        """Check for memory-based behavior adjustments"""
        if not memory:
            return None
        
        command_lower = command.lower()
        
        # Check if user is asking about previous interactions
        if "what did i" in command_lower or "what was" in command_lower:
            return "Looking at your recent activity..."
        
        # Check for patterns in memory
        memory_text = " ".join(memory).lower()
        
        if "youtube" in memory_text and "youtube" in command_lower:
            return "Opening YouTube like usual?"
        
        if "music" in memory_text and "music" in command_lower:
            return "Continuing with your music preferences?"
        
        return None
    
    def _get_pattern_based_suggestion(self) -> Optional[str]:
        """Get suggestion based on user behavior patterns"""
        for pattern_name, pattern_data in self.user_patterns.items():
            count = pattern_data["count"]
            
            # Find corresponding proactive pattern
            for proactive_name, proactive_config in self.proactive_patterns.items():
                if proactive_name == pattern_name:
                    threshold = proactive_config["frequency_threshold"]
                    if count >= threshold:
                        return proactive_config["suggestion"]
        
        return None
    
    def _get_context_based_suggestion(self, current_context: Dict[str, Any] | None) -> Optional[str]:
        """Get suggestion based on current context"""
        if not current_context:
            return None
        
        context_type = current_context.get("type")
        
        if context_type == "browser":
            return "Need help navigating or searching?"
        
        if context_type == "system":
            return "Want me to optimize your system settings?"
        
        if context_type == "idle":
            return "Ready to assist with your next task?"
        
        return None
    
    def get_behavior_insights(self) -> Dict[str, Any]:
        """Get insights about user behavior patterns"""
        return {
            "total_interactions": len(self.command_history),
            "session_duration": time.time() - self.command_history[0]["timestamp"] if self.command_history else 0,
            "patterns_detected": list(self.user_patterns.keys()),
            "most_frequent_patterns": sorted(
                [(name, data["count"]) for name, data in self.user_patterns.items()],
                key=lambda x: x[1],
                reverse=True
            )[:5]
        }

# Global behavior layer instance
_behavior_layer = None

def get_behavior_layer() -> BehaviorLayer:
    """Get the global behavior layer instance"""
    global _behavior_layer
    if _behavior_layer is None:
        _behavior_layer = BehaviorLayer()
    return _behavior_layer

def adjust_behavior(command: str, context: Dict[str, Any] | None, memory: List[str] | None = None) -> Optional[str]:
    """Convenience function to adjust behavior"""
    behavior = get_behavior_layer()
    return behavior.adjust_behavior(command, context, memory)

def reset_behavior_layer():
    """Reset the global behavior layer instance (for testing)"""
    global _behavior_layer
    _behavior_layer = None
