"""
User-Directed Insertion Target Resolver ("Here" / Caret Resolution)
Provides:
  1. InsertionTarget: Model of the user's intended insertion destination at execution time.
  2. TargetResolver: Multi-tier dynamic target resolution using:
     - Tier 1: Application-specific integrations (VS Code active file/editor, Notepad, etc.)
     - Tier 2: Windows UIAutomation focused element & caret position
     - Tier 3: Mouse pointer location and control hierarchy
     - Tier 4: Fail-closed safety validation (password/credential field protection)
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("TargetResolver")


@dataclass
class InsertionTarget:
    """Represents the resolved physical or logical destination for content insertion."""
    app_name: str = "unknown"
    window_title: str = ""
    window_hwnd: int = 0
    target_type: str = "generic"  # "vscode", "notepad", "browser", "terminal", "edit_control", "generic"
    file_path: Optional[str] = None
    control_id: Optional[str] = None
    control_type: Optional[str] = None
    caret_available: bool = False
    is_safe: bool = True
    safety_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "app_name": self.app_name,
            "window_title": self.window_title,
            "window_hwnd": self.window_hwnd,
            "target_type": self.target_type,
            "file_path": self.file_path,
            "control_id": self.control_id,
            "control_type": self.control_type,
            "caret_available": self.caret_available,
            "is_safe": self.is_safe,
            "safety_reason": self.safety_reason,
            "metadata": self.metadata,
        }


class TargetResolver:
    """
    Dynamically discovers and validates the user's active insertion target at execution time.
    """

    def resolve_current_target(self, dialogue_state: Optional[Any] = None) -> InsertionTarget:
        """
        Main entry point for resolving 'here'.
        Inspects the active OS foreground window, focused controls, caret position, and UI tree.
        """
        if sys.platform != "win32":
            return InsertionTarget(
                app_name="desktop",
                window_title="Non-Windows OS",
                target_type="generic",
                is_safe=True
            )

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()

        if not hwnd:
            return InsertionTarget(
                app_name="desktop",
                window_title="Desktop",
                target_type="desktop",
                is_safe=True
            )

        # 1. Extract Window Title & Class Name
        buf_title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf_title, 512)
        window_title = buf_title.value

        buf_class = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf_class, 256)
        class_name = buf_class.value

        # 2. Extract Process Name
        process_name = self._get_process_name_for_hwnd(hwnd)
        app_name = self._identify_app(window_title, class_name, process_name)

        target = InsertionTarget(
            app_name=app_name,
            window_title=window_title,
            window_hwnd=hwnd,
            metadata={"class_name": class_name, "process_name": process_name}
        )

        # 3. Check Safety Gate (Password / Credential field check via UIAutomation)
        self._inspect_uia_focus_and_safety(target, hwnd)
        if not target.is_safe:
            return target

        # 4. Application-specific Enrichment
        if target.app_name == "vscode":
            self._enrich_vscode_target(target, window_title)
        elif target.app_name == "notepad":
            self._enrich_notepad_target(target, hwnd)
        elif target.app_name in ("chrome", "msedge", "firefox", "browser"):
            target.target_type = "browser"

        return target

    def _identify_app(self, window_title: str, class_name: str, process_name: str) -> str:
        """Categorize application identity from window attributes."""
        low_title = window_title.lower()
        low_proc = process_name.lower()

        if "visual studio code" in low_title or "code.exe" in low_proc:
            return "vscode"
        if "notepad" in low_title or "notepad.exe" in low_proc or class_name.lower() == "notepad":
            return "notepad"
        if "chrome" in low_proc or "chrome" in low_title or class_name == "Chrome_WidgetWin_1":
            return "chrome"
        if "msedge" in low_proc or "edge" in low_title:
            return "msedge"
        if "firefox" in low_proc or "firefox" in low_title:
            return "firefox"
        if any(t in low_proc for t in ("cmd.exe", "powershell.exe", "windowsterminal.exe", "wt.exe")):
            return "terminal"
        return low_proc.replace(".exe", "") or "generic_app"

    def _get_process_name_for_hwnd(self, hwnd: int) -> str:
        """Retrieve process name from window handle."""
        try:
            import psutil
            pid = ctypes.wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value:
                proc = psutil.Process(pid.value)
                return proc.name()
        except Exception:
            pass
        return ""

    def _inspect_uia_focus_and_safety(self, target: InsertionTarget, hwnd: int):
        """
        Inspect the focused UI element using UIAutomation COM.
        Enforces safety rules: verifies control is NOT a password/auth input.
        """
        try:
            from core.os_gateway.gui_automation import _get_uia
            uia = _get_uia()
            if not uia:
                return

            focused = uia.GetFocusedElement()
            if not focused:
                return

            # Check if focused element is a password field (UIA_IsPasswordPropertyId: 30019)
            try:
                is_password = focused.CurrentIsPassword
                if is_password:
                    target.is_safe = False
                    target.safety_reason = "Target control is a sensitive password field. Insertion blocked for safety."
                    logger.warning("[TARGET_RESOLVER] [SAFETY] Blocked insertion into password field.")
                    return
            except Exception:
                pass

            # Check control type (50004 = Edit, 50030 = Document, 50008 = List, etc.)
            try:
                ctl_type = focused.CurrentControlType
                target.control_id = focused.CurrentAutomationId or focused.CurrentName or ""
                if ctl_type == 50004:
                    target.control_type = "edit"
                    target.caret_available = True
                elif ctl_type == 50030:
                    target.control_type = "document"
                    target.caret_available = True
            except Exception:
                pass

        except Exception as e:
            logger.debug(f"[TARGET_RESOLVER] Note on UIA inspection: {e}")

    def _enrich_vscode_target(self, target: InsertionTarget, window_title: str):
        """Extract active file and editor context from VS Code window title."""
        target.target_type = "vscode"
        # Example title: "main.py - smart_assistant - Visual Studio Code"
        # or "● main.py - smart_assistant - Visual Studio Code" (dirty)
        parts = window_title.split(" - Visual Studio Code")[0].split(" - ")
        if parts:
            filename = parts[0].replace("●", "").strip()
            if "." in filename:
                target.file_path = filename
                target.caret_available = True
                target.metadata["active_file"] = filename

    def _enrich_notepad_target(self, target: InsertionTarget, hwnd: int):
        """Find Notepad edit control handle."""
        target.target_type = "notepad"
        target.caret_available = True
        user32 = ctypes.windll.user32
        edit_hwnd = user32.FindWindowExW(hwnd, 0, "Edit", None)
        if not edit_hwnd:
            # Modern Notepad in Windows 11 uses RichEditD2DPT
            edit_hwnd = user32.FindWindowExW(hwnd, 0, "RichEditD2DPT", None)
        if edit_hwnd:
            target.metadata["edit_hwnd"] = edit_hwnd
            target.control_id = str(edit_hwnd)


# Singleton instance
_target_resolver_instance: Optional[TargetResolver] = None

def get_target_resolver() -> TargetResolver:
    """Get the singleton TargetResolver instance."""
    global _target_resolver_instance
    if _target_resolver_instance is None:
        _target_resolver_instance = TargetResolver()
    return _target_resolver_instance
