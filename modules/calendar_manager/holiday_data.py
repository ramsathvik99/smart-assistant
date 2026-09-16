"""
Holiday and Festival Data
Uses Special Days Service API for dynamic holiday fetching.
"""

from datetime import datetime
from typing import Dict, List, Optional

class HolidayData:
    """Manages holiday and festival information using API service."""
    
    @classmethod
    def get_holiday(cls, date_str: str) -> Optional[Dict]:
        """
        Get holiday information for a date using API service.
        date_str format: YYYY-MM-DD
        """
        try:
            from .special_days_service import get_special_days_service
            service = get_special_days_service()
            return service.get_special_day(date_str)
        except Exception as e:
            print(f"[Holiday Data] Error: {e}")
            return None
    
    @classmethod
    def get_holidays_in_range(cls, start_date: str, end_date: str) -> List[Dict]:
        """Get all holidays in a date range using API service."""
        try:
            from .special_days_service import get_special_days_service
            service = get_special_days_service()
            return service.get_special_days_in_range(start_date, end_date)
        except Exception as e:
            print(f"[Holiday Data] Error: {e}")
            return []
    
    @classmethod
    def is_holiday(cls, date_str: str) -> bool:
        """Check if a date is a holiday."""
        return cls.get_holiday(date_str) is not None
    
    @classmethod
    def get_today_holiday(cls) -> Optional[Dict]:
        """Get holiday for today."""
        try:
            from .special_days_service import get_special_days_service
            service = get_special_days_service()
            return service.get_today_special_day()
        except Exception as e:
            print(f"[Holiday Data] Error: {e}")
            return None
    
    @classmethod
    def get_tomorrow_holiday(cls) -> Optional[Dict]:
        """Get holiday for tomorrow."""
        try:
            from .special_days_service import get_special_days_service
            service = get_special_days_service()
            return service.get_tomorrow_special_day()
        except Exception as e:
            print(f"[Holiday Data] Error: {e}")
            return None
