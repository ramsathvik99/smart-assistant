"""
Calendar & Planning Intelligence Module (calendar_manager)
Provides comprehensive calendar management with events, holidays, and recurring events.
"""

from .calendar_controller import CalendarController
from .calendar_storage import CalendarStorage

__all__ = ['CalendarController', 'CalendarStorage']
