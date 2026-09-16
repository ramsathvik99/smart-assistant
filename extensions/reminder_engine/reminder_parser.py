"""
Reminder Parser Module
Extracts reminder text and timing from user commands.
"""

import re
import time
from typing import Optional, Tuple, Dict

class ReminderParser:
    """Parses reminder commands to extract text and timing."""
    
    def __init__(self):
        # Compile regex patterns for performance
        self._reminder_patterns = [
            # "remind me to [text] in [time]"
            re.compile(r'remind\s+me\s+to\s+(.+?)\s+in\s+(.+)$', re.IGNORECASE),
            # "remind me to [text] after [time]"
            re.compile(r'remind\s+me\s+to\s+(.+?)\s+after\s+(.+)$', re.IGNORECASE),
            # "set reminder to [text] in [time]"
            re.compile(r'set\s+reminder\s+to\s+(.+?)\s+in\s+(.+)$', re.IGNORECASE),
            # "remind me [text] in [time]" (without "to")
            re.compile(r'remind\s+me\s+(.+?)\s+in\s+(.+)$', re.IGNORECASE),
            # "reminder [text] in [time]" (minimal) - fixed pattern
            re.compile(r'reminder\s+(?:to\s+)?(.+?)\s+in\s+(.+)$', re.IGNORECASE),
        ]
        
        # Time parsing patterns
        self._time_patterns = {
            # Seconds
            r'(\d+)\s*seconds?': lambda m: int(m.group(1)),
            r'(\d+)\s*sec': lambda m: int(m.group(1)),
            
            # Minutes  
            r'(\d+)\s*minutes?': lambda m: int(m.group(1)) * 60,
            r'(\d+)\s*min': lambda m: int(m.group(1)) * 60,
            
            # Hours
            r'(\d+)\s*hours?': lambda m: int(m.group(1)) * 3600,
            r'(\d+)\s*hrs?': lambda m: int(m.group(1)) * 3600,
            r'(\d+)\s*h': lambda m: int(m.group(1)) * 3600,
            
            # Days
            r'(\d+)\s*days?': lambda m: int(m.group(1)) * 86400,
            r'(\d+)\s*d': lambda m: int(m.group(1)) * 86400,
            
            # Common phrases
            r'one\s*minute': lambda m: 60,
            r'a\s*minute': lambda m: 60,
            r'one\s*hour': lambda m: 3600,
            r'an\s*hour': lambda m: 3600,
            r'one\s*day': lambda m: 86400,
            r'a\s*day': lambda m: 86400,
        }
        
        # Compile time patterns
        self._compiled_time_patterns = [
            (re.compile(pattern, re.IGNORECASE), converter)
            for pattern, converter in self._time_patterns.items()
        ]
    
    def parse_reminder_command(self, text: str) -> Optional[Dict]:
        """
        Parse a reminder command to extract text and delay.
        
        Args:
            text: User command text
            
        Returns:
            Dict with 'text' and 'delay_seconds' if successful, None otherwise
        """
        text = text.strip()
        
        # Try each reminder pattern
        for pattern in self._reminder_patterns:
            match = pattern.search(text)
            if match:
                reminder_text = match.group(1).strip()
                time_text = match.group(2).strip()
                
                # Clean up reminder text (remove trailing punctuation)
                reminder_text = re.sub(r'[.!?]+$', '', reminder_text)
                
                # Parse the time
                delay_seconds = self._parse_time(time_text)
                if delay_seconds is not None and delay_seconds > 0:
                    return {
                        'text': reminder_text,
                        'delay_seconds': delay_seconds,
                        'original_time_text': time_text
                    }
        
        return None
    
    def _parse_time(self, time_text: str) -> Optional[int]:
        """
        Parse time text into seconds.
        
        Args:
            time_text: Time description (e.g., "5 minutes", "1 hour")
            
        Returns:
            Seconds as integer, or None if parsing failed
        """
        time_text = time_text.strip().lower()
        
        # Try each time pattern
        for pattern, converter in self._compiled_time_patterns:
            match = pattern.search(time_text)
            if match:
                try:
                    return converter(match)
                except (ValueError, AttributeError):
                    continue
        
        # Handle compound times like "1 hour 30 minutes"
        total_seconds = 0
        remaining_text = time_text
        
        for pattern, converter in self._compiled_time_patterns:
            match = pattern.search(remaining_text)
            if match:
                try:
                    seconds = converter(match)
                    total_seconds += seconds
                    # Remove the matched part
                    remaining_text = remaining_text[:match.start()] + remaining_text[match.end():]
                    remaining_text = remaining_text.strip()
                except (ValueError, AttributeError):
                    continue
        
        if total_seconds > 0:
            return total_seconds
        
        return None
    
    def is_reminder_command(self, text: str) -> bool:
        """
        Check if text is a reminder command.
        
        Args:
            text: User command text
            
        Returns:
            True if it's a reminder command
        """
        text_lower = text.lower()
        reminder_keywords = [
            'remind me to', 'remind me', 'set reminder', 'reminder',
            'remind', 'schedule reminder'
        ]
        
        return any(keyword in text_lower for keyword in reminder_keywords)
    
    def get_reminder_examples(self) -> list:
        """Get examples of supported reminder commands."""
        return [
            "remind me to drink water in 5 minutes",
            "remind me to call mom in 1 hour",
            "remind me to take medicine in 30 minutes",
            "set reminder to check email in 2 hours",
            "reminder to walk the dog in 1 hour",
            "remind me to go to bed in 30 minutes",
            "remind me to eat lunch in 1 hour",
            "remind me to call doctor in 2 days"
        ]


# Global parser instance
_parser = None

def get_parser() -> ReminderParser:
    """Get the global reminder parser instance."""
    global _parser
    if _parser is None:
        _parser = ReminderParser()
    return _parser
