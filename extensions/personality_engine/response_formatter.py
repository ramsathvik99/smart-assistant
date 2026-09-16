"""
NOVA Response Formatter
Formats all responses according to NOVA's personality before TTS output.
"""

import logging
from typing import Dict, Any, Optional
from .personality_core import get_personality

class ResponseFormatter:
    """Formats responses according to NOVA's personality"""
    
    def __init__(self, logger: logging.Logger | None = None):
        self.logger = logger or logging.getLogger("assistant.personality.formatter")
        self.personality = get_personality()
        
        # Response templates by intent type
        self.intent_templates = {
            "SYSTEM": [
                "Done. {text}",
                "System action completed. {text}",
                "{text} - handled.",
                "System task done. {text}"
            ],
            "REMINDER": [
                "Got it. {text}",
                "I'll remind you. {text}",
                "Reminder set. {text}",
                "Noted. {text}"
            ],
            "BROWSER": [
                "Opening that for you. {text}",
                "Browser action: {text}",
                "Navigating to {text}",
                "Web access: {text}"
            ],
            "AI": [
                "{text}",  # AI responses are already formatted
                "Here's what I found: {text}",
                "Thinking: {text}",
                "Analysis: {text}"
            ],
            "ERROR": [
                "That didn't go as planned. {text}",
                "Something went wrong. {text}",
                "Let me try that differently. {text}",
                "Technical issue: {text}"
            ],
            "CONFIRMATION": [
                "Got it.",
                "Done.",
                "Understood.",
                "On it.",
                "Confirmed."
            ],
            "GREETING": [
                "Ready to help.",
                "I'm here.",
                "What can I do?",
                "Listening."
            ],
            "PROACTIVE": [
                "Need anything, or should I suggest something?",
                "Anything else I can help with?",
                "Want me to suggest something useful?",
                "Ready for your next command?"
            ]
        }
        
        # Context-specific formatting rules
        self.context_rules = {
            "quick_action": {
                "max_length": 15,
                "style": "direct"
            },
            "complex_action": {
                "max_length": 50,
                "style": "informative"
            },
            "error_recovery": {
                "max_length": 40,
                "style": "reassuring"
            }
        }
    
    def format_response(self, text: str, intent: str | None = None, context: Dict[str, Any] | None = None) -> str:
        """
        Format response according to NOVA's personality and intent.
        
        Args:
            text: The raw response text
            intent: The intent type (SYSTEM, REMINDER, BROWSER, AI, ERROR, etc.)
            context: Additional context for formatting decisions
            
        Returns:
            Formatted response string
        """
        if not text or not text.strip():
            return ""
        
        # Get personality for context
        context_type = context.get("type") if context else None
        personality = self.personality.get_personality(context_type)
        
        # Apply intent-specific formatting
        if intent and intent in self.intent_templates:
            formatted = self._apply_intent_template(text, intent)
        else:
            formatted = text
        
        # Apply personality style
        formatted = self._apply_personality_style(formatted, personality, context)
        
        # Apply context rules
        formatted = self._apply_context_rules(formatted, context)
        
        # Ensure consistency with NOVA's voice
        formatted = self._ensure_voice_consistency(formatted)
        
        if self.logger:
            self.logger.debug(f"Formatted response: '{formatted}' (intent: {intent})")
        
        return formatted
    
    def _apply_intent_template(self, text: str, intent: str) -> str:
        """Apply intent-specific template to response"""
        templates = self.intent_templates.get(intent, [])
        if not templates:
            return text
        
        # Select template (could be more sophisticated with context)
        template = templates[0]  # Use first template for consistency
        
        # Format with the text
        if "{text}" in template:
            return template.format(text=text)
        else:
            return template
    
    def _apply_personality_style(self, text: str, personality, context: Dict[str, Any] | None) -> str:
        """Apply personality style to response"""
        # Apply personality traits
        if "concise" in personality.style:
            text = self._make_concise(text)
        
        if "intelligent" in personality.style:
            text = self._add_intelligence_flair(text)
        
        if "slightly human-like" in personality.style:
            text = self._add_human_touch(text)
        
        if "efficient" in personality.traits:
            text = self._make_efficient(text)
        
        return text
    
    def _apply_context_rules(self, text: str, context: Dict[str, Any] | None) -> str:
        """Apply context-specific formatting rules"""
        if not context:
            return text
        
        rule_type = context.get("rule_type")
        if rule_type and rule_type in self.context_rules:
            rule = self.context_rules[rule_type]
            
            if rule.get("max_length") and len(text) > rule["max_length"]:
                text = text[:rule["max_length"]].rstrip() + "..."
            
            if rule.get("style") == "direct":
                text = self._make_direct(text)
            elif rule.get("style") == "informative":
                text = self._make_informative(text)
            elif rule.get("style") == "reassuring":
                text = self._make_reassuring(text)
        
        return text
    
    def _ensure_voice_consistency(self, text: str) -> str:
        """Ensure response is consistent with NOVA's voice"""
        # Avoid overly casual language
        casual_phrases = ["yeah", "nope", "sure thing", "you bet"]
        for phrase in casual_phrases:
            text = text.replace(phrase, phrase.replace(phrase, {
                "yeah": "yes",
                "nope": "no", 
                "sure thing": "certainly",
                "you bet": "absolutely"
            }.get(phrase, phrase)))
        
        # Ensure professional but friendly tone
        text = text.replace("I think", "I believe")
        text = text.replace("I guess", "I suggest")
        
        return text
    
    def _make_concise(self, text: str) -> str:
        """Make response more concise"""
        # Remove unnecessary words
        unnecessary_words = ["just", "really", "actually", "basically"]
        for word in unnecessary_words:
            text = text.replace(f" {word} ", " ")
            text = text.replace(f"{word} ", "")
            text = text.replace(f" {word}", "")
        
        return text.strip()
    
    def _add_intelligence_flair(self, text: str) -> str:
        """Add intelligent flair to response"""
        # This could add sophisticated vocabulary or structure
        # For now, keep it subtle
        return text
    
    def _add_human_touch(self, text: str) -> str:
        """Add slight human touch without being too casual"""
        # Add subtle conversational elements
        if not any(text.endswith(punct) for punct in [".", "!", "?"]):
            text += "."
        
        return text
    
    def _make_efficient(self, text: str) -> str:
        """Make response more efficient"""
        # Remove filler words and get straight to point
        filler_phrases = ["as you know", "to be honest", "if you ask me"]
        for phrase in filler_phrases:
            text = text.replace(phrase, "")
        
        return text.strip()
    
    def _make_direct(self, text: str) -> str:
        """Make response more direct"""
        # Remove hedging language
        hedges = ["maybe", "perhaps", "possibly", "might"]
        for hedge in hedges:
            text = text.replace(hedge, "")
        
        return text.strip()
    
    def _make_informative(self, text: str) -> str:
        """Make response more informative"""
        # Could add more detail here if needed
        return text
    
    def _make_reassuring(self, text: str) -> str:
        """Make response more reassuring"""
        # Add reassuring elements
        reassuring_prefixes = ["Don't worry.", "It's okay.", "No problem."]
        if not any(text.startswith(prefix) for prefix in reassuring_prefixes):
            text = f"No problem. {text}"
        
        return text

# Global formatter instance
_response_formatter = None

def get_response_formatter() -> ResponseFormatter:
    """Get the global response formatter instance"""
    global _response_formatter
    if _response_formatter is None:
        _response_formatter = ResponseFormatter()
    return _response_formatter

def format_response(text: str, intent: str | None = None, context: Dict[str, Any] | None = None) -> str:
    """Convenience function to format a response"""
    formatter = get_response_formatter()
    return formatter.format_response(text, intent, context)

def reset_response_formatter():
    """Reset the global response formatter instance (for testing)"""
    global _response_formatter
    _response_formatter = None
