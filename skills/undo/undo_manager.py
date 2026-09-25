"""
Undo Subsystem
Maintains a user-isolated stack of reversible operations with human-readable labels.
Enforces multi-tenant isolation: User A cannot undo or see User B's actions.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)

MAX_DEPTH = 10


@dataclass
class _UndoEntry:
    user_id: int
    label: str
    undo_fn: Callable[[], Any]
    created_at: float = field(default_factory=time.monotonic)


class UndoManager:
    """Thread-safe undo stack segregated per user_id."""

    def __init__(self, max_depth: int = MAX_DEPTH):
        self.max_depth = max_depth
        self._lock = threading.RLock()
        # user_id -> list[_UndoEntry]
        self._stacks: dict[int, list[_UndoEntry]] = {}

    def push_undo(self, user_id: int, label: str, undo_fn: Callable[[], Any]) -> None:
        """Record that `label` occurred for user_id and `undo_fn()` reverses it."""
        if not callable(undo_fn):
            return
        with self._lock:
            stack = self._stacks.setdefault(user_id, [])
            stack.append(_UndoEntry(user_id=user_id, label=str(label)[:120], undo_fn=undo_fn))
            while len(stack) > self.max_depth:
                stack.pop(0)
            logger.info(f"Pushed undo for user {user_id}: {label}")

    def can_undo(self, user_id: int) -> bool:
        with self._lock:
            return bool(self._stacks.get(user_id))

    def peek(self, user_id: int) -> str:
        with self._lock:
            stack = self._stacks.get(user_id)
            return stack[-1].label if stack else ""

    def history(self, user_id: int) -> list[str]:
        with self._lock:
            stack = self._stacks.get(user_id, [])
            return [e.label for e in reversed(stack)]

    def undo_last(self, user_id: int) -> dict[str, Any]:
        """Reverse the most recent reversible operation for user_id."""
        with self._lock:
            stack = self._stacks.get(user_id, [])
            if not stack:
                return {
                    "success": False,
                    "status": "nothing_to_undo",
                    "message": "There are no recent actions available to undo."
                }
            entry = stack.pop()

        try:
            result = entry.undo_fn()
            detail = f": {result}" if result else ""
            msg = f"Undid: {entry.label}{detail}."
            logger.info(f"Undid for user {user_id}: {entry.label}")
            return {
                "success": True,
                "status": "success",
                "label": entry.label,
                "result": result,
                "message": msg
            }
        except Exception as e:
            logger.error(f"Undo failed for user {user_id} on '{entry.label}': {e}")
            return {
                "success": False,
                "status": "error",
                "label": entry.label,
                "error": str(e),
                "message": f"Failed to undo '{entry.label}': {e}"
            }


_undo_instance: Optional[UndoManager] = None
_undo_lock = threading.Lock()


def get_undo_manager() -> UndoManager:
    global _undo_instance
    with _undo_lock:
        if _undo_instance is None:
            _undo_instance = UndoManager()
        return _undo_instance
