"""
Background Task Queue
Provides asynchronous, prioritized background task scheduling, cancellation, and user-isolated status monitoring.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional
from uuid import uuid4

from .task_models import BackgroundTask, TaskPriority, TaskStatus

logger = logging.getLogger(__name__)


class TaskQueue:
    """
    Thread-safe prioritized queue for background asynchronous operations.
    Enforces user isolation across all task operations.
    """

    def __init__(self, max_concurrent: int = 2):
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._queue: list[BackgroundTask] = []
        self._tasks: dict[str, BackgroundTask] = {}  # task_id -> BackgroundTask
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._max_concurrent = max_concurrent
        self.start()

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                daemon=True,
                name="AssistantTaskQueueWorker"
            )
            self._worker_thread.start()
            logger.info("Background TaskQueue started")

    def stop(self) -> None:
        with self._condition:
            self._running = False
            self._condition.notify_all()
        logger.info("Background TaskQueue stopped")

    def submit(
        self,
        user_id: int,
        goal: str,
        action_fn: Optional[Callable[[], Any]] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        on_complete: Optional[Callable[[BackgroundTask], Any]] = None,
    ) -> str:
        """
        Submit a new background task bound to user_id.
        Returns task_id.
        """
        task_id = uuid4().hex[:8]
        task = BackgroundTask(
            priority=priority.value,
            created_at=time.time(),
            task_id=task_id,
            user_id=user_id,
            goal=goal,
            action_fn=action_fn,
            on_complete=on_complete,
        )

        with self._condition:
            self._queue.append(task)
            # Sort by priority ascending (1=HIGH, 2=NORMAL, 3=LOW), then by created_at
            self._queue.sort(key=lambda t: (t.priority, t.created_at))
            self._tasks[task_id] = task
            self._condition.notify()

        logger.info(f"Task queued [{task_id}] (priority={priority.name}) for user {user_id}: {goal[:50]}")
        return task_id

    def cancel(self, user_id: int, task_id: str) -> bool:
        """
        Cancel a pending or running task belonging to user_id.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.user_id != user_id:
                return False
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                return False

            task.cancel_flag.set()
            task.status = TaskStatus.CANCELLED
            task.completed_at = time.time()
            task.error = "Cancelled by user"

            # Remove from pending queue if still there
            self._queue = [t for t in self._queue if t.task_id != task_id]
            logger.info(f"Task [{task_id}] cancelled for user {user_id}")
            return True

    def get_status(self, user_id: int, task_id: str) -> Optional[dict[str, Any]]:
        """Get status of a specific task belonging to user_id."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.user_id != user_id:
                return None
            return task.to_dict()

    def list_user_tasks(self, user_id: int, limit: int = 20) -> list[dict[str, Any]]:
        """List all tasks for a specific user, sorted most recent first."""
        with self._lock:
            user_tasks = [
                t for t in self._tasks.values()
                if t.user_id == user_id
            ]
            user_tasks.sort(key=lambda t: t.created_at, reverse=True)
            return [t.to_dict() for t in user_tasks[:limit]]

    def _next_task(self) -> Optional[BackgroundTask]:
        with self._lock:
            while self._queue:
                task = self._queue.pop(0)
                if not task.cancel_flag.is_set():
                    return task
            return None

    def _worker_loop(self) -> None:
        while self._running:
            with self._condition:
                while self._running and not self._queue:
                    self._condition.wait(timeout=1.0)

            if not self._running:
                break

            task = self._next_task()
            if not task:
                continue

            self._run_task(task)

    def _run_task(self, task: BackgroundTask) -> None:
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()
        logger.info(f"Running task [{task.task_id}]: {task.goal[:50]}")

        try:
            if task.cancel_flag.is_set():
                task.status = TaskStatus.CANCELLED
                task.completed_at = time.time()
                return

            if task.action_fn is not None:
                task.result = task.action_fn()
            else:
                # Default execution: run through assistant command router
                from core.unified_command_router import route_and_execute
                task.result = route_and_execute(task.goal, user_id=task.user_id)

            if task.cancel_flag.is_set():
                task.status = TaskStatus.CANCELLED
            else:
                task.status = TaskStatus.COMPLETED
            logger.info(f"Task [{task.task_id}] completed successfully")

        except Exception as e:
            logger.error(f"Task [{task.task_id}] failed: {e}")
            task.error = str(e)
            task.status = TaskStatus.FAILED
            try:
                from .error_recovery import analyze_task_error
                task.result = {"error": str(e), "recovery": analyze_task_error(task.goal, str(e))}
            except Exception:
                pass

        finally:
            task.completed_at = time.time()
            if task.on_complete:
                try:
                    task.on_complete(task)
                except Exception as cb_err:
                    logger.warning(f"Task [{task.task_id}] completion callback failed: {cb_err}")


_queue_instance: Optional[TaskQueue] = None
_queue_lock = threading.Lock()


def get_task_queue() -> TaskQueue:
    global _queue_instance
    with _queue_lock:
        if _queue_instance is None:
            _queue_instance = TaskQueue()
        return _queue_instance
