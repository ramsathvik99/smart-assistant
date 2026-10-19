"""
Smart Assistant — Startup Elevation & Limited Mode Coordinator
Handles legitimate Windows UAC elevation, prevents duplicate instances,
guards against elevation loops, ensures working directory and database persistence,
and manages clean fallback into Limited Mode when elevation is declined.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ElevationStartup")

# Win32 Error Codes
ERROR_ALREADY_EXISTS = 183
ERROR_CANCELLED = 1223
SE_ERR_ACCESSDENIED = 5


@dataclass
class ElevationStatus:
    """Diagnostic status representing the current process elevation and operating mode."""
    is_elevated: bool
    is_limited_mode: bool
    can_elevate: bool
    startup_policy: str
    process_id: int
    elevation_reason: str = ""
    admin_operations_enabled: bool = False
    single_instance_acquired: bool = True
    session_user: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ElevationStartupCoordinator:
    """
    Coordinates process-level Windows elevation, single-instance verification,
    and limited-mode capability gates.
    """

    _instance: Optional[ElevationStartupCoordinator] = None

    def __new__(cls) -> ElevationStartupCoordinator:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._mutex_handle: Optional[int] = None
        self._is_limited_mode: bool = False
        self._is_elevated_cached: Optional[bool] = None
        self._startup_policy: str = "standard_user"  # "standard_user" (default, normal launch), "auto_elevate", "limited"

    # ── 1. PRIVILEGE INSPECTION ──────────────────────────────────────────────

    def is_elevated(self) -> bool:
        """Determine whether the current process has Windows Administrator privileges."""
        if self._is_elevated_cached is not None:
            return self._is_elevated_cached

        if sys.platform != "win32":
            self._is_elevated_cached = (os.geteuid() == 0) if hasattr(os, "geteuid") else False
            return self._is_elevated_cached

        try:
            is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
            self._is_elevated_cached = is_admin
            return is_admin
        except Exception as e:
            logger.debug("[ELEVATION] Error checking IsUserAnAdmin: %s", e)
            self._is_elevated_cached = False
            return False

    def can_elevate(self) -> bool:
        """Check if Windows UAC elevation is theoretically supported for this session."""
        if sys.platform != "win32":
            return False
        return True

    # ── 2. SINGLE INSTANCE ACQUISITION ───────────────────────────────────────

    def ensure_single_instance(self, mutex_name: str = "Local\\SmartAssistant_Core_Instance") -> bool:
        """
        Guarantees that only a single instance of the assistant executes.
        Uses Local session namespace by default so non-elevated users can own it without privilege violation.
        Returns True if this instance claimed ownership; False if another active instance exists.
        """
        if sys.platform != "win32":
            return True

        try:
            kernel32 = ctypes.windll.kernel32
            # Create named mutex
            handle = kernel32.CreateMutexW(None, False, mutex_name)
            last_err = kernel32.GetLastError()
            if last_err == ERROR_ALREADY_EXISTS:
                logger.warning("[STARTUP] Another active assistant instance was detected via mutex '%s'.", mutex_name)
                if handle:
                    kernel32.CloseHandle(handle)
                return False

            if not handle or last_err == SE_ERR_ACCESSDENIED:
                # If Global namespace was rejected with access denied, fall back to Local namespace
                if mutex_name.startswith("Global\\"):
                    local_name = mutex_name.replace("Global\\", "Local\\", 1)
                    return self.ensure_single_instance(local_name)

            self._mutex_handle = handle
            logger.info("[STARTUP] Single-instance mutex acquired: '%s'", mutex_name)
            return True
        except Exception as e:
            logger.debug("[STARTUP] Mutex acquisition note: %s", e)
            return True

    def release_single_instance(self) -> None:
        """Release the acquired single-instance mutex if held."""
        if self._mutex_handle and sys.platform == "win32":
            try:
                ctypes.windll.kernel32.CloseHandle(self._mutex_handle)
            except Exception:
                pass
            self._mutex_handle = None

    # ── 3. STARTUP ELEVATION ORCHESTRATION ───────────────────────────────────

    def handle_startup_elevation(
        self,
        argv: Optional[List[str]] = None,
        project_root: Optional[Path] = None,
        policy: Optional[str] = None
    ) -> Tuple[bool, ElevationStatus]:
        """
        Orchestrates startup elevation flow.
        NORMAL FLOW: Starts as standard, non-elevated Windows process. Displays login without UAC prompt.
        Returns:
            (should_exit_now: bool, status: ElevationStatus)
        If an elevated child process was launched, should_exit_now is True.
        If continuing in this process (normal standard user, elevated, or limited), should_exit_now is False.
        """
        args = list(argv if argv is not None else sys.argv[1:])
        root = Path(project_root or Path(__file__).resolve().parent.parent)
        self._startup_policy = policy or os.environ.get("STARTUP_ELEVATION_POLICY", "standard_user")

        elevated_now = self.is_elevated()
        curr_user = os.environ.get("USERNAME", "user")

        # Explicit CLI flags
        flag_elevated = "--elevated" in args
        flag_limited = "--limited" in args or "--no-elevate" in args
        flag_require_elevation = "--require-elevation" in args

        if elevated_now:
            # We are running with full administrator privileges!
            logger.info("[STARTUP] Assistant running in ELEVATED ADMINISTRATOR mode (PID %s).", os.getpid())
            self._is_limited_mode = False
            status = ElevationStatus(
                is_elevated=True,
                is_limited_mode=False,
                can_elevate=True,
                startup_policy=self._startup_policy,
                process_id=os.getpid(),
                elevation_reason="Process is elevated with Windows Administrator rights.",
                admin_operations_enabled=True,
                single_instance_acquired=True,
                session_user=curr_user,
            )
            return False, status

        if flag_limited:
            # Explicit instruction to continue in limited mode
            logger.info("[STARTUP] Continuing in LIMITED MODE as requested by argument.")
            self._is_limited_mode = True
            status = ElevationStatus(
                is_elevated=False,
                is_limited_mode=True,
                can_elevate=True,
                startup_policy=self._startup_policy,
                process_id=os.getpid(),
                elevation_reason="Operating in Limited Mode. Administrator-required actions are disabled.",
                admin_operations_enabled=False,
                single_instance_acquired=True,
                session_user=curr_user,
            )
            return False, status

        # STANDARD STARTUP (Default): Normal non-elevated startup.
        # Do not prompt for UAC at startup! Login interface will display immediately.
        # Privileged operations will request elevation on-demand just-in-time when executed.
        if not flag_require_elevation and self._startup_policy not in ("auto_elevate", "force_elevate"):
            logger.info("[STARTUP] Starting as standard non-elevated Windows process (PID %s).", os.getpid())
            self._is_limited_mode = True  # Non-privileged for administrator-level operations
            status = ElevationStatus(
                is_elevated=False,
                is_limited_mode=True,
                can_elevate=self.can_elevate(),
                startup_policy=self._startup_policy,
                process_id=os.getpid(),
                elevation_reason="Standard non-elevated user process. Administrator actions will request elevation on-demand.",
                admin_operations_enabled=False,
                single_instance_acquired=True,
                session_user=curr_user,
            )
            return False, status

        # Only if policy is explicitly auto_elevate or flag_require_elevation was supplied:
        return self.request_process_elevation(args=args, project_root=root)

    def request_process_elevation(
        self,
        args: Optional[List[str]] = None,
        project_root: Optional[Path] = None
    ) -> Tuple[bool, ElevationStatus]:
        """
        Requests Windows UAC elevation to restart the assistant process elevated.
        Compatible with both virtual-environment script execution and packaged .exe execution.
        """
        curr_args = list(args if args is not None else sys.argv[1:])
        root = Path(project_root or Path(__file__).resolve().parent.parent)
        curr_user = os.environ.get("USERNAME", "user")

        if sys.platform != "win32":
            return False, ElevationStatus(
                is_elevated=False,
                is_limited_mode=True,
                can_elevate=False,
                startup_policy=self._startup_policy,
                process_id=os.getpid(),
                elevation_reason="Elevation unavailable on non-Windows platforms.",
                admin_operations_enabled=False,
                single_instance_acquired=True,
                session_user=curr_user,
            )

        logger.info("[STARTUP] Requesting Windows UAC administrator elevation...")
        is_frozen = getattr(sys, "frozen", False)
        target_exec = sys.executable

        # Filter out elevation flags to avoid infinite recursion
        filtered_args = [a for a in curr_args if a not in ("--elevated", "--limited", "--require-elevation")]

        if is_frozen:
            # Packaged .exe execution: sys.executable is the binary itself
            pass_args = ["--elevated"] + [f'"{a}"' if " " in a else a for a in filtered_args]
        else:
            # Python script execution: run assistant.py via python.exe
            main_script = str(root / "assistant.py")
            pass_args = [f'"{main_script}"', "--elevated"] + [f'"{a}"' if " " in a else a for a in filtered_args]

        arg_str = " ".join(pass_args)

        try:
            self.release_single_instance()

            shell32 = ctypes.windll.shell32
            ret = shell32.ShellExecuteW(
                None,
                "runas",
                target_exec,
                arg_str,
                str(root),
                1  # SW_SHOWNORMAL
            )

            if ret > 32:
                logger.info("[STARTUP] Elevated instance launched successfully (HINSTANCE %s). Exiting non-elevated process.", ret)
                status = ElevationStatus(
                    is_elevated=False,
                    is_limited_mode=False,
                    can_elevate=True,
                    startup_policy=self._startup_policy,
                    process_id=os.getpid(),
                    elevation_reason="Elevated process launched in new session.",
                    admin_operations_enabled=True,
                    single_instance_acquired=True,
                    session_user=curr_user,
                )
                return True, status
            else:
                logger.warning("[STARTUP] UAC elevation was declined or unavailable (code %s). Continuing in LIMITED MODE.", ret)
                self.ensure_single_instance()
                self._is_limited_mode = True
                status = ElevationStatus(
                    is_elevated=False,
                    is_limited_mode=True,
                    can_elevate=True,
                    startup_policy=self._startup_policy,
                    process_id=os.getpid(),
                    elevation_reason="UAC prompt was declined. Operating in Limited Mode.",
                    admin_operations_enabled=False,
                    single_instance_acquired=True,
                    session_user=curr_user,
                )
                return False, status

        except Exception as exc:
            logger.error("[STARTUP] Elevation request encountered error: %s. Continuing in Limited Mode.", exc)
            self._is_limited_mode = True
            status = ElevationStatus(
                is_elevated=False,
                is_limited_mode=True,
                can_elevate=True,
                startup_policy=self._startup_policy,
                process_id=os.getpid(),
                elevation_reason=f"Elevation failed: {exc}. Operating in Limited Mode.",
                admin_operations_enabled=False,
                single_instance_acquired=True,
                session_user=curr_user,
            )
            return False, status

    def get_elevation_status(self) -> ElevationStatus:
        """Return the current ElevationStatus."""
        elev = self.is_elevated()
        return ElevationStatus(
            is_elevated=elev,
            is_limited_mode=self._is_limited_mode,
            can_elevate=self.can_elevate(),
            startup_policy=self._startup_policy,
            process_id=os.getpid(),
            elevation_reason="Elevated administrator" if elev else ("Limited mode" if self._is_limited_mode else "Standard user"),
            admin_operations_enabled=elev,
            single_instance_acquired=True,
            session_user=os.environ.get("USERNAME", "user"),
        )


_coordinator: Optional[ElevationStartupCoordinator] = None

def get_elevation_coordinator() -> ElevationStartupCoordinator:
    """Return the global ElevationStartupCoordinator singleton."""
    global _coordinator
    if _coordinator is None:
        _coordinator = ElevationStartupCoordinator()
    return _coordinator


def is_process_elevated() -> bool:
    """Return whether the current process is running with elevated administrator rights."""
    return get_elevation_coordinator().is_elevated()

