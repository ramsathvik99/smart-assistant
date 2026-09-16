"""
NOVA Launcher Module
Provides floating launcher panel and context menu components.
"""

from modules.launcher.launcher_panel import LauncherPanel
from modules.launcher.context_menu import FloatingButtonContextMenu
from modules.launcher.animation import SlideInAnimation, calculate_panel_position

__all__ = [
    'LauncherPanel',
    'FloatingButtonContextMenu',
    'SlideInAnimation',
    'calculate_panel_position',
]
