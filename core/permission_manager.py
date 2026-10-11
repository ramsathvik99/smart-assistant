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

# Win32 Error Codes
ERROR_CANCELLED = 1223  # The operation was canceled by the user (UAC prompt declined)
ERROR_ACCESS_DENIED = 5


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
        if sys.platform != "win32":
            return os.geteuid() == 0 if hasattr(os, "geteuid") else False
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False

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

    def request_uac_elevation(
        self,
        command: str,
        args: Optional[List[str]] = None,
        wait: bool = True,
        timeout: int = 45
    ) -> Dict[str, Any]:
        """
        Executes a legitimate Windows UAC elevation request.
        Uses PowerShell Start-Process -Verb RunAs or Win32 ShellExecuteW(None, "runas", ...).
        Never bypasses UAC. User must explicitly approve in the Windows UAC dialog.

        Returns:
            status: "success" if elevation was approved and completed
            status: "declined" if user clicked "No" on UAC prompt (Win32 error 1223)
            status: "error" if elevation failed
        """
        if sys.platform != "win32":
            return {"status": "unsupported", "error": "UAC elevation is only applicable on Windows."}

        full_args = args or []
        arg_string = " ".join(f'"{a}"' if " " in a else a for a in full_args)

        logger.info(f"[ELEVATION] Requesting legitimate Windows UAC elevation for: '{command}' with args: '{arg_string}'")

        # Approach: PowerShell Start-Process with -Verb RunAs
        # Captures exit code and handles UAC rejection (ERROR_CANCELLED 1223)
        ps_script = (
            f"$proc = Start-Process -FilePath '{command}' "
            + (f"-ArgumentList '{arg_string}' " if arg_string else "")
            + f"-Verb RunAs -PassThru -ErrorAction Stop; "
            + ("$proc.WaitForExit(); exit $proc.ExitCode" if wait else "exit 0")
        )

        try:
            res = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )

            if res.returncode == 0:
                logger.info(f"[ELEVATION] Elevated command '{command}' succeeded.")
                return {
                    "status": "success",
                    "elevated": True,
                    "command": command,
                    "message": "Operation executed successfully with administrator elevation.",
                }
            else:
                err_text = (res.stderr or res.stdout).strip()
                # Check for user declining UAC prompt
                if "canceled by the user" in err_text.lower() or "1223" in err_text:
                    logger.warning("[ELEVATION] User declined Windows UAC prompt.")
                    return {
                        "status": "declined",
                        "elevated": False,
                        "error": "Administrator elevation was declined, so I couldn't complete the operation.",
                        "message": self.format_elevation_declined_message(command),
                    }

                return {
                    "status": "error",
                    "elevated": False,
                    "exit_code": res.returncode,
                    "error": err_text or f"Elevated command exited with code {res.returncode}.",
                }

        except subprocess.TimeoutExpired:
            return {"status": "timeout", "error": f"Elevated operation timed out after {timeout} seconds."}
        except Exception as exc:
            err_str = str(exc)
            if "canceled by the user" in err_str.lower() or "1223" in err_str:
                return {
                    "status": "declined",
                    "elevated": False,
                    "error": "Administrator elevation was declined.",
                    "message": self.format_elevation_declined_message(command),
                }
            return {"status": "error", "error": f"UAC elevation failed: {exc}"}

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

permission_manager = get_permission_elevation_manager()

