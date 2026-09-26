"""
skills/audio_management/confirmation_gate.py — Unforgeable, session-isolated confirmation gate.

Provides strict separation between confirmation request and execution:
- Confirmation tokens are issued by the interface, NEVER accepted directly from LLM text output.
- Actions register a callback with a unique key, title, detail, user ID, and expiration timeout.
- Resolution requires explicit UI confirmation by the authenticated user.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional, Dict, Any

logger = logging.getLogger(__name__)

# Default timeout in seconds after which pending confirmation is abandoned
DEFAULT_TIMEOUT_SECONDS = 90.0


@dataclass
class PendingConfirmation:
    key: str
    title: str
    detail: str
    action_callable: Callable[[], Any]
    user_id: int
    created_at: float
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


class ConfirmationGate:
    """
    Thread-safe confirmation gate preventing unverified or LLM-forged execution
    of irreversible / destructive operations.
    """

    def __init__(self):
        self._pending: Dict[str, PendingConfirmation] = {}
        self._lock = threading.Lock()
        self._show_cb: Optional[Callable[[str, str, int], None]] = None
        self._hide_cb: Optional[Callable[[], None]] = None

    def bind_ui(
        self,
        show_callback: Callable[[str, str, int], None],
        hide_callback: Callable[[], None]
    ) -> None:
        """Bind UI banner handlers for displaying/dismissing confirmation requests."""
        self._show_cb = show_callback
        self._hide_cb = hide_callback

    def request_confirmation(
        self,
        key: str,
        title: str,
        detail: str,
        action_callable: Callable[[], Any],
        user_id: int = 1,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    ) -> Dict[str, Any]:
        """
        Register an action requiring user confirmation.
        Returns a structured confirmation requirement payload.
        """
        with self._lock:
            self._pending[key] = PendingConfirmation(
                key=key,
                title=title,
                detail=detail,
                action_callable=action_callable,
                user_id=user_id,
                created_at=time.monotonic(),
                timeout_seconds=timeout_seconds
            )

        if self._show_cb:
            try:
                self._show_cb(title, detail, user_id)
            except Exception as e:
                logger.error(f"[CONFIRM] UI show callback failed: {e}")

        logger.info(f"[CONFIRM] Awaiting confirmation for '{title}' (user_id={user_id}, key={key})")
        return {
            "status": "confirmation_required",
            "confirmation_key": key,
            "title": title,
            "detail": detail,
            "user_id": user_id,
            "message": f"Confirmation required on screen for: {title}."
        }

    def resolve(self, key: str, accepted: bool, user_id: int = 1) -> Dict[str, Any]:
        """
        Resolve a pending confirmation by key and user ID.
        Executes the action ONLY if accepted, not expired, and user ID matches.
        """
        with self._lock:
            pending = self._pending.pop(key, None)

        if self._hide_cb:
            try:
                self._hide_cb()
            except Exception as e:
                logger.debug(f"[CONFIRM] UI hide callback notice: {e}")

        if pending is None:
            return {
                "success": False,
                "status": "not_found",
                "message": f"No pending confirmation found for key '{key}'."
            }

        # Validate user isolation
        if pending.user_id != user_id:
            logger.warning(f"[CONFIRM] User mismatch: expected {pending.user_id}, got {user_id}")
            return {
                "success": False,
                "status": "unauthorized",
                "message": "Confirmation rejected: user identity does not match."
            }

        # Validate timeout
        elapsed = time.monotonic() - pending.created_at
        if elapsed > pending.timeout_seconds:
            logger.warning(f"[CONFIRM] Confirmation '{pending.title}' expired after {elapsed:.1f}s")
            return {
                "success": False,
                "status": "expired",
                "message": f"Confirmation for '{pending.title}' has expired."
            }

        if not accepted:
            logger.info(f"[CONFIRM] Action '{pending.title}' was cancelled by user {user_id}")
            return {
                "success": False,
                "status": "cancelled",
                "message": f"Action '{pending.title}' was cancelled."
            }

        # Execute confirmed action safely
        try:
            result = pending.action_callable()
            logger.info(f"[CONFIRM] Action '{pending.title}' executed successfully.")
            return {
                "success": True,
                "status": "executed",
                "result": result,
                "message": f"Action '{pending.title}' confirmed and executed."
            }
        except Exception as e:
            logger.error(f"[CONFIRM] Execution failed for '{pending.title}': {e}")
            return {
                "success": False,
                "status": "execution_failed",
                "error": str(e),
                "message": f"Failed to execute confirmed action: {e}"
            }

    def cancel_all(self, user_id: Optional[int] = None) -> int:
        """Cancel all pending confirmations, optionally filtered by user ID."""
        with self._lock:
            if user_id is None:
                count = len(self._pending)
                self._pending.clear()
            else:
                to_remove = [k for k, p in self._pending.items() if p.user_id == user_id]
                count = len(to_remove)
                for k in to_remove:
                    del self._pending[k]
        return count


# Global singleton instance
confirmation_gate = ConfirmationGate()

def get_confirmation_gate() -> ConfirmationGate:
    """Return the central confirmation gate singleton."""
    return confirmation_gate
