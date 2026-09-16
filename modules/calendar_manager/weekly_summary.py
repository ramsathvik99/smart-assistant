"""
Weekly Summary Generator
Provides weekly planning summaries.
"""

from datetime import datetime, timedelta
from typing import Dict, List
from .holiday_data import HolidayData

class WeeklySummary:
    """Generates weekly planning summaries."""
    
    @staticmethod
    def generate_summary(events_by_date: Dict[str, List[Dict]], start_date: str, end_date: str) -> str:
        """
        Generate a natural language summary of the week.
        """
        total_events = sum(len(events) for events in events_by_date.values())
        
        if total_events == 0:
            return "You have no events planned for this week."
        
        # Get holidays in range
        holidays = HolidayData.get_holidays_in_range(start_date, end_date)
        
        summary_parts = []
        
        # Event count
        summary_parts.append(f"This week you have {total_events} event{'s' if total_events != 1 else ''}")
        
        # Mention holidays
        if holidays:
            holiday_names = [h['name'] for h in holidays]
            if len(holiday_names) == 1:
                summary_parts.append(f"and {holiday_names[0]} is on {holidays[0]['date']}")
            else:
                summary_parts.append(f"and includes {', '.join(holiday_names)}")
        
        summary = ". ".join(summary_parts) + "."
        
        return summary
    
    @staticmethod
    def get_week_range(reference_date: str = None) -> tuple:
        """Get start and end date of the current week."""
        if reference_date:
            ref = datetime.strptime(reference_date, "%Y-%m-%d")
        else:
            ref = datetime.now()
        
        # Get Monday of current week
        start = ref - timedelta(days=ref.weekday())
        end = start + timedelta(days=6)
        
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
