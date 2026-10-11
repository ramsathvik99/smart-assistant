"""
Universal OS Operations — Native System Operations
Provides native Windows API operations:
- Lock workstation, sign out, sleep, hibernate, restart, shutdown
- System information, uptime, display metrics, clipboard, screenshot
"""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

import psutil

logger = logging.getLogger(__name__)


def is_safe_mode() -> bool:
    """
    Returns True if execution is running within a test suite, dry-run mode,
    or simulated environment where native destructive OS operations must be intercepted.
    """
    return bool(
        os.environ.get("PYTEST_CURRENT_TEST")
        or os.environ.get("SMART_ASSISTANT_DRY_RUN") == "1"
        or os.environ.get("SMART_ASSISTANT_TEST_MODE") == "1"
    )


def lock_workstation(dry_run: bool = False) -> Dict[str, Any]:
    """Lock the Windows workstation via user32.LockWorkStation."""
    if dry_run or is_safe_mode():
        logger.warning("[SAFETY] Safe mode active (PYTEST_CURRENT_TEST/DRY_RUN). Intercepting native lock.")
        return {"success": True, "status": "simulated", "action": "lock", "dry_run": True, "message": "Simulated workstation lock (safe test mode)."}

    if sys.platform != "win32":
        return {"success": False, "status": "unsupported", "message": "Lock is only supported on Windows."}

    try:
        res = ctypes.windll.user32.LockWorkStation()
        if res:
            return {"success": True, "status": "locked", "message": "Workstation locked successfully."}
        else:
            return {"success": False, "status": "error", "message": "LockWorkStation API call returned false."}
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Lock failed: {exc}"}


def sign_out(dry_run: bool = False) -> Dict[str, Any]:
    """Sign out the current Windows user session."""
    if dry_run or is_safe_mode():
        logger.warning("[SAFETY] Safe mode active (PYTEST_CURRENT_TEST/DRY_RUN). Intercepting native sign_out.")
        return {"success": True, "status": "simulated", "action": "sign_out", "dry_run": True, "message": "Simulated sign out (safe test mode)."}

    if sys.platform != "win32":
        return {"success": False, "status": "unsupported", "message": "Sign out only supported on Windows."}

    try:
        # ExitWindowsEx with EWX_LOGOFF (0)
        ctypes.windll.user32.ExitWindowsEx(0, 0)
        return {"success": True, "status": "signed_out", "message": "Sign out initiated."}
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Sign out failed: {exc}"}


def sleep_system(dry_run: bool = False) -> Dict[str, Any]:
    """Put the system to sleep via SetSuspendState."""
    if dry_run or is_safe_mode():
        logger.warning("[SAFETY] Safe mode active (PYTEST_CURRENT_TEST/DRY_RUN). Intercepting native sleep.")
        return {"success": True, "status": "simulated", "action": "sleep", "dry_run": True, "message": "Simulated sleep (safe test mode)."}

    if sys.platform != "win32":
        return {"success": False, "status": "unsupported", "message": "Sleep only supported on Windows."}

    try:
        # SetSuspendState(0, 0, 0) -> Suspend
        ctypes.windll.PowrProf.SetSuspendState(0, 0, 0)
        return {"success": True, "status": "sleeping", "message": "System sleep initiated."}
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Sleep failed: {exc}"}


def hibernate_system(dry_run: bool = False) -> Dict[str, Any]:
    """Hibernate the system via SetSuspendState."""
    if dry_run or is_safe_mode():
        logger.warning("[SAFETY] Safe mode active (PYTEST_CURRENT_TEST/DRY_RUN). Intercepting native hibernate.")
        return {"success": True, "status": "simulated", "action": "hibernate", "dry_run": True, "message": "Simulated hibernation (safe test mode)."}

    if sys.platform != "win32":
        return {"success": False, "status": "unsupported", "message": "Hibernate only supported on Windows."}

    try:
        # SetSuspendState(1, 0, 0) -> Hibernate
        ctypes.windll.PowrProf.SetSuspendState(1, 0, 0)
        return {"success": True, "status": "hibernating", "message": "System hibernation initiated."}
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Hibernate failed: {exc}"}


def restart_system(delay_seconds: int = 0, dry_run: bool = False) -> Dict[str, Any]:
    """Restart the Windows computer."""
    if dry_run or is_safe_mode():
        logger.warning("[SAFETY] Safe mode active (PYTEST_CURRENT_TEST/DRY_RUN). Intercepting native restart.")
        return {"success": True, "status": "simulated", "action": "restart", "delay": delay_seconds, "dry_run": True, "message": f"Simulated restart (delay: {delay_seconds}s, safe test mode)."}

    if sys.platform != "win32":
        return {"success": False, "status": "unsupported", "message": "Restart only supported on Windows."}

    try:
        subprocess.run(f"shutdown /r /t {delay_seconds}", shell=True, check=True)
        return {"success": True, "status": "restarting", "message": f"System restart initiated (delay: {delay_seconds}s)."}
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Restart failed: {exc}"}


def shutdown_system(delay_seconds: int = 0, dry_run: bool = False) -> Dict[str, Any]:
    """Shutdown the Windows computer."""
    if dry_run or is_safe_mode():
        logger.warning("[SAFETY] Safe mode active (PYTEST_CURRENT_TEST/DRY_RUN). Intercepting native shutdown.")
        return {"success": True, "status": "simulated", "action": "shutdown", "delay": delay_seconds, "dry_run": True, "message": f"Simulated shutdown (delay: {delay_seconds}s, safe test mode)."}

    if sys.platform != "win32":
        return {"success": False, "status": "unsupported", "message": "Shutdown only supported on Windows."}

    try:
        subprocess.run(f"shutdown /s /t {delay_seconds}", shell=True, check=True)
        return {"success": True, "status": "shutting_down", "message": f"System shutdown initiated (delay: {delay_seconds}s)."}
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Shutdown failed: {exc}"}


def get_system_overview() -> Dict[str, Any]:
    """Get complete system hardware, OS, and telemetry summary."""
    boot_time = psutil.boot_time()
    uptime_secs = int(time.time() - boot_time)
    hours = uptime_secs // 3600
    minutes = (uptime_secs % 3600) // 60

    cpu_pct = psutil.cpu_percent(interval=None)
    cpu_count = psutil.cpu_count(logical=True)
    mem = psutil.virtual_memory()

    return {
        "success": True,
        "status": "inspected",
        "os": platform.system(),
        "os_release": platform.release(),
        "os_version": platform.version(),
        "architecture": platform.architecture()[0],
        "processor": platform.processor(),
        "cpu_cores": cpu_count,
        "cpu_usage_percent": cpu_pct,
        "ram_total_gb": round(mem.total / (1024 ** 3), 2),
        "ram_used_gb": round(mem.used / (1024 ** 3), 2),
        "ram_available_gb": round(mem.available / (1024 ** 3), 2),
        "ram_usage_percent": mem.percent,
        "uptime_hours": hours,
        "uptime_minutes": minutes,
        "uptime_string": f"{hours}h {minutes}m",
        "message": f"{platform.system()} {platform.release()}, {cpu_count} CPU cores ({cpu_pct}% load), {round(mem.used / (1024 ** 3), 1)}/{round(mem.total / (1024 ** 3), 1)} GB RAM used. Uptime: {hours}h {minutes}m.",
    }
