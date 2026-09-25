"""
Window Management Controller
Provides conversational commands for inspecting active window context and capturing active window screenshots.
"""

from __future__ import annotations

from typing import Any, Optional
from .window_context import (
    get_foreground_window_info,
    capture_active_window_screenshot,
    minimize_active_window,
    restore_active_window,
)


class WindowController:
    def get_active_window(self) -> dict[str, Any]:
        info = get_foreground_window_info()
        title = info.get("title", "Unknown")
        cls_name = info.get("class_name", "Unknown")
        pid = info.get("pid", 0)

        msg = f"The active window is '{title}' (Process: {cls_name}, PID: {pid})."
        return {
            "success": True,
            "status": "success",
            "info": info,
            "message": msg
        }

    def capture_screenshot(self) -> dict[str, Any]:
        path = capture_active_window_screenshot()
        if path:
            return {
                "success": True,
                "status": "success",
                "file_path": path,
                "message": f"Captured screenshot of active window and saved to {path}."
            }
        return {
            "success": False,
            "status": "error",
            "message": "Failed to capture active window screenshot."
        }

    def handle_command(self, user_input: str) -> dict[str, Any]:
        text_low = user_input.lower().strip()

        if "minimize" in text_low and any(w in text_low for w in ["current window", "active window", "this window"]):
            success = minimize_active_window()
            return {
                "success": success,
                "status": "minimized" if success else "error",
                "message": "Minimized the active window." if success else "Could not minimize active window."
            }

        if "restore" in text_low and any(w in text_low for w in ["current window", "active window", "this window", "window"]):
            success = restore_active_window()
            return {
                "success": success,
                "status": "restored" if success else "error",
                "message": "Restored the window." if success else "Could not restore window."
            }

        is_screenshot = (
            any(w in text_low for w in ["screenshot", "capture", "snap"]) and
            any(w in text_low for w in ["active window", "foreground window", "current window", "window screenshot", "window capture"])
        ) or any(w in text_low for w in ["capture active window", "screenshot active window", "snap active window", "take a screenshot of the active window", "take screenshot of active window"])

        if is_screenshot:
            return self.capture_screenshot()

        return self.get_active_window()


_controller_instance: Optional[WindowController] = None


def get_window_controller() -> WindowController:
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = WindowController()
    return _controller_instance
