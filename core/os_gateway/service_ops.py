"""
Universal OS Operations — Windows Service Controller
Provides inspection and lifecycle control for Windows services:
- List, inspect, start, stop, restart services
- Check service status and startup configuration
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ServiceList(list):
    """List subclass that also supports dict-like access for compatibility."""
    def __init__(self, services_list: list):
        super().__init__(services_list)
        self.success = True
        self.status = "listed"
        self.services = services_list
        self.count = len(services_list)
        self.message = f"Found {len(services_list)} services."

    def get(self, key: str, default: Any = None) -> Any:
        if key == "services":
            return list(self)
        if key == "success":
            return True
        if key == "status":
            return "listed"
        if key == "count":
            return len(self)
        if key == "message":
            return self.message
        return default

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, str):
            val = self.get(item)
            if val is not None:
                return val
            raise KeyError(item)
        return super().__getitem__(item)


def list_services(name_filter: Optional[str] = None, limit: int = 40) -> Any:
    """List Windows services with status."""
    services = []
    norm_filter = name_filter.lower().strip() if name_filter else None

    # Use PowerShell Get-Service for rich metadata
    ps_cmd = "Get-Service | Select-Object -Property Name, DisplayName, Status, StartType | ConvertTo-Json -Compress"
    try:
        res = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if res.returncode == 0 and res.stdout.strip():
            import json
            data = json.loads(res.stdout)
            items = data if isinstance(data, list) else [data]
            for it in items:
                s_name = it.get("Name", "")
                d_name = it.get("DisplayName", "")
                if norm_filter and norm_filter not in s_name.lower() and norm_filter not in d_name.lower():
                    continue

                status_code = it.get("Status", 1)
                status_str = "Running" if status_code == 4 else ("Stopped" if status_code == 1 else str(status_code))

                services.append({
                    "name": s_name,
                    "display_name": d_name,
                    "status": status_str,
                    "start_type": str(it.get("StartType", "")),
                })
                if len(services) >= limit:
                    break

            return ServiceList(services)
    except Exception as exc:
        logger.debug("[SERVICE_OPS] PowerShell service query failed: %s", exc)

    # sc.exe fallback
    try:
        out = subprocess.check_output("sc.exe query state= all", shell=True, text=True, timeout=5)
        for block in out.split("SERVICE_NAME:"):
            lines = block.strip().splitlines()
            if lines:
                name = lines[0].strip()
                if norm_filter and norm_filter not in name.lower():
                    continue
                services.append({"name": name, "status": "unknown"})
                if len(services) >= limit:
                    break
        return ServiceList(services)
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Failed to list services: {exc}"}


def inspect_service(service_name: str) -> Dict[str, Any]:
    """Inspect detailed status and configuration of a Windows service."""
    clean_name = service_name.strip()
    ps_cmd = f"Get-Service -Name '{clean_name}' -ErrorAction SilentlyContinue | Select-Object -Property Name, DisplayName, Status, StartType, ServiceType | ConvertTo-Json -Compress"

    try:
        res = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if res.returncode == 0 and res.stdout.strip():
            import json
            data = json.loads(res.stdout)
            status_code = data.get("Status", 1)
            status_str = "Running" if status_code == 4 else ("Stopped" if status_code == 1 else str(status_code))

            return {
                "success": True,
                "status": "inspected",
                "name": data.get("Name"),
                "display_name": data.get("DisplayName"),
                "service_status": status_str,
                "is_running": (status_str == "Running"),
                "start_type": str(data.get("StartType")),
                "message": f"Service '{data.get('DisplayName', clean_name)}' is currently {status_str}.",
            }
        else:
            return {"success": False, "status": "not_found", "message": f"Service '{clean_name}' was not found."}
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Failed to inspect service: {exc}"}


def start_service(service_name: str) -> Dict[str, Any]:
    """Start a Windows service."""
    clean_name = service_name.strip()
    try:
        res = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", f"Start-Service -Name '{clean_name}' -PassThru | Select-Object -Property Name, Status | ConvertTo-Json -Compress"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if res.returncode == 0:
            return {
                "success": True,
                "status": "started",
                "service_name": clean_name,
                "message": f"Started service '{clean_name}'.",
            }
        else:
            err = res.stderr.strip() or "Permission denied or service cannot be started."
            return {"success": False, "status": "error", "error": err, "message": f"Could not start service '{clean_name}': {err}"}
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Failed to start service: {exc}"}


def stop_service(service_name: str) -> Dict[str, Any]:
    """Stop a Windows service."""
    clean_name = service_name.strip()
    try:
        res = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", f"Stop-Service -Name '{clean_name}' -Force -PassThru | Select-Object -Property Name, Status | ConvertTo-Json -Compress"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if res.returncode == 0:
            return {
                "success": True,
                "status": "stopped",
                "service_name": clean_name,
                "message": f"Stopped service '{clean_name}'.",
            }
        else:
            err = res.stderr.strip() or "Permission denied or service cannot be stopped."
            return {"success": False, "status": "error", "error": err, "message": f"Could not stop service '{clean_name}': {err}"}
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Failed to stop service: {exc}"}


def restart_service(service_name: str) -> Dict[str, Any]:
    """Restart a Windows service."""
    stop_res = stop_service(service_name)
    time.sleep(1.0)
    start_res = start_service(service_name)
    return {
        "success": start_res.get("success", False),
        "status": "restarted" if start_res.get("success") else "failed",
        "service_name": service_name,
        "message": f"Restarted service '{service_name}'." if start_res.get("success") else f"Failed to restart service '{service_name}'.",
    }
