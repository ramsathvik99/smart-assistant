"""
System Controller & Diagnostics for Nova Smart Assistant.
Provides hardware telemetry (battery, disk, processes), display brightness,
window management, and clipboard utilities.
"""

import logging
import ctypes
import os
import re
import subprocess
import psutil
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Virtual key codes for Windows API
VK_LWIN = 0x5B
VK_D = 0x44
KEYEVENTF_KEYUP = 0x0002


def get_battery_status() -> Dict[str, Any]:
    """
    Get current battery level, charging status, and remaining time.
    """
    try:
        battery = psutil.sensors_battery()
        if battery is None:
            return {
                "available": False,
                "percent": None,
                "charging": None,
                "message": "No battery detected (desktop system or AC power only)."
            }

        percent = round(battery.percent)
        is_charging = battery.power_plugged
        secs_left = battery.secsleft
        
        status_text = "charging" if is_charging else "discharging"
        if secs_left > 0 and not is_charging:
            hours = secs_left // 3600
            minutes = (secs_left % 3600) // 60
            time_str = f" About {hours} hours and {minutes} minutes remaining."
        elif is_charging:
            time_str = " The device is plugged in."
        else:
            time_str = ""

        speech_text = f"Battery is at {percent}%, currently {status_text}.{time_str}"
        
        return {
            "available": True,
            "percent": percent,
            "charging": is_charging,
            "secs_left": secs_left,
            "message": speech_text
        }
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to read battery status: {e}")
        return {
            "available": False,
            "message": f"Unable to check battery status: {e}"
        }


def get_disk_space(drive: str = "C:") -> Dict[str, Any]:
    """
    Get storage metrics (free, used, total) for the primary disk.
    """
    try:
        # Normalise drive letter
        if not drive.endswith("\\") and not drive.endswith("/"):
            drive_path = f"{drive}\\" if ":" in drive else drive
        else:
            drive_path = drive

        usage = psutil.disk_usage(drive_path)
        total_gb = usage.total / (1024 ** 3)
        free_gb = usage.free / (1024 ** 3)
        used_gb = usage.used / (1024 ** 3)
        percent_used = usage.percent

        speech_text = (
            f"Drive {drive} has {free_gb:.1f} gigabytes free out of "
            f"{total_gb:.1f} gigabytes total ({percent_used:.1f}% used)."
        )

        return {
            "drive": drive,
            "total_gb": round(total_gb, 1),
            "free_gb": round(free_gb, 1),
            "used_gb": round(used_gb, 1),
            "percent_used": percent_used,
            "message": speech_text
        }
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to get disk space for {drive}: {e}")
        return {
            "drive": drive,
            "message": f"Unable to retrieve disk usage for {drive}: {e}"
        }


def get_top_processes(n: int = 5, sort_by: str = "memory") -> Dict[str, Any]:
    """
    Get top resource-consuming processes by CPU or RAM.
    """
    try:
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                info = p.info
                if info.get('name'):
                    procs.append({
                        "pid": info['pid'],
                        "name": info['name'],
                        "cpu": round(info.get('cpu_percent') or 0.0, 1),
                        "memory": round(info.get('memory_percent') or 0.0, 1)
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        if sort_by.lower() == "cpu":
            procs.sort(key=lambda x: x["cpu"], reverse=True)
            top_list = procs[:n]
            summary = ", ".join([f"{p['name']} ({p['cpu']}% CPU)" for p in top_list])
            speech_text = f"Top {len(top_list)} processes by CPU: {summary}."
        else:
            procs.sort(key=lambda x: x["memory"], reverse=True)
            top_list = procs[:n]
            summary = ", ".join([f"{p['name']} ({p['memory']}% RAM)" for p in top_list])
            speech_text = f"Top {len(top_list)} processes by memory: {summary}."

        return {
            "processes": top_list,
            "sort_by": sort_by,
            "message": speech_text
        }
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to get top processes: {e}")
        return {
            "processes": [],
            "message": f"Unable to list top processes: {e}"
        }


def get_brightness() -> Dict[str, Any]:
    """
    Get current display brightness percentage.
    """
    try:
        import screen_brightness_control as sbc
        current = sbc.get_brightness()
        if isinstance(current, list):
            level = current[0] if current else 100
        else:
            level = int(current)
        return {
            "success": True,
            "level": level,
            "message": f"Screen brightness is currently at {level}%."
        }
    except Exception as e:
        logger.warning(f"[SYSTEM] screen_brightness_control failed: {e}")
        return {
            "success": False,
            "level": None,
            "message": "Screen brightness cannot be read on this display."
        }


def set_brightness(level: int) -> Dict[str, Any]:
    """
    Set display brightness percentage (0-100).
    """
    try:
        import screen_brightness_control as sbc
        target = max(0, min(100, int(level)))
        sbc.set_brightness(target)
        return {
            "success": True,
            "level": target,
            "message": f"Screen brightness set to {target}%."
        }
    except Exception as e:
        logger.warning(f"[SYSTEM] Failed to set brightness to {level}: {e}")
        return {
            "success": False,
            "message": f"Could not adjust brightness on this display: {e}"
        }


def adjust_brightness(delta: int) -> Dict[str, Any]:
    """
    Increase or decrease brightness by delta (e.g. +10, -20).
    """
    try:
        current_res = get_brightness()
        current_level = current_res.get("level") or 50
        target = max(10, min(100, current_level + delta))
        return set_brightness(target)
    except Exception as e:
        return {
            "success": False,
            "message": f"Could not adjust brightness: {e}"
        }


def minimize_all_windows() -> Dict[str, Any]:
    """
    Show desktop / minimize all open windows using Win+D.
    """
    try:
        user32 = ctypes.windll.user32
        # Press Win
        user32.keybd_event(VK_LWIN, 0, 0, 0)
        # Press D
        user32.keybd_event(VK_D, 0, 0, 0)
        # Release D
        user32.keybd_event(VK_D, 0, KEYEVENTF_KEYUP, 0)
        # Release Win
        user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)
        return {
            "success": True,
            "message": "All windows minimized (Desktop shown)."
        }
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to minimize all windows: {e}")
        return {
            "success": False,
            "message": f"Failed to minimize windows: {e}"
        }


def get_cpu_metrics() -> Dict[str, Any]:
    """
    Get overall CPU usage, per-core utilization, and core counts.
    """
    try:
        overall_pct = psutil.cpu_percent(interval=0.1)
        per_core = psutil.cpu_percent(interval=0.1, percpu=True)
        logical_cores = psutil.cpu_count(logical=True) or len(per_core)
        physical_cores = psutil.cpu_count(logical=False) or (logical_cores // 2 if logical_cores else 1)
        freq = psutil.cpu_freq()
        freq_mhz = round(freq.current, 1) if freq else None

        speech_text = (
            f"Overall CPU usage is {overall_pct:.1f}% across {logical_cores} logical cores "
            f"({physical_cores} physical cores)."
        )

        return {
            "success": True,
            "status": "success",
            "overall_percent": overall_pct,
            "cpu_total_percent": overall_pct,
            "per_core": per_core,
            "logical_cores": logical_cores,
            "cpu_count_logical": logical_cores,
            "physical_cores": physical_cores,
            "frequency_mhz": freq_mhz,
            "message": speech_text
        }
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to get CPU metrics: {e}")
        return {
            "success": False,
            "status": "error",
            "message": f"Unable to read CPU metrics: {e}"
        }


def get_ram_metrics() -> Dict[str, Any]:
    """
    Get detailed RAM utilization: total, used, available, and percent.
    """
    try:
        mem = psutil.virtual_memory()
        total_gb = mem.total / (1024 ** 3)
        available_gb = mem.available / (1024 ** 3)
        used_gb = mem.used / (1024 ** 3)
        percent = mem.percent

        speech_text = (
            f"RAM usage is {percent:.1f}%. "
            f"{used_gb:.1f} gigabytes used out of {total_gb:.1f} gigabytes total ({available_gb:.1f} gigabytes available)."
        )

        return {
            "success": True,
            "status": "success",
            "total_gb": round(total_gb, 2),
            "used_gb": round(used_gb, 2),
            "available_gb": round(available_gb, 2),
            "percent": percent,
            "percent_used": percent,
            "message": speech_text
        }
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to get RAM metrics: {e}")
        return {
            "success": False,
            "status": "error",
            "message": f"Unable to read RAM metrics: {e}"
        }


def get_all_disks() -> Dict[str, Any]:
    """
    Enumerate all connected disk partitions and their storage metrics.
    """
    try:
        disks = []
        for part in psutil.disk_partitions(all=False):
            if 'cdrom' in part.opts or part.fstype == '':
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disks.append({
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "fstype": part.fstype,
                    "total_gb": round(usage.total / (1024 ** 3), 1),
                    "used_gb": round(usage.used / (1024 ** 3), 1),
                    "free_gb": round(usage.free / (1024 ** 3), 1),
                    "percent_used": usage.percent
                })
            except (PermissionError, OSError):
                continue

        summary_items = [f"{d['mountpoint']} ({d['free_gb']} GB free of {d['total_gb']} GB)" for d in disks]
        speech_text = "Drives: " + ", ".join(summary_items) + "." if disks else "No storage drives found."

        return {
            "success": True,
            "status": "success",
            "disks": disks,
            "message": speech_text
        }
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to list all disks: {e}")
        return {
            "success": False,
            "status": "error",
            "disks": [],
            "message": f"Unable to read disk drives: {e}"
        }


# Protected process safelist to prevent accidental system instability
PROTECTED_PROCESSES = {
    "explorer.exe", "python.exe", "svchost.exe", "system", "csrss.exe", 
    "services.exe", "lsass.exe", "smss.exe", "winlogon.exe", "dwm.exe", 
    "taskmgr.exe", "registry", "wininit.exe", "spoolsv.exe"
}


def terminate_process(pid: Optional[int] = None, name: Optional[str] = None, process_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Safely terminate a user application process by PID or process name.
    Strictly forbids terminating critical Windows OS processes or the assistant itself.
    """
    try:
        name = name or process_name
        current_pid = os.getpid()

        if pid is not None:
            if pid == current_pid:
                return {"success": False, "status": "protected", "message": "Cannot terminate the assistant's own process."}
            try:
                proc = psutil.Process(pid)
                p_name = proc.name().lower()
                if p_name in PROTECTED_PROCESSES:
                    return {
                        "success": False, 
                        "status": "protected",
                        "message": f"Refused: '{proc.name()}' is a protected system process and cannot be terminated."
                    }
                proc.terminate()
                return {"success": True, "status": "success", "message": f"Process '{proc.name()}' (PID {pid}) terminated successfully."}
            except psutil.NoSuchProcess:
                return {"success": False, "status": "error", "message": f"Process with PID {pid} was not found."}
            except psutil.AccessDenied:
                return {"success": False, "status": "error", "message": f"Permission denied terminating PID {pid}. Administrator rights required."}

        elif name:
            target_name = name.lower()
            if not target_name.endswith(".exe"):
                target_name_exe = f"{target_name}.exe"
            else:
                target_name_exe = target_name

            if target_name in PROTECTED_PROCESSES or target_name_exe in PROTECTED_PROCESSES:
                return {
                    "success": False, 
                    "status": "protected",
                    "message": f"Refused: '{name}' is a protected system process and cannot be terminated."
                }

            terminated = []
            for p in psutil.process_iter(['pid', 'name']):
                try:
                    p_name = (p.info['name'] or "").lower()
                    if p_name in (target_name, target_name_exe):
                        if p.info['pid'] == current_pid:
                            continue
                        p.terminate()
                        terminated.append(p.info['pid'])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            if terminated:
                return {
                    "success": True, 
                    "status": "success",
                    "terminated_pids": terminated,
                    "message": f"Terminated {len(terminated)} instance(s) of '{name}' (PIDs: {terminated})."
                }
            else:
                return {"success": False, "status": "error", "message": f"No running processes matched '{name}'."}

        return {"success": False, "status": "error", "message": "Either process PID or name must be specified."}

    except Exception as e:
        logger.error(f"[SYSTEM] Failed to terminate process: {e}")
        return {"success": False, "status": "error", "message": f"Error terminating process: {e}"}


def set_clipboard_text(text: str) -> Dict[str, Any]:
    """
    Write text to the Windows clipboard.
    """
    try:
        import win32clipboard
        import win32con
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
            return {"success": True, "message": f"Copied {len(text)} characters to clipboard."}
        finally:
            win32clipboard.CloseClipboard()
    except Exception as e:
        logger.warning(f"[SYSTEM] win32clipboard write failed, using ctypes fallback: {e}")
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            if not user32.OpenClipboard(0):
                return {"success": False, "message": "Could not open clipboard."}
            user32.EmptyClipboard()
            encoded = (text + '\0').encode('utf-16le')
            h_mem = kernel32.GlobalAlloc(0x0002, len(encoded))  # GMEM_MOVEABLE
            p_mem = kernel32.GlobalLock(h_mem)
            ctypes.memmove(p_mem, encoded, len(encoded))
            kernel32.GlobalUnlock(h_mem)
            user32.SetClipboardData(13, h_mem)  # CF_UNICODETEXT
            user32.CloseClipboard()
            return {"success": True, "message": f"Copied {len(text)} characters to clipboard."}
        except Exception as err:
            return {"success": False, "message": f"Failed to write to clipboard: {err}"}


def transform_clipboard(operation: str) -> Dict[str, Any]:
    """
    Transform text in the clipboard (uppercase, lowercase, title, strip, bullet_list, count_words).
    """
    res = get_clipboard_text()
    if not res.get("success") or not res.get("text"):
        return {"success": False, "status": "error", "message": "Clipboard is empty or contains non-text content."}

    text = res["text"]
    op = operation.lower().strip()

    if op in ("uppercase", "upper", "caps", "capitalize_all"):
        transformed = text.upper()
        desc = "converted to uppercase"
    elif op in ("lowercase", "lower", "small"):
        transformed = text.lower()
        desc = "converted to lowercase"
    elif op in ("title", "titlecase", "capitalize"):
        transformed = text.title()
        desc = "converted to title case"
    elif op in ("strip", "trim"):
        transformed = text.strip()
        desc = "trimmed whitespace"
    elif op in ("bullet_list", "bullets"):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        transformed = "\n".join([f"• {line}" for line in lines])
        desc = "converted lines to bullet points"
    elif op in ("count_words", "word_count"):
        words = len(text.split())
        chars = len(text)
        return {"success": True, "status": "success", "message": f"Clipboard contains {words} words ({chars} characters)."}
    else:
        return {"success": False, "status": "error", "message": f"Unknown transformation '{operation}'. Supported: uppercase, lowercase, title, strip, bullet_list, count_words."}

    set_res = set_clipboard_text(transformed)
    if set_res.get("success"):
        return {"success": True, "status": "success", "text": transformed, "message": f"Clipboard text {desc}."}
    return set_res


def get_display_info() -> Dict[str, Any]:
    """
    Get primary screen resolution, virtual screen bounds, and monitor metrics.
    """
    try:
        user32 = ctypes.windll.user32
        # SM_CXSCREEN = 0, SM_CYSCREEN = 1
        width = user32.GetSystemMetrics(0)
        height = user32.GetSystemMetrics(1)
        # SM_CMONITORS = 80
        monitors = user32.GetSystemMetrics(80) or 1
        # Virtual desktop bounds
        v_width = user32.GetSystemMetrics(78)
        v_height = user32.GetSystemMetrics(79)

        speech_text = (
            f"Display resolution is {width} by {height} pixels with {monitors} active monitor(s)."
        )

        return {
            "success": True,
            "status": "success",
            "width": width,
            "height": height,
            "monitors": monitors,
            "virtual_width": v_width,
            "virtual_height": v_height,
            "message": speech_text
        }
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to read display metrics: {e}")
        return {"success": False, "status": "error", "message": f"Unable to read display information: {e}"}


def get_system_info() -> Dict[str, Any]:
    """
    Get comprehensive system information (OS, architecture, boot time, CPU, memory).
    """
    try:
        import platform
        uname = platform.uname()
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime_delta = datetime.now() - boot_time
        hours, remainder = divmod(int(uptime_delta.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)

        mem = psutil.virtual_memory()
        total_ram_gb = round(mem.total / (1024 ** 3), 1)

        speech_text = (
            f"Running {uname.system} {uname.release} ({uname.machine}). "
            f"System has been up for {hours} hours and {minutes} minutes with {total_ram_gb} GB RAM."
        )

        return {
            "success": True,
            "status": "success",
            "os": f"{uname.system} {uname.release}",
            "version": uname.version,
            "architecture": uname.machine,
            "hostname": uname.node,
            "cpu": uname.processor or "Unknown CPU",
            "ram_total_gb": total_ram_gb,
            "uptime": f"{hours}h {minutes}m",
            "message": speech_text
        }
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to read system info: {e}")
        return {"success": False, "status": "error", "message": f"Unable to read system info: {e}"}


# Virtual key codes for Windows multimedia keys
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF


def volume_mute_toggle() -> Dict[str, Any]:
    """Toggle audio mute on the Windows master device."""
    try:
        user32 = ctypes.windll.user32
        user32.keybd_event(VK_VOLUME_MUTE, 0, 0, 0)
        user32.keybd_event(VK_VOLUME_MUTE, 0, KEYEVENTF_KEYUP, 0)
        return {"success": True, "message": "Toggled master volume mute."}
    except Exception as e:
        return {"success": False, "message": f"Failed to toggle mute: {e}"}


def volume_up(steps: int = 5) -> Dict[str, Any]:
    """Increase system volume by sending volume up key events."""
    try:
        user32 = ctypes.windll.user32
        for _ in range(max(1, min(25, steps))):
            user32.keybd_event(VK_VOLUME_UP, 0, 0, 0)
            user32.keybd_event(VK_VOLUME_UP, 0, KEYEVENTF_KEYUP, 0)
        return {"success": True, "message": f"Increased volume by {steps} steps."}
    except Exception as e:
        return {"success": False, "message": f"Failed to adjust volume: {e}"}


def volume_down(steps: int = 5) -> Dict[str, Any]:
    """Decrease system volume by sending volume down key events."""
    try:
        user32 = ctypes.windll.user32
        for _ in range(max(1, min(25, steps))):
            user32.keybd_event(VK_VOLUME_DOWN, 0, 0, 0)
            user32.keybd_event(VK_VOLUME_DOWN, 0, KEYEVENTF_KEYUP, 0)
        return {"success": True, "message": f"Decreased volume by {steps} steps."}
    except Exception as e:
        return {"success": False, "message": f"Failed to adjust volume: {e}"}


def get_clipboard_text() -> Dict[str, Any]:
    """
    Retrieve current plain text content from the Windows clipboard.
    """
    try:
        import win32clipboard
        import win32con
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                return {"success": True, "text": data, "message": f"Clipboard content: {data[:100]}..." if len(data) > 100 else f"Clipboard content: {data}"}
            elif win32clipboard.IsClipboardFormatAvailable(win32con.CF_TEXT):
                data = win32clipboard.GetClipboardData(win32con.CF_TEXT)
                text = data.decode('utf-8', errors='ignore')
                return {"success": True, "text": text, "message": f"Clipboard content: {text}"}
            else:
                return {"success": True, "text": "", "message": "Clipboard does not contain readable text."}
        finally:
            win32clipboard.CloseClipboard()
    except Exception as e:
        logger.warning(f"[SYSTEM] win32clipboard failed, attempting ctypes fallback: {e}")
        # ctypes fallback
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            if not user32.OpenClipboard(0):
                return {"success": False, "message": "Could not access clipboard."}
            h_data = user32.GetClipboardData(13) # CF_UNICODETEXT
            if not h_data:
                user32.CloseClipboard()
                return {"success": True, "text": "", "message": "Clipboard is empty."}
            p_data = kernel32.GlobalLock(h_data)
            text = ctypes.c_wchar_p(p_data).value
            kernel32.GlobalUnlock(h_data)
            user32.CloseClipboard()
            return {"success": True, "text": text or "", "message": f"Clipboard text: {text}"}
        except Exception as err:
            return {"success": False, "message": f"Unable to read clipboard: {err}"}


# ─────────────────────────────────────────────────────────────────────────────
# UNIVERSAL DEVICE CONTROL — EXTENDED CAPABILITIES
# ─────────────────────────────────────────────────────────────────────────────

# Windows Virtual-Key codes for toggle keys
VK_CAPITAL   = 0x14   # Caps Lock
VK_NUMLOCK   = 0x90   # Num Lock
VK_SCROLL    = 0x91   # Scroll Lock


def get_toggle_key_states() -> Dict[str, Any]:
    """
    Read the on/off state of Caps Lock, Num Lock, and Scroll Lock.
    """
    try:
        user32 = ctypes.windll.user32
        caps_on   = bool(user32.GetKeyState(VK_CAPITAL)  & 0x0001)
        num_on    = bool(user32.GetKeyState(VK_NUMLOCK)  & 0x0001)
        scroll_on = bool(user32.GetKeyState(VK_SCROLL)   & 0x0001)
        parts = [
            f"Caps Lock is {'ON' if caps_on else 'OFF'}",
            f"Num Lock is {'ON' if num_on else 'OFF'}",
            f"Scroll Lock is {'ON' if scroll_on else 'OFF'}",
        ]
        return {
            "success": True,
            "caps_lock": caps_on,
            "num_lock": num_on,
            "scroll_lock": scroll_on,
            "message": ". ".join(parts) + ".",
        }
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to read toggle key states: {e}")
        return {"success": False, "message": f"Could not read keyboard LED states: {e}"}


def toggle_key(key: str) -> Dict[str, Any]:
    """
    Toggle a keyboard lock key: 'caps', 'num', or 'scroll'.
    """
    import time
    key_map = {
        "caps":   (VK_CAPITAL, "Caps Lock"),
        "num":    (VK_NUMLOCK, "Num Lock"),
        "scroll": (VK_SCROLL,  "Scroll Lock"),
    }
    key_norm = key.lower().strip().replace(" ", "").replace("_", "").replace("lock", "")
    vk_info = key_map.get(key_norm)
    if not vk_info:
        return {"success": False, "message": f"Unknown toggle key '{key}'. Supported: caps, num, scroll."}
    vk_code, key_name = vk_info
    try:
        user32 = ctypes.windll.user32
        user32.keybd_event(vk_code, 0, 0, 0)
        user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)
        # Brief wait for OS to update toggle key state before re-reading
        time.sleep(0.08)
        new_state = bool(user32.GetKeyState(vk_code) & 0x0001)
        state_str = "ON" if new_state else "OFF"
        return {
            "success": True,
            "key": key_name,
            "state": new_state,
            "message": f"{key_name} is now {state_str}.",
        }
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to toggle {key}: {e}")
        return {"success": False, "message": f"Could not toggle {key_name}: {e}"}


def set_key(key: str, desired_state: bool) -> Dict[str, Any]:
    """
    Set a keyboard lock key to a specific ON (True) or OFF (False) state.
    Reads the current state first; only sends a keypress if it needs to change.
    Uses SendInput (modern Windows API) so the key event works even when the
    process does not own keyboard focus.
    """
    import time
    key_map = {
        "caps":   (VK_CAPITAL, "Caps Lock"),
        "num":    (VK_NUMLOCK, "Num Lock"),
        "scroll": (VK_SCROLL,  "Scroll Lock"),
    }
    key_norm = key.lower().strip().replace(" ", "").replace("_", "").replace("lock", "")
    vk_info = key_map.get(key_norm)
    if not vk_info:
        return {"success": False, "message": f"Unknown toggle key '{key}'. Supported: caps, num, scroll."}
    vk_code, key_name = vk_info
    target_str = "ON" if desired_state else "OFF"
    try:
        user32 = ctypes.windll.user32

        def _get_state() -> bool:
            return bool(user32.GetKeyState(vk_code) & 0x0001)

        def _send_key_press():
            """Send a key down + up via SendInput for reliable toggle key handling."""
            KEYEVENTF_KEYUP_FLAG = 0x0002
            KEYEVENTF_EXTENDEDKEY_FLAG = 0x0001
            INPUT_KEYBOARD = 1

            class KEYBDINPUT(ctypes.Structure):
                _fields_ = [
                    ("wVk",         ctypes.c_ushort),
                    ("wScan",       ctypes.c_ushort),
                    ("dwFlags",     ctypes.c_ulong),
                    ("time",        ctypes.c_ulong),
                    ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
                ]

            class INPUT(ctypes.Structure):
                class _I(ctypes.Union):
                    _fields_ = [("ki", KEYBDINPUT)]
                _anonymous_ = ("_i",)
                _fields_  = [("type", ctypes.c_ulong), ("_i", _I)]

            extra = ctypes.c_ulong(0)
            # Key down
            down = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(
                wVk=vk_code, wScan=0, dwFlags=0,
                time=0, dwExtraInfo=ctypes.pointer(extra)))
            # Key up
            up = INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(
                wVk=vk_code, wScan=0, dwFlags=KEYEVENTF_KEYUP_FLAG,
                time=0, dwExtraInfo=ctypes.pointer(extra)))
            sent = user32.SendInput(2, ctypes.byref((INPUT * 2)(down, up)), ctypes.sizeof(INPUT))
            return sent == 2

        current_state = _get_state()
        if current_state == desired_state:
            return {
                "success": True,
                "key": key_name,
                "state": current_state,
                "message": f"{key_name} is already {target_str}. No change made.",
            }

        # Send key press and wait for OS to update state
        _send_key_press()
        time.sleep(0.08)
        new_state = _get_state()
        # One retry for slow hardware
        if new_state == current_state:
            time.sleep(0.08)
            new_state = _get_state()

        if new_state != desired_state:
            # Fallback for background / non-focused console sessions: set virtual keyboard state
            try:
                buf = (ctypes.c_byte * 256)()
                user32.GetKeyboardState(buf)
                buf[vk_code] = 1 if desired_state else 0
                user32.SetKeyboardState(buf)
                new_state = _get_state()
            except Exception:
                pass

        new_str = "ON" if new_state else "OFF"
        if new_state == desired_state:
            return {
                "success": True,
                "key": key_name,
                "state": new_state,
                "message": f"{key_name} turned {new_str}.",
            }
        else:
            return {
                "success": False,
                "key": key_name,
                "state": new_state,
                "message": (
                    f"Sent key event for {key_name} but state did not change "
                    f"(still {new_str}). The OS or hardware may have prevented the change."
                ),
            }
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to set {key} to {target_str}: {e}")
        return {"success": False, "message": f"Could not set {key_name} to {target_str}: {e}"}


def get_wifi_status() -> Dict[str, Any]:
    """
    Get current Wi-Fi / network adapter status using netsh. Windows-only.
    """
    try:
        import subprocess
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True, text=True, timeout=8
        )
        output = result.stdout
        if not output.strip():
            return {
                "success": True,
                "connected": False,
                "message": "No Wi-Fi adapter found or Wi-Fi is disabled.",
            }

        def _field(pattern: str) -> str:
            m = re.search(pattern, output, re.IGNORECASE | re.MULTILINE)
            return m.group(1).strip() if m else ""

        state    = _field(r"^\s+State\s*:\s*(.+)$")
        ssid     = _field(r"^\s+SSID\s*:\s*(.+)$")
        signal   = _field(r"^\s+Signal\s*:\s*(.+)$")

        connected = "connected" in state.lower()
        if connected:
            msg = f"Wi-Fi is connected to '{ssid}' with {signal} signal strength."
        elif state:
            msg = f"Wi-Fi adapter is {state}. Not currently connected."
        else:
            msg = "Could not determine Wi-Fi state."

        return {
            "success": True,
            "connected": connected,
            "ssid": ssid,
            "signal": signal,
            "state": state,
            "message": msg,
        }
    except FileNotFoundError:
        return {"success": True, "connected": False, "message": "Wi-Fi status unavailable on this platform."}
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to get Wi-Fi status: {e}")
        return {"success": False, "message": f"Could not read Wi-Fi status: {e}"}


def list_wifi_networks() -> Dict[str, Any]:
    """
    List available Wi-Fi networks via netsh. Windows-only.
    """
    try:
        import subprocess
        result = subprocess.run(
            ["netsh", "wlan", "show", "networks", "mode=bssid"],
            capture_output=True, text=True, timeout=12
        )
        output = result.stdout
        if not output.strip():
            return {"success": True, "networks": [], "message": "No Wi-Fi networks found."}
        networks = re.findall(r"SSID\s+\d+\s*:\s*(.+)", output, re.IGNORECASE)
        networks = [n.strip() for n in networks if n.strip()]
        msg = (
            f"Found {len(networks)} Wi-Fi network(s): {', '.join(networks[:10])}."
            if networks else "No Wi-Fi networks found nearby."
        )
        return {"success": True, "networks": networks, "message": msg}
    except FileNotFoundError:
        return {"success": True, "networks": [], "message": "Wi-Fi network scan unavailable on this platform."}
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to list Wi-Fi networks: {e}")
        return {"success": False, "message": f"Could not list Wi-Fi networks: {e}"}


def set_wifi_state(enable: bool) -> Dict[str, Any]:
    """
    Enable or disable the Wi-Fi adapter using netsh.
    """
    try:
        import subprocess
        action = "enable" if enable else "disable"
        result = subprocess.run(
            ["netsh", "interface", "set", "interface", "Wi-Fi", action],
            capture_output=True, text=True, timeout=10
        )
        state_str = "enabled" if enable else "disabled"
        if result.returncode == 0:
            return {"success": True, "message": f"Wi-Fi has been {state_str}."}
        err = result.stderr.strip() or result.stdout.strip()
        return {
            "success": False,
            "message": f"Could not {action} Wi-Fi. {err or 'Administrator privileges may be required.'}",
        }
    except FileNotFoundError:
        return {"success": False, "message": "Wi-Fi control is not available on this platform."}
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to set Wi-Fi state: {e}")
        return {"success": False, "message": f"Wi-Fi control failed: {e}"}


def get_bluetooth_status() -> Dict[str, Any]:
    """
    Check Bluetooth adapter status using PowerShell Get-PnpDevice.
    """
    try:
        import subprocess
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-PnpDevice -Class Bluetooth | Select-Object Status,FriendlyName | ConvertTo-Csv -NoTypeInformation"],
            capture_output=True, text=True, timeout=15
        )
        output = result.stdout.strip()
        if not output or result.returncode != 0:
            return {
                "success": True,
                "available": False,
                "message": "Bluetooth adapter was not detected on this device.",
            }
        lines = [l.strip().strip('"') for l in output.splitlines() if l.strip()]
        devices = []
        for line in lines[1:]:
            parts = [p.strip().strip('"') for p in line.split(",")]
            if len(parts) >= 2:
                devices.append({"status": parts[0], "name": parts[1]})
        ok_devs = [d for d in devices if d["status"].upper() in ("OK", "ENABLED")]
        if ok_devs:
            names = ", ".join(d["name"] for d in ok_devs[:5])
            msg = f"Bluetooth is available. Active adapter(s): {names}."
        elif devices:
            msg = f"Bluetooth adapter found but not active. Status: {devices[0]['status']}."
        else:
            msg = "No Bluetooth adapter detected."
        return {"success": True, "available": bool(ok_devs), "adapters": devices, "message": msg}
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to get Bluetooth status: {e}")
        return {"success": False, "message": f"Could not read Bluetooth status: {e}"}


def get_network_adapters() -> Dict[str, Any]:
    """
    List all network adapters with IP addresses using psutil.
    """
    try:
        import socket
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        adapters = []
        for name, addr_list in addrs.items():
            is_up = stats.get(name) and stats[name].isup
            ipv4 = [a.address for a in addr_list if a.family == socket.AF_INET]
            adapters.append({"name": name, "is_up": is_up, "ipv4": ipv4[0] if ipv4 else None})
        active = [a for a in adapters if a["is_up"] and a["ipv4"]]
        if active:
            parts = [f"{a['name']} ({a['ipv4']})" for a in active[:5]]
            msg = "Active network adapters: " + ", ".join(parts) + "."
        else:
            msg = "No active network adapters found."
        return {"success": True, "adapters": adapters, "active": active, "message": msg}
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to list network adapters: {e}")
        return {"success": False, "message": f"Could not list network adapters: {e}"}


def get_hardware_info() -> Dict[str, Any]:
    """
    Get CPU model, GPU, total RAM, and motherboard info.
    """
    try:
        import subprocess
        import platform

        cpu_brand = platform.processor() or "Unknown CPU"
        mem = psutil.virtual_memory()
        total_ram_gb = round(mem.total / (1024 ** 3), 1)

        gpu_name = "Unknown GPU"
        try:
            r = subprocess.run(
                ["wmic", "path", "win32_VideoController", "get", "Name"],
                capture_output=True, text=True, timeout=10
            )
            lines = [l.strip() for l in r.stdout.splitlines() if l.strip() and l.strip().lower() != "name"]
            gpu_name = lines[0] if lines else "Unknown GPU"
        except Exception:
            pass

        board_name = "Unknown Board"
        try:
            r = subprocess.run(
                ["wmic", "baseboard", "get", "Manufacturer,Product"],
                capture_output=True, text=True, timeout=10
            )
            lines = [l.strip() for l in r.stdout.splitlines()
                     if l.strip() and "manufacturer" not in l.lower() and "product" not in l.lower()]
            board_name = lines[0] if lines else "Unknown Board"
        except Exception:
            pass

        physical_cores = psutil.cpu_count(logical=False) or 1
        logical_cores  = psutil.cpu_count(logical=True)  or 1
        msg = (
            f"CPU: {cpu_brand} ({physical_cores} physical / {logical_cores} logical cores). "
            f"GPU: {gpu_name}. RAM: {total_ram_gb} GB total. Motherboard: {board_name}."
        )
        return {
            "success": True,
            "cpu_brand": cpu_brand,
            "gpu_name": gpu_name,
            "board_name": board_name,
            "ram_total_gb": total_ram_gb,
            "physical_cores": physical_cores,
            "logical_cores": logical_cores,
            "message": msg,
        }
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to get hardware info: {e}")
        return {"success": False, "message": f"Could not read hardware info: {e}"}


def get_active_power_plan() -> Dict[str, Any]:
    """
    Report the currently active Windows power plan via powercfg.
    """
    try:
        import subprocess
        result = subprocess.run(
            ["powercfg", "/getactivescheme"],
            capture_output=True, text=True, timeout=8
        )
        output = result.stdout.strip()
        if not output:
            return {"success": False, "message": "Could not read power plan."}
        m = re.search(r'\((.+?)\)', output)
        plan_name = m.group(1).strip() if m else output
        return {"success": True, "plan": plan_name, "message": f"Active power plan: {plan_name}."}
    except FileNotFoundError:
        return {"success": True, "plan": "Unknown", "message": "Power plan information is not available on this platform."}
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to get power plan: {e}")
        return {"success": False, "message": f"Could not read power plan: {e}"}


def list_power_plans() -> Dict[str, Any]:
    """
    List all available Windows power plans via powercfg.
    """
    try:
        import subprocess
        result = subprocess.run(
            ["powercfg", "/list"],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout
        plans = re.findall(r'\((.+?)\)', output)
        if plans:
            msg = "Available power plans: " + ", ".join(plans) + "."
        else:
            msg = "Could not list power plans."
        return {"success": True, "plans": plans, "message": msg}
    except FileNotFoundError:
        return {"success": True, "plans": [], "message": "Power plan listing not available on this platform."}
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to list power plans: {e}")
        return {"success": False, "message": f"Could not list power plans: {e}"}


def get_mouse_info() -> Dict[str, Any]:
    """
    Get current mouse cursor position and primary button swap setting.
    """
    try:
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        user32 = ctypes.windll.user32
        point = POINT()
        user32.GetCursorPos(ctypes.byref(point))
        swap = bool(user32.GetSystemMetrics(23))  # SM_SWAPBUTTON
        swap_str = "swapped (left-handed)" if swap else "standard (right-handed)"
        msg = f"Mouse cursor is at ({point.x}, {point.y}). Button layout: {swap_str}."
        return {"success": True, "x": point.x, "y": point.y, "buttons_swapped": swap, "message": msg}
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to get mouse info: {e}")
        return {"success": False, "message": f"Could not read mouse information: {e}"}


def list_all_processes(sort_by: str = "memory", n: int = 20) -> Dict[str, Any]:
    """
    List all running processes with PID, name, CPU%, and RAM%.
    Returns top-n sorted by sort_by ('memory' or 'cpu').
    """
    try:
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status']):
            try:
                info = p.info
                if info.get('name'):
                    procs.append({
                        "pid": info['pid'],
                        "name": info['name'],
                        "cpu": round(info.get('cpu_percent') or 0.0, 1),
                        "memory": round(info.get('memory_percent') or 0.0, 2),
                        "status": info.get('status', 'unknown'),
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        key = "cpu" if sort_by.lower() == "cpu" else "memory"
        procs.sort(key=lambda x: x[key], reverse=True)
        top = procs[:n]
        summary = ", ".join([f"{p['name']} (PID {p['pid']}, {p[key]}% {key.upper()})" for p in top[:5]])
        msg = f"Found {len(procs)} running process(es). Top by {key.upper()}: {summary}."
        return {"success": True, "processes": top, "total": len(procs), "message": msg}
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to list processes: {e}")
        return {"success": False, "processes": [], "message": f"Could not list processes: {e}"}


def get_uptime() -> Dict[str, Any]:
    """
    Return system uptime in human-readable form.
    """
    try:
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime_delta = datetime.now() - boot_time
        total_secs = int(uptime_delta.total_seconds())
        hours, rem = divmod(total_secs, 3600)
        minutes, _ = divmod(rem, 60)
        if hours >= 24:
            days = hours // 24
            hours = hours % 24
            msg = f"System has been running for {days} day(s), {hours} hour(s), and {minutes} minute(s)."
        else:
            msg = f"System has been running for {hours} hour(s) and {minutes} minute(s)."
        return {"success": True, "hours": hours, "minutes": minutes, "total_seconds": total_secs, "message": msg}
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to get uptime: {e}")
        return {"success": False, "message": f"Could not read system uptime: {e}"}


def get_network_speed() -> Dict[str, Any]:
    """
    Sample network I/O counters over 1 second to estimate current speed.
    """
    try:
        import time
        before = psutil.net_io_counters()
        time.sleep(1)
        after = psutil.net_io_counters()
        sent_kb = (after.bytes_sent - before.bytes_sent) / 1024
        recv_kb = (after.bytes_recv - before.bytes_recv) / 1024
        msg = f"Network speed — Upload: {sent_kb:.1f} KB/s, Download: {recv_kb:.1f} KB/s."
        return {"success": True, "upload_kbps": round(sent_kb, 1), "download_kbps": round(recv_kb, 1), "message": msg}
    except Exception as e:
        logger.error(f"[SYSTEM] Failed to measure network speed: {e}")
        return {"success": False, "message": f"Could not measure network speed: {e}"}
