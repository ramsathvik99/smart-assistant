# ════════════════════════════════════════════════════════════════════════
# RETIRED — This module contains legacy Tkinter launcher components.
# Active Production UI: modules/ui/floating_launcher.py (PyQt6)
# Preserved for historical reference only.
# ════════════════════════════════════════════════════════════════════════
"""
NOVA Launcher Module (Retired Tkinter Implementation)
Provides floating launcher panel and context menu components.
"""

from modules.launcher.launcher_panel_stable import LauncherPanel
from modules.launcher.system_menu import AssistantSystemMenu

__all__ = [
    'LauncherPanel',
    'AssistantSystemMenu',
]

