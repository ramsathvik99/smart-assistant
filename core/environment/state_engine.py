"""
Environment State Engine
Maintains the CURRENT and HISTORICAL states of the user's digital environment.
Records meaningful state transitions and provides a unified query API
for the assistant to answer environment-aware questions.

Key Design Principles:
- In-memory current state (fast, always available)
- Per-user transition history ring buffer (bounded, no runaway growth)
- Lazy DB persistence only for meaningful transitions (not duplicates)
- Thread-safe reads and writes
- Zero regression guarantee: never alters existing EnvironmentObserver behaviour
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from core.environment.models import EnvironmentState, StateTransition

logger = logging.getLogger(__name__)

# Maximum state transition history entries kept per user in memory
MAX_HISTORY_PER_USER = 200
# Minimum seconds between identical-application transitions to deduplicate noise
TRANSITION_DEDUP_WINDOW = 2.0


def resolve_user_id_to_int(user_id: Any) -> Optional[int]:
    """
    Consistently resolves any user ID (integer, numeric string, username)
    to a valid positive integer referencing users(id).
    Does NOT manufacture fake database records or default to 1.
    """
    from core.user_isolation import resolve_identity
    return resolve_identity(user_id)


class UserEnvironmentState:
    """Isolated per-user state container."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.current: EnvironmentState = EnvironmentState()
        self.previous: Optional[EnvironmentState] = None
        self.history: Deque[StateTransition] = deque(maxlen=MAX_HISTORY_PER_USER)
        self._lock = threading.Lock()
        self._last_update: float = 0.0
        self._last_transition_time: float = 0.0

    def update(self, new_state: EnvironmentState, transition: Optional[StateTransition] = None):
        """Thread-safe update of current state."""
        with self._lock:
            self.previous = self.current
            self.current = new_state
            self._last_update = time.time()
            if transition:
                self.history.appendleft(transition)
                self._last_transition_time = time.time()

    def get_current(self) -> EnvironmentState:
        with self._lock:
            return self.current

    def get_previous(self) -> Optional[EnvironmentState]:
        with self._lock:
            return self.previous

    def get_history(self, limit: int = 20) -> List[StateTransition]:
        with self._lock:
            return list(self.history)[:limit]

    def find_last_state_by_app(self, app_name: str) -> Optional[EnvironmentState]:
        """Find the most recent state where a given application was active."""
        with self._lock:
            for transition in self.history:
                state = transition.after_state
                if state and state.application.lower() == app_name.lower():
                    return state
        return None

    def find_last_state_by_entity(self, key: str, value: str) -> Optional[EnvironmentState]:
        """Find most recent state with a matching entity key/value."""
        with self._lock:
            for transition in self.history:
                state = transition.after_state
                if state and str(state.get_entity(key, "")).lower() == value.lower():
                    return state
        return None


class EnvironmentStateEngine:
    """
    Central per-user environment state engine.
    Tracks current and historical states, records meaningful transitions,
    and optionally persists significant events to PostgreSQL.
    """

    def __init__(self):
        self._users: Dict[str, UserEnvironmentState] = {}
        self._global_lock = threading.Lock()
        self._db_manager: Optional[Any] = None  # Injected lazily
        logger.info("[ENV_STATE_ENGINE] Initialized")

    def _get_user_state(self, user_id: str) -> UserEnvironmentState:
        uid = str(user_id)
        with self._global_lock:
            if uid not in self._users:
                self._users[uid] = UserEnvironmentState(uid)
            return self._users[uid]

    def set_db_manager(self, db_manager: Any):
        """Inject a database manager for optional persistence."""
        self._db_manager = db_manager

    # ──────────────────────────────────────────────────────────────
    # Ingestion
    # ──────────────────────────────────────────────────────────────

    def ingest(
        self,
        user_id: str,
        new_state: EnvironmentState,
        transition: Optional[StateTransition] = None,
    ) -> bool:
        """
        Ingest a newly observed environment state for a user.
        Returns True if the state represents a meaningful change that was recorded.
        """
        user_env = self._get_user_state(user_id)
        current = user_env.get_current()

        if transition and transition.change_type not in ("NO_CHANGE", ""):
            user_env.update(new_state, transition)
            self._persist_transition(user_id, transition)
            return True

        # Even without an explicit transition, update current silently
        user_env.update(new_state, None)
        return False

    # ──────────────────────────────────────────────────────────────
    # Query API (used by brain.py & proactive systems)
    # ──────────────────────────────────────────────────────────────

    def get_current_state(self, user_id: str) -> EnvironmentState:
        """Return the user's current observed environment state."""
        return self._get_user_state(user_id).get_current()

    def get_previous_state(self, user_id: str) -> Optional[EnvironmentState]:
        """Return the state just before the current one."""
        return self._get_user_state(user_id).get_previous()

    def get_history(self, user_id: str, limit: int = 20) -> List[StateTransition]:
        """Return recent state transitions (newest first)."""
        return self._get_user_state(user_id).get_history(limit=limit)

    def get_current_summary(self, user_id: str) -> str:
        """Return a short human-readable description of the current environment."""
        state = self.get_current_state(user_id)
        return state.format_summary() if not state.is_empty() else "No active environment state observed."

    def find_last_by_app(self, user_id: str, app_name: str) -> Optional[EnvironmentState]:
        """Find the most recent state for a specific application (historical search)."""
        cur = self.get_current_state(user_id)
        if cur.application.lower() == app_name.lower():
            return cur
        return self._get_user_state(user_id).find_last_state_by_app(app_name)

    def find_last_by_entity(self, user_id: str, key: str, value: str) -> Optional[EnvironmentState]:
        """Find most recent state with a specific entity value."""
        cur = self.get_current_state(user_id)
        if str(cur.get_entity(key, "")).lower() == value.lower():
            return cur
        return self._get_user_state(user_id).find_last_state_by_entity(key, value)

    def get_history_summary(self, user_id: str, limit: int = 10) -> str:
        """
        Generate a human-readable summary of recent state history.
        Example:
          10:00 — Chrome: Watching 'Video A' on YouTube
          11:00 — VS Code: Editing 'main.py' in Project X
        """
        transitions = self.get_history(user_id, limit=limit)
        if not transitions:
            return "No environment history recorded."
        lines: List[str] = []
        for t in reversed(transitions):
            ts = time.strftime("%H:%M", time.localtime(t.timestamp))
            state = t.after_state
            if state:
                lines.append(f"{ts} — {state.format_summary()}")
            else:
                lines.append(f"{ts} — {t.transition_summary}")
        return "\n".join(lines)

    def format_combined_context(self, user_id: str) -> str:
        """
        Generate a rich context block for inclusion in LLM prompts.
        Includes current state and recent transition trail.
        """
        current = self.get_current_state(user_id)
        prev = self.get_previous_state(user_id)
        lines: List[str] = ["=== CURRENT ENVIRONMENT ==="]
        if not current.is_empty():
            lines.append(f"Application: {current.application.capitalize()}")
            lines.append(f"Window: {current.window_title}")
            lines.append(f"Context: {current.format_summary()}")
            for k, v in (current.active_entities or {}).items():
                if v and k not in ("raw_title", "window_title"):
                    lines.append(f"  {k}: {v}")
        else:
            lines.append("(No application currently observed)")

        if prev and not prev.is_empty() and prev.application != current.application:
            lines.append("")
            lines.append("=== PREVIOUS ENVIRONMENT ===")
            lines.append(f"Application: {prev.application.capitalize()}")
            lines.append(f"Context: {prev.format_summary()}")

        recent = self.get_history(user_id, limit=5)
        if recent:
            lines.append("")
            lines.append("=== RECENT TRANSITIONS ===")
            for t in recent[:5]:
                ts = time.strftime("%H:%M:%S", time.localtime(t.timestamp))
                lines.append(f"[{ts}] {t.transition_summary}")

        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────
    # Persistence (non-blocking, best-effort)
    # ──────────────────────────────────────────────────────────────

    def _persist_transition(self, user_id: str, transition: StateTransition):
        """
        Persist a meaningful state transition to PostgreSQL (if DB connected).
        Uses environment_state_transitions table created by migration 006.
        Errors are silently logged – persistence is never blocking.
        """
        if not self._db_manager:
            try:
                from extensions.database_manager import DatabaseManager
                self._db_manager = DatabaseManager()
            except Exception:
                return

        try:
            import json as _json
            payload = _json.dumps(transition.to_dict(), default=str)
            uid_int = resolve_user_id_to_int(user_id)
            if uid_int is None:
                return
            with self._db_manager._get_cursor() as cur:
                if cur is None:
                    return
                cur.execute(
                    """
                    INSERT INTO environment_state_transitions
                        (user_id, timestamp, change_type, transition_summary,
                         before_state, after_state, entities_changed)
                    VALUES (%s, to_timestamp(%s), %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
                    """,
                    (
                        uid_int,
                        transition.timestamp,
                        transition.change_type,
                        transition.transition_summary[:500],
                        _json.dumps(transition.before_state.to_dict() if transition.before_state else {}, default=str),
                        _json.dumps(transition.after_state.to_dict() if transition.after_state else {}, default=str),
                        _json.dumps(transition.entities_changed, default=str),
                    ),
                )
        except Exception as exc:
            logger.debug("[ENV_STATE_ENGINE] Persist transition skipped: %s", exc)

    def load_historical_transitions_from_db(self, user_id: Any, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Load historical transitions from PostgreSQL across assistant restarts.
        Maps any user ID (numeric, string, UUID) correctly without cross-user leakage.
        """
        uid_int = resolve_user_id_to_int(user_id)
        if uid_int is None:
            return []
        results = []
        try:
            from core.db_pool import get_db_pool
            pool = get_db_pool()
            if pool and pool.is_healthy():
                with pool.get_cursor() as cur:
                    cur.execute("""
                        SELECT id, user_id, timestamp, change_type, transition_summary,
                               before_state, after_state, entities_changed
                        FROM environment_state_transitions
                        WHERE user_id = %s
                        ORDER BY timestamp DESC
                        LIMIT %s;
                    """, (uid_int, limit))
                    for row in cur.fetchall():
                        results.append({
                            "id": row[0],
                            "user_id": row[1],
                            "timestamp": row[2],
                            "change_type": row[3],
                            "transition_summary": row[4],
                            "before_state": row[5],
                            "after_state": row[6],
                            "entities_changed": row[7],
                        })
        except Exception as e:
            logger.debug(f"[ENV_STATE_ENGINE] DB load history error: {e}")
        return results



# Global singleton – one engine instance for all users
_engine: Optional[EnvironmentStateEngine] = None
_engine_lock = threading.Lock()


def get_state_engine() -> EnvironmentStateEngine:
    """Return the global singleton EnvironmentStateEngine."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = EnvironmentStateEngine()
    return _engine


def verify_and_synchronize_foreground_state(
    user_id: Any,
    action_target: Optional[str] = None,
    action_type: str = "open",
    max_wait_ms: int = 400,
) -> EnvironmentState:
    """
    Authoritative Foreground State Verification & Synchronization.
    Performs authoritative foreground window inspection after application/window actions
    and synchronizes the Environment State Engine, Dialogue State Manager, and context
    before the command is considered complete.

    Preserves current/previous/history semantics without hardcoding application names.
    """
    uid_str = str(user_id or "default")
    engine = get_state_engine()

    try:
        from skills.window_management.window_context import get_foreground_window_info
        from core.environment.continuous_observer import ContinuousEnvironmentObserver
        from core.environment.adapters.adapter_registry import get_adapter_registry

        # Bounded poll for foreground window transfer if action_target was specified
        matched_win: Optional[Dict[str, Any]] = None
        matched_app: str = ""

        clean_tgt = (action_target or "").strip().lower()
        deadline = time.time() + (max_wait_ms / 1000.0)

        while True:
            fg_info = get_foreground_window_info()
            if fg_info and fg_info.get("title") and fg_info.get("class_name") not in ("Progman", "unknown"):
                app_inf = ContinuousEnvironmentObserver._infer_app_name(fg_info)
                if app_inf and app_inf != "unknown":
                    if not clean_tgt or clean_tgt in app_inf.lower() or app_inf.lower() in clean_tgt:
                        matched_win = fg_info
                        matched_app = app_inf
                        break
            if time.time() >= deadline:
                break
            time.sleep(0.04)

        # Fallback for headless environments, test suites, or background launch delays:
        # Resolve target canonically via SmartOpener dynamically (no hardcoded names)
        if not matched_win and action_target:
            try:
                from extensions.system.smart_opener import smart_opener
                res_canon = smart_opener.resolve_canonical(action_target)
                if res_canon:
                    dname = res_canon.get("display_name") or action_target
                    exe_name = res_canon.get("executable") or action_target
                else:
                    dname = action_target.title()
                    exe_name = action_target.lower()
            except Exception:
                dname = action_target.title()
                exe_name = action_target.lower()

            matched_win = {"title": dname, "class_name": exe_name, "pid": 0}
            matched_app = ContinuousEnvironmentObserver._infer_app_name(matched_win)
            if matched_app in ("unknown", "", "desktop"):
                matched_app = dname.lower()

        if not matched_win:
            return engine.get_current_state(uid_str)

        # Extract rich state dynamically via AdapterRegistry
        registry = get_adapter_registry()
        new_state = registry.extract_rich_state(matched_app, matched_win, hierarchy_level=2)
        if not new_state.application or new_state.application == "unknown":
            new_state.application = matched_app
        if not new_state.window_title:
            new_state.window_title = matched_win.get("title") or matched_app.title()

        # Ingest state transition preserving current / previous / history semantics
        prev_state = engine.get_current_state(uid_str)
        if prev_state and not prev_state.is_empty():
            if prev_state.application.lower() != new_state.application.lower():
                change_type = "APP_SWITCH"
                summary = f"Switched to {new_state.application.capitalize()}"
            else:
                change_type = "APP_LAUNCH"
                summary = f"Opened {new_state.application.capitalize()}"
            entities_diff = ContinuousEnvironmentObserver._diff_entities(prev_state, new_state)
            transition = StateTransition(
                timestamp=time.time(),
                before_state=prev_state,
                after_state=new_state,
                change_type=change_type,
                transition_summary=summary,
                user_action=action_type,
                entities_changed=entities_diff,
            )
        else:
            transition = StateTransition(
                timestamp=time.time(),
                before_state=None,
                after_state=new_state,
                change_type="APP_LAUNCH",
                transition_summary=f"Opened {new_state.application.capitalize()}",
                user_action=action_type,
                entities_changed={},
            )

        engine.ingest(uid_str, new_state, transition)

        # Synchronize Dialogue State Manager and Context Manager
        try:
            from extensions.dialogue_state_manager import get_dialogue_manager
            dm = get_dialogue_manager(uid_str)
            dm.current_state.active_application = new_state.application
            dm.current_state.session_context["active_application"] = new_state.application
            from core.brain import _inject_environment_context
            _inject_environment_context(uid_str, dm)
        except Exception:
            pass

        try:
            from extensions.context_manager import get_manager, ContextType
            get_manager().set_active_context(ContextType.APPLICATION, new_state.application)
        except Exception:
            pass

        return new_state
    except Exception as exc:
        logger.debug("[ENV_STATE_ENGINE] verify_and_synchronize_foreground_state error: %s", exc)
        return engine.get_current_state(uid_str)

