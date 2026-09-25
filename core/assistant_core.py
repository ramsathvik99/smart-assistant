"""
Smart Assistant — Canonical Assistant Core & Service Bus
Single Source of Truth for runtime state, authenticated user context,
and backend service coordination. Decoupled from any presentation layer.
"""

import time
import threading
import psutil
from typing import Callable, Optional, Dict, Any, List

from core.state_manager import state_manager


class AssistantCore:
    """
    Canonical Assistant Core controller.
    Ensures both PyQt6 Desktop UI, Web Dashboard, and background services
    share a single unified runtime state without duplicate databases,
    memory systems, or routers.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AssistantCore, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        self._state = "idle"
        self._user_id: Optional[int] = None
        self._username: str = "guest"
        self._assistant_name: str = "Assistant"
        self._start_time = time.time()
        self._audio_level: float = 0.0
        self._last_speech: str = ""
        self._state_listeners: List[Callable[[str], None]] = []
        self._visual_listeners: List[Callable[[Any], None]] = []
        self._active_visual_responses: Dict[str, Any] = {}
        self._ui_handlers: Dict[str, List[Callable[[], None]]] = {}
        self._state_lock = threading.Lock()
        self._initialized = True
        print("[CORE] Canonical Assistant Core initialized as Single Source of Truth.")

    # ── User Context & Strict Isolation ──────────────────────────────────────
    def set_authenticated_user(self, user_id: int, username: str, assistant_name: str = None):
        """Set active authenticated user context."""
        with self._state_lock:
            self._user_id = user_id
            self._username = username or "user"
            if assistant_name:
                self._assistant_name = assistant_name
            else:
                try:
                    from legacy.memory_manager import get_assistant_name_db
                    self._assistant_name = get_assistant_name_db(user_id) or "Assistant"
                except Exception:
                    self._assistant_name = "Assistant"
        print(f"[CORE] Authenticated user registered: {self._username} (ID: {self._user_id}) | Assistant: {self._assistant_name}")
        try:
            from core.proactive_observer import proactive_coordinator
            if user_id and user_id != 0:
                proactive_coordinator.start(str(user_id))
            else:
                proactive_coordinator.logout_user()
        except Exception as e:
            print(f"[CORE] Proactive coordinator user context update error: {e}")

    def get_user_context(self) -> Dict[str, Any]:
        """Return active user context ensuring isolation."""
        with self._state_lock:
            if self._user_id is None:
                try:
                    from instance.config import settings
                    uid = getattr(settings, "CURRENT_USER_ID", None) or settings.get_last_user()
                    if uid:
                        from legacy.memory_manager import get_username_by_id, get_assistant_name_db
                        uname = get_username_by_id(uid)
                        if uname:
                            self._user_id = uid
                            self._username = uname
                            self._assistant_name = get_assistant_name_db(uid) or "Assistant"
                except Exception:
                    pass
            return {
                "user_id": self._user_id,
                "username": self._username,
                "assistant_name": self._assistant_name,
                "authenticated": self._user_id is not None
            }

    def set_assistant_name(self, name: str):
        """Update assistant name and persist to user preferences."""
        if not name:
            return
        with self._state_lock:
            self._assistant_name = name
            uid = self._user_id
        if uid:
            try:
                from legacy.memory_manager import set_assistant_name_db
                set_assistant_name_db(uid, name)
            except Exception as e:
                print(f"[CORE] Error saving assistant name: {e}")

    # ── Real-Time State Management ───────────────────────────────────────────
    def get_state(self) -> str:
        """Return active assistant state: idle, listening, thinking, planning, executing, speaking, error."""
        with self._state_lock:
            return self._state

    def set_state(self, state: str):
        """Update active state and notify all attached UI listeners."""
        with self._state_lock:
            if state == self._state:
                return
            self._state = state
            listeners = list(self._state_listeners)

        for callback in listeners:
            try:
                callback(state)
            except Exception as e:
                print(f"[CORE] Error notifying state listener: {e}")

    def register_state_listener(self, callback: Callable[[str], None]):
        """Attach a listener (e.g. PyQt6 signal or Dashboard broadcast) for state changes."""
        with self._state_lock:
            if callback not in self._state_listeners:
                self._state_listeners.append(callback)

    def unregister_state_listener(self, callback: Callable[[str], None]):
        with self._state_lock:
            if callback in self._state_listeners:
                self._state_listeners.remove(callback)

    # ── Presentation Layer Handlers (Decoupled UI Bridge) ────────────────────
    def register_ui_action_handler(self, action: str, callback: Callable[[], None]):
        """Register presentation layer action callbacks (e.g. open_dashboard)."""
        with self._state_lock:
            if not hasattr(self, "_ui_handlers"):
                self._ui_handlers = {}
            if action not in self._ui_handlers:
                self._ui_handlers[action] = []
            if callback not in self._ui_handlers[action]:
                self._ui_handlers[action].append(callback)

    def unregister_ui_action_handler(self, action: str, callback: Callable[[], None]):
        with self._state_lock:
            if hasattr(self, "_ui_handlers") and action in self._ui_handlers:
                if callback in self._ui_handlers[action]:
                    self._ui_handlers[action].remove(callback)

    def trigger_ui_action(self, action: str) -> bool:
        """Trigger presentation layer action from router, voice, or background services."""
        with self._state_lock:
            handlers = list(getattr(self, "_ui_handlers", {}).get(action, []))
        if not handlers:
            return False
        for handler in handlers:
            try:
                handler()
            except Exception as e:
                print(f"[CORE] Error executing UI handler for {action}: {e}")
        return True

    # ── Ephemeral Visual Response Surface Handlers ───────────────────────────
    def register_visual_listener(self, callback: Callable[[Any], None]):
        """Attach a listener (e.g. PyQt6 VisualResponsePanel) for visual response popups."""
        with self._state_lock:
            if callback not in self._visual_listeners:
                self._visual_listeners.append(callback)

    def unregister_visual_listener(self, callback: Callable[[Any], None]):
        with self._state_lock:
            if callback in self._visual_listeners:
                self._visual_listeners.remove(callback)

    def show_visual_response(self, visual_response: Any):
        """Dispatch a visual response to all registered presentation surfaces."""
        vr_dict = visual_response.to_dict() if hasattr(visual_response, "to_dict") else dict(visual_response)
        uid = str(vr_dict.get("user_id") or self._user_id or "default")
        with self._state_lock:
            self._active_visual_responses[uid] = vr_dict
            listeners = list(self._visual_listeners)

        for callback in listeners:
            try:
                callback(vr_dict)
            except Exception as e:
                print(f"[CORE] Error dispatching visual response: {e}")

    def dismiss_visual_response(self, user_id: Optional[str] = None):
        """Dismiss visual response for the user (or all if user_id is None)."""
        with self._state_lock:
            if user_id:
                self._active_visual_responses.pop(str(user_id), None)
            elif self._user_id:
                self._active_visual_responses.pop(str(self._user_id), None)
            else:
                self._active_visual_responses.clear()
            listeners = list(self._visual_listeners)

        for callback in listeners:
            try:
                callback(None)  # None signals dismissal
            except Exception as e:
                print(f"[CORE] Error notifying visual dismissal: {e}")

    def get_active_visual_response(self, user_id: Optional[str] = None) -> Optional[Any]:
        """Get currently active visual response for user."""
        with self._state_lock:
            if user_id:
                res = self._active_visual_responses.get(str(user_id))
            elif self._user_id and str(self._user_id) in self._active_visual_responses:
                res = self._active_visual_responses.get(str(self._user_id))
            elif self._active_visual_responses:
                res = list(self._active_visual_responses.values())[-1]
            else:
                res = None

        if res is not None:
            from core.visual_response import VisualResponse
            return VisualResponse.from_dict(res)
        return None

    def set_audio_level(self, level: float):
        self._audio_level = max(0.0, min(1.0, float(level)))

    def get_audio_level(self) -> float:
        return self._audio_level

    # ── Canonical Command Execution ──────────────────────────────────────────
    def execute_command(self, text: str, user_id: Optional[int] = None) -> str:
        """
        Execute command through the canonical unified command router.
        Ensures identical handling whether sent from PyQt6 UI, Web Dashboard, or Voice.
        """
        if not text or not text.strip():
            return ""

        effective_uid = user_id or self._user_id
        self.set_state("thinking")
        try:
            from legacy.assistant import process_input
            response = process_input(text.strip())
            self.set_state("idle")
            return response or "Command executed."
        except Exception as e:
            self.set_state("error")
            print(f"[CORE] Command execution error: {e}")
            return f"Error executing command: {e}"

    # ── Canonical Task Control ───────────────────────────────────────────────
    def get_task_info(self) -> Dict[str, Any]:
        """Get live task status from state_manager."""
        return state_manager.get_current_task_info()

    def cancel_task(self):
        """Trigger canonical interrupt to stop ongoing tasks."""
        state_manager.trigger_interrupt()
        state_manager.complete_task(success=False)
        self.set_state("idle")
        print("[CORE] Current task cancelled via canonical interrupt signal.")

    # ── Canonical Memory Hub (PostgreSQL) ────────────────────────────────────
    def get_user_memory(self, user_id: Optional[int] = None) -> Dict[str, Any]:
        """Fetch user key-value memories with strict user isolation."""
        target_uid = user_id if user_id is not None else self._user_id
        if not target_uid:
            return {}
        try:
            from legacy.memory_manager import load_user_memory
            return load_user_memory(target_uid) or {}
        except Exception as e:
            print(f"[CORE] Error fetching user memory: {e}")
            return {}

    def get_user_notes(self, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Fetch user notes with strict user isolation."""
        target_uid = user_id if user_id is not None else self._user_id
        if not target_uid:
            return []
        try:
            from legacy.memory_manager import get_notes_db
            raw_notes = get_notes_db(target_uid) or []
            normalized = []
            for i, n in enumerate(raw_notes, 1):
                if isinstance(n, str):
                    normalized.append({"id": i, "content": n})
                elif isinstance(n, dict):
                    normalized.append({
                        "id": n.get("id", i),
                        "content": n.get("note", n.get("content", str(n)))
                    })
                else:
                    normalized.append({"id": i, "content": str(n)})
            return normalized
        except Exception as e:
            print(f"[CORE] Error fetching user notes: {e}")
            return []

    # ── Canonical Reminders (PostgreSQL) ─────────────────────────────────────
    def get_user_reminders(self, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Fetch reminders for authenticated user with strict user isolation."""
        target_uid = user_id if user_id is not None else self._user_id
        if not target_uid:
            return []
        try:
            from extensions.reminder_engine.reminder_scheduler import get_scheduler
            sched = get_scheduler()
            if sched:
                rems = sched.get_all_reminders()
                if rems:
                    user_rems = []
                    for r in rems:
                        if r.get("user_id") == target_uid:
                            user_rems.append({
                                "id": r.get("id"),
                                "title": r.get("text", "Reminder"),
                                "reminder_time": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r.get("trigger_time", time.time()))),
                                "is_completed": r.get("triggered", False)
                            })
                    if user_rems:
                        return user_rems
        except Exception as e:
            print(f"[CORE] Error fetching in-memory reminders: {e}")

        try:
            from extensions.database_manager import get_db
            db = get_db()
            if db:
                db_rems = db.get_reminders(target_uid)
                return [
                    {
                        "id": r["id"],
                        "title": r["task_text"],
                        "reminder_time": str(r["due_at"]),
                        "is_completed": bool(r["is_notified"])
                    }
                    for r in db_rems
                ]
        except Exception as e:
            print(f"[CORE] Error fetching DB reminders: {e}")
        return []

    def create_reminder(self, title: str, reminder_time_str: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        """Create reminder via canonical database persistence."""
        target_uid = user_id if user_id is not None else self._user_id
        if not target_uid:
            return {"success": False, "error": "No authenticated user"}
        try:
            from extensions.database_manager import get_db
            db = get_db()
            if db:
                rem_id = db.add_reminder(target_uid, title, reminder_time_str)
                if rem_id:
                    return {"success": True, "reminder_id": rem_id, "message": f"Reminder '{title}' scheduled for {reminder_time_str}"}
            from legacy.memory_manager import save_to_db
            query = """
                INSERT INTO reminders (user_id, task_text, due_at, is_notified, created_at)
                VALUES (%s, %s, %s, FALSE, NOW())
            """
            save_to_db(query, (target_uid, title, reminder_time_str))
            return {"success": True, "message": f"Reminder '{title}' scheduled for {reminder_time_str}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── System Telemetry & Diagnostics ───────────────────────────────────────
    def get_telemetry(self) -> Dict[str, Any]:
        """Return system health metrics (CPU, RAM, PostgreSQL, Uptime)."""
        uptime_sec = int(time.time() - self._start_time)
        hours = uptime_sec // 3600
        minutes = (uptime_sec % 3600) // 60
        seconds = uptime_sec % 60
        uptime_str = f"{hours}h {minutes}m {seconds}s"

        db_ok = False
        try:
            from legacy.memory_manager import get_connection
            conn = get_connection()
            if conn:
                conn.close()
                db_ok = True
        except Exception:
            db_ok = False

        mic_ok = False
        try:
            from legacy.sst import _continuous_audio_state
            mic_ok = _continuous_audio_state.get("running", False)
        except Exception:
            pass

        return {
            "uptime": uptime_str,
            "uptime_seconds": uptime_sec,
            "cpu_percent": psutil.cpu_percent(interval=None),
            "ram_percent": psutil.virtual_memory().percent,
            "db_connected": db_ok,
            "microphone_active": mic_ok,
            "thread_count": threading.active_count(),
            "state": self.get_state(),
            "assistant_name": self._assistant_name,
            "username": self._username,
            "user_id": self._user_id
        }


# Global singleton instance
assistant_core = AssistantCore()


def get_assistant_core() -> AssistantCore:
    """Return the global AssistantCore singleton."""
    return assistant_core
