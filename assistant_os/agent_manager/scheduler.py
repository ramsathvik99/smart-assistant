"""
assistant_os/agent_manager/scheduler.py
=====================================
NOVA OS - Agent Manager: Task Scheduler

Architecture:
    The Scheduler is responsible for the lifecycle of tasks AFTER they
    have been handed over by the Brain/Planner.  It knows:

        - What tasks are QUEUED (waiting for an agent).
        - What tasks are ASSIGNED (handed off to an agent).
        - What tasks FAILED and whether to retry them.
        - The history of all completed tasks in the current session.

    The Scheduler does NOT:
        ✗ Execute agent logic
        ✗ Select which agent handles a task (that is AgentManager's job)
        ✗ Communicate with Memory or Brain
        ✗ Call any external tools

    Priority Queue:
        Tasks are stored in a priority queue where higher priority
        numbers are dequeued first.  The default priority is 0.
        The Brain may assign higher priorities to time-sensitive tasks.

    Retry Logic:
        When a task transitions to FAILED, the scheduler checks
        task.can_retry.  If True, it resets state to RETRYING and
        increments retry_count.  The AgentManager is responsible for
        re-assigning RETRYING tasks.

    Thread Safety:
        All mutations use a threading.Lock.

SDD Reference: Section 13.1 (Agent Manager — Scheduler).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Dict, List, Optional

from assistant_os.agent_manager.models import ScheduledTask, TaskScheduleState
from assistant_os.planner.models import AgentType, RiskLevel, TaskNode

logger = logging.getLogger("assistant_os.agent_manager.scheduler")


class QueueFullError(RuntimeError):
    """Raised when the task queue has reached max_queue_depth."""
    pass


class AgentScheduler:
    """
    Manages the queue of ScheduledTasks and their state transitions.

    Usage:
        scheduler = AgentScheduler(max_queue_depth=200)
        scheduled = scheduler.schedule(task_node)
        scheduler.assign(task_id, agent_type)
        scheduler.complete(task_id)
    """

    def __init__(
        self,
        max_queue_depth: int = 200,
        default_max_retries: int = 2,
    ):
        self._max_queue_depth   = max_queue_depth
        self._default_max_retries = default_max_retries

        # Primary store: task_id → ScheduledTask
        self._tasks: Dict[str, ScheduledTask] = {}
        self._lock  = threading.Lock()

    # ------------------------------------------------------------------
    # Submission
    # ------------------------------------------------------------------

    def schedule(
        self,
        task_node: TaskNode,
        priority: int = 0,
        max_retries: Optional[int] = None,
    ) -> ScheduledTask:
        """
        Convert a TaskNode (from Planner) into a ScheduledTask and
        add it to the queue.

        Idempotent: if the task_id already exists in the scheduler,
        the existing record is returned unchanged.

        Args:
            task_node:   TaskNode produced by the Planner.
            priority:    Scheduling priority (higher = more urgent).
            max_retries: Override default retry limit.

        Returns:
            The ScheduledTask that was created or found.

        Raises:
            QueueFullError: Queue has reached max_queue_depth.
        """
        with self._lock:
            # Idempotency guard
            if task_node.task_id in self._tasks:
                logger.debug(
                    f"[Scheduler] Task {task_node.task_id[:8]} already scheduled — "
                    f"returning existing record."
                )
                return self._tasks[task_node.task_id]

            queued_count = sum(
                1 for t in self._tasks.values()
                if t.state == TaskScheduleState.QUEUED
            )
            if queued_count >= self._max_queue_depth:
                raise QueueFullError(
                    f"Task queue is full ({self._max_queue_depth} tasks queued). "
                    f"Cannot schedule task {task_node.task_id}."
                )

            scheduled = ScheduledTask(
                task_id           = task_node.task_id,
                plan_id           = task_node.plan_id,
                agent_type        = task_node.agent_type,
                instruction       = task_node.instruction,
                risk_level        = task_node.risk_level,
                requires_approval = task_node.requires_approval,
                priority          = priority,
                max_retries       = max_retries if max_retries is not None
                                    else self._default_max_retries,
            )
            self._tasks[scheduled.task_id] = scheduled

        logger.info(
            f"[Scheduler] Queued: task={task_node.task_id[:8]} "
            f"agent={task_node.agent_type.value} "
            f"priority={priority} "
            f"approval_required={task_node.requires_approval}"
        )
        return scheduled

    # ------------------------------------------------------------------
    # State Transitions
    # ------------------------------------------------------------------

    def assign(self, task_id: str, agent_type: AgentType) -> bool:
        """
        Mark a QUEUED task as ASSIGNED to a specific agent.

        Called by AgentManager after it has selected an available agent
        from the Registry.

        Args:
            task_id:    ID of the task to assign.
            agent_type: The agent type that accepted the task.

        Returns:
            True on success, False if task not found or wrong state.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                logger.warning(f"[Scheduler] assign: unknown task {task_id[:8]}")
                return False
            if task.state not in (
                TaskScheduleState.QUEUED,
                TaskScheduleState.RETRYING,
            ):
                logger.warning(
                    f"[Scheduler] assign: task {task_id[:8]} is in state "
                    f"{task.state.value} — cannot assign."
                )
                return False

            task.state              = TaskScheduleState.ASSIGNED
            task.assigned_agent_key = agent_type.value
            task.assigned_at        = datetime.utcnow()

        logger.info(
            f"[Scheduler] Assigned: task={task_id[:8]} → agent={agent_type.value}"
        )
        return True

    def mark_running(self, task_id: str) -> bool:
        """
        Transition a task from ASSIGNED to RUNNING.

        Called when the agent signals it has begun processing.

        Args:
            task_id: ID of the task.

        Returns:
            True on success, False otherwise.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.state != TaskScheduleState.ASSIGNED:
                logger.warning(
                    f"[Scheduler] mark_running: task {task_id[:8]} is "
                    f"{task.state.value}, not ASSIGNED."
                )
                return False
            task.state      = TaskScheduleState.RUNNING
            task.started_at = datetime.utcnow()

        logger.debug(f"[Scheduler] Running: task={task_id[:8]}")
        return True

    def complete(self, task_id: str) -> bool:
        """
        Mark a task as COMPLETED (terminal state — success).

        Args:
            task_id: ID of the completed task.

        Returns:
            True if transitioned, False if task not found.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                logger.warning(f"[Scheduler] complete: unknown task {task_id[:8]}")
                return False
            task.state        = TaskScheduleState.COMPLETED
            task.completed_at = datetime.utcnow()

        logger.info(f"[Scheduler] Completed: task={task_id[:8]}")
        return True

    def fail(self, task_id: str, error: str = "") -> TaskScheduleState:
        """
        Mark a task as FAILED.  Applies retry logic if eligible.

        If the task can be retried:
            state → RETRYING, retry_count incremented.
        Otherwise:
            state → ABORTED (terminal).

        Args:
            task_id: ID of the failed task.
            error:   Human-readable error message.

        Returns:
            The new TaskScheduleState (RETRYING or ABORTED).
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                logger.warning(f"[Scheduler] fail: unknown task {task_id[:8]}")
                return TaskScheduleState.ABORTED

            task.error_message = error
            task.completed_at  = datetime.utcnow()

            if task.can_retry:
                task.retry_count  += 1
                task.state         = TaskScheduleState.RETRYING
                task.assigned_at   = None
                task.started_at    = None
                task.completed_at  = None
                new_state          = TaskScheduleState.RETRYING
                logger.warning(
                    f"[Scheduler] Retrying: task={task_id[:8]} "
                    f"attempt={task.retry_count}/{task.max_retries} "
                    f"error={error!r:.80}"
                )
            else:
                task.state = TaskScheduleState.ABORTED
                new_state  = TaskScheduleState.ABORTED
                logger.error(
                    f"[Scheduler] Aborted: task={task_id[:8]} — "
                    f"max retries ({task.max_retries}) exceeded. "
                    f"Last error: {error!r:.80}"
                )

        return new_state

    def cancel(self, task_id: str, reason: str = "") -> bool:
        """
        Cancel a non-terminal task.  Sets state to CANCELLED.

        Non-terminal states: QUEUED, ASSIGNED, RUNNING, RETRYING.

        Args:
            task_id: Task to cancel.
            reason:  Human-readable cancellation reason.

        Returns:
            True if cancelled, False if already terminal or not found.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.is_terminal:
                logger.debug(
                    f"[Scheduler] cancel: task {task_id[:8]} is already "
                    f"terminal ({task.state.value})."
                )
                return False
            task.state        = TaskScheduleState.CANCELLED
            task.error_message = reason or "Cancelled"
            task.completed_at  = datetime.utcnow()

        logger.info(f"[Scheduler] Cancelled: task={task_id[:8]} reason={reason!r:.60}")
        return True

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        """Return a ScheduledTask by task_id, or None."""
        return self._tasks.get(task_id)

    def get_queued(self) -> List[ScheduledTask]:
        """
        Return all QUEUED tasks sorted by descending priority, then
        ascending scheduled_at (highest priority, earliest first).
        """
        with self._lock:
            queued = [
                t for t in self._tasks.values()
                if t.state == TaskScheduleState.QUEUED
            ]
        return sorted(queued, key=lambda t: (-t.priority, t.scheduled_at))

    def get_retrying(self) -> List[ScheduledTask]:
        """Return all tasks in RETRYING state."""
        with self._lock:
            return [
                t for t in self._tasks.values()
                if t.state == TaskScheduleState.RETRYING
            ]

    def get_tasks_for_agent(self, agent_type: AgentType) -> List[ScheduledTask]:
        """Return all non-terminal tasks assigned to a specific agent type."""
        with self._lock:
            return [
                t for t in self._tasks.values()
                if t.agent_type == agent_type and not t.is_terminal
            ]

    def get_tasks_for_plan(self, plan_id: str) -> List[ScheduledTask]:
        """Return all tasks belonging to a given plan."""
        with self._lock:
            return [t for t in self._tasks.values() if t.plan_id == plan_id]

    def stats(self) -> Dict[str, int]:
        """Return counts per state — useful for health dashboards."""
        counts: Dict[str, int] = {s.value: 0 for s in TaskScheduleState}
        with self._lock:
            for task in self._tasks.values():
                counts[task.state.value] += 1
        counts["total"] = len(self._tasks)
        return counts
