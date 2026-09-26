"""
Clock Manager Skill Package
Provides Alarm Clock, Countdown Timers, Stopwatch, World Clock, and Local Clock functions.
"""

from .clock_controller import ClockController, get_clock_controller

__all__ = [
    "ClockController",
    "get_clock_controller",
]
