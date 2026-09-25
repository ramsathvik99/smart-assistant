"""
Active Window & Foreground Application Context
Uses Windows Win32 APIs via ctypes to inspect the user's current focused application,
window title, and capture targeted screenshots of the active window for situational awareness.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

user32 = ctypes.windll.user32 if sys.platform == "win32" else None
kernel32 = ctypes.windll.kernel32 if sys.platform == "win32" else None


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


def get_foreground_window_info() -> Dict[str, Any]:
    """
    Returns metadata about the currently active foreground window:
    - title: Window title string
    - class_name: Executable or window class name
    - pid: Process ID
    - hwnd: Window handle
    - rect: (x, y, w, h)
    - bbox: (left, top, right, bottom)
    """
    if not user32:
        return {"title": "Desktop Environment", "class_name": "unknown", "pid": 0, "hwnd": 0, "rect": (0, 0, 0, 0)}

    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return {"title": "Desktop", "class_name": "Progman", "pid": 0, "hwnd": 0, "rect": (0, 0, 0, 0)}

        length = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if length > 0:
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value.strip()

        class_buff = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buff, 256)
        class_name = class_buff.value.strip()

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = max(0, rect.right - rect.left)
        h = max(0, rect.bottom - rect.top)

        return {
            "title": title or "Untitled Window",
            "class_name": class_name,
            "pid": pid.value,
            "hwnd": hwnd,
            "rect": (rect.left, rect.top, w, h),
            "bbox": (rect.left, rect.top, rect.right, rect.bottom),
        }
    except Exception as exc:
        return {"title": "Error inspecting window", "class_name": "error", "error": str(exc), "rect": (0, 0, 0, 0)}


def capture_active_window_screenshot(output_path: Optional[str] = None) -> Optional[str]:
    """
    Captures a screenshot of the current foreground window.
    Saves to output_path or returns path in data/screenshots/.
    """
    info = get_foreground_window_info()
    bbox = info.get("bbox")

    try:
        from PIL import ImageGrab
        import time
        if not output_path:
            project_root = Path(__file__).resolve().parent.parent.parent
            out_dir = project_root / "data" / "screenshots"
            out_dir.mkdir(parents=True, exist_ok=True)
            output_path = str(out_dir / f"active_window_{int(time.time())}.jpg")

        rect = info.get("rect", (0, 0, 0, 0))
        if not bbox or rect[2] < 10 or rect[3] < 10:
            img = ImageGrab.grab()
        else:
            img = ImageGrab.grab(bbox=bbox)

        img.save(output_path, format="JPEG", quality=85)
        return output_path
    except Exception as exc:
        logger.warning(f"Active window screenshot failed: {exc}")
        return None


def minimize_active_window() -> bool:
    """Minimizes the currently focused foreground window."""
    if not user32:
        return False
    hwnd = user32.GetForegroundWindow()
    if hwnd:
        user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
        return True
    return False


def restore_active_window(hwnd: Optional[int] = None) -> bool:
    """Restores the active or specified window."""
    if not user32:
        return False
    target = hwnd or user32.GetForegroundWindow()
    if target:
        user32.ShowWindow(target, 9)  # SW_RESTORE
        return True
    return False

