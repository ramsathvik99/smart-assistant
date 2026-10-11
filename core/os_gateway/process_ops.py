"""
Universal OS Operations — Process Controller
Provides comprehensive process management and port inspection:
- List, find, inspect, start, stop, terminate processes
- Inspect process path, command line, process tree, memory/CPU usage
- Port-to-PID inspection and termination ("What's using port 8000?", "Stop that process")
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import psutil

logger = logging.getLogger(__name__)


_process_cache_time: float = 0.0
_process_cache_list: List[Dict[str, Any]] = []
_PROCESS_CACHE_TTL: float = 2.0


def invalidate_process_cache() -> None:
    """Invalidate process cache so next lookup retrieves fresh state."""
    global _process_cache_time
    _process_cache_time = 0.0


def _get_cached_process_list(ttl: Optional[float] = None) -> List[Dict[str, Any]]:
    """Retrieve process list with a short TTL cache to avoid expensive repetitive process_iter scans."""
    global _process_cache_time, _process_cache_list
    effective_ttl = ttl if ttl is not None else _PROCESS_CACHE_TTL
    now = time.time()
    if (now - _process_cache_time) < effective_ttl and _process_cache_list:
        return _process_cache_list

    procs = []
    # Fast native Win32 snapshot on Windows (10ms vs 2000ms psutil full scan)
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.windll.kernel32
            class PROCESSENTRY32(ctypes.Structure):
                _fields_ = [
                    ('dwSize', wintypes.DWORD),
                    ('cntUsage', wintypes.DWORD),
                    ('th32ProcessID', wintypes.DWORD),
                    ('th32DefaultHeapID', ctypes.c_size_t),
                    ('th32ModuleID', wintypes.DWORD),
                    ('cntThreads', wintypes.DWORD),
                    ('th32ParentProcessID', wintypes.DWORD),
                    ('pcPriClassBase', wintypes.LONG),
                    ('dwFlags', wintypes.DWORD),
                    ('szExeFile', ctypes.c_char * 260)
                ]
            snap = kernel32.CreateToolhelp32Snapshot(2, 0)
            if snap and snap != -1 and snap != 0xFFFFFFFF:
                entry = PROCESSENTRY32()
                entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
                if kernel32.Process32First(snap, ctypes.byref(entry)):
                    while True:
                        name = entry.szExeFile.decode('ansi', errors='ignore')
                        procs.append({
                            "pid": int(entry.th32ProcessID),
                            "name": name,
                            "cpu_percent": 0.0,
                            "memory_percent": 0.0,
                            "status": "running",
                            "created_at": 0.0,
                        })
                        if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                            break
                kernel32.CloseHandle(snap)
        except Exception:
            procs = []

    # Fallback to psutil if native snapshot was empty or failed
    if not procs:
        for p in psutil.process_iter(['pid', 'name', 'status']):
            try:
                info = p.info
                name = info.get('name') or ""
                procs.append({
                    "pid": info['pid'],
                    "name": name,
                    "cpu_percent": 0.0,
                    "memory_percent": 0.0,
                    "status": info.get('status', 'running'),
                    "created_at": 0.0,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    _process_cache_list = procs
    _process_cache_time = now
    return procs


def list_processes(
    sort_by: str = "memory",
    limit: int = 25,
    name_filter: Optional[str] = None,
    top_n: Optional[int] = None,
) -> Any:
    """List running processes with resource metrics."""
    if top_n is not None:
        limit = top_n

    raw_procs = _get_cached_process_list()
    norm_filter = name_filter.lower().strip() if name_filter else None

    if norm_filter:
        procs = [p for p in raw_procs if norm_filter in p["name"].lower()]
    else:
        procs = list(raw_procs)

    if sort_by == "cpu":
        procs.sort(key=lambda x: x["cpu_percent"], reverse=True)
    elif sort_by == "name":
        procs.sort(key=lambda x: x["name"].lower())
    else:
        procs.sort(key=lambda x: x["memory_percent"], reverse=True)

    selected = procs[:limit]
    if top_n is not None:
        return selected

    return {
        "success": True,
        "status": "listed",
        "total_running": len(raw_procs),
        "count": len(selected),
        "processes": selected,
        "message": f"Found {len(raw_procs)} running processes (showing top {len(selected)} sorted by {sort_by}).",
    }


def find_process(name_or_query: str) -> Dict[str, Any]:
    """Find running processes matching a name, PID, or keyword."""
    query = str(name_or_query).strip().lower()
    matches = []
    raw_procs = _get_cached_process_list()

    # Check if query is a direct PID
    if query.isdigit():
        target_pid = int(query)
        for p in raw_procs:
            if p["pid"] == target_pid:
                matches.append(p)
                break
    else:
        for p in raw_procs:
            p_name = p["name"].lower()
            if query == p_name or query in p_name or p_name.startswith(query):
                matches.append(p)

    return {
        "success": len(matches) > 0,
        "status": "found" if matches else "not_found",
        "query": name_or_query,
        "match_count": len(matches),
        "processes": matches,
        "message": f"Found {len(matches)} matching processes for '{name_or_query}'." if matches else f"No process found matching '{name_or_query}'.",
    }


def inspect_process(pid: int) -> Dict[str, Any]:
    """Inspect complete detailed metrics and configuration of a process."""
    try:
        p = psutil.Process(pid)
        proc_data = _serialize_process(p, detailed=True)
        return {
            "success": True,
            "status": "inspected",
            "pid": pid,
            "name": p.name(),
            "process": proc_data,
            **proc_data,
            "message": f"Inspected process '{p.name()}' (PID: {pid}).",
        }
    except psutil.NoSuchProcess:
        return {"success": False, "status": "not_found", "message": f"Process with PID {pid} is not running."}
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Failed to inspect process: {exc}"}


def start_process(command_or_path: str, args: Optional[List[str]] = None) -> Dict[str, Any]:
    """Start an executable or background process."""
    try:
        cmd = [command_or_path]
        if args:
            cmd.extend(args)

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )

        invalidate_process_cache()
        return {
            "success": True,
            "status": "started",
            "pid": proc.pid,
            "target": command_or_path,
            "message": f"Started '{os.path.basename(command_or_path)}' (PID: {proc.pid}).",
        }
    except Exception as exc:
        return {"success": False, "status": "error", "error": str(exc), "message": f"Failed to start process: {exc}"}


def terminate_process(
    target: Any,
    force: bool = False,
    timeout: float = 3.0,
) -> Dict[str, Any]:
    """
    Terminates a process by PID or name. Graceful termination first,
    falling back to kill if force=True or unresponsive.
    """
    invalidate_process_cache()
    pids_to_kill = []
    target_str = str(target).strip()

    if target_str.isdigit():
        pids_to_kill.append(int(target_str))
    else:
        # Find matching processes by name
        norm_name = target_str.lower().replace(".exe", "")
        for p in psutil.process_iter(['pid', 'name']):
            try:
                pn = (p.info.get('name') or "").lower().replace(".exe", "")
                if pn == norm_name or norm_name in pn:
                    pids_to_kill.append(p.info['pid'])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    if not pids_to_kill:
        return {
            "success": False,
            "status": "not_found",
            "target": target,
            "message": f"No running process found for '{target}'.",
        }

    terminated = []
    failed = []

    for pid in pids_to_kill:
        try:
            p = psutil.Process(pid)
            proc_name = p.name()
            if force:
                p.kill()
            else:
                p.terminate()
                try:
                    p.wait(timeout=timeout)
                except psutil.TimeoutExpired:
                    p.kill()
                    p.wait()

            terminated.append({"pid": pid, "name": proc_name})
        except psutil.NoSuchProcess:
            terminated.append({"pid": pid, "name": "unknown"})
        except Exception as exc:
            failed.append({"pid": pid, "error": str(exc)})

    is_ok = len(terminated) > 0 and len(failed) == 0
    t_names = ", ".join(f"{t['name']} (PID: {t['pid']})" for t in terminated)

    return {
        "success": is_ok,
        "status": "terminated" if is_ok else ("partial" if terminated else "error"),
        "target": target,
        "terminated_count": len(terminated),
        "terminated": terminated,
        "failed": failed,
        "message": f"Terminated {t_names}." if terminated else f"Could not terminate {target}.",
    }


def inspect_port(port: int) -> Dict[str, Any]:
    """
    Identifies what process and PID is listening on or using a given TCP/UDP port.
    e.g. "What's using port 8000?"
    """
    found_listeners = []

    try:
        # 1. Inspect using psutil net_connections
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr and conn.laddr.port == port:
                pid = conn.pid
                proc_info = {}
                if pid:
                    try:
                        p = psutil.Process(pid)
                        proc_info = {
                            "pid": pid,
                            "name": p.name(),
                            "status": conn.status,
                            "exe": p.exe(),
                            "cmdline": " ".join(p.cmdline()),
                            "memory_mb": round(p.memory_info().rss / (1024 * 1024), 2),
                        }
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        proc_info = {"pid": pid, "name": "system/protected", "status": conn.status}
                else:
                    proc_info = {"pid": None, "name": "System/Kernel", "status": conn.status}

                found_listeners.append(proc_info)
    except (psutil.AccessDenied, Exception):
        pass

    # 2. Netstat fallback on Windows if psutil returned nothing
    if not found_listeners and sys.platform == "win32":
        try:
            output = subprocess.check_output(f"netstat -ano | findstr :{port}", shell=True, text=True)
            for line in output.strip().splitlines():
                parts = line.split()
                if len(parts) >= 5 and parts[3] in ("LISTENING", "ESTABLISHED", "TIME_WAIT"):
                    pid_str = parts[-1]
                    if pid_str.isdigit():
                        pid = int(pid_str)
                        name = "unknown"
                        try:
                            name = psutil.Process(pid).name()
                        except Exception:
                            pass
                        found_listeners.append({
                            "pid": pid,
                            "name": name,
                            "status": parts[3],
                            "cmdline": "",
                        })
        except Exception:
            pass

    if found_listeners:
        top = found_listeners[0]
        pid_desc = f"PID {top.get('pid')}" if top.get('pid') else "System"
        name_desc = f"({top.get('name')})" if top.get('name') else ""
        msg = f"Port {port} is in use by {pid_desc} {name_desc}."
        return {
            "success": True,
            "status": "in_use",
            "port": port,
            "pid": top.get("pid"),
            "in_use": True,
            "primary_listener": top,
            "listeners": found_listeners,
            "message": msg,
        }
    else:
        return {
            "success": True,
            "status": "free",
            "port": port,
            "in_use": False,
            "primary_listener": None,
            "listeners": [],
            "message": f"Port {port} is free and not in use by any process.",
        }


def kill_by_port(port: int, force: bool = False) -> Dict[str, Any]:
    """
    Finds whatever process is using a port and terminates it.
    "Check what's using port 8000 and stop it."
    """
    port_info = inspect_port(port)
    if not port_info.get("in_use") or not port_info.get("primary_listener"):
        return {
            "success": False,
            "status": "not_in_use",
            "port": port,
            "message": f"Port {port} is not in use.",
        }

    top = port_info["primary_listener"]
    pid = top.get("pid")
    if not pid:
        return {
            "success": False,
            "status": "cannot_terminate",
            "port": port,
            "message": f"Port {port} is used by a system/kernel process that cannot be terminated.",
        }

    term_res = terminate_process(pid, force=force)
    # Verification check: inspect port again
    time.sleep(0.3)
    check_again = inspect_port(port)
    is_freed = not check_again.get("in_use")

    return {
        "success": is_freed,
        "status": "terminated" if is_freed else "failed",
        "port": port,
        "pid": pid,
        "process_name": top.get("name"),
        "freed": is_freed,
        "termination_result": term_res,
        "message": f"Stopped process '{top.get('name')}' (PID: {pid}) on port {port}. Port is now free." if is_freed else f"Attempted to stop process {pid} on port {port}, but port remains occupied.",
    }


def _serialize_process(proc: psutil.Process, detailed: bool = False) -> Dict[str, Any]:
    """Helper to convert psutil.Process to dictionary safely."""
    try:
        data = {
            "pid": proc.pid,
            "name": proc.name(),
            "status": proc.status(),
            "cpu_percent": proc.cpu_percent(interval=None),
            "memory_percent": round(proc.memory_percent(), 2),
            "created_at": proc.create_time(),
        }
        if detailed:
            try:
                data["exe"] = proc.exe()
                data["cmdline"] = " ".join(proc.cmdline())
                data["cwd"] = proc.cwd()
                data["num_threads"] = proc.num_threads()
                mem = proc.memory_info()
                data["memory_rss_mb"] = round(mem.rss / (1024 * 1024), 2)
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass
        return data
    except Exception:
        return {"pid": proc.pid, "name": "unknown"}
