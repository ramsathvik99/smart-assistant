"""
Task Management Skill Package
Provides asynchronous prioritized background tasks, status inspection, cancellation, and error recovery analysis.
"""

from .error_recovery import ErrorDecision, analyze_task_error
from .task_models import BackgroundTask, TaskPriority, TaskStatus
from .task_queue import TaskQueue, get_task_queue

__all__ = [
    "TaskStatus",
    "TaskPriority",
    "BackgroundTask",
    "TaskQueue",
    "get_task_queue",
    "ErrorDecision",
    "analyze_task_error",
]
