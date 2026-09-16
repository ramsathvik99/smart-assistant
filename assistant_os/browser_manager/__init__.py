"""
assistant_os/browser_manager/__init__.py
=====================================
NOVA OS - Browser Automation Manager Package

Architecture:
    This package handles direct browser automation operations.
    It wraps the existing `BrowserEngine` (extensions/browser_engine.py)
    and uses native libraries (`pyautogui` and `beautifulsoup4`) to
    support lightweight automation (Click, Fill, Extract, Screenshot, Navigate).

    This package does NOT:
        ✗ Integrate with the Planner yet.
        ✗ Require new external browser drivers (headless chrome/playwright) to run basic tests.

Public API:
    from assistant_os.browser_manager import BrowserAutomationManager
"""

from assistant_os.browser_manager.browser_manager import BrowserAutomationManager

__all__ = ["BrowserAutomationManager"]
