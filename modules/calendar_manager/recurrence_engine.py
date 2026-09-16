"""
Recurrence Engine
Handles recurring event logic and generation.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

class RecurrenceRule:
    """Represents a recurrence rule for events."""
    
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    
    def __init__(self, frequency: str, interval: int = 1, day_of_week: Optional[int] = None, day_of_month: Optional[int] = None):
        """
        frequency: 'daily', 'weekly', 'monthly', 'yearly'
        interval: repeat every N periods
        day_of_week: 0-6 for Monday-Sunday (for weekly)
        day_of_month: 1-31 (for monthly)
        """
        self.frequency = frequency
        self.interval = interval
        self.day_of_week = day_of_week
        self.day_of_month = day_of_month
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for storage."""
        return {
            "frequency": self.frequency,
            "interval": self.interval,
            "day_of_week": self.day_of_week,
            "day_of_month": self.day_of_month
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'RecurrenceRule':
        """Create from dictionary."""
        return cls(
            frequency=data['frequency'],
            interval=data.get('interval', 1),
            day_of_week=data.get('day_of_week'),
            day_of_month=data.get('day_of_month')
        )

class RecurrenceEngine:
    """Generates recurring events dynamically."""
    
    @staticmethod
    def generate_occurrences(base_event: Dict, start_date: str, end_date: str) -> List[Dict]:
        """
        Generate all occurrences of a recurring event in a date range.
        """
        if 'recurrence' not in base_event or not base_event['recurrence']:
            return []
        
        recurrence = RecurrenceRule.from_dict(base_event['recurrence'])
        occurrences = []
        
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            base_date = datetime.strptime(base_event['date'], "%Y-%m-%d")
            
            current = max(start, base_date)
            
            while current <= end:
                if current >= base_date:
                    # Create occurrence
                    occurrence = base_event.copy()
                    occurrence['date'] = current.strftime("%Y-%m-%d")
                    occurrence['id'] = f"{occurrence['id']}_recur_{current.strftime('%Y%m%d')}"
                    occurrences.append(occurrence)
                
                # Calculate next occurrence
                if recurrence.frequency == RecurrenceRule.DAILY:
                    current += timedelta(days=recurrence.interval)
                elif recurrence.frequency == RecurrenceRule.WEEKLY:
                    current += timedelta(weeks=recurrence.interval)
                elif recurrence.frequency == RecurrenceRule.MONTHLY:
                    # Move to next month
                    month = current.month + recurrence.interval
                    year = current.year
                    while month > 12:
                        month -= 12
                        year += 1
                    try:
                        current = current.replace(year=year, month=month)
                    except ValueError:
                        # Handle day overflow (e.g., Jan 31 -> Feb 31)
                        current = current.replace(year=year, month=month, day=1)
                elif recurrence.frequency == RecurrenceRule.YEARLY:
                    current = current.replace(year=current.year + recurrence.interval)
                else:
                    break
        
        except Exception as e:
            print(f"[Recurrence Engine] Error: {e}")
        
        return occurrences
    
    @staticmethod
    def parse_recurrence_from_text(text: str) -> Optional[RecurrenceRule]:
        """Parse recurrence rule from natural language."""
        text_lower = text.lower()
        
        if "every day" in text_lower or "daily" in text_lower:
            return RecurrenceRule(RecurrenceRule.DAILY)
        
        if "every week" in text_lower or "weekly" in text_lower:
            return RecurrenceRule(RecurrenceRule.WEEKLY)
        
        if "every monday" in text_lower:
            return RecurrenceRule(RecurrenceRule.WEEKLY, day_of_week=0)
        if "every tuesday" in text_lower:
            return RecurrenceRule(RecurrenceRule.WEEKLY, day_of_week=1)
        if "every wednesday" in text_lower:
            return RecurrenceRule(RecurrenceRule.WEEKLY, day_of_week=2)
        if "every thursday" in text_lower:
            return RecurrenceRule(RecurrenceRule.WEEKLY, day_of_week=3)
        if "every friday" in text_lower:
            return RecurrenceRule(RecurrenceRule.WEEKLY, day_of_week=4)
        if "every saturday" in text_lower:
            return RecurrenceRule(RecurrenceRule.WEEKLY, day_of_week=5)
        if "every sunday" in text_lower:
            return RecurrenceRule(RecurrenceRule.WEEKLY, day_of_week=6)
        
        if "every month" in text_lower or "monthly" in text_lower:
            return RecurrenceRule(RecurrenceRule.MONTHLY)
        
        if "every year" in text_lower or "yearly" in text_lower or "annually" in text_lower:
            return RecurrenceRule(RecurrenceRule.YEARLY)
        
        return None
