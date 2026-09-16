"""
NOVA Personality Core
Defines NOVA's identity and core personality traits.
"""

import logging
from typing import Dict, List, Any
from dataclasses import dataclass

@dataclass
class PersonalityProfile:
    """NOVA's personality profile"""
    name: str
    traits: List[str]
    tone: str
    style: str
    greeting_style: str
    error_style: str
    confirmation_style: str
    proactive_style: str

class PersonalityCore:
    """Core personality management for NOVA"""
    
    def __init__(self, logger: logging.Logger | None = None):
        self.logger = logger or logging.getLogger("assistant.personality")
        
        # Load assistant name dynamically — never hardcode "NOVA"
        try:
            from instance.config import settings as _cfg
            _asst_name = _cfg.get_assistant_name() or "Assistant"
        except Exception:
            _asst_name = "Assistant"

        # Define core personality
        self._personality = PersonalityProfile(
            name=_asst_name,
            traits=["calm", "confident", "helpful", "slightly witty", "efficient"],
            tone="professional-friendly",
            style="concise, intelligent, slightly human-like",
            greeting_style="Ready to help.",
            error_style="That didn't go as planned.",
            confirmation_style="Got it.",
            proactive_style="Need anything, or should I suggest something?"
        )
        
        # Personality variations based on context
        self._context_variations = {
            "system": {
                "style": "direct, efficient",
                "confirmation_style": "Done.",
                "error_style": "System issue detected."
            },
            "reminder": {
                "style": "caring, attentive",
                "confirmation_style": "I'll remind you.",
                "error_style": "Reminder setup failed."
            },
            "browser": {
                "style": "helpful, guiding",
                "confirmation_style": "Opening that for you.",
                "error_style": "Browser action failed."
            },
            "ai": {
                "style": "thoughtful, conversational",
                "confirmation_style": "Let me think about that.",
                "error_style": "I couldn't process that."
            }
        }
        
        # Response variations for personality
        self._response_variations = {
            "greetings": [
                "Ready to help.",
                "I'm here.",
                "What can I do?",
                "Listening."
            ],
            "confirmations": [
                "Got it.",
                "Done.",
                "Understood.",
                "On it."
            ],
            "errors": [
                "That didn't go as planned.",
                "Something went wrong.",
                "Let me try that differently.",
                "Technical issue encountered."
            ],
            "proactive": [
                "Need anything, or should I suggest something?",
                "Anything else I can help with?",
                "Want me to suggest something useful?",
                "Ready for your next command?"
            ]
        }
        
        # Memory-based personality adaptation
        self._user_patterns = {}
        self._interaction_count = 0
        
    def get_personality(self, context: str | None = None) -> PersonalityProfile:
        """Get personality profile, optionally context-adjusted"""
        try:
            from instance.config import settings as _cfg
            asst_name = _cfg.get_assistant_name() or "Assistant"
        except Exception:
            asst_name = "Assistant"
        self._personality.name = asst_name
        base_personality = self._personality
        
        if context and context in self._context_variations:
            # Apply context-specific variations
            variations = self._context_variations[context]
            return PersonalityProfile(
                name=base_personality.name,
                traits=base_personality.traits,
                tone=base_personality.tone,
                style=variations.get("style", base_personality.style),
                greeting_style=base_personality.greeting_style,
                error_style=variations.get("error_style", base_personality.error_style),
                confirmation_style=variations.get("confirmation_style", base_personality.confirmation_style),
                proactive_style=base_personality.proactive_style
            )
        
        return base_personality
    
    def get_response_variation(self, response_type: str) -> str:
        """Get a varied response to avoid repetition"""
        variations = self._response_variations.get(response_type, [])
        if variations:
            # Cycle through variations based on interaction count
            index = self._interaction_count % len(variations)
            self._interaction_count += 1
            return variations[index]
        return ""
    
    def adapt_to_user_pattern(self, pattern_type: str, frequency: int):
        """Adapt personality based on user behavior patterns"""
        self._user_patterns[pattern_type] = {
            "frequency": frequency,
            "last_seen": self._interaction_count
        }
        
        if self.logger:
            self.logger.info(f"Personality adapted to pattern: {pattern_type} (freq: {frequency})")
    
    def should_be_proactive(self, idle_time: int) -> bool:
        """Determine if NOVA should be proactive based on personality and context"""
        # NOVA is helpful but not intrusive
        # Be proactive after reasonable idle time
        return idle_time > 1200  # 20 minutes
    
    def get_proactive_suggestion(self, context: Dict[str, Any]) -> str | None:
        """Get personality-driven proactive suggestion"""
        # Check user patterns for personalized suggestions
        for pattern, data in self._user_patterns.items():
            if data["frequency"] > 3:  # Frequent pattern
                if pattern == "youtube":
                    return "You use YouTube often. Want me to open it?"
                elif pattern == "music":
                    return "Time for some music?"
                elif pattern == "search":
                    return "Need help finding something?"
        
        # Default proactive suggestion based on personality
        return self.get_response_variation("proactive")
    
    def format_greeting(self) -> str:
        """Get personality-appropriate greeting"""
        return self.get_response_variation("greetings")
    
    def format_confirmation(self, context: str | None = None) -> str:
        """Get personality-appropriate confirmation"""
        personality = self.get_personality(context)
        return personality.confirmation_style
    
    def format_error(self, context: str | None = None, error_detail: str = "") -> str:
        """Get personality-appropriate error message"""
        personality = self.get_personality(context)
        base_error = personality.error_style
        return f"{base_error} {error_detail}".strip() if error_detail else base_error

# Global personality instance
_personality_core = None

def get_personality() -> PersonalityCore:
    """Get the global personality core instance"""
    global _personality_core
    if _personality_core is None:
        _personality_core = PersonalityCore()
    return _personality_core

def reset_personality():
    """Reset the global personality instance (for testing)"""
    global _personality_core
    _personality_core = None
