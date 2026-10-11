"""
Continuous Environment Observer
Background thread that continuously observes the user's active foreground window,
extracts rich environment state via the adapter registry, compares with the
previous state, records meaningful transitions, and feeds updates into the
EnvironmentStateEngine.

Architecture:
  - One observer thread per user (or a shared singleton for single-user mode)
  - Polling interval: configurable (default 4 seconds)
  - Only observes active foreground window + process list (lightweight, no screenshots)
  - State comparison done by application-specific adapter detect_action()
  - Transitions stored in EnvironmentStateEngine (memory) and PostgreSQL (best-effort)
  - Thread lifecycle: start / stop / pause with graceful shutdown

This module integrates ALONGSIDE the existing ProactiveObserver (Phase 6),
which observes background tasks and devices. The ContinuousEnvironmentObserver
is exclusively responsible for rich window/content state tracking.

ZERO REGRESSION: Does not modify ProactiveObserver, EnvironmentObserver, brain.py,
or UnifiedCommandRouter. It is an additive layer.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

from core.environment.adapters.adapter_registry import get_adapter_registry
from core.environment.models import EnvironmentState, StateTransition
from core.environment.state_engine import EnvironmentStateEngine, get_state_engine

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL: float = 4.0      # seconds
MIN_POLL_INTERVAL: float = 2.0          # hard minimum
MAX_POLL_INTERVAL: float = 30.0         # hard maximum


class ContinuousEnvironmentObserver:
    """
    Per-user background thread that watches the user's active window,
    extracts rich application state, detects meaningful changes, and
    updates the EnvironmentStateEngine.

    Guarantee: READ-ONLY observer. Never executes actions or modifies OS state.
    """

    def __init__(
        self,
        user_id: str,
        state_engine: Optional[EnvironmentStateEngine] = None,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
    ):
        self.user_id = str(user_id)
        self._engine = state_engine or get_state_engine()
        self._interval = max(MIN_POLL_INTERVAL, min(MAX_POLL_INTERVAL, poll_interval))
        self._registry = get_adapter_registry()

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._paused = threading.Event()   # set = running, clear = paused
        self._paused.set()                 # start in running state

        self._last_window_hwnd: int = 0
        self._last_title: str = ""

    # ──────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────────────

    def start(self):
        """Start the background observation thread (idempotent)."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._observe_loop,
            name=f"ContinuousEnvObserver-{self.user_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info("[CONT_ENV_OBS] Started observer for user %s (interval=%.1fs)", self.user_id, self._interval)

    def stop(self):
        """Signal graceful shutdown and wait for the thread to exit."""
        self._stop_event.set()
        self._paused.set()  # ensure not frozen in pause
        if self._thread:
            self._thread.join(timeout=self._interval + 2)
        logger.info("[CONT_ENV_OBS] Stopped observer for user %s", self.user_id)

    def pause(self):
        """Pause observation (thread sleeps, does not stop)."""
        self._paused.clear()

    def resume(self):
        """Resume observation after a pause."""
        self._paused.set()

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and not self._stop_event.is_set())

    # ──────────────────────────────────────────────────────────────────────────
    # Observation Loop
    # ──────────────────────────────────────────────────────────────────────────

    def _observe_loop(self):
        """Main background observation loop."""
        while not self._stop_event.is_set():
            self._paused.wait(timeout=self._interval)  # blocks during pause
            if self._stop_event.is_set():
                break
            try:
                self._tick()
            except Exception as exc:
                logger.debug("[CONT_ENV_OBS] tick exception: %s", exc)
            self._stop_event.wait(timeout=self._interval)

    def _tick(self):
        """Single observation cycle: observe → compare → record → ingest."""
        window_info = self._get_foreground_window()
        if not window_info:
            return

        title = window_info.get("title", "")
        hwnd = window_info.get("hwnd", 0)

        # Fast deduplication: skip if window title and hwnd are identical to last tick
        if hwnd and hwnd == self._last_window_hwnd and title == self._last_title:
            return

        self._last_window_hwnd = hwnd
        self._last_title = title

        # Determine app name from window info
        app_name = self._infer_app_name(window_info)

        # Extract rich state via best-fit adapter
        try:
            new_state = self._registry.extract_rich_state(
                app_name,
                window_info,
                hierarchy_level=2,  # allow accessibility tier (URL, etc.)
            )
        except Exception as exc:
            logger.debug("[CONT_ENV_OBS] Adapter extraction failed: %s", exc)
            return

        # Compare with current state using adapter's detect_action()
        current_state = self._engine.get_current_state(self.user_id)
        transition: Optional[StateTransition] = None

        if not current_state.is_empty():
            adapter = self._registry.find_adapter(app_name, window_info)
            try:
                change_type, user_action, summary = adapter.detect_action(current_state, new_state)
            except Exception:
                change_type = "CONTENT_UPDATE" if current_state.window_title != new_state.window_title else "NO_CHANGE"
                user_action = ""
                summary = f"Window changed to '{new_state.window_title}'"

            if change_type not in ("NO_CHANGE", ""):
                transition = StateTransition(
                    timestamp=time.time(),
                    before_state=current_state,
                    after_state=new_state,
                    change_type=change_type,
                    transition_summary=summary,
                    user_action=user_action,
                    entities_changed=self._diff_entities(current_state, new_state),
                )
                logger.debug(
                    "[CONT_ENV_OBS] user=%s change=%s: %s",
                    self.user_id, change_type, summary,
                )

        self._engine.ingest(self.user_id, new_state, transition)

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _get_foreground_window() -> Optional[Dict[str, Any]]:
        """Get foreground window info using the existing window_context module."""
        try:
            from skills.window_management.window_context import get_foreground_window_info
            info = get_foreground_window_info()
            if info and info.get("title"):
                return info
        except Exception:
            pass
        return None

    @staticmethod
    def _infer_app_name(window_info: Dict[str, Any]) -> str:
        """Infer a normalized application name from window metadata."""
        title = (window_info.get("title") or "").lower()
        cls_name = (window_info.get("class_name") or "").lower()

        if "youtube" in title:
            return "youtube"
        # ── IDE / Electron apps checked BEFORE browser class names ───────────────
        # VS Code and Cursor use Chrome_WidgetWin_1 (Electron), so must check titles first
        if "visual studio code" in title or "vs code" in title or "vscode" in title:
            return "vscode"
        if "pycharm" in title:
            return "pycharm"
        # ── Browsers ──────────────────────────────────────────────────────────────
        if "chrome" in cls_name or "google chrome" in title:
            return "chrome"
        if "brave" in cls_name or "brave" in title:
            return "brave"
        if "msedge" in cls_name or "microsoft edge" in title or "edge" in title:
            return "msedge"
        if "firefox" in cls_name or "firefox" in title:
            return "firefox"
        # ── IDE class-name fallback (after browser checks) ────────────────────────
        if "code" in cls_name or "cursor" in title or "cursor" in cls_name:
            return "vscode"
        # ── Other apps ────────────────────────────────────────────────────────────
        if "spotify" in title or "spotify" in cls_name:
            return "spotify"
        if "vlc" in title:
            return "vlc"
        if cls_name in ("cabinetwclass", "explorewclass") or "file explorer" in title:
            return "explorer"
        if "acrobat" in title or "sumatrapdf" in title:
            return "acrobat"
        if "winword" in cls_name or " - word" in title or "microsoft word" in title:
            return "winword"
        if " - excel" in title:
            return "excel"
        if " - powerpoint" in title:
            return "powerpnt"
        if "terminal" in title or "terminal" in cls_name or cls_name == "windowsterminal.exe":
            return "terminal"
        if "powershell" in title or "powershell" in cls_name:
            return "powershell"
        if "consolewindowclass" == cls_name or "command prompt" in title:
            return "cmd"
        if "calculator" in title:
            return "calculator"
        if "notepad" in title or cls_name == "notepad":
            return "notepad"
        # Generic: last word after " - "
        if " - " in title:
            return title.split(" - ")[-1].strip().lower()
        return cls_name.split("_")[0] or "unknown"

    @staticmethod
    def _diff_entities(before: EnvironmentState, after: EnvironmentState) -> Dict[str, Any]:
        """Return a dict of entity keys that changed between states."""
        diff: Dict[str, Any] = {}
        all_keys = set(before.active_entities.keys()) | set(after.active_entities.keys())
        for k in all_keys:
            b_val = before.active_entities.get(k)
            a_val = after.active_entities.get(k)
            if b_val != a_val:
                diff[k] = {"before": b_val, "after": a_val}
        return diff


# ──────────────────────────────────────────────────────────────────────────────
# Coordinator (manages per-user observers)
# ──────────────────────────────────────────────────────────────────────────────

class EnvironmentObserverCoordinator:
    """
    Manages ContinuousEnvironmentObserver instances for multiple users.
    Thread-safe. Exposes start/stop/pause/resume per user.
    """

    def __init__(self):
        self._observers: Dict[str, ContinuousEnvironmentObserver] = {}
        self._lock = threading.Lock()
        self._state_engine = get_state_engine()

    def ensure_running(self, user_id: str, poll_interval: float = DEFAULT_POLL_INTERVAL) -> ContinuousEnvironmentObserver:
        """Ensure an observer is running for the given user. Start if not present."""
        uid = str(user_id)
        with self._lock:
            obs = self._observers.get(uid)
            if obs and obs.is_running():
                return obs
            obs = ContinuousEnvironmentObserver(
                user_id=uid,
                state_engine=self._state_engine,
                poll_interval=poll_interval,
            )
            self._observers[uid] = obs
            obs.start()
            return obs

    def stop_user(self, user_id: str):
        uid = str(user_id)
        with self._lock:
            obs = self._observers.pop(uid, None)
        if obs:
            obs.stop()

    def stop_all(self):
        with self._lock:
            all_obs = list(self._observers.values())
            self._observers.clear()
        for obs in all_obs:
            obs.stop()

    def pause_user(self, user_id: str):
        uid = str(user_id)
        with self._lock:
            obs = self._observers.get(uid)
        if obs:
            obs.pause()

    def resume_user(self, user_id: str):
        uid = str(user_id)
        with self._lock:
            obs = self._observers.get(uid)
        if obs:
            obs.resume()

    def get_current_state(self, user_id: str) -> EnvironmentState:
        return self._state_engine.get_current_state(user_id)

    def get_current_summary(self, user_id: str) -> str:
        return self._state_engine.get_current_summary(user_id)

    def get_history(self, user_id: str, limit: int = 20):
        return self._state_engine.get_history(user_id, limit=limit)

    def get_history_summary(self, user_id: str, limit: int = 10) -> str:
        return self._state_engine.get_history_summary(user_id, limit=limit)

    def format_combined_context(self, user_id: str) -> str:
        return self._state_engine.format_combined_context(user_id)


# ──────────────────────────────────────────────────────────────────────────────
# Global singleton
# ──────────────────────────────────────────────────────────────────────────────

_coordinator: Optional[EnvironmentObserverCoordinator] = None
_coord_lock = threading.Lock()


def get_environment_coordinator() -> EnvironmentObserverCoordinator:
    """Return the global singleton EnvironmentObserverCoordinator."""
    global _coordinator
    if _coordinator is None:
        with _coord_lock:
            if _coordinator is None:
                _coordinator = EnvironmentObserverCoordinator()
    return _coordinator
