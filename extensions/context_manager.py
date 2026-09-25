# context_manager.py
import os
import time
from typing import Optional, Dict, Any, List

class ContextType:
    BROWSER = "browser"
    APP = "app"
    SYSTEM = "system"
    NONE = "none"

class ContextManager:
    """
    SINGLE CONTEXT MANAGER (CRITICAL)
    Tracks conversational memory and active domain context (apps/websites).
    Also manages user-isolated short-term artifact references ("it", "that file", "the PDF").
    """
    def __init__(self, max_history=10, db_manager=None):
        self.max_history = max_history
        self.history = [] # List of {'role': 'user'/'assistant', 'text': str, 'intent': str, 'timestamp': float}
        
        # USER-ISOLATED SHORT-TERM ARTIFACT CONTEXT
        # Map: user_id -> List of artifact dicts
        self.user_artifacts: Dict[Any, List[Dict[str, Any]]] = {}

        # ACTIVE DOMAIN CONTEXT
        self.active_context = {
            "type": ContextType.NONE,
            "name": None,
            "metadata": {},
            "timestamp": 0,
            "awaiting_confirmation": False,
            # granular history for smart defaults
            "last_app": None,
            "last_browser": None,
            "last_action": None,
            # conversational slots
            "awaiting_input": False,
            "awaiting_type": None
        }

        # USER PREFERENCES (Volatile per-session, loaded from DB on login)
        self.active_preferences = {
            "tone": "professional",
            "browser": "chrome",
            "continuous_listening": True,
            "voice_id": None
        }
        
        # Database Manager Reference (dependency injection)
        self.db_manager = db_manager
        self.current_user_id = None

    def _resolve_uid(self, user_id: Any = None) -> Any:
        if user_id is not None:
            return user_id
        if self.current_user_id is not None:
            return self.current_user_id
        try:
            from instance.config import settings
            return getattr(settings, 'CURRENT_USER_ID', None) or settings.get_last_user() or 1
        except Exception:
            return 1

    def add_user_artifact(self, user_id: Any, artifact: Dict[str, Any]):
        """Register a successfully created file/artifact for user short-term reference."""
        uid = self._resolve_uid(user_id)
        if uid not in self.user_artifacts:
            self.user_artifacts[uid] = []
        
        raw_path = artifact.get("path") or artifact.get("filepath")
        if not raw_path:
            return

        ext = (artifact.get("type") or "").lower().lstrip(".")
        if not ext and "." in os.path.basename(raw_path):
            ext = os.path.basename(raw_path).rsplit(".", 1)[-1].lower()

        art_entry = {
            "path": os.path.abspath(raw_path),
            "filename": artifact.get("filename") or os.path.basename(raw_path),
            "type": ext,
            "source_action": artifact.get("source_action", "file_creation"),
            "timestamp": artifact.get("timestamp", time.time())
        }
        # Prepend to list, keeping max 20 entries
        self.user_artifacts[uid].insert(0, art_entry)
        self.user_artifacts[uid] = self.user_artifacts[uid][:20]
        print(f"[CONTEXT] Artifact registered for user {uid}: {art_entry['filename']} ({art_entry['type']})")

    def get_recent_user_artifacts(self, user_id: Any = None, artifact_type: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent artifacts for the given user, optionally filtered by file type."""
        uid = self._resolve_uid(user_id)
        arts = self.user_artifacts.get(uid, [])
        if artifact_type:
            target_type = artifact_type.lower().lstrip(".")
            arts = [a for a in arts if a.get("type") == target_type or a.get("filename", "").lower().endswith(f".{target_type}")]
        return arts[:limit]

    def get_last_user_artifact(self, user_id: Any = None, artifact_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get the most recent artifact for the given user."""
        arts = self.get_recent_user_artifacts(user_id=user_id, artifact_type=artifact_type, limit=1)
        return arts[0] if arts else None


    def set_active_preference(self, key: str, value: Any):
        self.active_preferences[key] = value
        print(f"[CONTEXT] Preference updated: {key} -> {value}")

    def get_active_preference(self, key: str, default: Any = None) -> Any:
        return self.active_preferences.get(key, default)

    # --- CONVERSATION HISTORY ---
    def add_turn(self, role: str, text: str, intent: Optional[str] = None):
        self.history.append({
            'role': role,
            'text': text,
            'intent': intent,
            'timestamp': time.time()
        })
        if len(self.history) > self.max_history * 2:
            self.history = self.history[-self.max_history * 2:]

    def get_recent_context(self):
        return "\n".join([f"{h['role'].capitalize()}: {h['text']}" for h in self.history])

    def get_last_intent(self):
        for h in reversed(self.history):
            if h['role'] == 'user' and h['intent']:
                return h['intent']
        return None

    # --- DOMAIN CONTEXT TRACKING ---

    def set_db_manager(self, db_manager, user_id):
        self.db_manager = db_manager
        self.current_user_id = user_id
        self._load_persisted_context()

    def _load_persisted_context(self):
        if not self.db_manager or not self.current_user_id: return
        data = self.db_manager.load_context(self.current_user_id)
        if data:
            # Load basic fields
            for k in ["last_app", "last_browser", "last_action"]:
                if k in data: self.active_context[k] = data[k]
            # Load active state if valid? active_context usually resets on restart
            # But we can load history/preferences here if expanded
            print(f"[CONTEXT] Loaded persisted context for user {self.current_user_id}")


    # --- DOMAIN CONTEXT TRACKING ---
    def set_active_context(self, context_type: str, name: str, metadata: Optional[Dict] = None, await_confirm: bool = False):
        self.active_context.update({
            "type": context_type,
            "name": name.lower() if name else None,
            "metadata": metadata or {},
            "timestamp": time.time(),
            "awaiting_confirmation": await_confirm
        })
        
        # specific tracking
        if context_type == ContextType.APP:
            self.active_context["last_app"] = name.lower() if name else None
        elif context_type == ContextType.BROWSER:
            self.active_context["last_browser"] = name.lower() if name else None
            
        print(f"[CONTEXT] Active context set: {context_type} -> {name}")
        
        # PERSIST
        if self.db_manager and self.current_user_id and name:
            self.db_manager.update_context(self.current_user_id, "last_active_context", name)
            if context_type == ContextType.APP:
                self.db_manager.update_context(self.current_user_id, "last_app", name)
            elif context_type == ContextType.BROWSER:
                self.db_manager.update_context(self.current_user_id, "last_browser", name)

    def set_awaiting_input(self, state: bool, input_type: Optional[str] = None):
        """Sets the system to wait for specific user input (e.g. folder name)"""
        self.active_context["awaiting_input"] = state
        self.active_context["awaiting_type"] = input_type
        print(f"[CONTEXT] Awaiting Input: {state} ({input_type})")


    def get_active_context(self) -> Dict[str, Any]:
        return self.active_context

    def set_confirmation_state(self, state: bool):
        self.active_context["awaiting_confirmation"] = state
        print(f"[CONTEXT] Awaiting confirmation set to: {state}")

    def clear_context(self):
        self.history = []
        self.active_context = {
            "type": ContextType.NONE,
            "name": None,
            "metadata": {},
            "timestamp": 0,
            "awaiting_confirmation": False
        }
        print("[CONTEXT] All contexts cleared.")

    def is_context_active(self, name_to_check: str) -> bool:
        return self.active_context["name"] == name_to_check.lower()

# Singleton instance for system-wide use
_instance = None
def get_manager():
    global _instance
    if _instance is None:
        _instance = ContextManager()
    return _instance

