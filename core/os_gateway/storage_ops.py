"""
Universal OS Operations — Storage and Drive Operations
Inspects all accessible drives and partitions:
- Drive letter, volume label, filesystem, total capacity, free space, used space
- Drive type (Fixed, Removable, Network, CD-ROM)
- "How much space is left on D?"
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from typing import Any, Dict, List, Optional

import psutil

logger = logging.getLogger(__name__)


def list_accessible_drives() -> List[Dict[str, Any]]:
    """List all accessible drives and partitions with metrics."""
    drives = []

    try:
        partitions = psutil.disk_partitions(all=False)
        for part in partitions:
            drive_letter = part.device.rstrip("\\/")
            mount_point = part.mountpoint
            fstype = part.fstype
            opts = part.opts

            usage_info: Dict[str, Any] = {}
            try:
                u = psutil.disk_usage(mount_point)
                usage_info = {
                    "total_gb": round(u.total / (1024 ** 3), 2),
                    "free_gb": round(u.free / (1024 ** 3), 2),
                    "used_gb": round(u.used / (1024 ** 3), 2),
                    "percent_used": u.percent,
                }
            except Exception:
                usage_info = {"total_gb": 0, "free_gb": 0, "used_gb": 0, "percent_used": 0}

            # Windows volume label and drive type inspection via Win32
            vol_label = ""
            drive_type_str = "Fixed"
            if sys.platform == "win32":
                try:
                    vol_buf = ctypes.create_unicode_buffer(256)
                    fs_buf = ctypes.create_unicode_buffer(256)
                    path_to_inspect = f"{drive_letter}\\" if not drive_letter.endswith("\\") else drive_letter
                    ctypes.windll.kernel32.GetVolumeInformationW(
                        path_to_inspect, vol_buf, 256, None, None, None, fs_buf, 256
                    )
                    vol_label = vol_buf.value
                    if not fstype:
                        fstype = fs_buf.value

                    dtype = ctypes.windll.kernel32.GetDriveTypeW(path_to_inspect)
                    type_map = {
                        2: "Removable (USB)",
                        3: "Fixed Disk",
                        4: "Network Drive",
                        5: "CD-ROM",
                        6: "RAM Disk",
                    }
                    drive_type_str = type_map.get(dtype, "Unknown")
                except Exception:
                    pass

            drives.append({
                "drive": drive_letter,
                "drive_letter": drive_letter,
                "volume_label": vol_label,
                "mount_point": mount_point,
                "filesystem": fstype,
                "drive_type": drive_type_str,
                "is_removable": "removable" in drive_type_str.lower(),
                **usage_info,
            })
    except Exception as exc:
        logger.error(f"[STORAGE_OPS] Error listing drives: {exc}")

    return drives


def inspect_drive(drive_name_or_letter: str) -> Dict[str, Any]:
    """Inspect capacity and free space on a specific drive."""
    clean = drive_name_or_letter.strip().upper().rstrip(":\\/")
    target_letter = f"{clean}:" if len(clean) == 1 else clean

    all_drives = list_accessible_drives()
    for d in all_drives:
        if d.get("drive_letter") == target_letter or d.get("mount_point", "").startswith(target_letter):
            free_gb = d.get("free_gb", 0)
            total_gb = d.get("total_gb", 0)
            pct = d.get("percent_used", 0)
            msg = f"Drive {target_letter} has {free_gb} GB free out of {total_gb} GB ({pct}% used)."
            return {
                "success": True,
                "status": "inspected",
                "drive": target_letter,
                "free_gb": free_gb,
                "total_gb": total_gb,
                "percent_used": pct,
                "drive_info": d,
                "message": msg,
            }

    # If drive not in partitions, check direct path
    path_cand = f"{target_letter}\\"
    try:
        u = psutil.disk_usage(path_cand)
        free_gb = round(u.free / (1024 ** 3), 2)
        total_gb = round(u.total / (1024 ** 3), 2)
        pct = u.percent
        return {
            "success": True,
            "status": "inspected",
            "drive": target_letter,
            "free_gb": free_gb,
            "total_gb": total_gb,
            "percent_used": pct,
            "message": f"Drive {target_letter} has {free_gb} GB free out of {total_gb} GB ({pct}% used).",
        }
    except Exception as exc:
        return {
            "success": False,
            "status": "not_found",
            "drive": target_letter,
            "message": f"Could not inspect drive {target_letter}: {exc}",
        }
