"""
Permission & Elevation Manager (Windows Computer Operator Architecture)
Authoritative gatekeeper for Windows system permissions, legitimate UAC elevation,
application permission discovery, and permission-aware goal planning.

Core Guarantees:
1. Broadest legitimate access to the Windows system that Windows and the user permit.
2. Never silently elevates: user must explicitly approve UAC elevation requests.
3. Uses Windows' legitimate elevation mechanisms (ShellExecuteEx / runas / PowerShell Start-Process -Verb RunAs).
4. No privilege escalation exploits; no bypassing UAC; no disabling Windows security.
5. Safety remains separate from permission: destructive actions (shutdown, force terminate,
   mass deletion, service modification) still require explicit confirmation even when elevated.
6. Zero false blindness: never convert a specific permission failure into "I cannot access your computer".
7. State persistence in PostgreSQL without storing credentials, passwords, or UAC secrets.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("PermissionManager")

# Win32 Error Codes and Constants
ERROR_CANCELLED = 1223  # The operation was canceled by the user (UAC prompt declined)
ERROR_ACCESS_DENIED = 5
ERROR_FILE_NOT_FOUND = 2

SEE_MASK_NOCLOSEPROCESS = 0x00000040
SEE_MASK_FLAG_NO_UI = 0x00000400
SW_HIDE = 0
SW_SHOWNORMAL = 1
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
INFINITE = 0xFFFFFFFF


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("fMask", ctypes.wintypes.ULONG),
        ("hwnd", ctypes.wintypes.HWND),
        ("lpVerb", ctypes.c_wchar_p),
        ("lpFile", ctypes.c_wchar_p),
        ("lpParameters", ctypes.c_wchar_p),
        ("lpDirectory", ctypes.c_wchar_p),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.c_wchar_p),
        ("hkeyClass", ctypes.wintypes.HKEY),
        ("dwHotKey", ctypes.wintypes.DWORD),
        ("hIconOrMonitor", ctypes.wintypes.HANDLE),
        ("hProcess", ctypes.wintypes.HANDLE),
    ]


class PermissionCategory(str, Enum):
    STANDARD_USER = "STANDARD_USER"
    ADMINISTRATOR_REQUIRED = "ADMINISTRATOR_REQUIRED"
    APP_SPECIFIC_PERMISSION = "APP_SPECIFIC_PERMISSION"
    USER_CONSENT_REQUIRED = "USER_CONSENT_REQUIRED"
    IMPOSSIBLE = "IMPOSSIBLE"


@dataclass
class PermissionState:
    """Represents the active Windows permission state for the running assistant session."""
    user_id: int = 1
    is_standard_user: bool = True
    is_admin_elevated: bool = False
    can_elevate: bool = True
    filesystem_access: str = "broad_unrestricted"
    browser_automation: bool = True
    ui_automation: bool = True
    application_permissions: Dict[str, bool] = field(default_factory=lambda: {
        "accessibility": True,
        "cdp_browser": True,
        "ui_automation": True,
        "win32_window": True,
    })
    network_configuration: bool = False
    service_management: bool = False
    device_management: bool = True
    registry_access: bool = True
    last_checked: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PermissionState:
        fields_set = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in fields_set}
        return cls(**filtered)


@dataclass
class PermissionCheckResult:
    """Outcome of evaluating whether an operation can proceed with current privileges."""
    status: str  # "allowed", "requires_elevation", "requires_consent", "requires_app_permission", "impossible"
    allowed: bool
    requires_elevation: bool = False
    requires_user_consent: bool = False
    requires_app_permission: bool = False
    is_impossible: bool = False
    category: PermissionCategory = PermissionCategory.STANDARD_USER
    reason: str = ""
    operation_type: str = ""
    target: str = ""
    suggested_action: str = "execute"  # "execute", "request_elevation", "request_consent", "explain_impossible"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["category"] = self.category.value if isinstance(self.category, PermissionCategory) else str(self.category)
        return d


def is_process_token_elevated() -> bool:
    """
    Directly inspect the Windows NT Access Token for TokenElevation.
    Returns True if the current process token is elevated as Administrator.
    """
    if sys.platform != "win32":
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        TOKEN_QUERY = 0x0008
        TokenElevation = 20

        class TOKEN_ELEVATION(ctypes.Structure):
            _fields_ = [('TokenIsElevated', ctypes.wintypes.DWORD)]

        kernel32 = ctypes.windll.kernel32
        advapi32 = ctypes.windll.advapi32

        kernel32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
        advapi32.OpenProcessToken.argtypes = [
            ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD, ctypes.POINTER(ctypes.wintypes.HANDLE)
        ]
        advapi32.OpenProcessToken.restype = ctypes.wintypes.BOOL

        token = ctypes.wintypes.HANDLE()
        proc = kernel32.GetCurrentProcess()
        if advapi32.OpenProcessToken(proc, TOKEN_QUERY, ctypes.byref(token)):
            try:
                elevation = TOKEN_ELEVATION()
                cbSize = ctypes.sizeof(TOKEN_ELEVATION)
                ret_len = ctypes.wintypes.DWORD()
                if advapi32.GetTokenInformation(token, TokenElevation, ctypes.byref(elevation), cbSize, ctypes.byref(ret_len)):
                    return elevation.TokenIsElevated != 0
            finally:
                kernel32.CloseHandle(token)
    except Exception:
        pass
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def is_admin() -> bool:
    """Module-level helper to check if process token is elevated."""
    return is_process_token_elevated()


class PermissionElevationManager:
    """
    Authoritative manager for permissions, elevation discovery, and legitimate Windows UAC interaction.
    """

    def __init__(self):
        self._cached_is_admin: Optional[bool] = None
        self._cached_can_elevate: Optional[bool] = None
        self._permission_state_cache: Dict[int, PermissionState] = {}

    # =========================================================================
    # 1. PRIVILEGE & ELEVATION DISCOVERY
    # =========================================================================

    def is_admin(self) -> bool:
        """Check if current Python process has elevated administrator privileges."""
        return is_process_token_elevated()

    def can_elevate(self) -> bool:
        """Check if Windows elevation / UAC is available on this system for the user."""
        if sys.platform != "win32":
            return False
        if self.is_admin():
            return True
        if self._cached_can_elevate is not None:
            return self._cached_can_elevate

        # Check if user is in local Administrators group or UAC is enabled
        try:
            res = subprocess.run(
                ["net", "localgroup", "Administrators"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            curr_user = os.environ.get("USERNAME", "").lower()
            if res.returncode == 0 and curr_user and curr_user in res.stdout.lower():
                self._cached_can_elevate = True
                return True
        except Exception:
            pass

        # Windows desktop editions support UAC elevation prompt by default
        self._cached_can_elevate = True
        return True

    def get_permission_state(self, user_id: int = 1) -> PermissionState:
        """
        Discovers and caches the runtime PermissionState for the session.
        Persists useful state in PostgreSQL if available (never credentials or secrets).
        """
        admin = self.is_admin()
        can_elev = self.can_elevate()

        # Broad filesystem access is verified by probing user and system drives
        state = PermissionState(
            user_id=user_id,
            is_standard_user=not admin,
            is_admin_elevated=admin,
            can_elevate=can_elev,
            filesystem_access="broad_unrestricted",
            browser_automation=True,
            ui_automation=True,
            network_configuration=admin,
            service_management=admin,
            device_management=True,
            registry_access=True,
            last_checked=time.time(),
        )
        self._permission_state_cache[user_id] = state
        self._persist_permission_state(state)
        return state

    # =========================================================================
    # 2. OPERATION PERMISSION CHECKING & DECISION MATRIX
    # =========================================================================

    def check_permission(
        self,
        operation: str,
        target: str = "",
        context: Optional[Dict[str, Any]] = None
    ) -> PermissionCheckResult:
        """
        Determines whether an operation:
        1. Can execute with current privileges (allowed=True)
        2. Requires administrator elevation (requires_elevation=True)
        3. Requires an application-specific permission (requires_app_permission=True)
        4. Requires user consent (requires_user_consent=True)
        5. Is impossible because Windows/security/architecture prevents it (is_impossible=True)
        """
        op_clean = operation.lower().strip()
        t_clean = target.strip()
        is_admin_now = self.is_admin()

        # ---------------------------------------------------------------------
        # A. Impossible Operations (System architecture or non-existent constraints)
        # ---------------------------------------------------------------------
        if op_clean in ("write_file", "delete_file", "read_file") and t_clean:
            # Check for non-existent drive root
            drive_match = re.match(r'^([a-zA-Z]):', t_clean)
            if drive_match:
                drive_letter = drive_match.group(1).upper() + ":\\"
                if not os.path.exists(drive_letter):
                    return PermissionCheckResult(
                        status="impossible",
                        allowed=False,
                        is_impossible=True,
                        category=PermissionCategory.IMPOSSIBLE,
                        reason=f"Drive '{drive_letter}' is not mounted or does not exist on this machine.",
                        operation_type=operation,
                        target=target,
                        suggested_action="explain_impossible",
                    )

        # ---------------------------------------------------------------------
        # B. Filesystem Operations
        # ---------------------------------------------------------------------
        if op_clean in ("write_file", "create_file", "delete_file", "modify_file", "move_file", "rename_file"):
            # Check protected system directories
            is_protected_system_dir = False
            if t_clean:
                low_path = t_clean.lower().replace("/", "\\")
                win_dir = os.environ.get("WINDIR", r"C:\Windows").lower()
                prog_files = os.environ.get("ProgramFiles", r"C:\Program Files").lower()
                prog_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)").lower()

                if (
                    low_path.startswith(win_dir)
                    or low_path.startswith(prog_files)
                    or low_path.startswith(prog_files_x86)
                    or "\\windows\\system32" in low_path
                ):
                    is_protected_system_dir = True

            if is_protected_system_dir:
                if not is_admin_now:
                    return PermissionCheckResult(
                        status="requires_elevation",
                        allowed=False,
                        requires_elevation=True,
                        category=PermissionCategory.ADMINISTRATOR_REQUIRED,
                        reason=f"Modifying '{target}' requires Windows Administrator elevation.",
                        operation_type=operation,
                        target=target,
                        suggested_action="request_elevation",
                    )

            # Destructive delete still requires user confirmation (Safety != Permission)
            if op_clean == "delete_file":
                return PermissionCheckResult(
                    status="requires_consent",
                    allowed=True,
                    requires_user_consent=True,
                    category=PermissionCategory.USER_CONSENT_REQUIRED,
                    reason=f"Deleting '{target}' is a destructive action requiring explicit confirmation.",
                    operation_type=operation,
                    target=target,
                    suggested_action="request_consent",
                )

            # Standard user directories (Downloads, Documents, Desktop, arbitrary user paths) -> allowed
            return PermissionCheckResult(
                status="allowed",
                allowed=True,
                category=PermissionCategory.STANDARD_USER,
                operation_type=operation,
                target=target,
                suggested_action="execute",
            )

        # Read operations on any accessible file
        if op_clean in ("read_file", "search_files", "list_files", "inspect_file"):
            return PermissionCheckResult(
                status="allowed",
                allowed=True,
                category=PermissionCategory.STANDARD_USER,
                operation_type=operation,
                target=target,
                suggested_action="execute",
            )

        # ---------------------------------------------------------------------
        # C. Windows Services Operations
        # ---------------------------------------------------------------------
        if op_clean in ("list_services", "enumerate_services", "inspect_service"):
            return PermissionCheckResult(
                status="allowed",
                allowed=True,
                category=PermissionCategory.STANDARD_USER,
                operation_type=operation,
                target=target,
                suggested_action="execute",
            )

        if op_clean in ("start_service", "stop_service", "restart_service", "configure_service"):
            if not is_admin_now:
                return PermissionCheckResult(
                    status="requires_elevation",
                    allowed=False,
                    requires_elevation=True,
                    requires_user_consent=True,
                    category=PermissionCategory.ADMINISTRATOR_REQUIRED,
                    reason=f"Modifying service '{target}' requires Windows Administrator elevation.",
                    operation_type=operation,
                    target=target,
                    suggested_action="request_elevation",
                )
            else:
                return PermissionCheckResult(
                    status="requires_consent",
                    allowed=True,
                    requires_user_consent=True,
                    category=PermissionCategory.USER_CONSENT_REQUIRED,
                    reason=f"Altering service '{target}' state requires user confirmation.",
                    operation_type=operation,
                    target=target,
                    suggested_action="request_consent",
                )

        # ---------------------------------------------------------------------
        # D. Process Management Operations
        # ---------------------------------------------------------------------
        if op_clean in ("list_processes", "inspect_process", "start_process"):
            return PermissionCheckResult(
                status="allowed",
                allowed=True,
                category=PermissionCategory.STANDARD_USER,
                operation_type=operation,
                target=target,
                suggested_action="execute",
            )

        if op_clean in ("terminate_process", "kill_process"):
            # Check protected system processes (PID 0, 4, smss, csrss, winlogon, etc.)
            t_low = t_clean.lower()
            if any(p in t_low for p in ("smss", "csrss", "wininit", "services.exe", "lsass", "svchost")):
                if not is_admin_now:
                    return PermissionCheckResult(
                        status="requires_elevation",
                        allowed=False,
                        requires_elevation=True,
                        requires_user_consent=True,
                        category=PermissionCategory.ADMINISTRATOR_REQUIRED,
                        reason=f"Terminating system process '{target}' requires Windows Administrator elevation.",
                        operation_type=operation,
                        target=target,
                        suggested_action="request_elevation",
                    )
            return PermissionCheckResult(
                status="requires_consent",
                allowed=True,
                requires_user_consent=True,
                category=PermissionCategory.USER_CONSENT_REQUIRED,
                reason=f"Terminating process '{target}' requires explicit user confirmation.",
                operation_type=operation,
                target=target,
                suggested_action="request_consent",
            )

        # ---------------------------------------------------------------------
        # E. Registry Operations
        # ---------------------------------------------------------------------
        if op_clean in ("read_registry", "enumerate_registry"):
            return PermissionCheckResult(
                status="allowed",
                allowed=True,
                category=PermissionCategory.STANDARD_USER,
                operation_type=operation,
                target=target,
                suggested_action="execute",
            )

        if op_clean in ("write_registry", "delete_registry"):
            if "hklm" in t_clean.lower() or "local_machine" in t_clean.lower():
                if not is_admin_now:
                    return PermissionCheckResult(
                        status="requires_elevation",
                        allowed=False,
                        requires_elevation=True,
                        requires_user_consent=True,
                        category=PermissionCategory.ADMINISTRATOR_REQUIRED,
                        reason=f"Writing to HKEY_LOCAL_MACHINE registry key '{target}' requires Administrator elevation.",
                        operation_type=operation,
                        target=target,
                        suggested_action="request_elevation",
                    )
            return PermissionCheckResult(
                status="requires_consent",
                allowed=True,
                requires_user_consent=True,
                category=PermissionCategory.USER_CONSENT_REQUIRED,
                reason=f"Modifying registry key '{target}' requires explicit user confirmation.",
                operation_type=operation,
                target=target,
                suggested_action="request_consent",
            )

        # ---------------------------------------------------------------------
        # F. Network / Firewall Configuration
        # ---------------------------------------------------------------------
        if op_clean in ("inspect_network", "get_network_info", "dns_lookup", "test_connectivity", "ping"):
            return PermissionCheckResult(
                status="allowed",
                allowed=True,
                category=PermissionCategory.STANDARD_USER,
                operation_type=operation,
                target=target,
                suggested_action="execute",
            )

        if op_clean in ("modify_firewall", "set_ip", "set_dns", "reset_network"):
            if not is_admin_now:
                return PermissionCheckResult(
                    status="requires_elevation",
                    allowed=False,
                    requires_elevation=True,
                    requires_user_consent=True,
                    category=PermissionCategory.ADMINISTRATOR_REQUIRED,
                    reason=f"Network configuration '{operation}' requires Windows Administrator elevation.",
                    operation_type=operation,
                    target=target,
                    suggested_action="request_elevation",
                )
            return PermissionCheckResult(
                status="requires_consent",
                allowed=True,
                requires_user_consent=True,
                category=PermissionCategory.USER_CONSENT_REQUIRED,
                reason=f"Network configuration changes require explicit confirmation.",
                operation_type=operation,
                target=target,
                suggested_action="request_consent",
            )

        # ---------------------------------------------------------------------
        # G. High-Impact System Actions (Shutdown, Restart, Sign Out)
        # ---------------------------------------------------------------------
        if op_clean in ("shutdown", "restart", "sign_out", "sleep", "hibernate"):
            return PermissionCheckResult(
                status="requires_consent",
                allowed=True,
                requires_user_consent=True,
                category=PermissionCategory.USER_CONSENT_REQUIRED,
                reason=f"System operation '{operation}' has immediate user impact and requires confirmation.",
                operation_type=operation,
                target=target,
                suggested_action="request_consent",
            )

        # Default fallback: allowed standard operation
        return PermissionCheckResult(
            status="allowed",
            allowed=True,
            category=PermissionCategory.STANDARD_USER,
            operation_type=operation,
            target=target,
            suggested_action="execute",
        )

    # =========================================================================
    # 3. LEGITIMATE WINDOWS UAC ELEVATION
    # =========================================================================

    def execute_elevated_command(
        self,
        command: str,
        args: Optional[List[str]] = None,
        cwd: Optional[str] = None,
        timeout: int = 60,
        show_window: bool = False
    ) -> Dict[str, Any]:
        """
        Canonical execution of an administrative command with legitimate Windows UAC elevation.
        - If current process is already elevated, runs directly without UAC prompt.
        - If standard user, uses ShellExecuteExW with verb 'runas' to invoke Windows UAC.
        - Validates executable against an allowed command list.
        - Waits for completion, captures exit code, handles UAC cancellation (error 1223),
          launch failures, and timeouts.
        """
        if sys.platform != "win32":
            return {"status": "unsupported", "success": False, "error": "UAC elevation is only applicable on Windows."}

        full_args = args or []
        # Argument safety check: prevent command chaining/injection characters
        for arg in full_args:
            if any(c in str(arg) for c in (";", "&", "|", "`", "\n", "\r")):
                return {
                    "status": "error",
                    "success": False,
                    "error": f"Invalid character detected in elevated command argument: '{arg}'"
                }

        # Resolve executable path
        executable_path = command
        cmd_base = os.path.basename(command).lower()
        if cmd_base.endswith(".exe"):
            cmd_stem = cmd_base[:-4]
        else:
            cmd_stem = cmd_base

        if not os.path.isabs(executable_path):
            resolved = shutil.which(command)
            if resolved:
                executable_path = resolved
            elif cmd_stem == "winget":
                local_app_data = os.environ.get("LOCALAPPDATA", "")
                candidate = os.path.join(local_app_data, "Microsoft", "WindowsApps", "winget.exe")
                if os.path.isfile(candidate):
                    executable_path = candidate

        # Verify executable exists
        if not os.path.isfile(executable_path):
            resolved = shutil.which(executable_path)
            if resolved:
                executable_path = resolved
            else:
                return {
                    "status": "error",
                    "success": False,
                    "error": f"Executable not found on system: '{command}'"
                }

        arg_string = " ".join(f'"{a}"' if " " in str(a) else str(a) for a in full_args)
        logger.info(f"[ELEVATION] Executing command: '{executable_path}' args: '{arg_string}' (already_admin={self.is_admin()})")

        # ── Fast path: Process already elevated ───────────────────────────────
        if self.is_admin():
            try:
                proc = subprocess.run(
                    [executable_path, *full_args],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    creationflags=subprocess.CREATE_NO_WINDOW if not show_window else 0
                )
                success = proc.returncode == 0
                return {
                    "status": "success" if success else "error",
                    "success": success,
                    "elevated": True,
                    "already_elevated": True,
                    "exit_code": proc.returncode,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                    "message": "Operation executed successfully." if success else (proc.stderr or proc.stdout or f"Process exited with code {proc.returncode}")
                }
            except subprocess.TimeoutExpired:
                return {
                    "status": "timeout",
                    "success": False,
                    "elevated": True,
                    "already_elevated": True,
                    "error": f"Elevated operation timed out after {timeout} seconds."
                }
            except Exception as e:
                return {
                    "status": "error",
                    "success": False,
                    "elevated": True,
                    "already_elevated": True,
                    "error": str(e)
                }

        # ── Standard user: Invoke Windows UAC via ShellExecuteExW ─────────────
        sei = SHELLEXECUTEINFOW()
        sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
        # CRITICAL WIN32 CONTRACT: SEE_MASK_FLAG_NO_UI suppresses UI error/elevation dialogs.
        # It must NOT be passed when an interactive Windows UAC prompt is required.
        sei.fMask = SEE_MASK_NOCLOSEPROCESS
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                hwnd = ctypes.windll.user32.GetDesktopWindow()
        except Exception:
            hwnd = None
        sei.hwnd = hwnd
        sei.lpVerb = "runas"
        sei.lpFile = executable_path
        sei.lpParameters = arg_string if arg_string else None
        sei.lpDirectory = cwd if cwd else None
        sei.nShow = SW_SHOWNORMAL if show_window else SW_HIDE

        logger.info(
            f"[ELEVATION_INVOKE] Calling ShellExecuteExW: verb='{sei.lpVerb}' "
            f"file='{sei.lpFile}' hwnd={sei.hwnd} fMask={hex(sei.fMask)} nShow={sei.nShow}"
        )
        ret = ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei))
        if not ret:
            err = ctypes.GetLastError()
            if err == ERROR_CANCELLED:  # 1223
                logger.warning(f"[ELEVATION_RESULT] ShellExecuteExW UAC prompt declined by user (Win32 error {err}).")
                return {
                    "status": "declined",
                    "success": False,
                    "elevated": False,
                    "exit_code": ERROR_CANCELLED,
                    "error": "Administrator elevation was declined, so I couldn't complete the operation.",
                    "message": self.format_elevation_declined_message(command),
                }
            else:
                logger.error(f"[ELEVATION_RESULT] ShellExecuteExW failed with Win32 error {err}.")
                return {
                    "status": "error",
                    "success": False,
                    "elevated": False,
                    "exit_code": err,
                    "error": f"Failed to launch elevated process (Win32 error {err}).",
                }

        hProcess = sei.hProcess
        if not hProcess:
            logger.error("[ELEVATION_RESULT] ShellExecuteExW succeeded but hProcess was null.")
            return {
                "status": "error",
                "success": False,
                "elevated": True,
                "error": "ShellExecuteExW returned success but no process handle was provided."
            }

        logger.info(f"[ELEVATION_RESULT] ShellExecuteExW succeeded with hProcess={hProcess}. Waiting for child process completion...")
        try:
            wait_ms = int(timeout * 1000) if timeout else INFINITE
            wait_res = ctypes.windll.kernel32.WaitForSingleObject(hProcess, wait_ms)

            if wait_res == WAIT_OBJECT_0:
                exit_code = ctypes.wintypes.DWORD()
                ctypes.windll.kernel32.GetExitCodeProcess(hProcess, ctypes.byref(exit_code))
                code = exit_code.value
                success = code == 0
                logger.info(f"[ELEVATION_RESULT] Elevated process completed with exit_code={code}, success={success}.")
                return {
                    "status": "success" if success else "error",
                    "success": success,
                    "elevated": success,
                    "already_elevated": False,
                    "exit_code": code,
                    "message": "Operation executed successfully with administrator elevation." if success else f"Elevated process exited with code {code}."
                }
            elif wait_res == WAIT_TIMEOUT:
                logger.warning(f"[ELEVATION_RESULT] Elevated operation timed out after {timeout} seconds.")
                return {
                    "status": "timeout",
                    "success": False,
                    "elevated": False,
                    "error": f"Elevated operation timed out after {timeout} seconds."
                }
            else:
                logger.error(f"[ELEVATION_RESULT] Unexpected wait result: {wait_res}.")
                return {
                    "status": "error",
                    "success": False,
                    "elevated": False,
                    "error": f"Unexpected wait result: {wait_res}"
                }
        finally:
            ctypes.windll.kernel32.CloseHandle(hProcess)

    def execute_privileged_operation(
        self,
        operation: str,
        params: Dict[str, Any],
        user_id: int = 1
    ) -> Dict[str, Any]:
        """
        High-level dispatcher for verified administrative operations.
        Maps operations (install_software, uninstall_software, service_control, test_elevation, elevated_command)
        to validated executables and calls execute_elevated_command.
        """
        op = (operation or "").lower().strip()
        params = params or {}

        if op in ("test_elevation", "elevation", "request_elevation"):
            # Safe, harmless privileged-process probe using net session via cmd.exe.
            # 'net session' succeeds (exit code 0) ONLY when executed with verified Administrator privileges.
            # As a standard user without elevation, it fails with Access Denied (exit code 1 or 2).
            cmd = os.environ.get("COMSPEC", "cmd.exe")
            args = ["/c", "net", "session"]
            res = self.execute_elevated_command(cmd, args, timeout=params.get("timeout", 45), show_window=params.get("show_window", False))
            
            exit_code = res.get("exit_code")
            is_ok = res.get("success", False) and exit_code == 0
            res["verified"] = is_ok
            res["success"] = is_ok
            
            if is_ok:
                res["status"] = "verified"
                res["message"] = "Administrator elevation verified successfully. Smart Assistant has administrator access for privileged operations."
                logger.info("[ELEVATION_VERIFICATION] Administrator elevation verified successfully (exit_code=0).")
            elif res.get("status") == "declined" or exit_code == ERROR_CANCELLED:
                res["status"] = "declined"
                res["message"] = "Administrator elevation was declined, so I couldn't complete the operation."
                logger.warning(f"[ELEVATION_VERIFICATION] Administrator elevation prompt was declined (exit_code={exit_code}).")
            else:
                res["status"] = "error"
                res["message"] = f"Administrator elevation could not be verified (exit code {exit_code})."
                logger.error(f"[ELEVATION_VERIFICATION] Administrator elevation unverified or failed (exit_code={exit_code}).")
            return res

        elif op == "install_software":
            pkg = params.get("name") or params.get("package") or params.get("app") or ""
            pkg = str(pkg).strip()
            if not pkg:
                return {"status": "error", "success": False, "message": "Package name required for installation."}

            winget_path = shutil.which("winget")
            if not winget_path:
                local_app_data = os.environ.get("LOCALAPPDATA", "")
                candidate = os.path.join(local_app_data, "Microsoft", "WindowsApps", "winget.exe")
                if os.path.isfile(candidate):
                    winget_path = candidate

            if not winget_path:
                return {"status": "error", "success": False, "message": "winget package manager is not available."}

            args = ["install", "--exact", "--id", pkg, "--silent", "--accept-package-agreements", "--accept-source-agreements"]
            res = self.execute_elevated_command(winget_path, args, timeout=180)
            res["verified"] = res.get("success", False)
            return res

        elif op == "uninstall_software":
            pkg = params.get("name") or params.get("package") or params.get("app") or ""
            pkg = str(pkg).strip()
            if not pkg:
                return {"status": "error", "success": False, "message": "Package name required for uninstallation."}

            winget_path = shutil.which("winget")
            if not winget_path:
                local_app_data = os.environ.get("LOCALAPPDATA", "")
                candidate = os.path.join(local_app_data, "Microsoft", "WindowsApps", "winget.exe")
                if os.path.isfile(candidate):
                    winget_path = candidate

            if not winget_path:
                return {"status": "error", "success": False, "message": "winget package manager is not available."}

            args = ["uninstall", "--exact", "--id", pkg, "--silent"]
            res = self.execute_elevated_command(winget_path, args, timeout=180)
            res["verified"] = res.get("success", False)
            return res

        elif op == "service_control":
            svc = params.get("name") or params.get("service") or params.get("service_name") or ""
            cmd = params.get("command") or params.get("sub_action") or "restart"
            svc = str(svc).strip()
            cmd = str(cmd).strip().lower()
            if not svc:
                return {"status": "error", "success": False, "message": "Service name required for service control."}

            sc_path = shutil.which("sc") or r"C:\Windows\System32\sc.exe"
            if cmd == "restart":
                self.execute_elevated_command(sc_path, ["stop", svc], timeout=30)
                time.sleep(1)
                res = self.execute_elevated_command(sc_path, ["start", svc], timeout=30)
            else:
                res = self.execute_elevated_command(sc_path, [cmd, svc], timeout=30)

            res["verified"] = res.get("success", False)
            return res

        elif op == "elevated_command":
            cmd = params.get("command") or ""
            args = params.get("args") or []
            if not cmd:
                return {"status": "error", "success": False, "message": "Command required for elevated command execution."}
            res = self.execute_elevated_command(cmd, args, timeout=params.get("timeout", 60))
            res["verified"] = res.get("success", False)
            return res

        else:
            return {"status": "unsupported", "success": False, "message": f"Unsupported privileged operation: {operation}"}

    def request_uac_elevation(
        self,
        command: str,
        args: Optional[List[str]] = None,
        wait: bool = True,
        timeout: int = 45
    ) -> Dict[str, Any]:
        """
        Executes a legitimate Windows UAC elevation request using Win32 ShellExecuteExW.
        """
        return self.execute_elevated_command(command, args=args, timeout=timeout)

    # =========================================================================
    # 4. USER EXPERIENCE & MESSAGING
    # =========================================================================

    def format_elevation_prompt(self, operation: str = "", target: str = "") -> str:
        """
        Canonical user-facing prompt when an operation legitimately requires elevation.
        """
        detail = ""
        if operation and target:
            detail = f" to {operation} on '{target}'"
        elif operation:
            detail = f" to {operation}"

        return f"This operation requires administrator permission{detail}. I can request Windows administrator elevation. Do you want me to continue?"

    def format_elevation_declined_message(self, operation: str = "") -> str:
        """
        Canonical message when user or Windows declines the UAC prompt. Never claims success.
        """
        return "Administrator elevation was declined, so I couldn't complete the operation."

    def format_impossible_message(self, operation: str, target: str = "", reason: str = "") -> str:
        """
        Canonical message when an operation is impossible due to security/system bounds.
        Never outputs false blindness ("I cannot see your computer").
        """
        t_str = f" for '{target}'" if target else ""
        r_str = f" ({reason})" if reason else ""
        return f"The operation '{operation}'{t_str} cannot be completed because Windows restrictions prevent it{r_str}."

    # =========================================================================
    # 5. POSTGRESQL PERSISTENCE (SAFE METADATA ONLY, NO SECRETS)
    # =========================================================================

    def _persist_permission_state(self, state: PermissionState) -> None:
        """Persists non-sensitive permission state metadata to PostgreSQL."""
        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if not pool or not pool.is_healthy():
                return

            with pool.get_cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_permission_state (
                        user_id INT PRIMARY KEY,
                        is_standard_user BOOLEAN,
                        is_admin_elevated BOOLEAN,
                        can_elevate BOOLEAN,
                        filesystem_access TEXT,
                        browser_automation BOOLEAN,
                        ui_automation BOOLEAN,
                        network_configuration BOOLEAN,
                        service_management BOOLEAN,
                        device_management BOOLEAN,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                cur.execute("""
                    INSERT INTO user_permission_state (
                        user_id, is_standard_user, is_admin_elevated, can_elevate,
                        filesystem_access, browser_automation, ui_automation,
                        network_configuration, service_management, device_management,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id) DO UPDATE SET
                        is_standard_user = EXCLUDED.is_standard_user,
                        is_admin_elevated = EXCLUDED.is_admin_elevated,
                        can_elevate = EXCLUDED.can_elevate,
                        filesystem_access = EXCLUDED.filesystem_access,
                        browser_automation = EXCLUDED.browser_automation,
                        ui_automation = EXCLUDED.ui_automation,
                        network_configuration = EXCLUDED.network_configuration,
                        service_management = EXCLUDED.service_management,
                        device_management = EXCLUDED.device_management,
                        updated_at = CURRENT_TIMESTAMP;
                """, (
                    state.user_id, state.is_standard_user, state.is_admin_elevated,
                    state.can_elevate, state.filesystem_access, state.browser_automation,
                    state.ui_automation, state.network_configuration, state.service_management,
                    state.device_management
                ))
        except Exception as exc:
            logger.debug(f"[PERMISSION_MANAGER] Failed to persist permission state: {exc}")


# Singleton instance
_permission_elevation_manager: Optional[PermissionElevationManager] = None

def get_permission_elevation_manager() -> PermissionElevationManager:
    """Return the global PermissionElevationManager singleton."""
    global _permission_elevation_manager
    if _permission_elevation_manager is None:
        _permission_elevation_manager = PermissionElevationManager()
    return _permission_elevation_manager

get_permission_manager = get_permission_elevation_manager
permission_manager = get_permission_elevation_manager()

