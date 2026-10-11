"""
Universal OS Operations — Environment Variables and Configuration
Supports reading, setting, and removing environment variables:
- Process-level (current environment)
- User-level (persisted via Windows HKCU Registry)
- System-level (persisted via Windows HKLM Registry - privileged)
- PATH inspection and manipulation
"""

from __future__ import annotations

import logging
import os
import sys
import winreg
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def read_env_var(name: str, scope: str = "process") -> Dict[str, Any]:
    """Read an environment variable from process, user, or system scope."""
    var_name = name.strip()
    norm_scope = scope.lower().strip()

    if norm_scope == "user" and sys.platform == "win32":
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_READ) as key:
                val, _ = winreg.QueryValueEx(key, var_name)
                return {
                    "success": True,
                    "status": "read",
                    "name": var_name,
                    "value": val,
                    "scope": "user",
                    "message": f"User environment variable '{var_name}' is set to '{val}'.",
                }
        except FileNotFoundError:
            return {"success": False, "status": "not_found", "name": var_name, "scope": "user", "message": f"User environment variable '{var_name}' is not set."}
        except Exception as exc:
            return {"success": False, "status": "error", "error": str(exc), "message": f"Error reading user env var: {exc}"}

    elif norm_scope == "system" and sys.platform == "win32":
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment", 0, winreg.KEY_READ) as key:
                val, _ = winreg.QueryValueEx(key, var_name)
                return {
                    "success": True,
                    "status": "read",
                    "name": var_name,
                    "value": val,
                    "scope": "system",
                    "message": f"System environment variable '{var_name}' is set to '{val}'.",
                }
        except FileNotFoundError:
            return {"success": False, "status": "not_found", "name": var_name, "scope": "system", "message": f"System environment variable '{var_name}' is not set."}
        except Exception as exc:
            return {"success": False, "status": "error", "error": str(exc), "message": f"Error reading system env var: {exc}"}

    else:
        # Process scope
        val = os.environ.get(var_name)
        if val is not None:
            return {
                "success": True,
                "status": "read",
                "name": var_name,
                "value": val,
                "scope": "process",
                "message": f"Environment variable '{var_name}' is set to '{val}'.",
            }
        else:
            return {
                "success": False,
                "status": "not_found",
                "name": var_name,
                "scope": "process",
                "message": f"Environment variable '{var_name}' is not set.",
            }


def set_env_var(name: str, value: str, scope: str = "process") -> Dict[str, Any]:
    """Set an environment variable in process, user, or system scope."""
    var_name = name.strip()
    var_value = str(value)
    norm_scope = scope.lower().strip()

    # Always update current process environment
    os.environ[var_name] = var_value

    if norm_scope == "user" and sys.platform == "win32":
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, var_name, 0, winreg.REG_SZ, var_value)
            return {
                "success": True,
                "status": "set",
                "name": var_name,
                "value": var_value,
                "scope": "user",
                "message": f"Set user environment variable '{var_name}' to '{var_value}'.",
            }
        except Exception as exc:
            return {"success": False, "status": "error", "error": str(exc), "message": f"Failed to persist user env var: {exc}"}

    elif norm_scope == "system" and sys.platform == "win32":
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment", 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, var_name, 0, winreg.REG_SZ, var_value)
            return {
                "success": True,
                "status": "set",
                "name": var_name,
                "value": var_value,
                "scope": "system",
                "message": f"Set system environment variable '{var_name}' to '{var_value}'.",
            }
        except Exception as exc:
            return {"success": False, "status": "error", "error": str(exc), "message": f"Failed to persist system env var: {exc}"}

    return {
        "success": True,
        "status": "set",
        "name": var_name,
        "value": var_value,
        "scope": "process",
        "message": f"Set process environment variable '{var_name}'.",
    }


def inspect_path() -> Dict[str, Any]:
    """Inspect all directories currently listed in PATH."""
    path_val = os.environ.get("PATH", "")
    dirs = [d.strip() for d in path_val.split(os.pathsep) if d.strip()]
    existing = [d for d in dirs if os.path.exists(d)]
    missing = [d for d in dirs if not os.path.exists(d)]

    return {
        "success": True,
        "status": "inspected",
        "total_entries": len(dirs),
        "valid_directories": len(existing),
        "missing_directories": len(missing),
        "directories": dirs,
        "entries": dirs,
        "missing": missing,
        "message": f"PATH contains {len(dirs)} entries ({len(existing)} valid directories).",
    }
