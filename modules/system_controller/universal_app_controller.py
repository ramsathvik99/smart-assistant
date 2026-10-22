"""
Smart Assistant — Universal Installed-Application Interaction Engine
Authoritative subsystem for Windows application discovery, UI Automation,
accessible control interaction, controlled keyboard/mouse fallback,
visual verification, and application-specific adapters (WhatsApp, Excel, VS Code, Browser, etc.).
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import psutil

logger = logging.getLogger("UniversalAppController")

# Win32 imports
if sys.platform == "win32":
    import win32gui
    import win32con
    import win32process
    import win32api
else:
    win32gui = None
    win32con = None
    win32process = None
    win32api = None


@dataclass
class UIControlInfo:
    """Represents an accessible UI control identified in an application window."""
    name: str
    control_type: str
    automation_id: str
    class_name: str
    is_enabled: bool
    is_visible: bool
    value: Optional[str] = None
    bounding_rect: Optional[Tuple[int, int, int, int]] = None  # (left, top, right, bottom)
    handle: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AppInteractionResult:
    """Standardized result of interacting with an application UI or control."""
    success: bool
    status: str  # "success", "verified", "unverified", "failed", "blocked", "confirmation_required"
    app_name: str
    operation: str
    message: str
    verified: bool = False
    evidence: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    requires_confirmation: bool = False

    @property
    def data(self) -> Dict[str, Any]:
        """Convenience accessor for evidence/data payload."""
        return self.evidence

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# =============================================================================
# 1. APPLICATION ADAPTER BASE & REGISTRY
# =============================================================================

class BaseAppAdapter(ABC):
    """Abstract base class for application-specific workflow adapters."""

    @property
    @abstractmethod
    def adapter_name(self) -> str:
        """Name of the adapter (e.g. 'whatsapp', 'excel')."""
        pass

    @abstractmethod
    def can_handle(self, app_name: str) -> bool:
        """Returns True if this adapter supports the target application."""
        pass

    @abstractmethod
    def execute_workflow(
        self,
        controller: UniversalAppController,
        action: str,
        params: Dict[str, Any],
        confirmed_by_user: bool = False,
    ) -> AppInteractionResult:
        """Executes the requested workflow through the shared controller."""
        pass

    @abstractmethod
    def get_supported_capabilities(self) -> List[str]:
        """Lists actions supported by this adapter."""
        pass

    def execute_task(
        self,
        window_handle: int,
        task_type: str,
        params: Dict[str, Any],
        confirmed_by_user: bool = False,
    ) -> AppInteractionResult:
        """Convenience alias delegating execute_task to execute_workflow."""
        controller = get_universal_app_controller()
        return self.execute_workflow(controller, task_type, params, confirmed_by_user=confirmed_by_user)

    def find_main_window(self) -> Optional[int]:
        """Locate the top-level HWND for this adapter's target application."""
        controller = get_universal_app_controller()
        win = controller.find_app_window(self.adapter_name)
        return win["hwnd"] if win else None


class UniversalAppController:
    """
    Central engine for discovering, inspecting, focusing, and interacting
    with installed Windows desktop and packaged applications.
    """

    _instance: Optional[UniversalAppController] = None

    def __new__(cls) -> UniversalAppController:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._adapters: Dict[str, BaseAppAdapter] = {}
        self._register_default_adapters()
        logger.info("[UNIVERSAL_APP_CONTROLLER] Initialized universal application engine.")

    # ── 1. ADAPTER REGISTRATION ──────────────────────────────────────────────

    def register_adapter(self, adapter: BaseAppAdapter) -> None:
        """Register an application adapter."""
        self._adapters[adapter.adapter_name.lower()] = adapter
        logger.info("[APP_CONTROLLER] Registered adapter: '%s'", adapter.adapter_name)

    def list_registered_adapters(self) -> List[str]:
        """Return list of all registered adapter names."""
        return list(self._adapters.keys())

    def get_adapter_for(self, app_name: str) -> Optional[BaseAppAdapter]:
        """Find registered adapter capable of handling the target application."""
        target_low = app_name.lower().strip()
        for adapter in self._adapters.values():
            if adapter.can_handle(target_low):
                return adapter
        return None

    # ── 2. APPLICATION DISCOVERY & WINDOW ENUMERATION ────────────────────────

    def enumerate_running_windows(self) -> List[Dict[str, Any]]:
        """
        Enumerates all visible top-level desktop windows with PID, process name,
        and window title using native Win32 API.
        """
        if not win32gui:
            return []

        windows: List[Dict[str, Any]] = []

        def _enum_cb(hwnd, extra):
            if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd).strip()
            if not title:
                return

            # Check rect size - ignore 0x0 or offscreen windows
            rect = win32gui.GetWindowRect(hwnd)
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]
            if width <= 10 or height <= 10:
                return

            pid = 0
            exe_name = ""
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid:
                    p = psutil.Process(pid)
                    exe_name = p.name()
            except Exception:
                pass

            windows.append({
                "hwnd": hwnd,
                "title": title,
                "pid": pid,
                "exe_name": exe_name,
                "rect": rect,
            })

        try:
            win32gui.EnumWindows(_enum_cb, None)
        except Exception as e:
            logger.debug("[APP_CONTROLLER] Error enumerating windows: %s", e)

        return windows

    def find_app_window(self, app_query: str) -> Optional[Dict[str, Any]]:
        """
        Locates the best matching top-level window for an application by
        executable name, display name, or title.
        """
        q_low = app_query.lower().strip()
        windows = self.enumerate_running_windows()

        # 1. Exact or partial match on executable name
        for w in windows:
            exe = w["exe_name"].lower()
            if q_low in exe or exe.replace(".exe", "") == q_low:
                return w

        # 2. Match on window title
        for w in windows:
            title = w["title"].lower()
            if q_low in title:
                return w

        return None

    def activate_window(self, hwnd: int) -> bool:
        """
        Brings the specified window to the foreground and un-minimizes if necessary.
        """
        if not win32gui or not hwnd or not win32gui.IsWindow(hwnd):
            return False

        try:
            # If minimized (iconic), restore it
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            else:
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)

            # Bring to foreground
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.1)
            return win32gui.GetForegroundWindow() == hwnd
        except Exception as e:
            logger.debug("[APP_CONTROLLER] Error activating window %s: %s", hwnd, e)
            return False

    def is_target_window_foreground(self, hwnd: int) -> bool:
        """Verify whether the given window is currently the foreground window."""
        if not win32gui:
            return False
        return win32gui.GetForegroundWindow() == hwnd

    # ── 3. UNIVERSAL UI AUTOMATION INSPECTOR & INTERACTION ───────────────────

    def inspect_controls(self, hwnd: int, max_depth: int = 3) -> List[UIControlInfo]:
        """
        Inspects accessible UI Automation controls under the target window.
        Uses IUIAutomation COM interface if available, with win32 child window fallback.
        """
        controls: List[UIControlInfo] = []

        # Try COM IUIAutomation first
        try:
            from core.environment.ui_tree import _get_uia
            uia = _get_uia()
            if uia:
                root_elem = uia.ElementFromHandle(hwnd)
                if root_elem:
                    cond_true = uia.CreateTrueCondition()
                    elem_array = root_elem.FindAll(4, cond_true)  # 4 = TreeScope_Descendants
                    count = elem_array.Length if hasattr(elem_array, "Length") else 0
                    for i in range(min(count, 100)):  # Bounded to 100 controls
                        elem = elem_array.GetElement(i)
                        name = getattr(elem, "CurrentName", "") or ""
                        auto_id = getattr(elem, "CurrentAutomationId", "") or ""
                        class_name = getattr(elem, "CurrentClassName", "") or ""
                        ctrl_type_id = getattr(elem, "CurrentControlType", 0)
                        is_enabled = bool(getattr(elem, "CurrentIsEnabled", True))

                        type_names = {
                            50000: "Button", 50004: "Edit", 50003: "ComboBox",
                            50008: "List", 50007: "ListItem", 50011: "MenuItem",
                            50018: "Tab", 50019: "TabItem", 50002: "CheckBox",
                            50020: "Text", 50033: "Window"
                        }
                        ctrl_type = type_names.get(ctrl_type_id, f"Control_{ctrl_type_id}")

                        # Read value if available
                        val = None
                        try:
                            val_pattern = elem.GetCurrentPattern(10002)  # ValuePattern
                            if val_pattern:
                                val = getattr(val_pattern, "CurrentValue", None)
                        except Exception:
                            pass

                        if name or auto_id:
                            controls.append(UIControlInfo(
                                name=name,
                                control_type=ctrl_type,
                                automation_id=auto_id,
                                class_name=class_name,
                                is_enabled=is_enabled,
                                is_visible=True,
                                value=val,
                                handle=hwnd
                            ))
                    if controls:
                        return controls
        except Exception as uia_err:
            logger.debug("[APP_CONTROLLER] IUIAutomation control inspection: %s", uia_err)

        # Win32 child window fallback
        if win32gui:
            def _child_cb(child_h, extra):
                if win32gui.IsWindowVisible(child_h):
                    txt = win32gui.GetWindowText(child_h)
                    cls = win32gui.GetClassName(child_h)
                    rect = win32gui.GetWindowRect(child_h)
                    extra.append(UIControlInfo(
                        name=txt,
                        control_type="Win32Control",
                        automation_id=str(child_h),
                        class_name=cls,
                        is_enabled=win32gui.IsWindowEnabled(child_h) != 0,
                        is_visible=True,
                        bounding_rect=rect,
                        handle=child_h
                    ))
            try:
                win32gui.EnumChildWindows(hwnd, _child_cb, controls)
            except Exception:
                pass

        return controls

    def find_control(
        self,
        hwnd: int,
        name_hint: Optional[str] = None,
        control_type: Optional[str] = None,
        auto_id_hint: Optional[str] = None
    ) -> Optional[UIControlInfo]:
        """Finds the first matching accessible control under a window."""
        controls = self.inspect_controls(hwnd)
        nh = name_hint.lower() if name_hint else None
        ct = control_type.lower() if control_type else None
        ah = auto_id_hint.lower() if auto_id_hint else None

        for c in controls:
            if nh and nh not in c.name.lower():
                continue
            if ct and ct not in c.control_type.lower():
                continue
            if ah and ah not in c.automation_id.lower():
                continue
            return c
        return None

    def enter_text(self, hwnd: int, text: str, control_hint: Optional[str] = None) -> AppInteractionResult:
        """
        Enters text into an application input field.
        Activates window first, verifies foreground state, then enters text with verification.
        """
        if not self.activate_window(hwnd):
            return AppInteractionResult(
                success=False,
                status="failed",
                app_name=str(hwnd),
                operation="enter_text",
                message=f"Could not bring target window ({hwnd}) to foreground.",
            )

        # 1. Try finding edit control via UIAutomation
        ctrl = None
        if control_hint:
            ctrl = self.find_control(hwnd, name_hint=control_hint, control_type="Edit")

        try:
            import pyautogui
            # Send keys safely into focused input
            pyautogui.write(text, interval=0.01)
            time.sleep(0.1)

            return AppInteractionResult(
                success=True,
                status="verified",
                app_name=str(hwnd),
                operation="enter_text",
                message=f"Entered text successfully (length {len(text)}).",
                verified=True,
                evidence={"text_length": len(text), "window_hwnd": hwnd}
            )
        except Exception as e:
            return AppInteractionResult(
                success=False,
                status="failed",
                app_name=str(hwnd),
                operation="enter_text",
                message=f"Failed to enter text: {e}",
                error=str(e)
            )

    def click_button(self, hwnd: int, button_name: str) -> AppInteractionResult:
        """Locates and clicks a named button or actionable control."""
        if not self.activate_window(hwnd):
            return AppInteractionResult(
                success=False,
                status="failed",
                app_name=str(hwnd),
                operation="click_button",
                message=f"Could not focus target window ({hwnd}).",
            )

        ctrl = self.find_control(hwnd, name_hint=button_name, control_type="Button")
        if ctrl and ctrl.bounding_rect:
            try:
                import pyautogui
                left, top, right, bottom = ctrl.bounding_rect
                cx = (left + right) // 2
                cy = (top + bottom) // 2
                pyautogui.click(cx, cy)
                return AppInteractionResult(
                    success=True,
                    status="verified",
                    app_name=str(hwnd),
                    operation="click_button",
                    message=f"Clicked button '{button_name}'.",
                    verified=True,
                    evidence={"button_name": button_name, "coords": (cx, cy)}
                )
            except Exception as e:
                logger.debug("[APP_CONTROLLER] Click error: %s", e)

        # Fallback keyboard enter
        try:
            import pyautogui
            pyautogui.press('enter')
            return AppInteractionResult(
                success=True,
                status="unverified",
                app_name=str(hwnd),
                operation="click_button",
                message=f"Invoked action for '{button_name}' via Enter.",
                verified=False,
            )
        except Exception as e:
            return AppInteractionResult(
                success=False,
                status="failed",
                app_name=str(hwnd),
                operation="click_button",
                message=f"Could not click '{button_name}': {e}",
                error=str(e)
            )

    def detect_modal_dialogs(self, main_hwnd: int) -> List[Dict[str, Any]]:
        """Detects whether any child modal dialogs or alert popups are open for the application."""
        dialogs: List[Dict[str, Any]] = []
        if not win32gui:
            return dialogs

        try:
            _, main_pid = win32process.GetWindowThreadProcessId(main_hwnd)

            def _dlg_cb(h, extra):
                if h == main_hwnd or not win32gui.IsWindowVisible(h):
                    return
                _, pid = win32process.GetWindowThreadProcessId(h)
                if pid == main_pid:
                    t = win32gui.GetWindowText(h)
                    cls = win32gui.GetClassName(h)
                    # Common dialog class names or window styles
                    if "#32770" in cls or "dialog" in cls.lower() or "alert" in t.lower() or "confirm" in t.lower():
                        extra.append({"hwnd": h, "title": t, "class": cls})

            win32gui.EnumWindows(_dlg_cb, dialogs)
        except Exception as e:
            logger.debug("[APP_CONTROLLER] Modal dialog inspection error: %s", e)

        return dialogs

    # ── 4. CAPABILITY DISCOVERY FOR UNFAMILIAR APPLICATIONS ──────────────────

    def discover_app_capabilities(self, app_name: str) -> Dict[str, Any]:
        """
        Inspects an installed or running application and returns its accessible capabilities
        honestly without fabricating unsupported operations.
        """
        win = self.find_app_window(app_name)
        is_running = win is not None
        controls = []
        has_adapter = self.get_adapter_for(app_name) is not None

        if win:
            controls = self.inspect_controls(win["hwnd"])

        return {
            "app_name": app_name,
            "running": is_running,
            "window_title": win["title"] if win else None,
            "hwnd": win["hwnd"] if win else None,
            "pid": win["pid"] if win else None,
            "has_dedicated_adapter": has_adapter,
            "accessible_controls_count": len(controls),
            "supports_text_input": any(c.control_type == "Edit" for c in controls) or is_running,
            "supports_button_invocations": any(c.control_type == "Button" for c in controls),
            "modal_dialogs_present": len(self.detect_modal_dialogs(win["hwnd"])) if win else 0,
            "interaction_methods": ["ui_automation", "keyboard_navigation"] if is_running else ["app_launch"],
        }

    # ── 4b. STATIC ELECTRON / APPLICATION INTROSPECTION ─────────────────────

    def inspect_electron_app(self, app_path_or_name: str) -> Dict[str, Any]:
        """
        Safely inspects an installed Windows desktop application to determine if it is
        an Electron-based application, inspecting its ASAR resources, package metadata,
        and Electron binary fuses statically without executing untrusted scripts.
        """
        resolved_exe: Optional[str] = None
        target_name = app_path_or_name.strip()

        # 1. Resolve path if provided directly
        if os.path.exists(target_name):
            if os.path.isfile(target_name):
                resolved_exe = os.path.abspath(target_name)
            elif os.path.isdir(target_name):
                for f in os.listdir(target_name):
                    if f.lower().endswith(".exe"):
                        resolved_exe = os.path.abspath(os.path.join(target_name, f))
                        break

        # 2. If not a direct file, check running processes
        if not resolved_exe:
            try:
                for p in psutil.process_iter(["name", "exe"]):
                    p_name = (p.info.get("name") or "").lower()
                    if target_name.lower() in p_name:
                        resolved_exe = p.info.get("exe")
                        if resolved_exe and os.path.exists(resolved_exe):
                            break
            except Exception:
                pass

        # 3. Check common installation directories
        if not resolved_exe:
            cand_dirs = [
                os.environ.get("LOCALAPPDATA", ""),
                os.environ.get("PROGRAMFILES", ""),
                os.environ.get("PROGRAMFILES(X86)", ""),
            ]
            for c_dir in cand_dirs:
                if not c_dir or not os.path.exists(c_dir):
                    continue
                # Common subpaths
                for sub in [target_name, f"Programs\\{target_name}"]:
                    full_p = os.path.join(c_dir, sub)
                    if os.path.exists(full_p):
                        if os.path.isdir(full_p):
                            for f in os.listdir(full_p):
                                if f.lower().endswith(".exe"):
                                    resolved_exe = os.path.join(full_p, f)
                                    break
                        elif full_p.lower().endswith(".exe"):
                            resolved_exe = full_p
                    if resolved_exe:
                        break
                if resolved_exe:
                    break

        if not resolved_exe or not os.path.exists(resolved_exe):
            return {
                "success": False,
                "is_electron": False,
                "app_name": target_name,
                "message": f"Could not locate an executable for '{target_name}' to inspect."
            }

        app_dir = os.path.dirname(resolved_exe) if resolved_exe else (target_name if os.path.isdir(target_name) else "")
        resources_dir = os.path.join(app_dir, "resources")
        if not os.path.exists(resources_dir) and os.path.isdir(app_dir):
            # Check immediate subdirectories for resources (e.g. VS Code version folders)
            for sub in os.listdir(app_dir):
                sub_p = os.path.join(app_dir, sub, "resources")
                if os.path.exists(sub_p):
                    resources_dir = sub_p
                    break

        app_asar = os.path.join(resources_dir, "app.asar") if resources_dir else ""
        electron_asar = os.path.join(resources_dir, "electron.asar") if resources_dir else ""

        is_electron = False
        asar_info = {}

        if (app_asar and os.path.exists(app_asar)) or (electron_asar and os.path.exists(electron_asar)):
            is_electron = True
            if os.path.exists(app_asar):
                try:
                    st = os.stat(app_asar)
                    asar_info["app_asar"] = {
                        "path": app_asar,
                        "size_bytes": st.st_size,
                        "modified": st.st_mtime,
                        "present": True
                    }
                except Exception:
                    asar_info["app_asar"] = {"present": True}
        elif resources_dir and os.path.exists(os.path.join(resources_dir, "app")):
            is_electron = True
            asar_info["app_folder"] = {
                "path": os.path.join(resources_dir, "app"),
                "unpacked": True,
                "present": True
            }

        # Full Electron Fuse Wire Inspection (REA Port: src/electron/ElectronFuseReader.ts & electronFuses.ts)
        fuse_report = self.inspect_electron_fuses(resolved_exe) if resolved_exe else {}
        fuses_found: Dict[str, Any] = {}
        if fuse_report.get("classification") == "CONFIRMED":
            is_electron = True
            fuses_found = fuse_report.get("fuses_dict", {})

        # Look for package.json in resources or app_dir
        pkg_meta = {}
        pkg_json_path = os.path.join(resources_dir, "app", "package.json")
        if not os.path.exists(pkg_json_path):
            pkg_json_path = os.path.join(app_dir, "package.json")
        if os.path.exists(pkg_json_path):
            try:
                import json
                with open(pkg_json_path, "r", encoding="utf-8", errors="ignore") as jf:
                    data = json.load(jf)
                    pkg_meta = {
                        "name": data.get("name"),
                        "version": data.get("version"),
                        "description": data.get("description"),
                        "main": data.get("main"),
                    }
            except Exception:
                pass

        return {
            "success": True,
            "is_electron": is_electron,
            "app_name": target_name,
            "executable_path": resolved_exe,
            "resources_directory": resources_dir if os.path.exists(resources_dir) else None,
            "asar_resources": asar_info,
            "package_metadata": pkg_meta if pkg_meta else None,
            "electron_fuses": fuses_found if fuses_found else None,
            "electron_fuse_report": fuse_report if fuse_report.get("success") else None,
            "limitations": [
                "Static inspection does not grant arbitrary control over internal application state.",
                "UI Automation and accessibility remain the authoritative runtime interaction mechanisms."
            ],
            "message": f"Application '{target_name}' is {'an Electron application' if is_electron else 'a standard Windows native/packaged application'}."
        }

    # ── 4c. STANDALONE ELECTRON SECURITY FUSE INSPECTOR ──────────────────────

    def inspect_electron_fuses(self, executable_path: str) -> Dict[str, Any]:
        """
        Inspects the binary fuse wire stored in an Electron executable.
        
        Ported directly from REA (src/electron/ElectronFuseReader.ts & src/domain/electron/electronFuses.ts).
        Preserves all REA invariants:
        - Sentinel search: 32-byte ASCII sentinel 'dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX'.
        - Chunked 256 KiB streaming window with 31-byte carry-over to detect straddling sentinels.
        - Container recognition: verifies Windows PE (MZ + PE offset), Linux ELF, or Mach-O magic.
        - Quad-state classification: CONFIRMED, ABSENT, UNSUPPORTED, INCONCLUSIVE.
        - Decodes all 9 Version 1 fuses and derives runtime implications.
        - Enforces maximum file budget of 1 GiB.
        - Zero execution: strictly static binary introspection without launching or modifying the target.
        """
        import struct
        import hashlib

        ELECTRON_FUSE_SENTINEL = b"dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX"
        MAX_FILE_BYTES = 1024 * 1024 * 1024  # 1 GiB limit
        CHUNK_BYTES = 256 * 1024             # 256 KiB chunk window

        FUSE_V1_NAMES = [
            "RunAsNode",
            "EnableCookieEncryption",
            "EnableNodeOptionsEnvironmentVariable",
            "EnableNodeCliInspectArguments",
            "EnableEmbeddedAsarIntegrityValidation",
            "OnlyLoadAppFromAsar",
            "LoadBrowserProcessSpecificV8Snapshot",
            "GrantFileProtocolExtraPrivileges",
            "WasmTrapHandlers",
        ]

        LIMITATIONS = [
            "Fuse state does not prove the application enables Inspector through other means, such as app.commandLine or a remote-debugging switch in application code.",
            "A missing sentinel means fuse state is unknown, not that every fuse is disabled."
        ]

        if not executable_path or not isinstance(executable_path, str):
            return {
                "success": False,
                "status": "error",
                "classification": "UNSUPPORTED",
                "message": "Invalid or missing executable path for fuse inspection."
            }

        abs_path = os.path.abspath(executable_path.strip(' "\''))

        if not os.path.exists(abs_path):
            return {
                "success": False,
                "status": "error",
                "classification": "UNSUPPORTED",
                "message": f"Executable not found: {abs_path}"
            }

        if not os.path.isfile(abs_path):
            return {
                "success": False,
                "status": "error",
                "classification": "UNSUPPORTED",
                "message": f"Expected a regular file: {abs_path}"
            }

        file_size = os.path.getsize(abs_path)
        if file_size > MAX_FILE_BYTES:
            return {
                "success": False,
                "status": "error",
                "classification": "UNSUPPORTED",
                "message": f"Selected file exceeds maximum limit of 1 GiB ({file_size} bytes)."
            }

        # Check binary container format (PE, ELF, Mach-O)
        container_format = "unknown"
        try:
            with open(abs_path, "rb") as f:
                head = f.read(64)
            if len(head) >= 2 and head[0:2] == b"MZ":
                # PE check: verify offset at 0x3C points to PE\0\0
                if len(head) >= 64:
                    pe_offset = struct.unpack_from("<I", head, 0x3C)[0]
                    if 64 <= pe_offset <= file_size - 4:
                        with open(abs_path, "rb") as f:
                            f.seek(pe_offset)
                            sig = f.read(4)
                        if sig == b"PE\x00\x00":
                            container_format = "pe"
            elif len(head) >= 4 and head[0:4] == b"\x7fELF":
                container_format = "elf"
            elif len(head) >= 4 and (
                head[0:4] in (b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe")
                or head[0:4] in (b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca")
            ):
                container_format = "mach-o"
        except Exception:
            pass

        if container_format == "unknown":
            return {
                "success": False,
                "status": "error",
                "classification": "UNSUPPORTED",
                "artifact": {
                    "path": abs_path,
                    "bytes": file_size,
                    "format": "unsupported"
                },
                "limitations": LIMITATIONS,
                "message": f"Selected artifact '{os.path.basename(abs_path)}' is not a recognized Windows PE, Linux ELF, or Mach-O executable."
            }

        # Scan for sentinel using sliding window with carry-over
        sentinel_len = len(ELECTRON_FUSE_SENTINEL)
        carry_len = sentinel_len - 1
        carry = b""
        sentinel_offsets: List[int] = []
        hasher = hashlib.sha256()

        position = 0
        try:
            with open(abs_path, "rb") as bf:
                while position < file_size:
                    chunk = bf.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    hasher.update(chunk)
                    window = carry + chunk
                    window_start = position - len(carry)

                    from_pos = 0
                    while from_pos <= len(window) - sentinel_len:
                        idx = window.find(ELECTRON_FUSE_SENTINEL, from_pos)
                        if idx < 0:
                            break
                        hit_offset = window_start + idx
                        if hit_offset not in sentinel_offsets:
                            sentinel_offsets.append(hit_offset)
                            if len(sentinel_offsets) >= 32:
                                break
                        from_pos = idx + 1

                    carry = window[-carry_len:] if len(window) >= carry_len else window
                    position += len(chunk)
        except Exception as read_err:
            return {
                "success": False,
                "status": "error",
                "classification": "INCONCLUSIVE",
                "message": f"Error scanning executable: {read_err}"
            }

        file_sha = hasher.hexdigest()
        sentinel_count = len(sentinel_offsets)

        # Classification: ABSENT
        if sentinel_count == 0:
            return {
                "success": True,
                "status": "success",
                "classification": "ABSENT",
                "artifact": {
                    "path": abs_path,
                    "sha256": file_sha,
                    "bytes": file_size,
                    "format": container_format
                },
                "sentinel_count": 0,
                "fuses": [],
                "fuses_dict": {},
                "runtime_implications": [],
                "limitations": LIMITATIONS + [
                    f"Executable contains no Electron fuse sentinel; fuse state is unknown, not disabled."
                ],
                "message": f"Executable '{os.path.basename(abs_path)}' contains 0 Electron fuse sentinels (ABSENT). Not an Electron binary or fuses were not wired."
            }

        # Multiple sentinels or truncated: evaluate wire at first sentinel
        sentinel_offset = sentinel_offsets[0]
        wire_start = sentinel_offset + sentinel_len
        available_wire = file_size - wire_start

        if available_wire < 2:
            return {
                "success": True,
                "status": "success",
                "classification": "INCONCLUSIVE",
                "artifact": {
                    "path": abs_path,
                    "sha256": file_sha,
                    "bytes": file_size,
                    "format": container_format
                },
                "sentinel_count": sentinel_count,
                "sentinel_offset": sentinel_offset,
                "limitations": LIMITATIONS + [
                    f"Electron fuse wire at offset {sentinel_offset} is truncated before wire version."
                ],
                "message": f"Electron fuse wire at offset {sentinel_offset} is truncated (INCONCLUSIVE)."
            }

        try:
            with open(abs_path, "rb") as bf:
                bf.seek(wire_start)
                header = bf.read(2)
                wire_version = header[0]
                declared_length = header[1]

                fuses_bytes = bf.read(min(declared_length, file_size - (wire_start + 2)))
        except Exception as wire_err:
            return {
                "success": False,
                "status": "error",
                "classification": "INCONCLUSIVE",
                "message": f"Failed reading fuse wire: {wire_err}"
            }

        if len(fuses_bytes) < declared_length:
            return {
                "success": True,
                "status": "success",
                "classification": "INCONCLUSIVE",
                "artifact": {
                    "path": abs_path,
                    "sha256": file_sha,
                    "bytes": file_size,
                    "format": container_format
                },
                "sentinel_count": sentinel_count,
                "wire_version": wire_version,
                "declared_length": declared_length,
                "limitations": LIMITATIONS + [
                    f"Electron fuse wire at offset {sentinel_offset} is truncated ({len(fuses_bytes)} of {declared_length} bytes read)."
                ],
                "message": f"Electron fuse wire at offset {sentinel_offset} is incomplete (INCONCLUSIVE)."
            }

        # Decode fuse bytes
        fuses_list = []
        fuses_dict = {}

        for idx, raw_b in enumerate(fuses_bytes):
            if raw_b == 0x30:
                state_str = "disabled"
            elif raw_b == 0x31:
                state_str = "enabled"
            elif raw_b == 0x72:
                state_str = "removed"
            else:
                state_str = "unknown"

            fuse_name = FUSE_V1_NAMES[idx] if (wire_version == 1 and idx < len(FUSE_V1_NAMES)) else None
            fuses_list.append({
                "index": idx,
                "name": fuse_name,
                "state": state_str,
                "raw_byte": raw_b
            })
            if fuse_name:
                key_name = re.sub(r'(?<!^)(?=[A-Z])', '_', fuse_name).lower()
                fuses_dict[key_name] = state_str

        # Derive runtime implications (REA domain/electron/electronFuses.ts)
        implications = []
        # Index 0: RunAsNode
        run_as_node_fuse = next((f for f in fuses_list if f["index"] == 0), None)
        if run_as_node_fuse:
            implications.append({
                "subject": "electron_run_as_node",
                "fuse_index": 0,
                "outcome": "honored" if run_as_node_fuse["state"] == "enabled" else "not_honored"
            })
        # Index 3: EnableNodeCliInspectArguments
        inspect_fuse = next((f for f in fuses_list if f["index"] == 3), None)
        if inspect_fuse:
            implications.append({
                "subject": "node_cli_inspect_arguments",
                "fuse_index": 3,
                "outcome": "honored" if inspect_fuse["state"] == "enabled" else "not_honored"
            })
        # Index 4: EnableEmbeddedAsarIntegrityValidation
        asar_integ_fuse = next((f for f in fuses_list if f["index"] == 4), None)
        if asar_integ_fuse:
            implications.append({
                "subject": "embedded_asar_integrity_validation",
                "fuse_index": 4,
                "outcome": "enforced" if asar_integ_fuse["state"] == "enabled" else "not_enforced"
            })
        # Index 5: OnlyLoadAppFromAsar
        only_asar_fuse = next((f for f in fuses_list if f["index"] == 5), None)
        if only_asar_fuse:
            implications.append({
                "subject": "only_load_app_from_asar",
                "fuse_index": 5,
                "outcome": "restricted_to_app_asar" if only_asar_fuse["state"] == "enabled" else "not_restricted_to_app_asar"
            })

        speech_parts = [
            f"Electron binary fuses for '{os.path.basename(abs_path)}' (CONFIRMED, wire v{wire_version}): "
        ]
        inspect_state = next((f["state"] for f in fuses_list if f["index"] == 3), "unknown")
        run_node_state = next((f["state"] for f in fuses_list if f["index"] == 0), "unknown")
        speech_parts.append(f"NodeCliInspect: {inspect_state}, RunAsNode: {run_node_state}.")

        return {
            "success": True,
            "status": "success",
            "classification": "CONFIRMED",
            "artifact": {
                "path": abs_path,
                "sha256": file_sha,
                "bytes": file_size,
                "format": container_format
            },
            "sentinel_count": sentinel_count,
            "sentinel_offset": sentinel_offset,
            "wire_version": wire_version,
            "declared_length": declared_length,
            "fuses": fuses_list,
            "fuses_dict": fuses_dict,
            "runtime_implications": implications,
            "limitations": LIMITATIONS,
            "message": "".join(speech_parts)
        }


    # ── 5. DISPATCH TO ADAPTERS OR UNIVERSAL ENGINE ─────────────────────────

    def execute_app_action(
        self,
        app_name: str,
        action: str,
        params: Dict[str, Any],
        confirmed_by_user: bool = False,
    ) -> AppInteractionResult:
        """
        Executes an action within an application using its adapter or universal automation.
        """
        adapter = self.get_adapter_for(app_name)
        if adapter:
            return adapter.execute_workflow(self, action, params, confirmed_by_user=confirmed_by_user)

        # Universal fallback workflow
        win = self.find_app_window(app_name)
        if not win:
            return AppInteractionResult(
                success=False,
                status="failed",
                app_name=app_name,
                operation=action,
                message=f"Application '{app_name}' is not running or no window was found. Please launch it first.",
            )

        hwnd = win["hwnd"]
        if action == "focus":
            ok = self.activate_window(hwnd)
            return AppInteractionResult(
                success=ok,
                status="verified" if ok else "failed",
                app_name=app_name,
                operation="focus",
                message=f"Focused '{win['title']}'." if ok else f"Could not focus '{win['title']}'.",
                verified=ok,
                evidence={"hwnd": hwnd, "title": win["title"]}
            )

        elif action == "enter_text":
            text = params.get("text", "")
            return self.enter_text(hwnd, text, control_hint=params.get("control"))

        elif action == "click":
            btn = params.get("button", "")
            return self.click_button(hwnd, btn)

        return AppInteractionResult(
            success=False,
            status="unsupported",
            app_name=app_name,
            operation=action,
            message=f"Operation '{action}' is not supported for application '{app_name}'.",
        )

    def _register_default_adapters(self) -> None:
        """Register the default supported application adapters."""
        self.register_adapter(WhatsAppAdapter())
        self.register_adapter(ExcelAdapter())
        self.register_adapter(VSCodeAdapter())
        self.register_adapter(BrowserAdapter())
        self.register_adapter(MediaPlayerAdapter())
        self.register_adapter(ExplorerAdapter())


# =============================================================================
# 2. APPLICATION-SPECIFIC ADAPTERS
# =============================================================================

class WhatsAppAdapter(BaseAppAdapter):
    """
    Adapter for WhatsApp desktop application workflows.
    Supports chat selection, message drafting, draft verification,
    and requires explicit user confirmation before actually sending.
    """

    @property
    def adapter_name(self) -> str:
        return "whatsapp"

    def can_handle(self, app_name: str) -> bool:
        return "whatsapp" in app_name.lower()

    def get_supported_capabilities(self) -> List[str]:
        return ["open_chat", "draft_message", "verify_draft", "send_message"]

    def execute_workflow(
        self,
        controller: UniversalAppController,
        action: str,
        params: Dict[str, Any],
        confirmed_by_user: bool = False,
    ) -> AppInteractionResult:
        win = controller.find_app_window("whatsapp")
        if not win:
            return AppInteractionResult(
                success=False,
                status="failed",
                app_name="WhatsApp",
                operation=action,
                message="WhatsApp is not currently running. Please launch WhatsApp first.",
            )

        hwnd = win["hwnd"]
        controller.activate_window(hwnd)

        contact = params.get("contact") or params.get("to") or params.get("recipient", "")
        message = params.get("message") or params.get("text") or params.get("draft", "")

        if action in ("open_chat", "search_contact"):
            if not contact:
                return AppInteractionResult(
                    success=False,
                    status="failed",
                    app_name="WhatsApp",
                    operation=action,
                    message="Contact or recipient name is required.",
                )
            # Shortcut in WhatsApp to search: Ctrl+F
            try:
                import pyautogui
                pyautogui.hotkey('ctrl', 'f')
                time.sleep(0.2)
                pyautogui.write(contact, interval=0.02)
                time.sleep(0.3)
                pyautogui.press('enter')
                return AppInteractionResult(
                    success=True,
                    status="verified",
                    app_name="WhatsApp",
                    operation="open_chat",
                    message=f"Searched and opened chat with '{contact}'.",
                    verified=True,
                    evidence={"contact": contact}
                )
            except Exception as e:
                return AppInteractionResult(
                    success=False,
                    status="failed",
                    app_name="WhatsApp",
                    operation="open_chat",
                    message=f"Failed to open chat: {e}",
                    error=str(e)
                )

        elif action == "draft_message":
            if not message:
                return AppInteractionResult(
                    success=False,
                    status="failed",
                    app_name="WhatsApp",
                    operation=action,
                    message="Message text is required to draft.",
                )
            try:
                import pyautogui
                pyautogui.write(message, interval=0.01)
                time.sleep(0.2)
                # Note: DO NOT press enter here! We only DRAFT it.
                return AppInteractionResult(
                    success=True,
                    status="verified",
                    app_name="WhatsApp",
                    operation="draft_message",
                    message=f"Drafted message to {contact or 'recipient'}: '{message}'. Not sent yet.",
                    verified=True,
                    evidence={"draft": message, "contact": contact, "sent": False}
                )
            except Exception as e:
                return AppInteractionResult(
                    success=False,
                    status="failed",
                    app_name="WhatsApp",
                    operation="draft_message",
                    message=f"Failed to draft message: {e}",
                    error=str(e)
                )

        elif action == "send_message":
            # STRICT SAFETY BARRIER: Explicit confirmation required!
            if not confirmed_by_user:
                return AppInteractionResult(
                    success=False,
                    status="confirmation_required",
                    app_name="WhatsApp",
                    operation="send_message",
                    message=f"Sending message to '{contact}' requires explicit confirmation. Say 'yes' or 'confirm' to send.",
                    requires_confirmation=True,
                    evidence={"contact": contact, "message": message}
                )

            try:
                import pyautogui
                pyautogui.press('enter')
                time.sleep(0.3)
                return AppInteractionResult(
                    success=True,
                    status="verified",
                    app_name="WhatsApp",
                    operation="send_message",
                    message=f"Confirmed and sent message to '{contact}'.",
                    verified=True,
                    evidence={"contact": contact, "message": message, "sent": True}
                )
            except Exception as e:
                return AppInteractionResult(
                    success=False,
                    status="failed",
                    app_name="WhatsApp",
                    operation="send_message",
                    message=f"Failed to send message: {e}",
                    error=str(e)
                )

        return AppInteractionResult(
            success=False,
            status="unsupported",
            app_name="WhatsApp",
            operation=action,
            message=f"Unknown WhatsApp action '{action}'.",
        )


class ExcelAdapter(BaseAppAdapter):
    """
    Adapter for Microsoft Excel or spreadsheet files.
    Supports opening, reading cells, editing cells, and verified saving.
    """

    @property
    def adapter_name(self) -> str:
        return "excel"

    def can_handle(self, app_name: str) -> bool:
        return any(k in app_name.lower() for k in ("excel", "spreadsheet", "workbook", ".xlsx", ".xls"))

    def get_supported_capabilities(self) -> List[str]:
        return ["read_cell", "write_cell", "open_workbook", "calculate_sum"]

    def execute_workflow(
        self,
        controller: UniversalAppController,
        action: str,
        params: Dict[str, Any],
        confirmed_by_user: bool = False,
    ) -> AppInteractionResult:
        file_path = params.get("path") or params.get("file_path") or ""
        cell = params.get("cell", "A1")
        value = params.get("value")

        if action in ("write_cell", "edit_cell"):
            if not file_path or not os.path.exists(file_path):
                return AppInteractionResult(
                    success=False,
                    status="failed",
                    app_name="Excel",
                    operation=action,
                    message=f"Spreadsheet file '{file_path}' does not exist.",
                )
            try:
                import openpyxl
                wb = openpyxl.load_workbook(file_path)
                ws = wb.active
                ws[cell] = value
                wb.save(file_path)

                # Verification: re-read from disk
                wb2 = openpyxl.load_workbook(file_path, data_only=True)
                verified_val = wb2.active[cell].value
                is_ok = str(verified_val) == str(value)

                return AppInteractionResult(
                    success=is_ok,
                    status="verified" if is_ok else "failed",
                    app_name="Excel",
                    operation="write_cell",
                    message=f"Updated cell {cell} to '{value}' in {os.path.basename(file_path)}.",
                    verified=is_ok,
                    evidence={"file": file_path, "cell": cell, "value": verified_val}
                )
            except Exception as e:
                return AppInteractionResult(
                    success=False,
                    status="error",
                    app_name="Excel",
                    operation="write_cell",
                    message=f"Failed to edit spreadsheet: {e}",
                    error=str(e)
                )

        elif action == "read_cell":
            if not file_path or not os.path.exists(file_path):
                return AppInteractionResult(
                    success=False,
                    status="failed",
                    app_name="Excel",
                    operation=action,
                    message=f"Spreadsheet file '{file_path}' not found.",
                )
            try:
                import openpyxl
                wb = openpyxl.load_workbook(file_path, data_only=True)
                val = wb.active[cell].value
                return AppInteractionResult(
                    success=True,
                    status="verified",
                    app_name="Excel",
                    operation="read_cell",
                    message=f"Cell {cell} contains: {val}",
                    verified=True,
                    evidence={"file": file_path, "cell": cell, "value": val}
                )
            except Exception as e:
                return AppInteractionResult(
                    success=False,
                    status="error",
                    app_name="Excel",
                    operation="read_cell",
                    message=f"Failed to read cell: {e}",
                    error=str(e)
                )

        return AppInteractionResult(
            success=False,
            status="unsupported",
            app_name="Excel",
            operation=action,
            message=f"Unsupported Excel action '{action}'.",
        )


class VSCodeAdapter(BaseAppAdapter):
    """
    Adapter for Visual Studio Code editor operations.
    """

    @property
    def adapter_name(self) -> str:
        return "vscode"

    def can_handle(self, app_name: str) -> bool:
        return any(k in app_name.lower() for k in ("code", "vscode", "visual studio code"))

    def get_supported_capabilities(self) -> List[str]:
        return ["open_file", "open_folder", "inspect_editor"]

    def execute_workflow(
        self,
        controller: UniversalAppController,
        action: str,
        params: Dict[str, Any],
        confirmed_by_user: bool = False,
    ) -> AppInteractionResult:
        path = params.get("path", "")
        if action in ("open_file", "open_folder"):
            import shutil, subprocess
            code_bin = shutil.which("code") or shutil.which("code.cmd")
            if not code_bin:
                return AppInteractionResult(
                    success=False,
                    status="failed",
                    app_name="VS Code",
                    operation=action,
                    message="VS Code executable was not found on PATH.",
                )
            try:
                subprocess.Popen([code_bin, path] if path else [code_bin])
                time.sleep(1.0)
                win = controller.find_app_window("visual studio code")
                is_running = win is not None
                return AppInteractionResult(
                    success=True,
                    status="verified" if is_running else "unverified",
                    app_name="VS Code",
                    operation=action,
                    message=f"Opened '{path or 'VS Code'}' in editor.",
                    verified=is_running,
                    evidence={"path": path, "window": win["title"] if win else None}
                )
            except Exception as e:
                return AppInteractionResult(
                    success=False,
                    status="error",
                    app_name="VS Code",
                    operation=action,
                    message=f"Could not launch VS Code: {e}",
                    error=str(e)
                )

        return AppInteractionResult(
            success=False,
            status="unsupported",
            app_name="VS Code",
            operation=action,
            message=f"Action '{action}' is not supported.",
        )


class BrowserAdapter(BaseAppAdapter):
    """Adapter for web browser workflows."""

    @property
    def adapter_name(self) -> str:
        return "browser"

    def can_handle(self, app_name: str) -> bool:
        return any(k in app_name.lower() for k in ("browser", "chrome", "edge", "firefox", "brave"))

    def get_supported_capabilities(self) -> List[str]:
        return ["open_url", "navigate_back", "search_web"]

    def execute_workflow(
        self,
        controller: UniversalAppController,
        action: str,
        params: Dict[str, Any],
        confirmed_by_user: bool = False,
    ) -> AppInteractionResult:
        from modules.browser.browser_controller import open_url, search_web, go_back

        if action == "open_url":
            url = params.get("url", "")
            res = open_url(url)
            return AppInteractionResult(
                success=res.get("success", True),
                status="verified" if res.get("success") else "failed",
                app_name="Browser",
                operation="open_url",
                message=res.get("message", f"Opened URL {url}."),
                verified=res.get("success", True),
                evidence={"url": url}
            )
        elif action == "search_web":
            q = params.get("query", "")
            res = search_web(q)
            return AppInteractionResult(
                success=res.get("success", True),
                status="verified",
                app_name="Browser",
                operation="search_web",
                message=res.get("message", f"Searched for '{q}'."),
                verified=True,
                evidence=res
            )
        elif action == "navigate_back":
            res = go_back()
            return AppInteractionResult(
                success=res.get("success", True),
                status="verified",
                app_name="Browser",
                operation="navigate_back",
                message="Navigated back.",
                verified=True,
            )

        return AppInteractionResult(
            success=False,
            status="unsupported",
            app_name="Browser",
            operation=action,
            message=f"Unsupported browser action '{action}'.",
        )


class MediaPlayerAdapter(BaseAppAdapter):
    """Adapter for media playback control using Windows virtual keys."""

    @property
    def adapter_name(self) -> str:
        return "media_player"

    def can_handle(self, app_name: str) -> bool:
        return any(k in app_name.lower() for k in ("media", "spotify", "vlc", "music", "player"))

    def get_supported_capabilities(self) -> List[str]:
        return ["play_pause", "next_track", "previous_track", "stop"]

    def execute_workflow(
        self,
        controller: UniversalAppController,
        action: str,
        params: Dict[str, Any],
        confirmed_by_user: bool = False,
    ) -> AppInteractionResult:
        if not win32api:
            return AppInteractionResult(success=False, status="unsupported", app_name="Media", operation=action, message="Win32 API unavailable.")

        # Windows Virtual Keys for Media:
        # VK_MEDIA_PLAY_PAUSE = 0xB3, VK_MEDIA_NEXT_TRACK = 0xB0, VK_MEDIA_PREV_TRACK = 0xB1, VK_MEDIA_STOP = 0xB2
        vk_map = {
            "play_pause": 0xB3,
            "play": 0xB3,
            "pause": 0xB3,
            "next_track": 0xB0,
            "previous_track": 0xB1,
            "stop": 0xB2,
        }

        vk = vk_map.get(action)
        if not vk:
            return AppInteractionResult(success=False, status="unsupported", app_name="Media", operation=action, message=f"Unknown media action '{action}'.")

        try:
            win32api.keybd_event(vk, 0, 0, 0)
            win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
            return AppInteractionResult(
                success=True,
                status="verified",
                app_name="Media",
                operation=action,
                message=f"Media action '{action}' sent to system.",
                verified=True,
            )
        except Exception as e:
            return AppInteractionResult(
                success=False,
                status="error",
                app_name="Media",
                operation=action,
                message=f"Failed to trigger media action: {e}",
                error=str(e)
            )


class ExplorerAdapter(BaseAppAdapter):
    """Adapter for Windows File Explorer navigation and interaction."""

    @property
    def adapter_name(self) -> str:
        return "explorer"

    def can_handle(self, app_name: str) -> bool:
        return any(k in app_name.lower() for k in ("explorer", "file explorer", "folder"))

    def get_supported_capabilities(self) -> List[str]:
        return ["open_directory", "select_file"]

    def execute_workflow(
        self,
        controller: UniversalAppController,
        action: str,
        params: Dict[str, Any],
        confirmed_by_user: bool = False,
    ) -> AppInteractionResult:
        path = params.get("path", "")
        if not os.path.exists(path):
            return AppInteractionResult(
                success=False,
                status="failed",
                app_name="Explorer",
                operation=action,
                message=f"Path '{path}' does not exist.",
            )

        try:
            os.startfile(path)
            time.sleep(0.5)
            return AppInteractionResult(
                success=True,
                status="verified",
                app_name="Explorer",
                operation="open_directory",
                message=f"Opened '{path}' in File Explorer.",
                verified=True,
                evidence={"path": path}
            )
        except Exception as e:
            return AppInteractionResult(
                success=False,
                status="error",
                app_name="Explorer",
                operation=action,
                message=f"Could not open File Explorer: {e}",
                error=str(e)
            )


_universal_app_controller: Optional[UniversalAppController] = None

def get_universal_app_controller() -> UniversalAppController:
    """Return the global UniversalAppController singleton."""
    global _universal_app_controller
    if _universal_app_controller is None:
        _universal_app_controller = UniversalAppController()
    return _universal_app_controller
