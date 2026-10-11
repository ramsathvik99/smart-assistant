"""
Smart Assistant — Universal Computer Access Layer
The single authoritative gateway for Windows computer & OS inspection and operation.

Exposes unified, structured capabilities for:
- Operating system (sysinfo, CPU, RAM, GPU, drives, env, PATH, registry, network)
- Filesystem (broad access across all drives, metadata, search, read, write, archive)
- Processes (enumerate, inspect, start, terminate)
- Applications (enumerate installed, launch, close, activate, UI control interaction)
- Windows (enumerate, active, focus, minimize, maximize, restore, resize, close)
- Terminal / Shell (PowerShell, cmd, Python, with full stdout/stderr/exit code capture)
- Browsers (CDP, UI Automation, tab/URL/title/video tracking for Chrome, Edge, Brave, Firefox)
- Universal UI Observation (deep application context for VS Code, Notepad, Explorer, etc.)
- Unified ComputerState capture & synchronization
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from ctypes import wintypes
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import psutil

from core.environment.models import ComputerState, EnvironmentState, StateTransition
from core.environment.state_engine import get_state_engine
from core.environment.ui_tree import (
    _get_uia,
    try_get_browser_cdp_info,
    try_get_browser_url,
    try_get_calculator_value,
    try_get_vscode_status_bar,
    try_resolve_git_branch,
    try_resolve_vscode_workspace,
)

logger = logging.getLogger(__name__)

# Win32 user32 / kernel32 initialization
user32 = ctypes.windll.user32 if sys.platform == "win32" else None
kernel32 = ctypes.windll.kernel32 if sys.platform == "win32" else None


class UniversalComputerAccess:
    """
    The central, authoritative Windows operating system operator.
    Provides deep observation, interaction, process control, filesystem management,
    window control, and shell execution without restrictive sandboxing.
    """

    _instance: Optional[UniversalComputerAccess] = None
    _lock = threading.Lock()

    def __new__(cls) -> UniversalComputerAccess:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.state_engine = get_state_engine()
        self._startup_discovery: Dict[str, Any] = {}
        self.discover_runtime_capabilities()
        logger.info("[UNIVERSAL_COMPUTER_ACCESS] Initialized authoritative computer access layer.")

    # =========================================================================
    # 1. RUNTIME CAPABILITY DISCOVERY
    # =========================================================================

    def discover_runtime_capabilities(self) -> Dict[str, Any]:
        """
        Discovers installed applications, browsers, drives, shells, and Windows capabilities.
        Exposed at startup and queryable by planners.
        """
        installed_browsers = self.detect_available_browsers()
        drives = self.get_drives_and_storage()
        shells = self.detect_available_shells()
        has_uia = _get_uia() is not None

        caps = {
            "os": f"{platform.system()} {platform.release()} (Build {platform.version()})",
            "hostname": platform.node(),
            "cpu_count": psutil.cpu_count(logical=True),
            "ram_total_gb": round(psutil.virtual_memory().total / (1024 ** 3), 2),
            "accessible_drives": [d["drive"] for d in drives],
            "available_browsers": installed_browsers,
            "available_shells": shells,
            "ui_automation_available": has_uia,
            "windows_api_available": sys.platform == "win32" and user32 is not None,
            "admin_privileges": self.is_admin(),
        }
        self._startup_discovery = caps
        return caps

    def is_admin(self) -> bool:
        """Check if current process has elevated administrator privileges."""
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False

    def detect_available_shells(self) -> List[str]:
        """Detect installed CLI and shell environments."""
        shells = ["cmd"]
        if shutil.which("powershell") or shutil.which("pwsh"):
            shells.append("powershell")
        if shutil.which("pwsh"):
            shells.append("pwsh")
        if shutil.which("bash") or shutil.which("wsl"):
            shells.append("wsl")
        if shutil.which("python") or shutil.which("py"):
            shells.append("python")
        return shells

    # =========================================================================
    # 2. OPERATING SYSTEM & HARDWARE INSPECTION
    # =========================================================================

    def get_system_info(self) -> Dict[str, Any]:
        """Inspect OS, architecture, CPU, RAM, GPU, and system uptime."""
        vm = psutil.virtual_memory()
        cpu_freq = psutil.cpu_freq()
        boot_time = psutil.boot_time()
        uptime_seconds = time.time() - boot_time

        gpus = self._get_gpu_info()

        return {
            "status": "success",
            "hostname": platform.node(),
            "os_name": platform.system(),
            "os_release": platform.release(),
            "os_version": platform.version(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "cpu_physical_cores": psutil.cpu_count(logical=False),
            "cpu_logical_cores": psutil.cpu_count(logical=True),
            "cpu_usage_percent": psutil.cpu_percent(interval=0.1),
            "cpu_freq_mhz": round(cpu_freq.current, 1) if cpu_freq else None,
            "ram_total_gb": round(vm.total / (1024 ** 3), 2),
            "ram_used_gb": round(vm.used / (1024 ** 3), 2),
            "ram_free_gb": round(vm.available / (1024 ** 3), 2),
            "ram_usage_percent": vm.percent,
            "gpus": gpus,
            "uptime_hours": round(uptime_seconds / 3600, 1),
            "is_admin": self.is_admin(),
        }

    def _get_gpu_info(self) -> List[Dict[str, Any]]:
        """Extract GPU details via WMI / PowerShell if accessible."""
        gpus = []
        if sys.platform != "win32":
            return gpus
        try:
            cmd = "Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM, DriverVersion | ConvertTo-Json"
            res = self.execute_shell_command(cmd, shell="powershell", timeout=5)
            if res["status"] == "success" and res["stdout"].strip():
                data = json.loads(res["stdout"])
                items = data if isinstance(data, list) else [data]
                for item in items:
                    name = item.get("Name")
                    if name:
                        vram = item.get("AdapterRAM")
                        vram_gb = round(vram / (1024 ** 3), 1) if vram else None
                        gpus.append({
                            "name": name,
                            "vram_gb": vram_gb,
                            "driver_version": item.get("DriverVersion"),
                        })
        except Exception as e:
            logger.debug(f"[UCA] GPU detection: {e}")
        return gpus

    def get_drives_and_storage(self) -> List[Dict[str, Any]]:
        """List all accessible drives, partitions, and storage usage."""
        drives = []
        try:
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    drives.append({
                        "drive": part.mountpoint,
                        "device": part.device,
                        "fstype": part.fstype,
                        "opts": part.opts,
                        "total_gb": round(usage.total / (1024 ** 3), 2),
                        "used_gb": round(usage.used / (1024 ** 3), 2),
                        "free_gb": round(usage.free / (1024 ** 3), 2),
                        "percent_used": usage.percent,
                    })
                except (PermissionError, OSError):
                    drives.append({
                        "drive": part.mountpoint,
                        "device": part.device,
                        "fstype": part.fstype,
                        "error": "Access denied or drive not ready",
                    })
        except Exception as e:
            logger.warning(f"[UCA] Drive enumeration error: {e}")
        return drives

    def get_environment_variables(self) -> Dict[str, str]:
        """Return all user and system environment variables."""
        return dict(os.environ)

    def get_path_entries(self) -> List[str]:
        """Return all individual directory entries in the system PATH."""
        path_str = os.environ.get("PATH", "")
        return [p for p in path_str.split(os.pathsep) if p.strip()]

    def read_registry(self, root: str, subkey: str, value_name: str) -> Dict[str, Any]:
        """Read a Windows registry key value."""
        if sys.platform != "win32":
            return {"status": "error", "error": "Registry access only supported on Windows"}
        import winreg
        root_map = {
            "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
            "HKCU": winreg.HKEY_CURRENT_USER,
            "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
            "HKLM": winreg.HKEY_LOCAL_MACHINE,
            "HKEY_CLASSES_ROOT": winreg.HKEY_CLASSES_ROOT,
        }
        hkey = root_map.get(root.upper())
        if not hkey:
            return {"status": "error", "error": f"Invalid registry root '{root}'"}

        try:
            with winreg.OpenKey(hkey, subkey, 0, winreg.KEY_READ) as key:
                val, val_type = winreg.QueryValueEx(key, value_name)
                return {"status": "success", "value": val, "type": val_type}
        except FileNotFoundError:
            return {"status": "error", "error": f"Key or value '{value_name}' not found"}
        except PermissionError:
            from core.permission_manager import get_permission_elevation_manager
            pm = get_permission_elevation_manager()
            return {
                "status": "requires_elevation",
                "requires_elevation": True,
                "error": "Permission denied reading registry. Administrator privileges required.",
                "prompt": pm.format_elevation_prompt("read registry key", f"{root}\\{subkey}\\{value_name}"),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def check_permission(self, operation: str, target: str = "") -> Any:
        """Check whether an operation can execute with current privileges or requires elevation."""
        from core.permission_manager import get_permission_elevation_manager
        pm = get_permission_elevation_manager()
        return pm.check_permission(operation=operation, target=target)

    def write_registry(
        self,
        root: str,
        subkey: str,
        value_name: str,
        value_data: Any,
        value_type: str = "REG_SZ",
        confirmed: bool = False
    ) -> Dict[str, Any]:
        """Write a Windows registry key value via UniversalOSGateway."""
        if not confirmed:
            return {
                "status": "confirmation_required",
                "warning": f"Writing to registry key '{root}\\{subkey}\\{value_name}' requires explicit confirmation.",
                "target": f"{root}\\{subkey}\\{value_name}",
            }
        from core.os_gateway import get_os_gateway, OSOperation, OSOperationType, OSCapability
        gw = get_os_gateway()
        op = OSOperation(
            operation_type=OSOperationType.WRITE_REGISTRY,
            capability=OSCapability.REGISTRY,
            target=subkey,
            parameters={"hive": root, "sub_key": subkey, "value_name": value_name, "value_data": value_data, "value_type": value_type},
            requires_confirmation=not confirmed,
        )
        res = gw.execute(op, confirmed_by_user=confirmed)
        return {"status": "success" if res.success else "error", "message": res.output if isinstance(res.output, str) else ("Registry updated." if res.success else res.error), "error": res.error}

    def enumerate_registry_keys(self, root: str, subkey: str) -> List[str]:
        """Enumerate subkeys under a registry key."""
        if sys.platform != "win32":
            return []
        import winreg
        root_map = {
            "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
            "HKCU": winreg.HKEY_CURRENT_USER,
            "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
            "HKLM": winreg.HKEY_LOCAL_MACHINE,
            "HKEY_CLASSES_ROOT": winreg.HKEY_CLASSES_ROOT,
        }
        hkey = root_map.get(root.upper())
        if not hkey:
            return []
        subkeys = []
        try:
            with winreg.OpenKey(hkey, subkey, 0, winreg.KEY_READ) as key:
                num_subkeys = winreg.QueryInfoKey(key)[0]
                for i in range(num_subkeys):
                    try:
                        subkeys.append(winreg.EnumKey(key, i))
                    except Exception:
                        pass
        except Exception:
            pass
        return subkeys

    # =========================================================================
    # 2b. WINDOWS SERVICES MANAGEMENT
    # =========================================================================

    def enumerate_services(self, name_filter: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Enumerate Windows services with current status and startup type."""
        try:
            from core.os_gateway.service_ops import list_services
            res = list_services(name_filter=name_filter, limit=limit)
            return list(res) if hasattr(res, "__iter__") else []
        except Exception as e:
            logger.debug(f"[UCA] Enumerate services failed: {e}")
            return []

    def inspect_service(self, service_name: str) -> Dict[str, Any]:
        """Inspect status, startup type, and configuration of a specific Windows service."""
        try:
            from core.os_gateway.service_ops import inspect_service
            return inspect_service(service_name)
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def start_service(self, service_name: str, confirmed: bool = False) -> Dict[str, Any]:
        """Start a Windows service via UniversalOSGateway."""
        if not confirmed:
            return {
                "status": "confirmation_required",
                "warning": f"Starting service '{service_name}' requires explicit confirmation.",
                "target": service_name,
            }
        from core.os_gateway import get_os_gateway, OSOperation, OSOperationType, OSCapability
        gw = get_os_gateway()
        op = OSOperation(
            operation_type=OSOperationType.START_SERVICE,
            capability=OSCapability.SERVICE,
            target=service_name,
            requires_confirmation=not confirmed,
        )
        res = gw.execute(op, confirmed_by_user=confirmed)
        return {"status": "success" if res.success else "error", "message": res.output if isinstance(res.output, str) else ("Service started." if res.success else res.error), "error": res.error}

    def stop_service(self, service_name: str, confirmed: bool = False) -> Dict[str, Any]:
        """Stop a Windows service via UniversalOSGateway."""
        if not confirmed:
            return {
                "status": "confirmation_required",
                "warning": f"Stopping service '{service_name}' requires explicit confirmation.",
                "target": service_name,
            }
        from core.os_gateway import get_os_gateway, OSOperation, OSOperationType, OSCapability
        gw = get_os_gateway()
        op = OSOperation(
            operation_type=OSOperationType.STOP_SERVICE,
            capability=OSCapability.SERVICE,
            target=service_name,
            requires_confirmation=not confirmed,
        )
        res = gw.execute(op, confirmed_by_user=confirmed)
        return {"status": "success" if res.success else "error", "message": res.output if isinstance(res.output, str) else ("Service stopped." if res.success else res.error), "error": res.error}

    def restart_service(self, service_name: str, confirmed: bool = False) -> Dict[str, Any]:
        """Restart a Windows service via UniversalOSGateway."""
        if not confirmed:
            return {
                "status": "confirmation_required",
                "warning": f"Restarting service '{service_name}' requires explicit confirmation.",
                "target": service_name,
            }
        from core.os_gateway import get_os_gateway, OSOperation, OSOperationType, OSCapability
        gw = get_os_gateway()
        op = OSOperation(
            operation_type=OSOperationType.RESTART_SERVICE,
            capability=OSCapability.SERVICE,
            target=service_name,
            requires_confirmation=not confirmed,
        )
        res = gw.execute(op, confirmed_by_user=confirmed)
        return {"status": "success" if res.success else "error", "message": res.output if isinstance(res.output, str) else ("Service restarted." if res.success else res.error), "error": res.error}

    # =========================================================================
    # 2c. FIREWALL & HARDWARE DEVICE MANAGEMENT
    # =========================================================================

    def inspect_firewall_rules(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Inspect active Windows Firewall rules via PowerShell."""
        if sys.platform != "win32":
            return []
        try:
            ps_cmd = f"Get-NetFirewallRule -Enabled True | Select-Object -First {limit} -Property Name, DisplayName, Direction, Action | ConvertTo-Json -Compress"
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
                return data if isinstance(data, list) else [data]
        except Exception as e:
            logger.debug(f"[UCA] Firewall inspection failed: {e}")
        return []

    def enumerate_devices(self) -> Dict[str, Any]:
        """Enumerate system hardware devices, displays, audio, printers, and storage."""
        devices: Dict[str, Any] = {"status": "success", "displays": [], "printers": [], "storage_drives": []}
        # Displays
        try:
            import win32api
            monitors = win32api.EnumDisplayMonitors()
            for hmon, hdc, rect in monitors:
                info = win32api.GetMonitorInfo(hmon)
                devices["displays"].append({
                    "device": info.get("Device"),
                    "is_primary": bool(info.get("Flags", 0) & 1),
                    "rect": {"left": rect[0], "top": rect[1], "right": rect[2], "bottom": rect[3]},
                })
        except Exception:
            pass

        # Printers
        try:
            import win32print
            printers = win32print.EnumPrinters(2)
            for p in printers:
                devices["printers"].append({"name": p[2], "port": p[1], "driver": p[3]})
        except Exception:
            pass

        devices["storage_drives"] = self.get_drives_and_storage()
        return devices

    def get_network_info(self) -> Dict[str, Any]:
        """Inspect network adapters, IP addresses, DNS, and test internet connectivity."""

        adapters = []
        for name, addrs in psutil.net_if_addrs().items():
            ad_info = {"name": name, "ipv4": [], "ipv6": [], "mac": None}
            for a in addrs:
                if a.family == 2:  # AF_INET
                    ad_info["ipv4"].append(a.address)
                elif a.family == 23:  # AF_INET6
                    ad_info["ipv6"].append(a.address)
                elif a.family == -1 or hasattr(psutil, "AF_LINK") and a.family == psutil.AF_LINK:
                    ad_info["mac"] = a.address
            adapters.append(ad_info)

        # Quick connectivity ping test
        connected = False
        try:
            import socket
            with socket.create_connection(("1.1.1.1", 53), timeout=1.5):
                connected = True
        except Exception:
            connected = False

        return {
            "status": "success",
            "connected": connected,
            "connected_to_internet": connected,
            "adapters": adapters,
        }

    # =========================================================================
    # 3. FULL FILESYSTEM OPERATIONS (NO PROJECT SANDBOX RESTRICTIONS)
    # =========================================================================

    def list_directory(self, folder_path: str) -> Dict[str, Any]:
        """List contents of any accessible directory on any drive."""
        path = os.path.abspath(os.path.expanduser(os.path.expandvars(folder_path)))
        if not os.path.exists(path):
            return {"status": "error", "error": f"Path '{path}' does not exist."}
        if not os.path.isdir(path):
            return {"status": "error", "error": f"Path '{path}' is a file, not a directory."}

        try:
            entries = []
            for entry in os.scandir(path):
                try:
                    st = entry.stat()
                    entries.append({
                        "name": entry.name,
                        "path": entry.path,
                        "is_dir": entry.is_dir(),
                        "is_file": entry.is_file(),
                        "size_bytes": st.st_size if entry.is_file() else 0,
                        "modified_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
                    })
                except (PermissionError, OSError):
                    entries.append({"name": entry.name, "path": entry.path, "error": "Access denied"})
            return {"status": "success", "path": path, "entries": entries, "count": len(entries)}
        except PermissionError:
            return {"status": "error", "error": f"Windows denied access to '{path}'. Administrator privileges or elevated permissions may be required."}
        except Exception as e:
            return {"status": "error", "error": f"Failed to list directory: {e}"}

    def read_file(self, file_path: str, max_bytes: int = 100000) -> Dict[str, Any]:
        """Read content from any accessible file."""
        path = os.path.abspath(os.path.expanduser(os.path.expandvars(file_path)))
        if not os.path.exists(path):
            return {"status": "error", "error": f"File '{path}' does not exist."}
        if os.path.isdir(path):
            return {"status": "error", "error": f"'{path}' is a directory, not a file."}

        try:
            size = os.path.getsize(path)
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(max_bytes)
            truncated = size > max_bytes
            return {
                "status": "success",
                "path": path,
                "size_bytes": size,
                "content": content,
                "truncated": truncated,
            }
        except PermissionError:
            return {"status": "error", "error": f"Windows denied access to read '{path}'. The file may be in use or require elevated permissions."}
        except Exception as e:
            return {"status": "error", "error": f"Failed to read file: {e}"}

    def write_file(self, file_path: str, content: str, append: bool = False) -> Dict[str, Any]:
        """Write content to any accessible file location via UniversalOSGateway."""
        from core.os_gateway import get_os_gateway, OSOperation, OSOperationType, OSCapability
        gw = get_os_gateway()
        op = OSOperation(
            operation_type=OSOperationType.WRITE_FILE,
            capability=OSCapability.FILESYSTEM,
            target=file_path,
            parameters={"content": content, "mode": "a" if append else "w"},
        )
        res = gw.execute(op)
        return {
            "status": "success" if res.success else "error",
            "path": file_path,
            "bytes_written": len(content) if res.success else 0,
            "error": res.error,
        }

    def create_file(self, file_path: str, content: str = "") -> Dict[str, Any]:
        """Create a new file via UniversalOSGateway."""
        from core.os_gateway import get_os_gateway, OSOperation, OSOperationType, OSCapability
        gw = get_os_gateway()
        op = OSOperation(
            operation_type=OSOperationType.CREATE_FILE,
            capability=OSCapability.FILESYSTEM,
            target=file_path,
            parameters={"content": content},
        )
        res = gw.execute(op)
        return {
            "status": "success" if res.success else "error",
            "path": file_path,
            "bytes_written": len(content) if res.success else 0,
            "error": res.error,
        }

    def rename_file(self, file_path: str, new_name_or_path: str) -> Dict[str, Any]:
        """Rename or move a file via UniversalOSGateway."""
        from core.os_gateway import get_os_gateway, OSOperation, OSOperationType, OSCapability
        gw = get_os_gateway()
        op = OSOperation(
            operation_type=OSOperationType.RENAME_FILE,
            capability=OSCapability.FILESYSTEM,
            target=file_path,
            parameters={"new_name": new_name_or_path},
        )
        res = gw.execute(op)
        return {
            "status": "success" if res.success else "error",
            "source": file_path,
            "destination": new_name_or_path,
            "error": res.error,
        }

    def copy_file(self, source: str, destination: str) -> Dict[str, Any]:
        """Copy a file or directory via UniversalOSGateway."""
        from core.os_gateway import get_os_gateway, OSOperation, OSOperationType, OSCapability
        gw = get_os_gateway()
        op = OSOperation(
            operation_type=OSOperationType.COPY_FILE,
            capability=OSCapability.FILESYSTEM,
            target=source,
            parameters={"destination": destination},
        )
        res = gw.execute(op)
        return {
            "status": "success" if res.success else "error",
            "source": source,
            "destination": destination,
            "error": res.error,
        }

    def delete_file(self, target_path: str, confirmed: bool = False) -> Dict[str, Any]:
        """Delete a file or directory via UniversalOSGateway with mandatory confirmation protection."""
        if not confirmed:
            return {
                "status": "confirmation_required",
                "message": f"Destructive operation: Are you sure you want to delete '{target_path}'?",
                "target": target_path,
                "requires_confirmation": True,
            }
        from core.os_gateway import get_os_gateway, OSOperation, OSOperationType, OSCapability
        gw = get_os_gateway()
        op = OSOperation(
            operation_type=OSOperationType.DELETE_FILE,
            capability=OSCapability.FILESYSTEM,
            target=target_path,
            requires_confirmation=not confirmed,
        )
        res = gw.execute(op, confirmed_by_user=confirmed)
        return {
            "status": "success" if res.success else "error",
            "deleted": target_path if res.success else None,
            "error": res.error,
        }

    def search_files(self, pattern: str, root_dir: str = "", max_results: int = 50) -> Dict[str, Any]:
        """Search for files matching pattern across any directory or drive."""
        if os.path.isdir(pattern) and not os.path.isdir(root_dir):
            pattern, root_dir = root_dir, pattern
        root = os.path.abspath(os.path.expanduser(os.path.expandvars(root_dir))) if root_dir else os.getcwd()
        if not os.path.exists(root):
            return {"status": "error", "error": f"Root directory '{root}' does not exist."}

        matches = []
        try:
            regex = re.compile(pattern.replace("*", ".*").replace("?", "."), re.IGNORECASE)
            for dirpath, _, filenames in os.walk(root):
                for f in filenames:
                    if regex.search(f):
                        full = os.path.join(dirpath, f)
                        matches.append({"name": f, "path": full})
                        if len(matches) >= max_results:
                            break
                if len(matches) >= max_results:
                    break
            return {"status": "success", "root": root, "pattern": pattern, "results": matches, "matches": matches, "count": len(matches)}
        except Exception as e:
            return {"status": "error", "error": f"Search failed: {e}"}

    def get_file_metadata(self, file_path: str) -> Dict[str, Any]:
        """Get full filesystem metadata for a file or folder."""
        path = os.path.abspath(os.path.expanduser(os.path.expandvars(file_path)))
        if not os.path.exists(path):
            return {"status": "error", "error": f"Path '{path}' does not exist."}
        try:
            st = os.stat(path)
            return {
                "status": "success",
                "path": path,
                "name": os.path.basename(path),
                "is_dir": os.path.isdir(path),
                "is_file": os.path.isfile(path),
                "size_bytes": st.st_size,
                "size_formatted": f"{round(st.st_size / 1024, 1)} KB" if st.st_size < 1048576 else f"{round(st.st_size / 1048576, 2)} MB",
                "created_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_ctime)),
                "modified_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
                "accessed_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_atime)),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def move_file(self, source: str, destination: str) -> Dict[str, Any]:
        """Move a file or folder from source to destination."""
        src = os.path.abspath(os.path.expanduser(os.path.expandvars(source)))
        dest = os.path.abspath(os.path.expanduser(os.path.expandvars(destination)))
        if not os.path.exists(src):
            return {"status": "error", "error": f"Source '{src}' does not exist."}
        from core.os_gateway import get_os_gateway, OSOperation, OSOperationType, OSCapability
        gw = get_os_gateway()
        op = OSOperation(
            operation_type=OSOperationType.MOVE_FILE,
            capability=OSCapability.FILESYSTEM,
            target=src,
            parameters={"destination": dest},
        )
        res = gw.execute(op)
        return {
            "status": "success" if res.success else "error",
            "source": src,
            "destination": dest,
            "error": res.error,
        }

    def open_file(self, file_path: str) -> Dict[str, Any]:
        """Open a file or directory via UniversalOSGateway."""
        path = os.path.abspath(os.path.expanduser(os.path.expandvars(file_path)))
        if not os.path.exists(path):
            return {"status": "error", "error": f"Path '{path}' does not exist."}
        from core.os_gateway import get_os_gateway, OSOperation, OSOperationType, OSCapability
        gw = get_os_gateway()
        op = OSOperation(
            operation_type=OSOperationType.OPEN_FILE,
            capability=OSCapability.FILESYSTEM,
            target=path,
        )
        res = gw.execute(op)
        return {
            "status": "success" if res.success else "error",
            "message": f"Opened '{path}'." if res.success else (res.error or "Could not open file."),
            "path": path,
            "error": res.error,
        }

    def archive_files(self, sources: List[str], archive_path: str, format: str = "zip") -> Dict[str, Any]:
        """Archive one or more files/directories into a zip file via UniversalOSGateway."""
        out_zip = os.path.abspath(os.path.expanduser(os.path.expandvars(archive_path)))
        if not out_zip.lower().endswith(".zip"):
            out_zip += ".zip"
        from core.os_gateway import get_os_gateway, OSOperation, OSOperationType, OSCapability
        gw = get_os_gateway()
        op = OSOperation(
            operation_type=OSOperationType.ARCHIVE_FILES,
            capability=OSCapability.FILESYSTEM,
            target=out_zip,
            parameters={"sources": sources, "archive_path": out_zip, "format": format},
        )
        res = gw.execute(op)
        return {
            "status": "success" if res.success else "error",
            "archive_path": out_zip,
            "file_count": len(sources),
            "error": res.error,
        }

    def extract_archive(self, archive_path: str, extract_dir: str) -> Dict[str, Any]:
        """Extract a zip archive into a destination directory via UniversalOSGateway."""
        arc = os.path.abspath(os.path.expanduser(os.path.expandvars(archive_path)))
        dest = os.path.abspath(os.path.expanduser(os.path.expandvars(extract_dir)))
        from core.os_gateway import get_os_gateway, OSOperation, OSOperationType, OSCapability
        gw = get_os_gateway()
        op = OSOperation(
            operation_type=OSOperationType.EXTRACT_ARCHIVE,
            capability=OSCapability.FILESYSTEM,
            target=arc,
            parameters={"extract_dir": dest, "destination": dest},
        )
        res = gw.execute(op)
        return {
            "status": "success" if res.success else "error",
            "archive": arc,
            "destination": dest,
            "error": res.error,
        }

    def execute_with_elevation_fallback(
        self,
        operation: str,
        target: str,
        func: Callable,
        *args,
        user_approved_elevation: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Executes an operation checking permissions first.
        If permission is denied or elevation is required, delegates privileged execution safely.
        """
        from core.permission_manager import get_permission_elevation_manager
        pm = get_permission_elevation_manager()
        check = pm.check_permission(operation=operation, target=target)

        if check.is_impossible:
            return {
                "status": "impossible",
                "error": pm.format_impossible_message(operation, target, check.reason),
                "is_impossible": True,
            }

        if check.requires_elevation and not user_approved_elevation:
            return {
                "status": "requires_elevation",
                "requires_elevation": True,
                "prompt": pm.format_elevation_prompt(operation, target),
                "reason": check.reason,
            }

        try:
            return func(*args, **kwargs)
        except PermissionError as pe:
            if pm.can_elevate():
                if user_approved_elevation:
                    elev_res = pm.request_uac_elevation(sys.executable, ["-c", f"# elevated execution for {operation}"])
                    if elev_res.get("status") == "success":
                        try:
                            return func(*args, **kwargs)
                        except Exception as e2:
                            return {"status": "error", "error": f"Elevated retry failed: {e2}"}
                    elif elev_res.get("status") == "declined":
                        return {"status": "declined", "error": pm.format_elevation_declined_message(operation)}
                    else:
                        return {"status": "error", "error": elev_res.get("error", "Elevation failed")}
                else:
                    return {
                        "status": "requires_elevation",
                        "requires_elevation": True,
                        "prompt": pm.format_elevation_prompt(operation, target),
                        "reason": str(pe),
                    }
            return {"status": "error", "error": f"Permission denied: {pe}"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}


    # =========================================================================
    # 4. PROCESS MANAGEMENT
    # =========================================================================

    def list_processes(self, limit: int = 50, sort_by: str = "cpu") -> List[Dict[str, Any]]:
        """Enumerate active processes with resource usage."""
        procs = []
        for p in psutil.process_iter(["pid", "name", "username", "cpu_percent", "memory_info", "status", "exe"]):
            try:
                info = p.info
                mem_mb = round(info["memory_info"].rss / (1024 * 1024), 1) if info.get("memory_info") else 0
                procs.append({
                    "pid": info["pid"],
                    "name": info["name"] or "Unknown",
                    "username": info.get("username") or "",
                    "cpu_percent": info.get("cpu_percent") or 0.0,
                    "memory_mb": mem_mb,
                    "status": info.get("status") or "",
                    "exe": info.get("exe") or "",
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if sort_by == "cpu":
            procs.sort(key=lambda x: x["cpu_percent"], reverse=True)
        elif sort_by == "memory":
            procs.sort(key=lambda x: x["memory_mb"], reverse=True)
        else:
            procs.sort(key=lambda x: x["name"].lower())

        return procs[:limit]

    def inspect_process(self, pid_or_name: Union[int, str]) -> Dict[str, Any]:
        """Inspect detailed information about a specific process."""
        proc = None
        if isinstance(pid_or_name, int) or (isinstance(pid_or_name, str) and pid_or_name.isdigit()):
            pid = int(pid_or_name)
            try:
                proc = psutil.Process(pid)
            except psutil.NoSuchProcess:
                return {"status": "error", "error": f"No process found with PID {pid}."}
        else:
            name_lower = str(pid_or_name).lower()
            for p in psutil.process_iter(["pid", "name"]):
                try:
                    if name_lower in (p.info["name"] or "").lower():
                        proc = p
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        if not proc:
            return {"status": "error", "error": f"Process '{pid_or_name}' not found."}

        try:
            with proc.oneshot():
                return {
                    "status": "success",
                    "pid": proc.pid,
                    "name": proc.name(),
                    "exe": proc.exe(),
                    "cmdline": " ".join(proc.cmdline()),
                    "process_status": proc.status(),
                    "cpu_percent": proc.cpu_percent(),
                    "memory_mb": round(proc.memory_info().rss / (1024 * 1024), 1),
                    "create_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(proc.create_time())),
                    "parent_pid": proc.ppid(),
                    "num_threads": proc.num_threads(),
                }
        except psutil.AccessDenied:
            return {"status": "error", "error": f"Permission denied inspecting PID {proc.pid}. Administrator privileges required."}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def start_process(self, executable: str, args: Optional[List[str]] = None, cwd: Optional[str] = None) -> Dict[str, Any]:
        """Start a new process via UniversalOSGateway."""
        from core.os_gateway import get_os_gateway, OSOperation, OSOperationType, OSCapability
        gw = get_os_gateway()
        op = OSOperation(
            operation_type=OSOperationType.START_PROCESS,
            capability=OSCapability.PROCESS,
            target=executable,
            parameters={"args": args, "cwd": cwd},
        )
        res = gw.execute(op)
        pid = res.output.get("pid") if isinstance(res.output, dict) else (res.output if isinstance(res.output, int) else None)
        return {
            "status": "success" if res.success else "error",
            "pid": pid,
            "executable": executable,
            "error": res.error,
        }

    def terminate_process(self, pid_or_name: Union[int, str], force: bool = False, confirmed: bool = False) -> Dict[str, Any]:
        """Terminate a process via UniversalOSGateway with safety confirmation gate."""
        if not confirmed:
            return {
                "status": "confirmation_required",
                "warning": f"Terminating process '{pid_or_name}' is a destructive action requiring explicit confirmation.",
                "target": str(pid_or_name),
                "force": force,
            }
        from core.os_gateway import get_os_gateway, OSOperation, OSOperationType, OSCapability
        gw = get_os_gateway()
        op = OSOperation(
            operation_type=OSOperationType.TERMINATE_PROCESS,
            capability=OSCapability.PROCESS,
            target=str(pid_or_name),
            parameters={"force": force},
            requires_confirmation=not confirmed,
        )
        res = gw.execute(op, confirmed_by_user=confirmed)
        return {
            "status": "success" if res.success else "error",
            "message": f"Terminated process '{pid_or_name}'." if res.success else (res.error or "Failed to terminate process."),
            "error": res.error,
        }

    # =========================================================================
    # 5. APPLICATION MANAGEMENT & UI INTERACTION
    # =========================================================================

    def enumerate_installed_applications(self) -> List[Dict[str, Any]]:
        """Enumerate installed software discoverable from Windows Registry and Start Menu."""
        apps = []
        if sys.platform != "win32":
            return apps
        import winreg
        reg_paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]

        seen_names = set()
        for hkey, subkey_path in reg_paths:
            try:
                with winreg.OpenKey(hkey, subkey_path) as root_key:
                    num_subkeys = winreg.QueryInfoKey(root_key)[0]
                    for i in range(num_subkeys):
                        try:
                            sub_name = winreg.EnumKey(root_key, i)
                            with winreg.OpenKey(root_key, sub_name) as app_key:
                                try:
                                    display_name = winreg.QueryValueEx(app_key, "DisplayName")[0]
                                    if display_name and display_name not in seen_names:
                                        seen_names.add(display_name)
                                        loc = ""
                                        try:
                                            loc = winreg.QueryValueEx(app_key, "InstallLocation")[0]
                                        except Exception:
                                            pass
                                        apps.append({"name": display_name, "install_location": loc})
                                except FileNotFoundError:
                                    pass
                        except Exception:
                            continue
            except Exception:
                continue

        apps.sort(key=lambda x: x["name"].lower())
        return apps

    def launch_application(self, app_name_or_path: str, args: Optional[List[str]] = None) -> Dict[str, Any]:
        """Launch an application via UniversalOSGateway."""
        from core.os_gateway import get_os_gateway, OSOperation, OSOperationType, OSCapability
        gw = get_os_gateway()
        op = OSOperation(
            operation_type=OSOperationType.OPEN_APPLICATION,
            capability=OSCapability.APPLICATION,
            target=app_name_or_path,
            parameters={"args": args},
        )
        res = gw.execute(op)
        msg = res.output.get("message") if isinstance(res.output, dict) else (res.output or f"Launched '{app_name_or_path}'.")
        return {
            "status": "success" if res.success else "error",
            "response": msg,
            "error": res.error,
        }

    def activate_application(self, app_name: str) -> Dict[str, Any]:
        """Bring an application's window to the foreground via UniversalOSGateway."""
        from core.os_gateway import get_os_gateway, OSOperation, OSOperationType, OSCapability
        gw = get_os_gateway()
        op = OSOperation(
            operation_type=OSOperationType.FOCUS_WINDOW,
            capability=OSCapability.GUI_AUTOMATION,
            target=app_name,
        )
        res = gw.execute(op)
        hwnd = res.output.get("hwnd", 0) if isinstance(res.output, dict) else 0
        return {
            "status": "success" if res.success else "error",
            "response": f"Brought '{app_name}' to the front." if res.success else (res.error or f"No active window found matching '{app_name}'."),
            "hwnd": hwnd,
            "error": res.error,
        }

    def close_application(self, app_name: str, force: bool = False) -> Dict[str, Any]:
        """Close an application gracefully or terminate it via UniversalOSGateway."""
        from core.os_gateway import get_os_gateway, OSOperation, OSOperationType, OSCapability
        gw = get_os_gateway()
        op = OSOperation(
            operation_type=OSOperationType.CLOSE_APPLICATION,
            capability=OSCapability.APPLICATION,
            target=app_name,
            parameters={"force": force},
        )
        res = gw.execute(op)
        return {
            "status": "success" if res.success else "error",
            "response": f"Closed '{app_name}'." if res.success else (res.error or f"Failed to close '{app_name}'."),
            "error": res.error,
        }

    def interact_with_control(self, hwnd_or_name: Union[int, str], action: str = "click", text: str = "") -> Dict[str, Any]:
        """
        Interact with UI controls via Windows UI Automation through UniversalOSGateway.
        Supports: click, type, select, read.
        """
        from core.os_gateway import get_os_gateway, OSOperation, OSOperationType, OSCapability
        gw = get_os_gateway()
        op = OSOperation(
            operation_type=OSOperationType.CLICK_ELEMENT if action == "click" else OSOperationType.SET_ELEMENT_VALUE,
            capability=OSCapability.GUI_AUTOMATION,
            target=str(hwnd_or_name),
            parameters={"action": action, "text": text},
        )
        res = gw.execute(op)
        return {
            "status": "success" if res.success else "error",
            "message": res.output if isinstance(res.output, str) else ("Action completed." if res.success else res.error),
            "error": res.error,
        }

    def insert_text_at_cursor(self, text: str, user_id: int = 1) -> Dict[str, Any]:
        """
        Physically insert text at the active user cursor / caret position via UniversalOSGateway.
        """
        from core.os_gateway import get_os_gateway, OSOperation, OSOperationType, OSCapability
        gw = get_os_gateway()
        op = OSOperation(
            operation_type=OSOperationType.SET_ELEMENT_VALUE,
            capability=OSCapability.GUI_AUTOMATION,
            target=text,
            parameters={"text": text},
            user_id=user_id,
        )
        res = gw.execute(op, user_id=user_id)
        return {
            "status": "success" if res.success else "error",
            "inserted_length": len(text) if res.success else 0,
            "error": res.error,
        }


    # =========================================================================
    # 6. WINDOW MANAGEMENT
    # =========================================================================

    def enumerate_windows(self, only_visible: bool = True) -> List[Dict[str, Any]]:
        """Enumerate top-level Windows desktop windows."""
        windows = []
        if sys.platform != "win32" or not user32:
            return windows

        try:
            import win32gui
            import win32process

            fg_hwnd = user32.GetForegroundWindow()

            def enum_cb(h, _):
                if only_visible and not win32gui.IsWindowVisible(h):
                    return
                title = win32gui.GetWindowText(h).strip()
                if not title:
                    return
                cls_name = win32gui.GetClassName(h)
                if cls_name in ("Progman", "Shell_TrayWnd", "Button"):
                    return
                _, pid = win32process.GetWindowThreadProcessId(h)
                pname = ""
                try:
                    pname = psutil.Process(pid).name()
                except Exception:
                    pass
                rect = win32gui.GetWindowRect(h)
                windows.append({
                    "hwnd": h,
                    "title": title,
                    "class_name": cls_name,
                    "pid": pid,
                    "process_name": pname,
                    "rect": {"left": rect[0], "top": rect[1], "right": rect[2], "bottom": rect[3]},
                    "is_active": (h == fg_hwnd),
                })

            win32gui.EnumWindows(enum_cb, None)
        except Exception as e:
            logger.debug(f"[UCA] Window enum error: {e}")

        return windows

    def get_active_window(self) -> Dict[str, Any]:
        """Get details of the currently focused foreground window."""
        if not user32:
            return {"title": "Desktop", "class_name": "unknown", "pid": 0, "hwnd": 0, "process_name": ""}
        try:
            from skills.window_management.window_context import get_foreground_window_info
            info = get_foreground_window_info()
            if info.get("pid"):
                try:
                    proc = psutil.Process(info["pid"])
                    info["process_name"] = proc.name()
                except Exception:
                    info["process_name"] = ""
            return info
        except Exception as e:
            return {"title": "Desktop", "error": str(e), "hwnd": 0, "pid": 0, "process_name": ""}


    def minimize_window(self, hwnd: int) -> bool:
        if user32:
            return user32.ShowWindow(hwnd, 6) != 0  # SW_MINIMIZE
        return False

    def maximize_window(self, hwnd: int) -> bool:
        if user32:
            return user32.ShowWindow(hwnd, 3) != 0  # SW_MAXIMIZE
        return False

    def restore_window(self, hwnd: int) -> bool:
        if user32:
            return user32.ShowWindow(hwnd, 9) != 0  # SW_RESTORE
        return False

    def close_window(self, hwnd: int) -> bool:
        """
        Close a window by handle.
        Delegates to UniversalOSGateway to maintain the single OS mutation boundary.
        """
        try:
            from core.os_gateway.gateway import get_os_gateway
            from core.os_gateway.operation_model import OSOperation, OSOperationType, OSCapability, OSRiskLevel
            op = OSOperation(
                operation_type=OSOperationType.CLOSE_APPLICATION,
                capability=OSCapability.APPLICATION,
                target=str(hwnd),
                risk_level=OSRiskLevel.LOW_RISK,
                description=f"Close window {hwnd}",
            )
            res = get_os_gateway().execute(op)
            return res.success
        except Exception:
            return False

    # =========================================================================
    # 7. TERMINAL & SHELL EXECUTION (WITH FULL DIAGNOSTICS)
    # =========================================================================

    def execute_shell_command(
        self,
        command: str,
        shell: str = "powershell",
        cwd: Optional[str] = None,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """
        Execute a shell command with complete diagnostic capture.
        Delegates to UniversalOSGateway to maintain the single OS mutation boundary.
        Captures: stdout, stderr, exit code, execution time, shell, and working directory.
        Never silently discards errors.
        """
        start_t = time.time()
        working_dir = os.path.abspath(cwd) if cwd else os.getcwd()
        shell_lower = shell.lower()

        try:
            from core.os_gateway.gateway import get_os_gateway
            from core.os_gateway.operation_model import OSOperation, OSOperationType, OSCapability, OSRiskLevel
            op = OSOperation(
                operation_type=OSOperationType.EXECUTE_COMMAND,
                capability=OSCapability.SHELL,
                target=command,
                parameters={"command": command, "shell_type": shell_lower, "cwd": working_dir, "timeout": timeout},
                risk_level=OSRiskLevel.LOW_RISK,
                description=f"Execute command: {command}",
            )
            res = get_os_gateway().execute(op)
            data = res.data if isinstance(res.data, dict) else {}
            elapsed = round(time.time() - start_t, 3)
            return {
                "status": "success" if res.success else "error",
                "exit_code": data.get("exit_code", 0 if res.success else 1),
                "stdout": data.get("stdout", data.get("output", "")),
                "stderr": data.get("stderr", res.error or ""),
                "command": command,
                "shell": shell_lower,
                "cwd": working_dir,
                "execution_time_seconds": data.get("duration", elapsed),
                "execution_time_sec": data.get("duration", elapsed),
            }
        except Exception as e:
            return {
                "status": "error",
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "command": command,
                "shell": shell_lower,
                "cwd": working_dir,
                "execution_time_seconds": round(time.time() - start_t, 3),
            }

    # =========================================================================
    # 8. BROWSER INSPECTION (CDP + UI AUTOMATION + WINDOW)
    # =========================================================================

    def detect_available_browsers(self) -> List[str]:
        """Detect installed and running web browsers."""
        browsers = []
        checks = [
            ("chrome", [r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]),
            ("brave", [r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe", os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe")]),
            ("edge", [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]),
            ("firefox", [r"C:\Program Files\Mozilla Firefox\firefox.exe", r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe"]),
        ]
        for name, paths in checks:
            if any(os.path.exists(p) for p in paths) or shutil.which(name):
                browsers.append(name)
        return browsers

    def get_browser_state(self, title_hint: str = "") -> Dict[str, Any]:
        """
        Inspect current browser state via CDP, UIAutomation, or Window Title.
        Never calls web search.
        """
        # Tier 1: Check Chrome DevTools Protocol
        cdp = try_get_browser_cdp_info(title_hint=title_hint)
        if cdp and cdp.get("url"):
            url = cdp["url"]
            title = cdp.get("title", "")
            return {
                "browser": "browser",
                "url": url,
                "title": title,
                "source": "cdp",
                "is_video": "youtube.com" in url or "watch" in url,
            }

        # Tier 2: Check active window
        active = self.get_active_window()
        hwnd = active.get("hwnd", 0)
        title = active.get("title", "")
        app_name = active.get("class_name", "").lower()

        url = try_get_browser_url(hwnd, app_name, title_hint=title) if hwnd else None

        video_title = None
        if "youtube" in title.lower():
            m_yt = re.search(r'^(.*?)(?:\s*-\s*YouTube|\s*\|\s*YouTube)', title, re.IGNORECASE)
            if m_yt:
                video_title = m_yt.group(1).strip()

        return {
            "browser": app_name if any(b in app_name for b in ("chrome", "brave", "edge", "firefox")) else "browser",
            "url": url,
            "title": title,
            "video_title": video_title,
            "source": "accessibility" if url else "window_title",
            "is_video": video_title is not None,
        }

    # =========================================================================
    # 9. UNIVERSAL DEEP UI OBSERVATION (INSPECT APPLICATION INTERNALS)
    # =========================================================================

    def observe_ui_deep(self, hwnd: int, app_name: str) -> Dict[str, Any]:
        """
        Inspect the active application deeply:
        - VS Code: workspace, project, active file, git branch, cursor, selection
        - Notepad: document name, visible text
        - Explorer: current folder path, selected files
        - Terminal: shell, cwd, output
        """
        app_lower = app_name.lower()
        context: Dict[str, Any] = {"application": app_name, "hwnd": hwnd}

        # 1. VS Code Deep Observation
        if "code" in app_lower or "vscode" in app_lower:
            active_info = self.get_active_window()
            title = active_info.get("title", "")
            # Title pattern: "file.ext - project - Visual Studio Code"
            m = re.search(r'^([a-zA-Z0-9_\-\.\/\\]+)\s*[-—]\s*(.*?)\s*[-—]\s*Visual Studio Code', title, re.IGNORECASE)
            if m:
                context["active_file"] = m.group(1).strip()
                context["project"] = m.group(2).strip()

            proj = context.get("project", "")
            if proj:
                ws_info = try_resolve_vscode_workspace(proj)
                if ws_info and ws_info.get("folder"):
                    context["workspace_folder"] = ws_info["folder"]
                    branch = try_resolve_git_branch(ws_info["folder"], proj)
                    if branch:
                        context["git_branch"] = branch

            status = try_get_vscode_status_bar(hwnd)
            if status:
                context.update(status)

        # 2. Notepad Deep Observation
        elif "notepad" in app_lower:
            active_info = self.get_active_window()
            title = active_info.get("title", "")
            doc_name = title.replace("- Notepad", "").replace("Notepad", "").strip() or "Untitled"
            context["document"] = doc_name

            # Read visible text from Edit control
            try:
                import win32gui
                def enum_edit(child_hwnd, _):
                    cls_name = win32gui.GetClassName(child_hwnd)
                    if "edit" in cls_name.lower() or "rich" in cls_name.lower():
                        text = win32gui.GetWindowText(child_hwnd)
                        if text:
                            context["visible_text"] = text[:2000]
                win32gui.EnumChildWindows(hwnd, enum_edit, None)
            except Exception:
                pass

        # 3. File Explorer Deep Observation
        elif "explorer" in app_lower or "cabinetwclass" in app_lower:
            active_info = self.get_active_window()
            title = active_info.get("title", "")
            context["current_directory"] = title

        # 4. Terminal / Shell Deep Observation
        elif any(t in app_lower for t in ("terminal", "powershell", "cmd", "conhost")):
            context["terminal_type"] = app_lower
            active_info = self.get_active_window()
            title = active_info.get("title", "")
            # Check if cwd is embedded in window title
            if ":\\" in title or ":/" in title:
                context["terminal_cwd"] = title

        return context

    # =========================================================================
    # 10. UNIFIED COMPUTER STATE CAPTURE
    # =========================================================================

    def capture_computer_state(self, user_id: Any = 1) -> ComputerState:
        """
        Capture the comprehensive, authoritative Unified ComputerState.
        Syncs state with StateEngine and records transitions.
        """
        active_win = self.get_active_window()
        hwnd = active_win.get("hwnd", 0)
        app_name = active_win.get("class_name", "unknown")
        win_title = active_win.get("title", "")

        deep_context = self.observe_ui_deep(hwnd, app_name) if hwnd else {}

        active_proc = None
        active_proc_name = active_win.get("process_name", "")
        if active_win.get("pid"):
            try:
                p = psutil.Process(active_win["pid"])
                active_proc_name = p.name()
                active_proc = {"pid": p.pid, "name": active_proc_name, "memory_mb": round(p.memory_info().rss / (1024 * 1024), 1)}
            except Exception:
                pass

        browser_info = self.get_browser_state() if any(b in (app_name + " " + active_proc_name).lower() for b in ("chrome", "brave", "edge", "firefox")) else {}

        # Normalize active_application to recognizable user-facing name
        app_name_clean = app_name
        if active_proc_name:
            p_low = active_proc_name.lower()
            if "code" in p_low:
                app_name_clean = "VS Code"
            elif "notepad" in p_low:
                app_name_clean = "Notepad"
            elif "chrome" in p_low:
                app_name_clean = "Google Chrome"
            elif "msedge" in p_low or "edge" in p_low:
                app_name_clean = "Microsoft Edge"
            elif "brave" in p_low:
                app_name_clean = "Brave Browser"
            elif "explorer" in p_low:
                app_name_clean = "File Explorer"
            elif "powershell" in p_low or "pwsh" in p_low:
                app_name_clean = "PowerShell"
            elif "cmd" in p_low:
                app_name_clean = "Command Prompt"
            elif "windowsterminal" in p_low:
                app_name_clean = "Windows Terminal"
            else:
                app_name_clean = active_proc_name.replace(".exe", "").capitalize()
        elif "cabinetwclass" in app_name.lower():
            app_name_clean = "File Explorer"

        sys_info = self.get_system_info()
        drives = self.get_drives_and_storage()
        open_wins = self.enumerate_windows(only_visible=True)

        comp_state = ComputerState(
            timestamp=time.time(),
            active_application=app_name_clean,
            active_window=win_title,

            active_process=active_proc,
            active_browser=browser_info.get("browser"),
            active_tab=browser_info.get("title"),
            current_url=browser_info.get("url"),
            current_page=browser_info.get("title"),
            current_video=browser_info.get("video_title"),
            current_document=deep_context.get("document"),
            current_file=deep_context.get("active_file"),
            current_project=deep_context.get("project"),
            current_terminal=deep_context.get("terminal_type"),
            terminal_cwd=deep_context.get("terminal_cwd"),
            cursor_context=deep_context.get("cursor_position"),
            selected_text=deep_context.get("selection") or deep_context.get("visible_text"),
            selected_files=deep_context.get("selected_files", []),
            open_applications=list(set(w["process_name"] for w in open_wins if w.get("process_name"))),
            open_windows=open_wins[:10],
            filesystem_context={"accessible_drives": drives},
            system_context=sys_info,
            network_context=self.get_network_info(),
        )

        # Ingest into state engine for historical transitions
        env_state = comp_state.to_environment_state()
        self.state_engine.ingest(str(user_id), env_state)

        return comp_state

    # Alias for state synchronization
    sync_computer_state = capture_computer_state

    # =========================================================================
    # 11. "CAN YOU SEE MY SYSTEM?" RUNTIME CAPABILITY EXPLANATION
    # =========================================================================

    def explain_system_visibility(self, user_id: Any = 1) -> str:
        """
        Generates an authoritative, factual overview of exactly what is observable
        on the current Windows system. Never claims blindness.
        """
        sys_info = self.get_system_info()
        active = self.get_active_window()
        drives = self.get_drives_and_storage()
        open_wins = self.enumerate_windows(only_visible=True)
        running_count = len(psutil.pids())

        drive_list = ", ".join(d["drive"] for d in drives)
        active_app = active.get("title") or active.get("class_name") or "Desktop"

        lines = [
            f"Yes, I have direct visibility into this Windows system ({sys_info['os_name']} {sys_info['os_release']}, Build {sys_info['os_version']}):",
            f"- Machine: Hostname '{sys_info['hostname']}' with {sys_info['cpu_logical_cores']} CPU cores and {sys_info['ram_total_gb']} GB RAM ({sys_info['ram_usage_percent']}% used).",
            f"- Storage: {len(drives)} accessible drive(s) ({drive_list}).",
            f"- Running Processes: {running_count} active processes running.",
            f"- Active Window: Currently focused on '{active_app}'.",
            f"- Open Windows: {len(open_wins)} visible application window(s) open.",
            f"- Interfaces: Windows UI Automation, Win32 APIs, PowerShell shell execution, and CDP browser adapters are active.",
        ]
        return "\n".join(lines)


# Singleton factory
_universal_computer_access: Optional[UniversalComputerAccess] = None

def get_universal_computer_access() -> UniversalComputerAccess:
    """Return the global UniversalComputerAccess singleton."""
    global _universal_computer_access
    if _universal_computer_access is None:
        _universal_computer_access = UniversalComputerAccess()
    return _universal_computer_access

# Canonical alias
get_computer_access = get_universal_computer_access
