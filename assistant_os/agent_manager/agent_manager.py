"""
assistant_os/agent_manager/agent_manager.py
=========================================
NOVA OS - Agent Manager: Top-Level Façade

Architecture:
    AgentManager is the single public entry point for all agent
    lifecycle and scheduling operations.  It composes:

        AgentRegistry   — who the agents are
        AgentScheduler  — what work is queued
        HealthMonitor   — whether agents are alive

    The AgentManager exposes a clean API that the Brain (or any future
    Event Bus subscriber) calls directly, without ever importing the
    sub-components individually.

    The AgentManager does NOT:
        ✗ Execute agent code
        ✗ Call any tools or external services
        ✗ Communicate with the Planner directly
        ✗ Modify Brain or Router

    Integration with the Brain:
        ┌──────────────────────────────────────────────────────────────┐
        │  # In Brain (pseudocode — Brain not modified here):          │
        │                                                              │
        │  from assistant_os.agent_manager import AgentManager              │
        │  from assistant_os.planner import Planner, BrainOutput            │
        │                                                              │
        │  manager = AgentManager()                                    │
        │  # Agents register themselves at startup (or auto-discover). │
        │                                                              │
        │  plan    = planner.create_plan(brain_output)                 │
        │  for task_node in plan.get_ready_tasks():                    │
        │      manager.schedule_task(task_node)                        │
        │                                                              │
        │  # Later: manager.complete_task(task_id)                     │
        │  #         manager.fail_task(task_id, error)                 │
        └──────────────────────────────────────────────────────────────┘

SDD Reference: Section 13 (Agent Manager).
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Dict, List, Optional

from assistant_os.agent_manager.health_monitor import HealthMonitor
from assistant_os.agent_manager.models import (
    AgentLifecycleState,
    AgentManifest,
    AgentManagerConfig,
    AgentRecord,
    HealthReport,
    ScheduledTask,
    TaskScheduleState,
)
from assistant_os.agent_manager.registry import AgentRegistry
from assistant_os.agent_manager.scheduler import AgentScheduler, QueueFullError
from assistant_os.planner.models import AgentType, TaskNode

logger = logging.getLogger("assistant_os.agent_manager")


class AgentManager:
    """
    Top-level façade for all agent lifecycle and scheduling operations.

    Usage:
        manager = AgentManager()
        manager.register_agent(manifest)
        scheduled = manager.schedule_task(task_node)
        manager.complete_task(task_id)
        reports = manager.get_health_report()
    """

    def __init__(self, config: Optional[AgentManagerConfig] = None):
        self.config   = config or AgentManagerConfig()
        self.registry = AgentRegistry(
            auto_idle_on_register=self.config.auto_idle_on_register
        )
        self.scheduler = AgentScheduler(
            max_queue_depth     = self.config.max_queue_depth,
            default_max_retries = self.config.default_max_retries,
        )
        self.health_monitor = HealthMonitor(
            heartbeat_timeout_sec = self.config.heartbeat_timeout_sec,
            auto_mark_unhealthy   = True,
        )
        logger.info(
            f"[AgentManager] Initialized — "
            f"heartbeat_timeout={self.config.heartbeat_timeout_sec}s, "
            f"max_queue={self.config.max_queue_depth}"
        )

    # ------------------------------------------------------------------
    # Agent Registration
    # ------------------------------------------------------------------

    def register_agent(self, manifest: AgentManifest) -> AgentRecord:
        """
        Register an agent from its manifest.

        If an agent of this type is already registered, its manifest
        is updated (hot-reload).

        Args:
            manifest: AgentManifest describing the agent.

        Returns:
            The created or updated AgentRecord.
        """
        record = self.registry.register(manifest)
        logger.info(
            f"[AgentManager] Agent registered: "
            f"{manifest.display_name} ({manifest.agent_type.value})"
        )
        return record

    def deregister_agent(self, agent_type: AgentType) -> bool:
        """
        Remove an agent from the registry.

        Any QUEUED or ASSIGNED tasks for this agent will remain in the
        scheduler as QUEUED (to be re-assigned when a replacement registers).

        Args:
            agent_type: The agent type to remove.

        Returns:
            True if successfully removed, False if not found.
        """
        result = self.registry.deregister(agent_type)
        if result:
            logger.info(f"[AgentManager] Agent deregistered: {agent_type.value}")
        return result

    def discover_agents(self, directory: Optional[str] = None) -> int:
        """
        Auto-discover and register agents from a directory.

        Delegates to AgentRegistry.discover_agents().  Uses
        config.agents_discovery_dir if directory not specified.

        Args:
            directory: Path to scan. Falls back to config default.

        Returns:
            Number of agents discovered and registered.
        """
        scan_dir = directory or self.config.agents_discovery_dir
        if not scan_dir:
            logger.warning(
                "[AgentManager] discover_agents: no directory specified."
            )
            return 0
        count = self.registry.discover_agents(scan_dir)
        logger.info(
            f"[AgentManager] Auto-discovery complete: {count} agent(s)."
        )
        return count

    # ------------------------------------------------------------------
    # Task Scheduling
    # ------------------------------------------------------------------

    def schedule_task(
        self,
        task_node: TaskNode,
        priority: int = 0,
        auto_assign: bool = True,
    ) -> ScheduledTask:
        """
        Schedule a TaskNode for agent execution.

        Steps:
            1. Convert TaskNode → ScheduledTask (state=QUEUED).
            2. If auto_assign=True AND an available agent exists:
               attempt immediate assignment (state→ASSIGNED).

        The AgentManager does NOT execute the task here.  Assignment
        means the task_id is handed off to the agent's work queue.
        Actual execution is the agent's responsibility (future module).

        Args:
            task_node:   TaskNode produced by the Planner.
            priority:    Scheduling priority (higher = more urgent).
            auto_assign: Attempt immediate assignment after queuing.

        Returns:
            The ScheduledTask (state may be QUEUED or ASSIGNED).

        Raises:
            QueueFullError: The task queue is full.
        """
        scheduled = self.scheduler.schedule(
            task_node, priority=priority
        )

        if auto_assign and not task_node.requires_approval:
            self._try_assign(scheduled)

        return scheduled

    def approve_and_assign(self, task_id: str) -> bool:
        """
        Approve a task that was pending user confirmation, then
        attempt assignment.

        Used by the Brain after the GUI captures user approval.

        Args:
            task_id: The task requiring approval.

        Returns:
            True if approval was processed, False if task not found.
        """
        task = self.scheduler.get_task(task_id)
        if not task:
            logger.warning(
                f"[AgentManager] approve_and_assign: task {task_id[:8]} not found."
            )
            return False

        task.requires_approval = False  # Clear the approval gate
        self._try_assign(task)
        return True

    # ------------------------------------------------------------------
    # Task Lifecycle Events (called by Agents — future modules)
    # ------------------------------------------------------------------

    def mark_task_running(self, task_id: str) -> bool:
        """
        Signal that an agent has started processing a task.

        Transitions: ASSIGNED → RUNNING.
        """
        return self.scheduler.mark_running(task_id)

    def complete_task(self, task_id: str) -> bool:
        """
        Signal that an agent successfully completed a task.

        Transitions: RUNNING → COMPLETED.
        Also decrements the agent's active_task_count in the Registry.

        Args:
            task_id: The completed task.

        Returns:
            True if transitioned successfully.
        """
        task = self.scheduler.get_task(task_id)
        if task and task.assigned_agent_key:
            try:
                agent_type = AgentType(task.assigned_agent_key)
                self.registry.decrement_active(agent_type, success=True)
            except ValueError:
                pass

        return self.scheduler.complete(task_id)

    def fail_task(self, task_id: str, error: str = "") -> TaskScheduleState:
        """
        Signal that an agent failed to complete a task.

        Applies retry logic:
            - If retries remain: task → RETRYING, re-queued.
            - If max retries exceeded: task → ABORTED.

        Also decrements the agent's active_task_count.

        Args:
            task_id: The failed task.
            error:   Error description.

        Returns:
            New TaskScheduleState (RETRYING or ABORTED).
        """
        task = self.scheduler.get_task(task_id)
        if task and task.assigned_agent_key:
            try:
                agent_type = AgentType(task.assigned_agent_key)
                self.registry.decrement_active(agent_type, success=False)
            except ValueError:
                pass

        new_state = self.scheduler.fail(task_id, error)

        # If RETRYING, attempt immediate re-assignment
        if new_state == TaskScheduleState.RETRYING:
            retrying_task = self.scheduler.get_task(task_id)
            if retrying_task:
                self._try_assign(retrying_task)

        return new_state

    def cancel_task(self, task_id: str, reason: str = "") -> bool:
        """
        Cancel a non-terminal task.

        Args:
            task_id: Task to cancel.
            reason:  Cancellation reason (stored in error_message).

        Returns:
            True if cancelled, False otherwise.
        """
        task = self.scheduler.get_task(task_id)
        if task and task.assigned_agent_key and not task.is_terminal:
            try:
                agent_type = AgentType(task.assigned_agent_key)
                self.registry.decrement_active(agent_type, success=False)
            except ValueError:
                pass

        return self.scheduler.cancel(task_id, reason)

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def heartbeat(self, agent_type: AgentType) -> bool:
        """
        Record a liveness signal from an agent.

        Transitions an UNHEALTHY agent back to IDLE if it recovers.

        Args:
            agent_type: The agent sending the heartbeat.

        Returns:
            True if the agent was found and updated.
        """
        result = self.registry.update_heartbeat(agent_type)
        if result:
            logger.debug(f"[AgentManager] Heartbeat: {agent_type.value}")
        else:
            logger.warning(
                f"[AgentManager] Heartbeat from unregistered agent: "
                f"{agent_type.value}"
            )
        return result

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def get_health_report(self) -> List[HealthReport]:
        """
        Run a full health check on all registered agents.

        Returns:
            List of HealthReport, one per registered agent.
        """
        return self.health_monitor.check_all(self.registry)

    def get_health_summary(self) -> Dict[str, object]:
        """
        Return a compact, JSON-serializable health summary.

        Returns:
            Dict with overall status and per-agent breakdown.
        """
        reports = self.get_health_report()
        return self.health_monitor.summarize(reports)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_scheduled_task(self, task_id: str) -> Optional[ScheduledTask]:
        """Return a ScheduledTask by ID, or None."""
        return self.scheduler.get_task(task_id)

    def get_registered_agent(self, agent_type: AgentType) -> Optional[AgentRecord]:
        """Return an AgentRecord by type, or None."""
        return self.registry.get(agent_type)

    def list_agents(self) -> List[AgentRecord]:
        """Return all registered agents."""
        return self.registry.list_all()

    def scheduler_stats(self) -> Dict[str, int]:
        """Return task counts per state from the scheduler."""
        return self.scheduler.stats()

    def registry_summary(self) -> Dict[str, object]:
        """Return agent counts and state summary from the registry."""
        return self.registry.summary()

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _try_assign(self, task: ScheduledTask) -> bool:
        """
        Attempt to assign a QUEUED or RETRYING task to an available agent.

        Does nothing if:
            - No agent of the required type is registered.
            - The agent is not currently IDLE/available.

        Returns:
            True if successfully assigned, False otherwise.
        """
        record = self.registry.get_available(task.agent_type)
        if not record:
            logger.debug(
                f"[AgentManager] No available agent for "
                f"{task.agent_type.value} — task {task.task_id[:8]} stays QUEUED."
            )
            return False

        assigned = self.scheduler.assign(task.task_id, task.agent_type)
        if assigned:
            self.registry.increment_active(task.agent_type)
            logger.info(
                f"[AgentManager] Assigned: task={task.task_id[:8]} "
                f"→ agent={task.agent_type.value}"
            )
        return assigned
