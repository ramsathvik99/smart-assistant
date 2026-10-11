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

import sys
import os
import re
import time
import threading
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
    volume: Optional[int] = None
    muted: Optional[bool] = None
    brightness: Optional[int] = None
    running_apps: List[str] = field(default_factory=list)
    app_states: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    folder_states: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    location: Optional[Dict[str, Any]] = None
    smart_home_devices: Optional[List[Dict[str, Any]]] = None
    clipboard_state: Optional[Dict[str, Any]] = None
    current_folder: Optional[str] = None
    selected_files: List[str] = field(default_factory=list)
    open_documents: List[Dict[str, Any]] = field(default_factory=list)
    active_document: Optional[Dict[str, Any]] = None
    recent_documents: List[str] = field(default_factory=list)
    observed_categories: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot to a clean dictionary representation."""
        d = asdict(self)
        # Flatten common keys for direct compatibility with existing observation consumers
        d["caps_lock"] = self.toggle_keys.get("caps_lock")
        d["num_lock"] = self.toggle_keys.get("num_lock")
        d["scroll_lock"] = self.toggle_keys.get("scroll_lock")
        d["volume"] = self.volume
        d["muted"] = self.muted
        d["brightness"] = self.brightness
        d["master_volume"] = self.volume
        d["current_folder"] = self.current_folder
        d["selected_files"] = list(self.selected_files)
        d["active_document"] = self.active_document
        d["open_documents"] = list(self.open_documents)
        d["recent_documents"] = list(self.recent_documents)
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


@dataclass
class CanonicalSystemSnapshot:
    """Canonical, read-only snapshot of hardware, OS, and active window state."""
    cpu_model: str = "Unknown"
    cpu_cores: int = 0
    cpu_threads: int = 0
    cpu_usage_percent: float = 0.0
    gpu_model: str = "Unknown"
    gpu_vram_mb: Optional[int] = None
    ram_total_gb: float = 0.0
    ram_available_gb: float = 0.0
    os: str = sys.platform
    display_resolution: str = "Unknown"
    storage_info: Dict[str, Any] = field(default_factory=dict)
    active_application: Optional[str] = None
    currently_focused_window: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def summary_text(self) -> str:
        gpu_str = f"{self.gpu_model}" + (f" ({self.gpu_vram_mb} MB VRAM)" if self.gpu_vram_mb else "")
        return (
            f"CPU: {self.cpu_model} ({self.cpu_cores} cores, {self.cpu_threads} threads)\n"
            f"GPU: {gpu_str}\n"
            f"RAM: {self.ram_total_gb:.2f} GB total ({self.ram_available_gb:.2f} GB available)\n"
            f"OS: {self.os}\n"
            f"Display: {self.display_resolution}\n"
            f"Active App: {self.active_application or 'None'}"
        )


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

    # 6. Audio & System Controls
    if intent in ("AUDIO_DEVICES", "DEVICE_CONTROL") or any(w in text for w in ["audio", "microphone", "speaker", "sound", "volume", "mute", "unmute", "brightness"]):
        categories.add("audio")
        categories.add("system")

    # 7. Location
    if intent == "WEATHER_QUERY" or any(w in text for w in ["location", "where am i", "weather", "city", "temperature"]):
        categories.add("location")

    # 8. Smart Home
    if intent == "SMART_HOME" or any(w in text for w in ["smart device", "smart home", "light", "fan", "bulb", "lamp", "thermostat", "ac"]):
        categories.add("smart_home")

    # 9. Clipboard (Strictly on-demand only)
    if any(w in text for w in ["read clipboard", "check clipboard", "analyze clipboard", "inspect clipboard", "what is on clipboard", "what's in my clipboard", "what is in my clipboard"]):
        categories.add("clipboard")

    # 10. Documents & PDF workflows
    if intent in ("DOCUMENT_INTELLIGENCE", "DOCUMENT_OPERATIONS", "SUMMARIZE", "PDF_OPERATIONS") or any(
        w in text for w in ["pdf", "document", "summarize", "big picture", "compare", "read to me", "read this", "read aloud", "read these"]
    ):
        categories.add("document")
        categories.add("window")

    # Personal, informational, reminder or conversational intents do NOT observe or verify OS desktop windows
    if intent in (
        "REMINDERS", "DAILY_BRIEFING", "NOTES", "GENERAL_CONVERSATION",
        "RAG_SEARCH", "TIME_QUERY", "DATE_QUERY", "CALCULATOR", "TRANSLATION", "RECOMMENDATION", "LEARNING", "UNDO"
    ):
        return categories

    # Fallback default if nothing matched
    if not categories:
        categories.add("window")
        categories.add("app")

    return categories


# ============================================================================
# Safe Explorer Windows Inspection
# ============================================================================

def _inspect_explorer_windows_safe(timeout_sec: float = 1.0) -> Tuple[Optional[str], List[str]]:
    """
    Inspects Windows Explorer for active directory and selected files.
    Runs inside a dedicated worker thread with a strict timeout to prevent
    synchronous COM calls from freezing the main thread if Explorer or network shares hang.
    Returns: (current_folder, selected_files)
    """
    if sys.platform != "win32":
        return None, []

    result: List[Any] = [None, []]

    def _worker():
        try:
            import pythoncom
            pythoncom.CoInitialize()
            try:
                import win32com.client
                shell = win32com.client.Dispatch("Shell.Application")
                for w in shell.Windows():
                    try:
                        name = getattr(w, "Name", "")
                        if "explorer" in name.lower():
                            doc = getattr(w, "Document", None)
                            if doc:
                                folder = getattr(doc, "Folder", None)
                                if folder and hasattr(folder, "Self"):
                                    fpath = folder.Self.Path
                                    if fpath and not result[0]:
                                        result[0] = fpath
                                selected_items = getattr(doc, "SelectedItems", None)
                                if selected_items:
                                    for item in selected_items():
                                        ipath = getattr(item, "Path", None)
                                        if ipath and ipath not in result[1]:
                                            result[1].append(ipath)
                    except Exception:
                        pass
            finally:
                pythoncom.CoUninitialize()
        except Exception:
            pass

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=timeout_sec)
    return result[0], result[1]


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
    categories = relevant_categories if relevant_categories is not None else {"window", "app"}
    if not categories:
        return EnvironmentSnapshot(observed_categories=[])
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

            # Populate running apps and detailed app_states
            try:
                from core.os_gateway.process_ops import _get_cached_process_list
                raw_procs = _get_cached_process_list()
                running_names = {p["name"].lower() for p in raw_procs if p.get("name")}
                snapshot.running_apps = sorted(list(running_names))
                for app_candidate in ("chrome", "notepad", "calculator", "edge", "msedge", "calc"):
                    is_running = any(app_candidate in rn for rn in running_names)
                    is_fg = bool(snapshot.active_application and (app_candidate in snapshot.active_application or snapshot.active_application in app_candidate))
                    snapshot.app_states[app_candidate] = {
                        "running": is_running,
                        "foreground": is_fg,
                        "active": is_fg
                    }
            except Exception:
                pass
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

    # ── 5. File & Folder State (Targeted Only) ────────────────────────────────
    if "files" in categories and target_file:
        try:
            p = os.path.abspath(target_file)
            exists = os.path.exists(p)
            is_dir = os.path.isdir(p) if exists else False
            is_f = os.path.isfile(p) if exists else False

            # Check desktop folder fallback if not found directly
            if not exists:
                try:
                    from modules.system_controller.folder_manager import get_desktop_path
                    cand = os.path.join(get_desktop_path(), target_file)
                    if os.path.exists(cand):
                        p = cand
                        exists = True
                        is_dir = os.path.isdir(p)
                        is_f = os.path.isfile(p)
                except Exception:
                    pass

            if is_dir or not is_f:
                snapshot.folder_states[p] = {
                    "exists": exists,
                    "is_directory": is_dir,
                    "name": os.path.basename(p) or target_file
                }
            snapshot.file_states[p] = {
                "exists": exists,
                "size": os.path.getsize(p) if (exists and is_f) else 0,
                "mtime": os.path.getmtime(p) if exists else 0.0,
                "is_file": is_f,
                "is_directory": is_dir
            }
        except Exception:
            snapshot.file_states[target_file] = {"exists": False, "size": 0, "mtime": 0.0, "is_file": False, "is_directory": False}

    # ── 6. Audio Devices & Audio/System Property State ────────────────────────
    if "audio" in categories or "system" in categories:
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

        try:
            from modules.system_controller import get_volume, get_brightness
            v_info = get_volume()
            snapshot.volume = v_info.get("level")
            snapshot.muted = v_info.get("is_muted")
        except Exception:
            pass

        try:
            from modules.system_controller import get_brightness
            b_info = get_brightness()
            snapshot.brightness = b_info.get("level")
        except Exception:
            pass

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

    # ── 10. Document & File Explorer Structured State ─────────────────────────
    if "document" in categories or "files" in categories:
        folder_path, sel_files = _inspect_explorer_windows_safe(timeout_sec=1.0)
        if folder_path and not snapshot.current_folder:
            snapshot.current_folder = folder_path
        for f in sel_files:
            if f not in snapshot.selected_files:
                snapshot.selected_files.append(f)

        # Also inspect active/foreground window for document viewers
        if snapshot.foreground_window_title:
            fg_title = snapshot.foreground_window_title
            m_doc = re.search(r'([a-zA-Z0-9_\-\s]+\.(?:pdf|docx|pptx|xlsx|txt|md))', fg_title, re.IGNORECASE)
            if m_doc:
                doc_name = m_doc.group(1).strip()
                ext = doc_name.split(".")[-1].lower()
                snapshot.active_document = {
                    "filename": doc_name,
                    "title": fg_title,
                    "document_type": ext,
                    "application": snapshot.active_application or "viewer",
                }

    return snapshot


def get_canonical_system_snapshot(user_id: str = "default") -> CanonicalSystemSnapshot:
    """
    Query the actual local machine through the canonical system information subsystem
    and return an authoritative, read-only snapshot of hardware and OS state.
    """
    snap = CanonicalSystemSnapshot()

    # 1. CPU
    try:
        from modules.system_controller import get_detailed_cpu_info
        cpu_info = get_detailed_cpu_info()
        if isinstance(cpu_info, dict):
            snap.cpu_model = cpu_info.get("cpu_name") or cpu_info.get("processor") or cpu_info.get("model") or snap.cpu_model
            snap.cpu_cores = cpu_info.get("physical_cores") or cpu_info.get("cores") or 0
            snap.cpu_threads = cpu_info.get("logical_processors") or cpu_info.get("logical_cores") or cpu_info.get("threads") or 0
            snap.cpu_usage_percent = float(cpu_info.get("overall_percent") or cpu_info.get("total_usage_percent") or cpu_info.get("usage") or 0.0)
    except Exception:
        pass

    # 2. RAM
    try:
        from modules.system_controller import get_detailed_ram_metrics
        ram_info = get_detailed_ram_metrics()
        if isinstance(ram_info, dict):
            snap.ram_total_gb = float(ram_info.get("total_gb") or 0.0)
            snap.ram_available_gb = float(ram_info.get("available_gb") or 0.0)
    except Exception:
        pass

    # 3. GPU
    try:
        from modules.system_controller import get_gpu_telemetry
        gpu_info = get_gpu_telemetry(detailed=True)
        if isinstance(gpu_info, dict):
            primary = gpu_info.get("primary_gpu") if isinstance(gpu_info.get("primary_gpu"), dict) else {}
            snap.gpu_model = primary.get("name") or gpu_info.get("name") or gpu_info.get("model") or snap.gpu_model
            vram = primary.get("vram_mb") or gpu_info.get("total_memory_mb") or gpu_info.get("vram_mb")
            snap.gpu_vram_mb = int(vram) if vram is not None else None
    except Exception:
        pass

    # 4. OS & Display
    try:
        import platform
        snap.os = f"{platform.system()} {platform.release()}"
    except Exception:
        snap.os = sys.platform

    try:
        from modules.system_controller import get_display_info
        disp = get_display_info()
        if isinstance(disp, dict):
            if disp.get("width") and disp.get("height"):
                snap.display_resolution = f"{disp['width']}x{disp['height']}"
            elif disp.get("resolution"):
                snap.display_resolution = disp["resolution"]
    except Exception:
        pass

    # 5. Storage
    try:
        from modules.system_controller import get_disk_space
        disk = get_disk_space()
        if isinstance(disk, dict):
            snap.storage_info = disk
    except Exception:
        pass

    # 6. Active Application & Window
    try:
        env = observe_environment(user_id=user_id, relevant_categories={"window", "app"})
        snap.active_application = env.active_application
        snap.currently_focused_window = env.foreground_window_title
    except Exception:
        pass

    return snap


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
    if not before or not after:
        return diff

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

    # 10. Application Running & Focus State Changes
    all_app_keys = set(before.app_states.keys()).union(set(after.app_states.keys()))
    for app_name in all_app_keys:
        b_app = before.app_states.get(app_name, {})
        a_app = after.app_states.get(app_name, {})
        b_run = b_app.get("running", False)
        a_run = a_app.get("running", False)
        b_fg = b_app.get("foreground", False)
        a_fg = a_app.get("foreground", False)

        if not b_run and a_run:
            changes.append(f"APP_{app_name.upper()}_OPENED")
            details[f"app_{app_name}"] = {"transition": "CLOSED -> OPEN", "running": True}
            summaries.append(f"Application '{app_name}' opened (CLOSED -> OPEN)")
        elif b_run and not a_run:
            changes.append(f"APP_{app_name.upper()}_CLOSED")
            details[f"app_{app_name}"] = {"transition": "OPEN -> CLOSED", "running": False}
            summaries.append(f"Application '{app_name}' closed (OPEN -> CLOSED)")
        elif b_run and a_run:
            if not b_fg and a_fg:
                changes.append(f"APP_{app_name.upper()}_ACTIVATED")
                details[f"app_{app_name}"] = {"transition": "OPEN -> ACTIVE", "foreground": True}
                summaries.append(f"Application '{app_name}' activated (OPEN -> ACTIVE)")
            elif b_fg and not a_fg:
                changes.append(f"APP_{app_name.upper()}_BACKGROUNDED")
                details[f"app_{app_name}"] = {"transition": "ACTIVE -> BACKGROUND", "foreground": False}
                summaries.append(f"Application '{app_name}' moved to background (ACTIVE -> BACKGROUND)")

    # 11. Folder State Changes
    all_folders = set(before.folder_states.keys()).union(set(after.folder_states.keys()))
    for fold_path in all_folders:
        b_fold = before.folder_states.get(fold_path, {})
        a_fold = after.folder_states.get(fold_path, {})
        b_f_exists = b_fold.get("exists", False)
        a_f_exists = a_fold.get("exists", False)
        fold_name = b_fold.get("name") or a_fold.get("name") or os.path.basename(fold_path)

        if not b_f_exists and a_f_exists:
            changes.append("FOLDER_CREATED")
            details[f"folder_{fold_name}"] = {"transition": "MISSING -> EXISTS", "path": fold_path}
            summaries.append(f"Folder '{fold_name}' was created (MISSING -> EXISTS)")
        elif b_f_exists and not a_f_exists:
            changes.append("FOLDER_DELETED")
            details[f"folder_{fold_name}"] = {"transition": "EXISTS -> MISSING", "path": fold_path}
            summaries.append(f"Folder '{fold_name}' was deleted (EXISTS -> MISSING)")

    # 12. Deterministic System Property Changes (Volume, Brightness, Mute)
    if before.volume is not None and after.volume is not None and before.volume != after.volume:
        changes.append("VOLUME_CHANGED")
        details["system_volume"] = {"transition": f"volume {before.volume} -> volume {after.volume}", "before": before.volume, "after": after.volume}
        summaries.append(f"Volume changed from {before.volume}% to {after.volume}%")

    if before.muted is not None and after.muted is not None and before.muted != after.muted:
        tr = "unmuted -> muted" if after.muted else "muted -> unmuted"
        changes.append("MUTE_STATE_CHANGED")
        details["system_mute"] = {"transition": tr, "before": before.muted, "after": after.muted}
        summaries.append(f"Audio mute state changed ({tr})")

    if before.brightness is not None and after.brightness is not None and before.brightness != after.brightness:
        changes.append("BRIGHTNESS_CHANGED")
        details["system_brightness"] = {"transition": f"brightness {before.brightness} -> brightness {after.brightness}", "before": before.brightness, "after": after.brightness}
        summaries.append(f"Brightness changed from {before.brightness}% to {after.brightness}%")

    diff.has_changes = len(changes) > 0
    diff.changes = changes
    diff.details = details
    diff.meaningful_summary = "; ".join(summaries) if summaries else "No significant state changes detected."

    return diff
