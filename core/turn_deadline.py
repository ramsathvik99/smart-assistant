"""
core/turn_deadline.py
=====================
Hard Turn-Level Deadline Manager for conversational turns.

Enforces a single non-extendable time budget (LLM_INTERACTIVE_BUDGET, default 5.0s)
for the entire turn (across semantic_resolve, multi-intent decomposition, answer generation,
and retries). Prevents individual per-call timeouts from accumulating into 15+ second turn delays.
"""

import time
import threading
from typing import Optional, Any, Union

_LOCAL = threading.local()


class TurnDeadline:
    """Represents the strict time budget for a single interaction turn."""

    def __init__(self, budget_seconds: float = 6.0, task_type: str = "interactive"):
        self.budget_seconds = float(budget_seconds)
        self.task_type = task_type
        self.start_time = time.monotonic()
        self.deadline_time = self.start_time + self.budget_seconds

    def time_remaining(self) -> float:
        """Return monotonic seconds remaining before turn budget is exhausted."""
        return max(0.0, self.deadline_time - time.monotonic())

    def is_expired(self) -> bool:
        """Return True if the turn deadline has elapsed."""
        return time.monotonic() >= self.deadline_time

    def remaining_seconds(self) -> float:
        """Alias for time_remaining."""
        return self.time_remaining()

    def check_deadline(self) -> None:
        """Raise TimeoutError if the turn budget has expired."""
        if self.is_expired():
            raise TimeoutError(f"Turn deadline exhausted ({self.budget_seconds:.1f}s budget exceeded)")

    def elapsed(self) -> float:
        """Return monotonic elapsed seconds since turn start."""
        return time.monotonic() - self.start_time

    def clamp_timeout(self, requested_timeout: float, min_floor: float = 0.5) -> float:
        """Clamp a requested call timeout so it cannot exceed turn deadline."""
        rem = self.time_remaining()
        if rem <= min_floor:
            return min_floor
        return max(min_floor, min(float(requested_timeout), rem))


_LAST_ACTIVE_DEADLINE: Optional['TurnDeadline'] = None
_DEADLINE_LOCK = threading.Lock()


def get_current_turn_deadline() -> Optional[TurnDeadline]:
    """Retrieve active turn deadline for current thread, falling back to process-level active turn."""
    dl = getattr(_LOCAL, "current_deadline", None)
    if dl is not None:
        return dl
    with _DEADLINE_LOCK:
        if _LAST_ACTIVE_DEADLINE is not None and not _LAST_ACTIVE_DEADLINE.is_expired():
            return _LAST_ACTIVE_DEADLINE
    return None


def set_current_turn_deadline(deadline: Optional[TurnDeadline]) -> None:
    """Set active turn deadline for current thread and active process turn."""
    _LOCAL.current_deadline = deadline
    global _LAST_ACTIVE_DEADLINE
    with _DEADLINE_LOCK:
        _LAST_ACTIVE_DEADLINE = deadline


class turn_deadline_scope:
    """Context manager setting active turn deadline for the current turn."""

    def __init__(self, budget_seconds: Any = 6.0, task_type: str = "interactive"):
        if isinstance(budget_seconds, TurnDeadline):
            self.deadline = budget_seconds
        else:
            self.deadline = TurnDeadline(budget_seconds=float(budget_seconds), task_type=task_type)
        self.prev = None

    def __enter__(self) -> TurnDeadline:
        self.prev = get_current_turn_deadline()
        set_current_turn_deadline(self.deadline)
        return self.deadline

    def __exit__(self, exc_type, exc_val, exc_tb):
        set_current_turn_deadline(self.prev)
