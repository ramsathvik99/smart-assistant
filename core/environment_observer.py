"""
Environment Observer & State Difference Detector for NOVA (PHASE 5)

Provides a lightweight, read-only observation layer that captures real OS / hardware / 
subsystem state before and after actions, and detects meaningful semantic state changes.

Key Principles:
- READ-ONLY: Never executes side-effects or modifies OS/subsystem state.
- RELEVANCE FILTERED: Only queries subsystems relevant to the current intent/action.
- USER-ISOLATED: User-specific state (tasks, paired devices, smart home) is strictly scoped by user_id.
- TRUTHFUL / EVIDENCE-BASED: Distinguishes True, False, and UNKNOWN. Never fabricates state.
- NO CONTINUOUS POLLING: Action-triggered and explicitly requested queries only.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class EnvironmentSnapshot:
    """Read-only snapshot of observed environment state at a given instant."""
    timestamp: float = field(default_factory=time.time)
    active_application: Optional[str] = None
    active_window: Optional[Dict[str, Any]] = None
    foreground_window_title: Optional[str] = None
    active_tasks: List[Dict[str, Any]] = field(default_factory=list)
    connected_devices: List[Dict[str, Any]] = field(default_factory=list)
    file_states: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    toggle_keys: Dict[str, Optional[bool]] = field(default_factory=dict)
    audio_devices: Optional[Dict[str, Any]] = None
    location: Optional[Dict[str, Any]] = None
    smart_home_devices: Optional[List[Dict[str, Any]]] = None
    clipboard_state: Optional[Dict[str, Any]] = None
    observed_categories: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot to a clean dictionary representation."""
        d = asdict(self)
        # Flatten common keys for direct compatibility with existing observation consumers
        d["caps_lock"] = self.toggle_keys.get("caps_lock")
        d["num_lock"] = self.toggle_keys.get("num_lock")
        d["scroll_lock"] = self.toggle_keys.get("scroll_lock")
        return d


@dataclass
class StateDifference:
    """Semantic comparison between two EnvironmentSnapshot instances."""
    has_changes: bool = False
    changes: List[str] = field(default_factory=list)
    details: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    meaningful_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# Relevance Filtering
# ============================================================================

def select_relevant_categories(
    intent_name: str,
    user_input: str = "",
    target_hint: Optional[str] = None,
) -> Set[str]:
    """
    Determine which observation categories are relevant for a command/intent.
    Prevents unnecessary disk, network, or process enumeration.
    """
    categories: Set[str] = set()
    text = (user_input or "").lower().strip()
    intent = (intent_name or "").upper().strip()

    # 1. Window & Application
    if intent in ("OPEN_APPLICATION", "WINDOW_CONTEXT") or any(
        w in text for w in ["open ", "launch ", "window", "app", "chrome", "edge", "notepad", "close "]
    ):
        categories.add("window")
        categories.add("app")

    # 2. Tasks
    if intent == "TASK_MANAGEMENT" or any(w in text for w in ["task", "background task", "queue"]):
        categories.add("tasks")

    # 3. Devices & Mobile
    if any(w in text for w in ["phone", "mobile", "device", "pair", "connect my phone", "paired devices"]):
        categories.add("devices")

    # 4. Keyboard Toggle Keys
    if any(w in text for w in ["caps lock", "num lock", "scroll lock", "toggle key", "keyboard"]):
        categories.add("toggle_keys")

    # 5. File System
    if intent == "FILE_OPERATIONS" or target_hint or any(
        w in text for w in [".txt", ".pdf", ".docx", ".pptx", ".xlsx", "file", "folder", "directory", "clean logs"]
    ):
        categories.add("files")

    # 6. Audio Devices
    if intent == "AUDIO_DEVICES" or any(w in text for w in ["audio", "microphone", "speaker", "sound", "volume", "mute"]):
        categories.add("audio")

    # 7. Location
    if intent == "WEATHER_QUERY" or any(w in text for w in ["location", "where am i", "weather", "city", "temperature"]):
        categories.add("location")

    # 8. Smart Home
    if intent == "SMART_HOME" or any(w in text for w in ["smart device", "smart home", "light", "fan", "bulb", "lamp", "thermostat", "ac"]):
        categories.add("smart_home")

    # 9. Clipboard (Strictly on-demand only)
    if any(w in text for w in ["read clipboard", "check clipboard", "analyze clipboard", "inspect clipboard", "what is on clipboard", "what's in my clipboard", "what is in my clipboard"]):
        categories.add("clipboard")

    # Fallback default if nothing matched
    if not categories:
        categories.add("window")
        categories.add("app")

    return categories


# ============================================================================
# Environment Observer
# ============================================================================

def observe_environment(
    user_id: str = "default",
    relevant_categories: Optional[Set[str]] = None,
    target_file: Optional[str] = None,
    explicit_clipboard: bool = False,
) -> EnvironmentSnapshot:
    """
    Capture the current state of the environment for selected relevant categories.
    
    Strictly READ-ONLY and user-isolated.
    """
    categories = relevant_categories or {"window", "app"}
    snapshot = EnvironmentSnapshot(observed_categories=sorted(list(categories)))
    uid_int = int(user_id) if str(user_id).isdigit() else 0

    # ── 1. Window & Application ───────────────────────────────────────────────
    if "window" in categories or "app" in categories:
        try:
            from skills.window_management.window_context import get_foreground_window_info
            win_info = get_foreground_window_info()
            if win_info:
                snapshot.active_window = win_info
                snapshot.foreground_window_title = win_info.get("title")
                title_lower = (win_info.get("title") or "").lower()
                class_lower = (win_info.get("class_name") or "").lower()

                if "youtube" in title_lower:
                    snapshot.active_application = "youtube"
                elif "chrome" in title_lower or "google" in title_lower or "chrome" in class_lower:
                    snapshot.active_application = "chrome"
                elif "msedge" in title_lower or "edge" in title_lower:
                    snapshot.active_application = "msedge"
                elif "notepad" in title_lower or "notepad" in class_lower:
                    snapshot.active_application = "notepad"
                else:
                    proc = title_lower.split(" - ")[-1].strip() if " - " in title_lower else title_lower
                    snapshot.active_application = proc or "unknown"
        except Exception:
            snapshot.active_application = "unknown"

    # ── 2. Toggle Keys ────────────────────────────────────────────────────────
    if "toggle_keys" in categories or "device" in categories:
        try:
            from modules.system_controller import get_toggle_key_states
            key_states = get_toggle_key_states()
            if isinstance(key_states, dict):
                snapshot.toggle_keys = {
                    "caps_lock": key_states.get("caps_lock", key_states.get("CapsLock")),
                    "num_lock": key_states.get("num_lock", key_states.get("NumLock")),
                    "scroll_lock": key_states.get("scroll_lock", key_states.get("ScrollLock")),
                }
        except Exception:
            snapshot.toggle_keys = {"caps_lock": None, "num_lock": None, "scroll_lock": None}

    # ── 3. Background Tasks (User-Isolated) ───────────────────────────────────
    if "tasks" in categories:
        try:
            from skills.task_management.task_queue import TaskQueue
            tq = TaskQueue.get_instance() if hasattr(TaskQueue, "get_instance") else None
            if tq is None:
                from core.unified_command_router import unified_router
                tq = getattr(unified_router, "_task_queue", None)
            if tq:
                tasks = tq.list_user_tasks(uid_int, limit=10)
                snapshot.active_tasks = [t if isinstance(t, dict) else t.to_dict() for t in tasks]
        except Exception:
            snapshot.active_tasks = []

    # ── 4. Paired Devices (User-Isolated) ─────────────────────────────────────
    if "devices" in categories:
        try:
            from skills.device_management.device_registry import DeviceRegistry
            registry = DeviceRegistry()
            devices = registry.list_devices(uid_int)
            snapshot.connected_devices = [d.to_dict() if hasattr(d, "to_dict") else dict(d) for d in devices]
        except Exception:
            snapshot.connected_devices = []

    # ── 5. File State (Targeted Only) ─────────────────────────────────────────
    if "files" in categories and target_file:
        try:
            p = os.path.abspath(target_file)
            exists = os.path.exists(p)
            snapshot.file_states[p] = {
                "exists": exists,
                "size": os.path.getsize(p) if exists else 0,
                "mtime": os.path.getmtime(p) if exists else 0.0,
                "is_file": os.path.isfile(p) if exists else False,
            }
        except Exception:
            snapshot.file_states[target_file] = {"exists": False, "size": 0, "mtime": 0.0, "is_file": False}

    # ── 6. Audio Devices ──────────────────────────────────────────────────────
    if "audio" in categories:
        try:
            from skills.audio_management.audio_devices import list_devices
            inputs = list_devices("input")
            outputs = list_devices("output")
            snapshot.audio_devices = {
                "inputs": inputs,
                "outputs": outputs,
                "status": "available" if (inputs or outputs) else "unavailable",
            }
        except Exception:
            snapshot.audio_devices = {"inputs": [], "outputs": [], "status": "UNKNOWN"}

    # ── 7. Location ───────────────────────────────────────────────────────────
    if "location" in categories:
        try:
            from skills.device_location.location_detector import get_location_detector
            loc = get_location_detector().get_current_location()
            if loc and loc.get("city") and loc.get("city") != "Unknown Location":
                snapshot.location = loc
            else:
                snapshot.location = {"status": "UNKNOWN", "city": "UNKNOWN"}
        except Exception:
            snapshot.location = {"status": "UNKNOWN", "city": "UNKNOWN"}

    # ── 8. Smart Home Devices (User-Isolated) ─────────────────────────────────
    if "smart_home" in categories:
        try:
            from skills.smart_home.storage import get_smart_home_storage
            storage = get_smart_home_storage()
            devs = storage.list_devices(uid_int)
            if devs is not None:
                snapshot.smart_home_devices = [d.to_dict() if hasattr(d, "to_dict") else dict(d) for d in devs]
            else:
                snapshot.smart_home_devices = []
        except Exception:
            snapshot.smart_home_devices = None  # UNKNOWN

    # ── 9. Clipboard (Explicit Request Only) ──────────────────────────────────
    if "clipboard" in categories or explicit_clipboard:
        try:
            from skills.clipboard.clipboard_analyzer import analyze_clipboard
            snapshot.clipboard_state = analyze_clipboard()
        except Exception:
            snapshot.clipboard_state = {"success": False, "category": "UNKNOWN"}

    return snapshot


# ============================================================================
# State Difference Detector
# ============================================================================

def compare_snapshots(
    before: EnvironmentSnapshot,
    after: EnvironmentSnapshot,
) -> StateDifference:
    """
    Compare two environment snapshots and identify meaningful, semantic changes.
    Does NOT emit false positive events for non-semantic or unobserved variations.
    """
    diff = StateDifference()
    changes: List[str] = []
    details: Dict[str, Dict[str, Any]] = {}
    summaries: List[str] = []

    # 1. Application Change
    if before.active_application and after.active_application:
        b_app = before.active_application.strip().lower()
        a_app = after.active_application.strip().lower()
        if b_app != a_app and b_app != "unknown" and a_app != "unknown":
            changes.append("APPLICATION_CHANGED")
            details["application"] = {"before": before.active_application, "after": after.active_application}
            summaries.append(f"Application changed from '{before.active_application}' to '{after.active_application}'")

    # 2. Window Change
    if before.active_window and after.active_window:
        b_hwnd = before.active_window.get("hwnd")
        a_hwnd = after.active_window.get("hwnd")
        b_title = (before.active_window.get("title") or "").strip()
        a_title = (after.active_window.get("title") or "").strip()
        
        # Only report window change if hwnd changed or title changed significantly
        if (b_hwnd and a_hwnd and b_hwnd != a_hwnd) or (b_title and a_title and b_title != a_title):
            changes.append("ACTIVE_WINDOW_CHANGED")
            details["active_window"] = {"before": b_title, "after": a_title}
            summaries.append(f"Active window changed to '{a_title}'")

    # 3. Toggle Keys Change
    for k in ("caps_lock", "num_lock", "scroll_lock"):
        b_val = before.toggle_keys.get(k)
        a_val = after.toggle_keys.get(k)
        if b_val is not None and a_val is not None and b_val != a_val:
            change_name = f"{k.upper()}_CHANGED"
            changes.append(change_name)
            details[k] = {"before": b_val, "after": a_val}
            summaries.append(f"{k.replace('_', ' ').title()} changed from {b_val} to {a_val}")

    # 4. Background Tasks Change
    b_task_ids = {str(t.get("task_id", t.get("id"))): t for t in before.active_tasks}
    a_task_ids = {str(t.get("task_id", t.get("id"))): t for t in after.active_tasks}

    # New tasks
    for tid, t_data in a_task_ids.items():
        if tid not in b_task_ids:
            changes.append("TASK_STARTED")
            details[f"task_started_{tid}"] = {"task_id": tid, "status": t_data.get("status", "pending")}
            summaries.append(f"Task '{tid}' was started")
        else:
            # Status change
            b_st = b_task_ids[tid].get("status")
            a_st = t_data.get("status")
            if b_st != a_st:
                if a_st in ("completed", "done", "finished"):
                    changes.append("TASK_COMPLETED")
                elif a_st in ("cancelled", "stopped"):
                    changes.append("TASK_CANCELLED")
                elif a_st in ("failed", "error"):
                    changes.append("TASK_FAILED")
                else:
                    changes.append("TASK_STATUS_CHANGED")
                details[f"task_status_{tid}"] = {"before": b_st, "after": a_st}
                summaries.append(f"Task '{tid}' status changed from '{b_st}' to '{a_st}'")

    # 5. Connected Devices Change
    b_dev_ids = {str(d.get("device_id")): d for d in before.connected_devices}
    a_dev_ids = {str(d.get("device_id")): d for d in after.connected_devices}

    for did, d_data in a_dev_ids.items():
        if did not in b_dev_ids:
            changes.append("DEVICE_CONNECTED")
            details[f"device_connected_{did}"] = {"device": d_data.get("name", did)}
            summaries.append(f"Device '{d_data.get('name', did)}' connected")
        else:
            b_online = b_dev_ids[did].get("online")
            a_online = d_data.get("online")
            if b_online != a_online:
                if a_online:
                    changes.append("DEVICE_CONNECTED")
                    summaries.append(f"Device '{d_data.get('name', did)}' came online")
                else:
                    changes.append("DEVICE_DISCONNECTED")
                    summaries.append(f"Device '{d_data.get('name', did)}' went offline")
                details[f"device_online_{did}"] = {"before": b_online, "after": a_online}

    for did, d_data in b_dev_ids.items():
        if did not in a_dev_ids:
            changes.append("DEVICE_DISCONNECTED")
            details[f"device_removed_{did}"] = {"device": d_data.get("name", did)}
            summaries.append(f"Device '{d_data.get('name', did)}' was removed")

    # 6. File State Changes
    all_files = set(before.file_states.keys()).union(set(after.file_states.keys()))
    for fp in all_files:
        b_f = before.file_states.get(fp, {})
        a_f = after.file_states.get(fp, {})
        b_exists = b_f.get("exists", False)
        a_exists = a_f.get("exists", False)

        if not b_exists and a_exists:
            changes.append("FILE_CREATED")
            details[f"file_created_{os.path.basename(fp)}"] = {"path": fp}
            summaries.append(f"File '{os.path.basename(fp)}' was created")
        elif b_exists and not a_exists:
            changes.append("FILE_DELETED")
            details[f"file_deleted_{os.path.basename(fp)}"] = {"path": fp}
            summaries.append(f"File '{os.path.basename(fp)}' was deleted")
        elif b_exists and a_exists:
            if b_f.get("size") != a_f.get("size") or b_f.get("mtime") != a_f.get("mtime"):
                changes.append("FILE_MODIFIED")
                details[f"file_modified_{os.path.basename(fp)}"] = {
                    "path": fp,
                    "before_size": b_f.get("size"),
                    "after_size": a_f.get("size"),
                }
                summaries.append(f"File '{os.path.basename(fp)}' was modified")

    # 7. Audio Device Changes
    if before.audio_devices and after.audio_devices:
        b_outs = before.audio_devices.get("outputs", [])
        a_outs = after.audio_devices.get("outputs", [])
        if b_outs != a_outs:
            changes.append("AUDIO_DEVICE_CHANGED")
            details["audio_outputs"] = {"before": b_outs, "after": a_outs}
            summaries.append("Audio output configuration changed")

    # 8. Location Changes
    if before.location and after.location:
        b_city = before.location.get("city")
        a_city = after.location.get("city")
        if b_city and a_city and b_city != "UNKNOWN" and a_city != "UNKNOWN" and b_city != a_city:
            changes.append("LOCATION_CHANGED")
            details["location"] = {"before": b_city, "after": a_city}
            summaries.append(f"Location changed from '{b_city}' to '{a_city}'")

    # 9. Smart Home State Changes
    if before.smart_home_devices is not None and after.smart_home_devices is not None:
        b_sh = {str(d.get("id", d.get("device_id", d.get("name")))): d for d in before.smart_home_devices}
        a_sh = {str(d.get("id", d.get("device_id", d.get("name")))): d for d in after.smart_home_devices}
        for did, d_data in a_sh.items():
            if did in b_sh:
                b_on = b_sh[did].get("is_on")
                a_on = d_data.get("is_on")
                if b_on is not None and a_on is not None and b_on != a_on:
                    changes.append("SMART_HOME_STATE_CHANGED")
                    details[f"smart_device_{did}"] = {"before_on": b_on, "after_on": a_on, "name": d_data.get("name", did)}
                    summaries.append(f"Smart device '{d_data.get('name', did)}' turned {'ON' if a_on else 'OFF'}")

    diff.has_changes = len(changes) > 0
    diff.changes = changes
    diff.details = details
    diff.meaningful_summary = "; ".join(summaries) if summaries else "No significant state changes detected."

    return diff
