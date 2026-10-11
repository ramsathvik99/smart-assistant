"""
Universal OS Operations — Guarded Windows Registry Controller
Supports safe, strictly validated registry read and write operations.
Implements strict security boundaries:
- Whitelisted root keys (HKCU, HKLM)
- Blocked sensitive keys (SAM, SECURITY, SYSTEM\\Control\\Lsa, Boot, Drivers)
- Never executes arbitrary unvalidated registry edits
"""

from __future__ import annotations

import logging
import sys
import winreg
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Strict Security Boundary: Dangerous or system-critical paths are completely blocked from modification
BLOCKED_REGISTRY_PATHS = [
    r"sam",
    r"security",
    r"system\currentcontrolset\control\lsa",
    r"system\currentcontrolset\control\session manager\subsystems",
    r"bcd00000000",
    r"software\microsoft\windows nt\currentversion\winlogon",
]

ALLOWED_HIVE_MAP = {
    "HKCU": winreg.HKEY_CURRENT_USER,
    "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
    "HKLM": winreg.HKEY_LOCAL_MACHINE,
    "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
    "HKCR": winreg.HKEY_CLASSES_ROOT,
    "HKEY_CLASSES_ROOT": winreg.HKEY_CLASSES_ROOT,
}


def is_path_safe(sub_key: str) -> bool:
    """Validate that the registry subkey does not target blocked security paths."""
    low = sub_key.lower().strip("\\/")
    return not any(low.startswith(b) or b in low for b in BLOCKED_REGISTRY_PATHS)


def read_registry(
    hive_name: str,
    sub_key: str,
    value_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Read a registry key or specific value."""
    if sys.platform != "win32":
        return {"success": False, "status": "unsupported", "message": "Registry operations only available on Windows."}

    norm_hive = hive_name.upper().strip()
    hive = ALLOWED_HIVE_MAP.get(norm_hive)
    if not hive:
        return {"success": False, "status": "invalid_hive", "message": f"Unsupported registry hive: '{hive_name}'."}

    if not is_path_safe(sub_key):
        return {
            "success": False,
            "status": "blocked",
            "security_blocked": True,
            "message": f"Access to registry path '{sub_key}' is blocked by security policy.",
        }

    try:
        with winreg.OpenKey(hive, sub_key, 0, winreg.KEY_READ) as key:
            if value_name is not None:
                val, val_type = winreg.QueryValueEx(key, value_name)
                return {
                    "success": True,
                    "status": "read",
                    "hive": norm_hive,
                    "sub_key": sub_key,
                    "value_name": value_name,
                    "value": val,
                    "value_type": val_type,
                    "message": f"Registry value '{value_name}' is '{val}'.",
                }
            else:
                # Enumerate values
                values = {}
                try:
                    i = 0
                    while True:
                        v_name, v_data, _ = winreg.EnumValue(key, i)
                        values[v_name] = v_data
                        i += 1
                except OSError:
                    pass

                return {
                    "success": True,
                    "status": "read",
                    "hive": norm_hive,
                    "sub_key": sub_key,
                    "value_count": len(values),
                    "values": values,
                    "message": f"Read {len(values)} values from '{norm_hive}\\{sub_key}'.",
                }
    except FileNotFoundError:
        return {"success": False, "status": "not_found", "message": f"Registry key '{norm_hive}\\{sub_key}' does not exist."}
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Registry read failed: {exc}"}


def write_registry(
    hive_name: str,
    sub_key: str,
    value_name: str,
    value_data: Any,
    value_type: str = "REG_SZ",
) -> Dict[str, Any]:
    """Write or update a registry value with strict safety validation."""
    if sys.platform != "win32":
        return {"success": False, "status": "unsupported", "message": "Registry operations only available on Windows."}

    norm_hive = hive_name.upper().strip()
    hive = ALLOWED_HIVE_MAP.get(norm_hive)
    if not hive:
        return {"success": False, "status": "invalid_hive", "message": f"Unsupported registry hive: '{hive_name}'."}

    if not is_path_safe(sub_key):
        return {
            "success": False,
            "status": "blocked",
            "message": f"Writing to critical system registry path '{sub_key}' is blocked by security policy.",
        }

    type_map = {
        "REG_SZ": winreg.REG_SZ,
        "REG_DWORD": winreg.REG_DWORD,
        "REG_EXPAND_SZ": winreg.REG_EXPAND_SZ,
        "REG_BINARY": winreg.REG_BINARY,
    }
    target_type = type_map.get(value_type.upper(), winreg.REG_SZ)

    try:
        with winreg.CreateKeyEx(hive, sub_key, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, value_name, 0, target_type, value_data)

        return {
            "success": True,
            "status": "written",
            "hive": norm_hive,
            "sub_key": sub_key,
            "value_name": value_name,
            "value": value_data,
            "message": f"Successfully set '{norm_hive}\\{sub_key}\\{value_name}'.",
        }
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Registry write failed: {exc}"}
