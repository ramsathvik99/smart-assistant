"""
Calendar & Planning Intelligence Module (calendar_manager)
Provides comprehensive calendar management with events, holidays, and recurring events.
"""

from .calendar_controller import CalendarController, calendar_controller
from .calendar_storage import CalendarStorage
from .daily_briefing import get_daily_briefing

__all__ = ['CalendarController', 'calendar_controller', 'CalendarStorage', 'get_daily_briefing']
