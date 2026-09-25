"""
Task Management Models
Defines task status, priority levels, and background task representations with user isolation.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    HIGH = 1
    NORMAL = 2
    LOW = 3


@dataclass(order=True)
class BackgroundTask:
    priority: int
    created_at: float = field(compare=False)
    task_id: str = field(compare=False)
    user_id: int = field(compare=False)
    goal: str = field(compare=False)
    status: TaskStatus = field(compare=False, default=TaskStatus.PENDING)
    result: Any = field(compare=False, default=None)
    error: str = field(compare=False, default="")
    action_fn: Optional[Callable[[], Any]] = field(compare=False, default=None)
    on_complete: Optional[Callable[[BackgroundTask], Any]] = field(compare=False, default=None)
    cancel_flag: threading.Event = field(compare=False, default_factory=threading.Event)
    started_at: Optional[float] = field(compare=False, default=None)
    completed_at: Optional[float] = field(compare=False, default=None)

    def to_dict(self) -> dict[str, Any]:
        duration = None
        if self.started_at and self.completed_at:
            duration = round(self.completed_at - self.started_at, 2)
        elif self.started_at:
            duration = round(time.time() - self.started_at, 2)

        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "goal": self.goal,
            "priority": TaskPriority(self.priority).name.lower(),
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": duration,
        }
