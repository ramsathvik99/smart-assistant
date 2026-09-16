"""
NOVA Proactive Personality
Handles proactive interactions and personality-driven suggestions.
"""

import logging
import time
import threading
from typing import Dict, Any, Optional, Callable
from .personality_core import get_personality
from .behavior_layer import get_behavior_layer

class ProactivePersonality:
    """Manages proactive personality-driven interactions"""
    
    def __init__(self, logger: logging.Logger | None = None):
        self.logger = logger or logging.getLogger("assistant.personality.proactive")
        self.personality = get_personality()
        self.behavior_layer = get_behavior_layer()
        
        # Proactive settings
        self.enabled = True
        self.idle_threshold = 1200  # 20 minutes
        self.last_interaction_time = time.time()
        self.proactive_thread = None
        self.proactive_running = False
        
        # Proactive message variations
        self.proactive_messages = [
            "Need anything, or should I suggest something?",
            "Anything else I can help with?", 
            "Want me to suggest something useful?",
            "Ready for your next command?",
            "How can I assist you further?"
        ]
        
        # Context-aware proactive messages
        self.context_proactive_messages = {
            "browser": [
                "Need help navigating or searching?",
                "Want me to find something specific?",
                "Ready for your next web task?"
            ],
            "system": [
                "Want me to optimize your system settings?",
                "Need help with any applications?",
                "Ready for your next system task?"
            ],
            "music": [
                "Time for some music?",
                "Want me to play something different?",
                "Ready for your next music request?"
            ]
        }
    
    def start_proactive_system(self):
        """Start the proactive personality system"""
        if not self.enabled or self.proactive_running:
            return
        
        self.proactive_running = True
        self.proactive_thread = threading.Thread(target=self._proactive_loop, daemon=True)
        self.proactive_thread.start()
        self.logger.info("Proactive personality system started")
    
    def stop_proactive_system(self):
        """Stop the proactive personality system"""
        self.proactive_running = False
        if self.proactive_thread:
            self.proactive_thread.join(timeout=2)
        self.logger.info("Proactive personality system stopped")
    
    def update_interaction_time(self):
        """Update the last interaction time"""
        self.last_interaction_time = time.time()
    
    def get_proactive_message(self, context: Dict[str, Any] | None = None) -> Optional[str]:
        """Get a personality-driven proactive message"""
        if not self.enabled:
            return None
        
        # Check for personalized suggestions first
        if context:
            personalized = self._get_personalized_suggestion(context)
            if personalized:
                return personalized
        
        # Get context-aware message
        context_type = context.get("type") if context else None
        if context_type and context_type in self.context_proactive_messages:
            messages = self.context_proactive_messages[context_type]
            index = int(time.time()) % len(messages)  # Cycle through messages
            return messages[index]
        
        # Get general proactive message
        index = int(time.time()) % len(self.proactive_messages)
        return self.proactive_messages[index]
    
    def _proactive_loop(self):
        """Main proactive interaction loop"""
        while self.proactive_running:
            try:
                current_time = time.time()
                idle_time = current_time - self.last_interaction_time
                
                # Check if should be proactive
                if idle_time > self.idle_threshold:
                    # Get current context
                    context = self._get_current_context()
                    
                    # Get proactive message
                    message = self.get_proactive_message(context)
                    
                    if message:
                        # Import here to avoid circular imports
                        from legacy.assistant import speak_with_personality
                        
                        # Speak proactive message
                        speak_with_personality(message, "PROACTIVE", context)
                        
                        # Reset interaction time to avoid spam
                        self.last_interaction_time = current_time
                
                # Sleep for a reasonable interval
                time.sleep(300)  # Check every 5 minutes
                
            except Exception as e:
                self.logger.error(f"Proactive loop error: {e}")
                time.sleep(60)  # Wait before retrying
    
    def _get_current_context(self) -> Dict[str, Any]:
        """Get current context for proactive suggestions"""
        return {"type": "none"}
    
    def _get_personalized_suggestion(self, context: Dict[str, Any]) -> Optional[str]:
        """Get personalized suggestion based on user patterns"""
        try:
            # Get behavior insights
            insights = self.behavior_layer.get_behavior_insights()
            
            # Check for frequent patterns
            most_frequent = insights.get("most_frequent_patterns", [])
            if most_frequent:
                pattern_name, count = most_frequent[0]
                
                # Map patterns to suggestions
                pattern_suggestions = {
                    "frequent_youtube": "You use YouTube often. Want me to open it?",
                    "frequent_music": "Time for some music?",
                    "frequent_search": "Need help finding something specific?",
                    "frequent_reminders": "Want me to help organize your schedule?"
                }
                
                if pattern_name in pattern_suggestions and count > 3:
                    return pattern_suggestions[pattern_name]
        
        except Exception as e:
            self.logger.error(f"Error getting personalized suggestion: {e}")
        
        return None
    
    def should_be_proactive(self, idle_time: int) -> bool:
        """Determine if NOVA should be proactive"""
        return self.enabled and idle_time > self.idle_threshold
    
    def set_idle_threshold(self, seconds: int):
        """Set the idle threshold for proactive interactions"""
        self.idle_threshold = max(300, seconds)  # Minimum 5 minutes
        self.logger.info(f"Idle threshold set to {seconds} seconds")
    
    def enable_proactive(self, enabled: bool):
        """Enable or disable proactive personality"""
        self.enabled = enabled
        if enabled and not self.proactive_running:
            self.start_proactive_system()
        elif not enabled and self.proactive_running:
            self.stop_proactive_system()
        
        self.logger.info(f"Proactive personality {'enabled' if enabled else 'disabled'}")

# Global proactive personality instance
_proactive_personality = None

def get_proactive_personality() -> ProactivePersonality:
    """Get the global proactive personality instance"""
    global _proactive_personality
    if _proactive_personality is None:
        _proactive_personality = ProactivePersonality()
    return _proactive_personality

def start_proactive_system():
    """Start the proactive personality system"""
    proactive = get_proactive_personality()
    proactive.start_proactive_system()

def stop_proactive_system():
    """Stop the proactive personality system"""
    proactive = get_proactive_personality()
    proactive.stop_proactive_system()

def update_proactive_interaction():
    """Update proactive interaction time"""
    proactive = get_proactive_personality()
    proactive.update_interaction_time()

def reset_proactive_personality():
    """Reset the global proactive personality instance (for testing)"""
    global _proactive_personality
    if _proactive_personality:
        _proactive_personality.stop_proactive_system()
    _proactive_personality = None
