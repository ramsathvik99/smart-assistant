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
    Authoritative Background Task Queue adapter.
    Delegates scheduling, cancellation, status, and persistence directly to
    core.task_execution_manager.TaskExecutionManager to ensure a single unified task registry.
    """

    _instance: Optional[TaskQueue] = None

    def __init__(self, max_concurrent: int = 2):
        self._max_concurrent = max_concurrent

    @classmethod
    def get_instance(cls) -> TaskQueue:
        return get_task_queue()

    def start(self) -> None:
        """Start worker thread / ensure TaskExecutionManager is active."""
        try:
            from core.task_execution_manager import get_task_execution_manager
            get_task_execution_manager()
        except Exception as e:
            logger.debug(f"[TaskQueue] ensure TEM active error: {e}")

    def stop(self) -> None:
        """Stop background worker cleanly."""
        pass

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
        Delegates directly to TaskExecutionManager.
        Returns task_id.
        """
        from core.task_execution_manager import get_task_execution_manager, TaskPriority as TEMPriority
        tem = get_task_execution_manager()

        uid_int = int(user_id) if str(user_id).isdigit() else 1

        if isinstance(priority, int):
            p = TEMPriority.HIGH if priority == 1 else (TEMPriority.LOW if priority == 3 else TEMPriority.NORMAL)
        elif hasattr(priority, "name"):
            p_name = priority.name.upper()
            p = getattr(TEMPriority, p_name, TEMPriority.NORMAL)
        else:
            p = TEMPriority.NORMAL

        def _exec_wrapper(task, report_progress, cancel_token):
            if cancel_token.is_set():
                return None
            if action_fn is not None:
                res = action_fn()
            else:
                from core.unified_command_router import route_and_execute
                res = route_and_execute(task.user_request, user_id=task.user_id)

            if on_complete:
                try:
                    bg_task = BackgroundTask(
                        priority=priority.value if hasattr(priority, "value") else 2,
                        created_at=task.created_at,
                        task_id=task.task_id,
                        user_id=task.user_id,
                        goal=task.user_request,
                        result=res,
                        status=TaskStatus.COMPLETED,
                    )
                    on_complete(bg_task)
                except Exception as cb_err:
                    logger.warning(f"Task [{task.task_id}] completion callback failed: {cb_err}")
            return res

        task = tem.create_task(
            user_request=goal,
            user_id=uid_int,
            priority=p,
            execution_fn=_exec_wrapper,
        )
        tem.submit_task(task)
        logger.info(f"Task queued [{task.task_id}] (priority={p.name}) for user {uid_int}: {goal[:50]}")
        return task.task_id

    def cancel(self, user_id: int, task_id: str) -> bool:
        """
        Cancel a pending or running task belonging to user_id.
        Delegates to TaskExecutionManager.
        """
        from core.task_execution_manager import get_task_execution_manager
        tem = get_task_execution_manager()
        uid_int = int(user_id) if str(user_id).isdigit() else 1
        res = tem.cancel_task(task_id, user_id=uid_int)
        success = res.get("status") in ("success", "noop") and res.get("cancellation_state") in ("CANCELLED", "CANCEL_REQUESTED")
        if success:
            logger.info(f"Task [{task_id}] cancelled for user {uid_int}")
        return success

    def get_status(self, user_id: int, task_id: str) -> Optional[dict[str, Any]]:
        """Get status of a specific task belonging to user_id."""
        from core.task_execution_manager import get_task_execution_manager
        tem = get_task_execution_manager()
        uid_int = int(user_id) if str(user_id).isdigit() else 1
        task = tem.get_task(task_id)
        if not task or task.user_id != uid_int:
            return None

        duration = None
        if task.started_at and task.completed_at:
            duration = round(task.completed_at - task.started_at, 2)
        elif task.started_at:
            duration = round(time.time() - task.started_at, 2)

        st_val = task.status.value.lower() if hasattr(task.status, "value") else str(task.status).lower()

        return {
            "task_id": task.task_id,
            "user_id": task.user_id,
            "goal": task.normalized_goal or task.user_request,
            "priority": task.priority.value.lower() if hasattr(task.priority, "value") else str(task.priority).lower(),
            "status": st_val,
            "progress": task.progress,
            "result": task.result,
            "error": task.error or "",
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "duration_seconds": duration,
        }

    def list_user_tasks(self, user_id: int, limit: int = 20) -> list[dict[str, Any]]:
        """List all tasks for a specific user, sorted most recent first."""
        from core.task_execution_manager import get_task_execution_manager
        tem = get_task_execution_manager()
        uid_int = int(user_id) if str(user_id).isdigit() else 1
        tasks = tem.list_tasks(user_id=uid_int)
        tasks_sorted = sorted(tasks, key=lambda t: t.created_at, reverse=True)
        out = []
        for t in tasks_sorted[:limit]:
            dur = None
            if t.started_at and t.completed_at:
                dur = round(t.completed_at - t.started_at, 2)
            elif t.started_at:
                dur = round(time.time() - t.started_at, 2)
            st_val = t.status.value.lower() if hasattr(t.status, "value") else str(t.status).lower()
            out.append({
                "task_id": t.task_id,
                "user_id": t.user_id,
                "goal": t.normalized_goal or t.user_request,
                "priority": t.priority.value.lower() if hasattr(t.priority, "value") else str(t.priority).lower(),
                "status": st_val,
                "progress": t.progress,
                "result": t.result,
                "error": t.error or "",
                "created_at": t.created_at,
                "started_at": t.started_at,
                "completed_at": t.completed_at,
                "duration_seconds": dur,
            })
        return out

    def list_tasks(self, user_id: int, limit: int = 20) -> list[dict[str, Any]]:
        """Compatibility alias for list_user_tasks."""
        return self.list_user_tasks(user_id, limit=limit)


_queue_instance: Optional[TaskQueue] = None
_queue_lock = threading.Lock()


def get_task_queue() -> TaskQueue:
    global _queue_instance
    with _queue_lock:
        if _queue_instance is None:
            _queue_instance = TaskQueue()
        return _queue_instance

