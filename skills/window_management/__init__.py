"""
Window Management Skill Package
"""

from .window_context import get_foreground_window_info, capture_active_window_screenshot
from .window_controller import WindowController, get_window_controller

__all__ = [
    "get_foreground_window_info",
    "capture_active_window_screenshot",
    "WindowController",
    "get_window_controller",
]
